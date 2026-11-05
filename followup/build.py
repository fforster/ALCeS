"""Build the follow-up store from NATIVE-RATE ALCeS sweeps (never training-mode / flat-log-z runs).

For every class and survey (WFD, DDF) it pools the finished runs of ~/data/alces_lcl/sweep_runs/<TAG>_{WFD_80k,DDF_40k},
weights each simulated object to expected real events over the 10-year survey (expected_counts.object_weights:
native SNANA rate x footprint >= 100 / 1000 visits, area-uniform), keeps the DETECTED objects inside the footprint and
stores, per object:

    ra, dec, z, weight (real events / 10 yr), t_fd (first detection MJD: first epoch with PHOTFLAG & 4096),
    mag[band, k] = noiseless MODEL AB magnitude (model_dense FLUX_MODEL, nJy, zp 31.4; includes MW and host
                   extinction) at t_fd + k days, k = 0..N_DAYS (observer frame); +inf where the model has no flux.

Output: <OUT>/<class>_<survey>.npz plus <OUT>/catalog.json.  Run with the alces-lcl or main venv:

    python -m followup.build [--out ~/data/alces_followup] [--classes SNII SLSN-I ...] [--jobs 6]
"""
from __future__ import annotations

import argparse
import os
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

# LSST_sim_lcs/tools (expected_counts.py); it lives next to the ALCeS checkout, not inside it
TOOLS = Path(os.environ.get("ALCES_TOOLS", "~/Dropbox/Work/Claude/LSST_sim_lcs/tools")).expanduser()
SWEEPS = Path("~/data/alces_lcl/sweep_runs").expanduser()
OPSIM_DB = Path("~/data/rubin_opsim/baseline_v5.3.1_10yrs.db").expanduser()
OUT_DEFAULT = Path("~/data/alces_followup").expanduser()
MIN_VISITS = {"DDF": 1000, "WFD": 100}
SWEEP_FMT = {"DDF": "{}_DDF_40k", "WFD": "{}_WFD_80k"}
BANDS = ["u", "g", "r", "i", "z", "Y"]
N_DAYS = 400
ZP_NJY = 31.4
DET_BIT = 4096

# class name -> list of (sweep tag, z_min, z_max, multiplier). Several parts are stitched by redshift; the per-object
# weights are expected counts within each sweep's own z range, so a z-cut subset of a sweep stays unbiased.
CLASSES = {
    "SNIa":         [("SNIASALT2", 0, 99, 1.0)],
    "SNIa-91bg":    [("SNIA91BGELASTIC", 0, 99, 1.0)],
    "SNIax":        [("SNIAXELASTIC", 0, 99, 1.0)],
    # all normal SNe II = 4 x SNII-NMF rate (as in the SNII_NMF_tail analysis); low-z sweep for statistics
    "SNII":         [("SNIINMFTAILLOWZ", 0, 0.3, 4.0), ("SNIINMFTAIL", 0.3, 99, 4.0)],
    "SNIIn":        [("SNIINMOSFIT", 0, 99, 1.0)],
    "SLSN-I":       [("SLSNI", 0, 99, 1.0)],
    "TDE":          [("TDEMOSFIT", 0, 99, 1.0)],
    "KN-Bulla19":   [("KNBULLA19", 0, 99, 1.0)],
    "KN-K17":       [("KNK17", 0, 99, 1.0)],
    "ILOT":         [("ILOTMOSFIT", 0, 99, 1.0)],
    "CaRT":         [("CART", 0, 99, 1.0)],
    "PISN-MOSFIT":  [("PISNMOSFIT", 0, 99, 1.0)],
    "PISN-He":      [("PISNSTELLAHECORE", 0, 99, 1.0)],
    "PISN-H":       [("PISNSTELLAHYDROGENIC", 0, 99, 1.0)],
}


def _ec():
    sys.path.insert(0, str(TOOLS))
    import expected_counts as ec  # noqa: E402
    return ec


def _runs(sweep_dir):
    for r in sorted((sweep_dir / "runs").glob("*/")):
        rh = json.loads((r / "run_hash.json").read_text())
        if rh.get("status") == "done":
            yield r, rh


def weights_for_sweep(sweep_dir, fp, survey, ec):
    heads, ngen = [], 0
    for r, rh in _runs(sweep_dir):
        h = pd.read_parquet(r / "head_df.parquet", columns=["SNID", "RA", "DEC", "REDSHIFT_HELIO", "PEAKMJD", "DETECTED"])
        h["run"] = r.name
        heads.append(h)
        ngen += int(rh["ngentot"])
    head = pd.concat(heads, ignore_index=True)
    cfg = json.loads((sweep_dir / "class_config_snapshot.json").read_text())
    zlo, zhi = cfg["genrange_redshift"]
    per_yr = ec.expected_all_sky_per_year(ec.rate_from_dndz(cfg["dndz"]), zlo, zhi)
    w, summ = ec.object_weights(head, fp, ngen, per_yr, MIN_VISITS[survey])
    head["WEIGHT"] = w.WEIGHT.to_numpy()
    head["SNID"] = head.SNID.astype(str)
    return head, summ, cfg


