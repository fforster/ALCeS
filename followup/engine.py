"""Follow-up potential of Rubin-detected transients from a ground site (native-rate ALCeS simulations).

Steps (per request):
 0. time grid [T0, T1 + t_max] with step dt;
 1. keep the steps where the Sun is below `sun_alt` (astronomical night by default) at the site;
 2. for each simulated detected object whose first Rubin detection t_fd falls in [T0 - t_max, T1], and each night
    step t with t_min <= t - t_fd <= t_max, interpolate the noiseless MODEL magnitude in `band` and require
    m <= mag_lim;
 3. require airmass(t) <= airmass_max at the site;
 4. per object: hours and nights it is followable, delay from first detection to the first opportunity;
 5. counts are expected REAL events: every simulated object carries a weight (real events per 10 yr represented by it,
    native SNANA rates x footprint); a sum of weights over any selection is the expected number, with Poisson-like
    error sqrt(sum w^2).
Instantaneous counts N(t) cover t in [T0, T1]; per-object statistics cover the objects first detected in [T0, T1]
(followed up to t_fd + t_max even beyond T1, so they are not truncated).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import astro

STORE = Path("~/data/alces_followup").expanduser()
MAX_PAIRS = 8_000_000


@dataclass
class Query:
    lat: float = -30.2446            # Cerro Pachon
    lon: float = -70.7494
    height: float = 2700.0
    classes: list = field(default_factory=lambda: ["SNIa", "SNII"])
    surveys: list = field(default_factory=lambda: ["WFD"])
    band: str = "r"
    mag_lim: float = 20.0
    airmass_max: float = 2.0
    t_min: float = 0.0               # days since first detection
    t_max: float = 30.0
    mjd_start: float = 61400.0
    mjd_end: float = 61765.0
    step_min: float = 15.0
    sun_alt: float = -18.0
    # False: the simulated objects at their simulated dates (default). True: also use the objects first detected in
    # the survey years `fold_year_list` (0 = first year; None = all), shifted by whole years into the window. This
    # assumes those years are equivalent (rolling stripes and other strategy changes make them differ): check with
    # the per-year breakdown returned in "by_year".
    fold_years: bool = False
    fold_year_list: list | None = None


@lru_cache(maxsize=None)
def catalog(store: str = str(STORE)):
    return json.loads((Path(store) / "catalog.json").read_text())


@lru_cache(maxsize=64)
def load(name: str, survey: str, store: str = str(STORE)):
    d = np.load(Path(store) / f"{name}_{survey}.npz")
    return {k: d[k] for k in d.files}


YEAR = 365.25
N_SURVEY_YEARS = 10


def survey_year(t_fd, t_survey0):
    """0-based survey year of a first detection (year 0 starts at the first simulated detection)."""
    return np.clip(np.floor((np.asarray(t_fd) - t_survey0) / YEAR).astype(int), 0, N_SURVEY_YEARS - 1)


def _instances(d, q, years_used, t_survey0):
    """(source index, first-detection MJD, weight, source survey year) of the objects used for this query.

    fold_years=False: the simulated objects at their simulated dates.
    fold_years=True : every simulated object first detected in one of `years_used` is also placed at
    t_fd + m * 365.25 d for every integer m that lands in [T0 - t_max, T1]. RA/Dec, light curve and the Sun-object
    geometry are unchanged by a whole-year shift; the Rubin strategy is NOT (rolling stripes, survey changes), so the
    result is the window as it would be if every year were like the average of `years_used`. Each copy is weighted by
    1 / len(years_used), which preserves the expected rate of those years."""
    t_fd, w = d["t_fd"], d["weight"]
    n = len(t_fd)
    yr = survey_year(t_fd, t_survey0)
    if not q.fold_years:
        return np.arange(n), t_fd, w, yr
    keep = np.isin(yr, years_used)
    lo, hi = q.mjd_start - q.t_max, q.mjd_end
    m0 = np.ceil((lo - t_fd) / YEAR).astype(int)
    m1 = np.floor((hi - t_fd) / YEAR).astype(int)
    cnt = np.where(keep, np.maximum(m1 - m0 + 1, 0), 0)
    src = np.repeat(np.arange(n), cnt)
    m = np.repeat(m0, cnt) + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    return src, t_fd[src] + m * YEAR, w[src] / len(years_used), yr[src]


MAX_SKY_FOLLOWABLE = 6000      # per class and survey
MAX_SKY_BACKGROUND = 600


def _sky_table(parts):
    """Column-wise table of sky points (rounded to keep the JSON small); 'sampled' < 1 when a cap applied."""
    if not parts:
        return {"n": 0}
    cat = lambda k: np.concatenate([np.asarray(p[k]) for p in parts]) if parts else np.zeros(0)  # noqa: E731
    n = [len(p["idx"]) for p in parts]
    return {
        "n": int(sum(n)),
        "cls": sum(([p["cls"]] * m for p, m in zip(parts, n)), []),
        "survey": sum(([p["survey"]] * m for p, m in zip(parts, n)), []),
        "idx": cat("idx").astype(int).tolist(), "shift": np.round(cat("shift"), 5).tolist(),
        "ra": np.round(cat("ra"), 4).tolist(), "dec": np.round(cat("dec"), 4).tolist(),
        "w": np.round(cat("w"), 4).tolist(), "hours": np.round(cat("hours"), 2).tolist(),
        "first": [None if not np.isfinite(x) else round(float(x), 3) for x in cat("first")],
        "sampled": {f"{p['cls']}_{p['survey']}": p["frac"] for p in parts},
    }


def _intervals(t, mask, step_days):
    """Contiguous True runs of mask on grid t -> [[start, end], ...] (end = last step + one step)."""
    if not mask.any():
        return []
    m = np.concatenate([[False], mask, [False]]).astype(int)
    d = np.diff(m)
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1
    return [[float(t[a]), float(t[b] + step_days)] for a, b in zip(s, e)]


@lru_cache(maxsize=8)
def _run_tables(sweep: str, run: str):
    """phot_df and model_dense of one ALCeS run (cached: clicks often hit the same run)."""
    import pandas as pd
    from .build import SWEEPS
    rd = SWEEPS / sweep / "runs" / run
    ph = pd.read_parquet(rd / "phot_df.parquet", columns=["SNID", "MJD", "FLT", "FLUXCAL", "FLUXCALERR", "PHOTFLAG"])
    dn = pd.read_parquet(rd / "model_dense.parquet", columns=["SNID", "MJD", "FLT", "FLUX_MODEL"])
    return ph.astype({"SNID": str}), dn.astype({"SNID": str})


def object_detail(q: Query, cls: str, survey: str, idx: int, shift: float = 0.0, store: Path = STORE,
                  pad_before: float = 30.0, pad_after: float = 30.0):
    """Everything the GUI shows for one simulated event: model light curve, Rubin photometry and visibility windows.

    `shift` (days, a whole number of years when folding) moves the event in time; the Rubin photometry is shifted
    with it, i.e. it shows the cadence of the year the event was actually simulated in."""
    cat = catalog(str(store))
    d = load(cls, survey, str(store))
    if not 0 <= idx < len(d["ra"]):
        raise ValueError("object index out of range")
    bands = cat["bands"]
    zp = 31.4
    ra, dec = float(d["ra"][idx]), float(d["dec"][idx])
    t_fd = float(d["t_fd"][idx]) + shift
    out = {"cls": cls, "survey": survey, "idx": idx, "shift_days": shift, "ra": ra, "dec": dec,
           "z": float(d["z"][idx]), "t_fd": t_fd, "t_peak": float(d["t_peak"][idx]) + shift,
           "weight_10yr": float(d["weight"][idx]), "bands": bands}
    has_prov = "run" in d
    if has_prov:
        out.update(sweep=str(d["sweep"][idx]), run=str(d["run"][idx]), snid=str(d["snid"][idx]))
    # --- light curves (relative to the first detection); the store's daily model mags are the fallback
    model, phot = {}, {}
    if has_prov:
        ph, dn = _run_tables(out["sweep"], out["run"])
        m = dn[dn.SNID == out["snid"]]
        for b, g in m.groupby("FLT"):
            g = g.sort_values("MJD")
            f = g.FLUX_MODEL.to_numpy()
            ok = f > 0
            model[b] = {"t": np.round(g.MJD.to_numpy()[ok] + shift - t_fd, 3).tolist(),
                        "mag": np.round(zp - 2.5 * np.log10(f[ok]), 3).tolist()}
        p = ph[ph.SNID == out["snid"]]
        for b, g in p.groupby("FLT"):
            det = (g.PHOTFLAG.astype(int) & 4096) > 0
            fl, er = g.FLUXCAL.to_numpy(), g.FLUXCALERR.to_numpy()
            with np.errstate(divide="ignore", invalid="ignore"):
                mag = np.where(fl > 0, zp - 2.5 * np.log10(fl), np.nan)
                merr = 1.0857 * er / np.abs(fl)
                lim5 = zp - 2.5 * np.log10(5 * er)
            t = g.MJD.to_numpy() + shift - t_fd
            phot[b] = {"t": np.round(t, 4).tolist(), "det": det.tolist(),
                       "mag": [None if not np.isfinite(x) else round(float(x), 3) for x in mag],
                       "err": [None if not np.isfinite(x) else round(float(x), 3) for x in merr],
                       "lim5": [None if not np.isfinite(x) else round(float(x), 3) for x in lim5]}
    else:
        k = np.arange(cat["n_days"] + 1)
        for i, b in enumerate(bands):
            mm = d["mag"][idx, i].astype(float)
            ok = np.isfinite(mm)
            model[b] = {"t": k[ok].tolist(), "mag": np.round(mm[ok], 3).tolist()}
    out["model"], out["phot"] = model, phot
    # --- visibility on the query grid, from t_fd - pad_before to t_fd + t_max + pad_after
    step = q.step_min / 1440.0
    # same phase as the counting grid (which starts at mjd_start), so the followable hours agree exactly
    t0 = q.mjd_start + np.floor((t_fd - pad_before - q.mjd_start) / step) * step
    t1 = t_fd + q.t_max + pad_after
    grid = astro.time_grid(t0, t1, q.step_min)
    dark = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    alt = astro.altitude(ra, dec, astro.local_sidereal_deg(grid, q.lon), q.lat)
    x = astro.airmass_from_alt(alt)
    observable = dark & (x <= q.airmass_max)
    # the same model magnitudes as the counting engine (store grid: daily from t_fd, linear interpolation)
    b = bands.index(q.band)
    magb = d["mag"][idx, b].astype(np.float32)
    dt = grid - t_fd
    kf = np.clip(dt, 0, cat["n_days"] - 1e-6)
    kk = kf.astype(int)
    m0, m1 = magb[kk], magb[np.minimum(kk + 1, cat["n_days"])]
    with np.errstate(invalid="ignore"):
        mag_q = np.where(np.isfinite(m0) & np.isfinite(m1), m0 + (kf - kk) * (m1 - m0), np.inf)
    followable = observable & (dt >= q.t_min) & (dt <= q.t_max) & (mag_q <= q.mag_lim)
    out["observable"] = [[a - t_fd, e - t_fd] for a, e in _intervals(grid, observable, step)]
    out["followable"] = [[a - t_fd, e - t_fd] for a, e in _intervals(grid, followable, step)]
    out["followable_hours"] = float(followable.sum() * q.step_min / 60.0)
    out["query"] = {"band": q.band, "mag_lim": q.mag_lim, "airmass_max": q.airmass_max,
                    "t_min": q.t_min, "t_max": q.t_max}
    return out


def _hist(x, w, bins):
    h = np.histogram(x, bins=bins, weights=w)[0]
    e = np.sqrt(np.histogram(x, bins=bins, weights=w ** 2)[0])
    return h, e


def run(q: Query, store: Path = STORE):
    cat = catalog(str(store))
    bands = cat["bands"]
    n_days = cat["n_days"]
    if q.band not in bands:
        raise ValueError(f"band must be one of {bands}")
    if not (0 <= q.t_min < q.t_max <= n_days):
        raise ValueError(f"need 0 <= t_min < t_max <= {n_days} d")
    if q.mjd_end <= q.mjd_start:
        raise ValueError("mjd_end must be after mjd_start")
    span = q.mjd_end - q.mjd_start
    step = max(q.step_min, 1.0)
    # keep the grid manageable for long windows
    step = max(step, (span + q.t_max) * 1440.0 / 400_000)
    b = bands.index(q.band)
    t_survey0 = min(e["t_fd_range"][0] for e in cat["entries"].values())
    years_used = sorted({int(y) for y in (q.fold_year_list if q.fold_year_list is not None
                                           else range(N_SURVEY_YEARS))})
    if q.fold_years and (not years_used or not all(0 <= y < N_SURVEY_YEARS for y in years_used)):
        raise ValueError(f"fold_year_list must hold survey years 0..{N_SURVEY_YEARS - 1}")

    grid = astro.time_grid(q.mjd_start, q.mjd_end + q.t_max, step)
    night = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    tn = grid[night]
    lst = astro.local_sidereal_deg(tn, q.lon) if len(tn) else np.zeros(0)
    night_id = np.floor(tn + q.lon / 360.0 - 0.5).astype(np.int64)     # changes at local noon
    in_win = tn <= q.mjd_end
    phi = np.radians(q.lat)
    # min zenith distance |dec - lat| must allow airmass <= airmass_max (plane-parallel is fine for a pre-cut)
    zmax_deg = np.degrees(np.arccos(1.0 / q.airmass_max)) + 0.5

    # followable objects have >= 1 step; log bins from one step to the longest possible (12 h per night)
    hours_bins = np.geomspace(0.999 * step / 60.0, max((q.t_max - q.t_min + 1) * 12.0, 1.0), 25)
    delay_bins = np.linspace(q.t_min, q.t_max, 31)
    nights_bins = np.arange(0, int(np.ceil(q.t_max - q.t_min)) + 3) - 0.5

    ts_total = np.zeros(len(tn))
    per_class, ts_class, night_class = [], {}, {}
    sky = {"followable": [], "detected": []}
    draws = []
    rng = np.random.default_rng(12345)
    u_nights = np.unique(night_id[in_win]) if len(tn) else np.zeros(0, int)

    for name in q.classes:
        ts = np.zeros(len(tn))
        objs = []   # per-object arrays for t_fd in [T0, T1]
        n_sim_det = n_inst_det = 0
        w_det = w2_det = 0.0
        night_w = {}
        for survey in q.surveys:
            key = f"{name}_{survey}"
            if key not in cat["entries"]:
                continue
            d = load(name, survey, str(store))
            # instances: the simulated objects themselves, or (fold_years) copies shifted by whole years
            src, t_fd, w, yr = _instances(d, q, years_used, t_survey0)
            ra, dec = d["ra"][src], d["dec"][src]
            in_range = (t_fd >= q.mjd_start) & (t_fd <= q.mjd_end)
            n_sim_det += int(len(np.unique(src[in_range])))
            n_inst_det += int(in_range.sum())
            w_det += float(w[in_range].sum())
            w2_det += float((w[in_range] ** 2).sum())
            cand = (t_fd >= q.mjd_start - q.t_max) & (t_fd <= q.mjd_end)
            cand &= np.abs(dec - q.lat) <= zmax_deg
            k0, k1 = int(np.floor(q.t_min)), int(np.ceil(q.t_max))
            magb = d["mag"][:, b, :]
            magmin = np.min(magb[:, k0:k1 + 1].astype(np.float32), axis=1)
            cand &= magmin[src] <= q.mag_lim
            idx = np.flatnonzero(cand)
            # every object in range gets a stats row (zeros if never followable)
            hours = np.zeros(len(t_fd))
            first = np.full(len(t_fd), np.nan)
            nnights = np.zeros(len(t_fd))
            if len(idx) and len(tn):
                lo = np.searchsorted(tn, t_fd[idx] + q.t_min)
                hi = np.searchsorted(tn, t_fd[idx] + q.t_max, side="right")
                cnt = np.maximum(hi - lo, 0)
                # chunk the objects so that the (object, time) pairs stay bounded
                csum = np.cumsum(cnt)
                starts = np.searchsorted(csum, np.arange(0, csum[-1] if len(csum) else 0, MAX_PAIRS), side="right")
                bounds = list(starts) + [len(idx)]
                for c0, c1 in zip(bounds[:-1], bounds[1:]):
                    if c1 <= c0:
                        continue
                    sl = slice(c0, c1)
                    o_loc = np.repeat(np.arange(c0, c1), cnt[sl])
                    if not len(o_loc):
                        continue
                    j = np.concatenate([np.arange(a, z) for a, z in zip(lo[sl], hi[sl])])
                    o = idx[o_loc]
                    dt = tn[j] - t_fd[o]
                    kf = np.clip(dt, 0, n_days - 1e-6)
                    k = kf.astype(np.int64)
                    f = (kf - k).astype(np.float32)
                    m0 = magb[src[o], k].astype(np.float32)
                    m1 = magb[src[o], np.minimum(k + 1, n_days)].astype(np.float32)
                    with np.errstate(invalid="ignore"):
                        m = np.where(np.isfinite(m0) & np.isfinite(m1), m0 + f * (m1 - m0), np.inf)
                    ok = m <= q.mag_lim
                    o, j, dt = o[ok], j[ok], dt[ok]
                    dec_r = np.radians(dec[o])
                    ha = np.radians(lst[j] - ra[o])
                    sin_alt = np.sin(phi) * np.sin(dec_r) + np.cos(phi) * np.cos(dec_r) * np.cos(ha)
                    alt = np.degrees(np.arcsin(np.clip(sin_alt, -1, 1)))
                    x = 1.0 / np.sin(np.radians(alt + 244.0 / (165.0 + 47.0 * np.abs(alt) ** 1.1)))
                    ok = (alt > 0) & (x <= q.airmass_max)
                    o, j, dt = o[ok], j[ok], dt[ok]
                    if not len(o):
                        continue
                    ts += np.bincount(j, weights=w[o], minlength=len(tn))
                    hours += np.bincount(o, minlength=len(t_fd)) * step / 60.0
                    np.fmin.at(first, o, dt)
                    on = np.unique(np.stack([o, night_id[j]]), axis=1)
                    nnights += np.bincount(on[0], minlength=len(t_fd))
                    # distinct objects per night (only nights inside the window)
                    sel_n = np.isin(on[1], u_nights)
                    if sel_n.any():
                        nn, inv = np.unique(on[1][sel_n], return_inverse=True)
                        ws = np.bincount(inv, weights=w[on[0][sel_n]])
                        for a, v in zip(nn, ws):
                            night_w[int(a)] = night_w.get(int(a), 0.0) + float(v)
            r = in_range
            # sky map: every followable event, plus a sample of detected-but-not-followable ones for context
            shift = t_fd - d["t_fd"][src]
            for kind, sel_k, cap in (("followable", r & (hours > 0), MAX_SKY_FOLLOWABLE),
                                     ("detected", r & (hours == 0), MAX_SKY_BACKGROUND)):
                ii = np.flatnonzero(sel_k)
                if len(ii) > cap:
                    ii = np.sort(rng.choice(ii, cap, replace=False))
                sky[kind].append({"cls": name, "survey": survey, "idx": src[ii], "shift": shift[ii],
                                  "ra": ra[ii], "dec": dec[ii], "w": w[ii], "hours": hours[ii], "first": first[ii],
                                  "frac": len(ii) / max(int(sel_k.sum()), 1)})
            # source id unique across surveys (copies of one simulated object are fully correlated)
            objs.append(dict(w=w[r], hours=hours[r], first=first[r], nights=nnights[r],
                             src=src[r] + (len(objs) << 32), yr=yr[r]))
            # ALCeS reuses its random seeds across classes: object k of a run has the same (RA, Dec, t0) in every
            # class. Events sharing a draw (and the year-shifted copies of one object) fluctuate together, so
            # errors of sums over classes group them by (survey, RA, Dec) before squaring.
            draws.append(dict(key=np.stack([np.full(int(r.sum()), q.surveys.index(survey)),
                                            np.round(ra[r] * 1e6).astype(np.int64),
                                            np.round(dec[r] * 1e6).astype(np.int64)], axis=1),
                              w=w[r], fu=hours[r] > 0, yr=yr[r]))
        if not objs:
            continue
        o = {k: np.concatenate([x[k] for x in objs]) for k in objs[0]}
        fu = o["hours"] > 0

        def src_err(sel):
            """sqrt(sum over simulated objects of (sum of their copies' weights)^2)."""
            if not sel.any():
                return 0.0
            _, inv = np.unique(o["src"][sel], return_inverse=True)
            return float(np.sqrt((np.bincount(inv, weights=o["w"][sel]) ** 2).sum()))
        hh, he = _hist(o["hours"][fu], o["w"][fu], hours_bins)
        dh, de = _hist(o["first"][fu], o["w"][fu], delay_bins)
        nh, ne = _hist(o["nights"][fu], o["w"][fu], nights_bins)
        wf = o["w"][fu]

        def nsim_hist(x, bins):
            """distinct simulated objects per bin (folded copies of one object count once per bin)."""
            ib = np.digitize(x, bins) - 1
            ok = (ib >= 0) & (ib < len(bins) - 1)
            pairs = np.unique(np.stack([ib[ok], o["src"][fu][ok]]), axis=1) if ok.any() else np.zeros((2, 0), int)
            return np.bincount(pairs[0], minlength=len(bins) - 1)[: len(bins) - 1].astype(int).tolist()

        def wq(x, p):
            if not fu.any():
                return None
            s = np.argsort(x)
            c = np.cumsum(wf[s]) / wf.sum()
            return float(x[s][np.searchsorted(c, p)])
        per_class.append({
            "class": name, "n_sim_detected": n_sim_det, "n_sim_followable": int(len(np.unique(o["src"][fu]))),
            "n_instances_detected": n_inst_det, "n_instances_followable": int(fu.sum()),
            "N_detected": w_det, "N_detected_err": src_err(np.ones(len(fu), bool)),
            "N_followable": float(wf.sum()), "N_followable_err": src_err(fu),
            "frac_followable": float(wf.sum() / w_det) if w_det > 0 else None,
            "median_hours": wq(o["hours"][fu], 0.5), "median_nights": wq(o["nights"][fu], 0.5),
            "median_delay_days": wq(o["first"][fu], 0.5),
            "hist_hours": hh.tolist(), "hist_hours_err": he.tolist(),
            "hist_delay": dh.tolist(), "hist_delay_err": de.tolist(),
            "hist_nights": nh.tolist(), "hist_nights_err": ne.tolist(),
            "hist_hours_nsim": nsim_hist(o["hours"][fu], hours_bins),
            "hist_delay_nsim": nsim_hist(o["first"][fu], delay_bins),
            "hist_nights_nsim": nsim_hist(o["nights"][fu], nights_bins),
        })
        if q.fold_years:
            # the window's numbers as estimated from each survey year alone (copy weights x number of years used):
            # years that disagree beyond their errors are not equivalent for these cuts
            k = len(years_used)
            by = {"detected": [], "detected_err": [], "followable": [], "followable_err": [], "n_sim_followable": []}
            for y in years_used:
                sy = o["yr"] == y
                by["detected"].append(k * float(o["w"][sy].sum()))
                by["detected_err"].append(k * src_err(sy))
                by["followable"].append(k * float(o["w"][sy & fu].sum()))
                by["followable_err"].append(k * src_err(sy & fu))
                by["n_sim_followable"].append(int(len(np.unique(o["src"][sy & fu]))))
            per_class[-1]["by_year"] = by
        ts_class[name] = ts
        night_class[name] = night_w
        ts_total += ts

    # instantaneous counts on night steps inside [T0, T1]; thin to <= 6000 points for plotting
    sel = np.flatnonzero(in_win)
    thin = sel[:: max(1, len(sel) // 6000)] if len(sel) else sel
    nights = [int(n) for n in u_nights]
    night_series = {c: [night_class[c].get(n, 0.0) for n in nights] for c in night_class}
    totals = {k: float(sum(pc[k] for pc in per_class)) for k in ("N_detected", "N_followable")}
    totals.update({k: int(sum(pc[k] for pc in per_class)) for k in ("n_sim_detected", "n_sim_followable")})
    if draws:
        dk = np.concatenate([x["key"] for x in draws])
        dw = np.concatenate([x["w"] for x in draws])
        dfu = np.concatenate([x["fu"] for x in draws])
        dyr = np.concatenate([x["yr"] for x in draws])
    else:
        dk, dw, dfu, dyr = np.zeros((0, 3), np.int64), np.zeros(0), np.zeros(0, bool), np.zeros(0, int)

    def draw_err(sel, scale=1.0):
        """error of a sum over classes: weights of events sharing a simulated draw are added before squaring."""
        if not sel.any():
            return 0.0
        _, inv = np.unique(dk[sel], axis=0, return_inverse=True)
        return float(scale * np.sqrt((np.bincount(inv.ravel(), weights=dw[sel]) ** 2).sum()))
    totals["N_detected_err"] = draw_err(np.ones(len(dw), bool))
    totals["N_followable_err"] = draw_err(dfu)
    totals["n_shared_draws_followable"] = int(len(np.unique(dk[dfu], axis=0))) if dfu.any() else 0
    n_nights = len(nights)
    dark_hours = float(in_win.sum() * step / 60.0)
    by_year = None
    if q.fold_years and per_class:
        by_year = {"years": years_used, "survey_start_mjd": t_survey0}
        for key in ("detected", "followable", "n_sim_followable"):
            by_year[key] = np.sum([pc["by_year"][key] for pc in per_class], axis=0).tolist()
        k_years = len(years_used)
        by_year["detected_err"] = [draw_err(dyr == y, k_years) for y in years_used]
        by_year["followable_err"] = [draw_err((dyr == y) & dfu, k_years) for y in years_used]
        f, e = np.array(by_year["followable"]), np.array(by_year["followable_err"])
        # chi^2 of the per-year estimates around their weighted mean: >> dof means the years differ
        ok = e > 0
        if ok.sum() >= 2:
            mean = np.sum(f[ok] / e[ok] ** 2) / np.sum(1 / e[ok] ** 2)
            by_year["chi2"] = float(np.sum(((f[ok] - mean) / e[ok]) ** 2))
            by_year["dof"] = int(ok.sum() - 1)
    return {
        "query": q.__dict__, "step_min_used": step, "by_year": by_year,
        "sky": {k: _sky_table(v) for k, v in sky.items()},
        "airmass_dec_band": [max(-90.0, q.lat - (zmax_deg - 0.5)), min(90.0, q.lat + (zmax_deg - 0.5))],
        "n_nights": n_nights, "dark_hours": dark_hours, "window_days": span,
        "totals": totals,
        "per_night_mean": (sum(sum(v) for v in night_series.values()) / n_nights) if n_nights else 0.0,
        "classes": per_class,
        "bins": {"hours": hours_bins.tolist(), "delay": delay_bins.tolist(), "nights": nights_bins.tolist()},
        "timeseries": {"mjd": tn[thin].tolist(), "total": ts_total[thin].tolist(),
                       "by_class": {c: v[thin].tolist() for c, v in ts_class.items()}},
        # night label = MJD of the local noon that starts the night
        "nightly": {"night_mjd": [n + 0.5 - q.lon / 360.0 for n in nights], "by_class": night_series},
    }