def curves_for_run(run_dir, snids):
    """first detection + model mags on t_fd + 0..N_DAYS d for the given SNIDs of one run."""
    snids = list(snids)
    ph = pd.read_parquet(run_dir / "phot_df.parquet", columns=["SNID", "MJD", "PHOTFLAG"],
                         filters=[("SNID", "in", snids)])
    ph = ph[(ph.PHOTFLAG.astype(int) & DET_BIT) > 0]
    t_fd = ph.astype({"SNID": str}).groupby("SNID").MJD.min()
    dense = pd.read_parquet(run_dir / "model_dense.parquet", columns=["SNID", "MJD", "FLT", "FLUX_MODEL"],
                            filters=[("SNID", "in", snids)]).astype({"SNID": str})
    out_ids, out_tfd, out_mag = [], [], []
    k = np.arange(N_DAYS + 1, dtype=float)
    for sid, g in dense.groupby("SNID", sort=False):
        if sid not in t_fd.index:
            continue
        tgrid = t_fd[sid] + k
        mag = np.full((len(BANDS), len(k)), np.inf, dtype=np.float32)
        for b, gb in g.groupby("FLT"):
            if b not in BANDS:
                continue
            gb = gb.sort_values("MJD")
            f = np.interp(tgrid, gb.MJD.to_numpy(), gb.FLUX_MODEL.to_numpy(), left=np.nan, right=np.nan)
            with np.errstate(divide="ignore", invalid="ignore"):
                m = np.where(f > 0, ZP_NJY - 2.5 * np.log10(f), np.inf)
            mag[BANDS.index(b)] = m
        out_ids.append(sid)
        out_tfd.append(t_fd[sid])
        out_mag.append(mag)
    return out_ids, np.array(out_tfd), (np.stack(out_mag) if out_mag else np.zeros((0, len(BANDS), len(k))))


def build_class_survey(args):
    name, survey, out = args
    ec = _ec()
    fp = ec.footprint(OPSIM_DB, survey)
    parts, info = [], []
    for tag, zmin, zmax, mult in CLASSES[name]:
        sweep = SWEEPS / SWEEP_FMT[survey].format(tag)
        head, summ, cfg = weights_for_sweep(sweep, fp, survey, ec)
        sel = head[head.DETECTED & (head.WEIGHT > 0) & (head.REDSHIFT_HELIO >= zmin) & (head.REDSHIFT_HELIO < zmax)]
        for run, hs in sel.groupby("run"):
            ids, tfd, mag = curves_for_run(sweep / "runs" / run, hs.SNID)
            hs = hs.set_index("SNID").loc[ids]
            parts.append(dict(ra=hs.RA.to_numpy(), dec=hs.DEC.to_numpy(), z=hs.REDSHIFT_HELIO.to_numpy(),
                              t_peak=hs.PEAKMJD.to_numpy(), weight=hs.WEIGHT.to_numpy() * mult, t_fd=tfd,
                              mag=mag.astype(np.float16)))
        info.append({"sweep": sweep.name, "class_key": cfg["class_key"], "z_cut": [zmin, zmax], "multiplier": mult,
                     "dndz": cfg["dndz"], "N_exp_10yr": summ["N_exp"] * mult,
                     "N_det_10yr_sweep": summ["N_det_weighted"] * mult, "n_sim_selected": int(len(sel))})
    cat = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    np.savez(out / f"{name}_{survey}.npz", **cat)
    return {"class": name, "survey": survey, "n_sim": int(len(cat["ra"])), "N_det_10yr": float(cat["weight"].sum()),
            "t_fd_range": [float(cat["t_fd"].min()), float(cat["t_fd"].max())], "parts": info,
            "survey_years": fp.t_years, "area_deg2": fp.area_deg2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--classes", nargs="*", default=list(CLASSES))
    ap.add_argument("--surveys", nargs="*", default=["WFD", "DDF"])
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    catf = a.out / "catalog.json"
    catalog = json.loads(catf.read_text()) if catf.exists() else {"bands": BANDS, "n_days": N_DAYS, "entries": {}}
    tasks = [(c, s, a.out) for c in a.classes for s in a.surveys]
    with ProcessPoolExecutor(a.jobs) as ex:
        for res in ex.map(build_class_survey, tasks):
            catalog["entries"][f"{res['class']}_{res['survey']}"] = res
            print(f"{res['class']:12s} {res['survey']}  n_sim={res['n_sim']:6d}  N_det(10yr)={res['N_det_10yr']:12,.0f}",
                  flush=True)
            catf.write_text(json.dumps(catalog, indent=1))


if __name__ == "__main__":
    main()
