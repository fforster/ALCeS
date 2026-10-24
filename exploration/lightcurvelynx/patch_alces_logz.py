"""Flat-log-z mode for the ALCeS sweep system (run on Leftraru, in exploration/lightcurvelynx/).

LSST_sim_lcs, 2026-10-05 -- see docs/logz_flat_mode.md. Adds to run_simsed_poc.py (one of sweep_hash.CODE_FILES):

  * derived classes "<base>|logz|<DDF|WFD>|w<k>" read from logz_configs.json (written by LSST_sim_lcs/tools/logz/
    plan_wave.py): the base class config with
      - dndz ("logz_piecewise", {edges, weights}): generation density piecewise constant in ln z (weights per bin);
      - genrange_redshift = (edges[0], edges[-1]);
      - keep_detected_only = True;
      - host_av = WV07 (A_V 0-3, R_V 3.1) when the entry asks for it and the base class has none;
  * dndz kind "logz_piecewise" in build_source_model();
  * main(), when keep_detected_only: gen_df.parquet with ALL generated objects (SNID, z, t0, RA, DEC, NOBS, MWEBV,
    HOST_AV, HOST_RV, SALT2_x1, SALT2_c, DETECTED) and head_df/phot_df restricted to the detected objects
    (head_df also gets MWEBV / HOST_AV / HOST_RV / SALT2_*). The survey mode of a derived class must match --wfd.

Backups: *.bak_logz_20261005.

    python3 patch_alces_logz.py
"""
import shutil
from pathlib import Path

HERE = Path.cwd()
TAG = "bak_logz_20261005"


def patch(path, pairs):
    p = HERE / path
    s = p.read_text()
    if "logz_piecewise" in s:
        print(f"{path}: already patched")
        return
    for a, b in pairs:
        assert s.count(a) == 1, (path, a[:90], s.count(a))
        s = s.replace(a, b)
    bak = p.with_suffix(p.suffix + "." + TAG)
    if not bak.exists():
        shutil.copy2(p, bak)
    p.write_text(s)
    print(f"{path}: patched (backup {bak.name})")


REGISTRY = '''


# --- flat-log-z mode (LSST_sim_lcs 2026-10-05, docs/logz_flat_mode.md) ---------------------------------------------
# Derived classes "<base>|logz|<DDF|WFD>|w<k>" from logz_configs.json (written by LSST_sim_lcs/tools/logz/plan_wave.py).
# Each is the base config with a piecewise log-z generation density, the class-mode redshift range, detected-only
# photometry plus gen_df.parquet (all generated objects), and WV07 host extinction when asked for and absent in the base.
LOGZ_CONFIGS_FILE = HERE / "logz_configs.json"
LOGZ_HOST_AV = dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1)


def _load_logz_configs():
    if not LOGZ_CONFIGS_FILE.exists():
        return
    for key, e in json.loads(LOGZ_CONFIGS_FILE.read_text()).items():
        base = CLASS_CONFIGS[e["base"]]
        cfg = {**base, "dndz": ("logz_piecewise", {"edges": list(e["edges"]), "weights": list(e["weights"])}),
               "genrange_redshift": (float(e["edges"][0]), float(e["edges"][-1])), "keep_detected_only": True,
               "logz": {"base": e["base"], "mode": e["mode"], "wave": int(e["wave"])}}
        if e.get("add_host_dust") and "host_av" not in base:
            cfg["host_av"] = dict(LOGZ_HOST_AV)
        CLASS_CONFIGS[key] = cfg


_load_logz_configs()


def _flat_params(lc):
    """Leaf arrays of the per-object parameter struct returned by simulate_lightcurves (lc["params"]), keyed
    "node.param" (same naming as GraphState.to_dict())."""
    import pyarrow as pa
    arr = lc["params"].array
    pa_arr = getattr(arr, "_pa_array", None)
    pa_arr = pa.array(arr) if pa_arr is None else pa_arr
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()
    out = {}

    def walk(a, prefix):
        if pa.types.is_struct(a.type):
            for i, f in enumerate(a.type):
                walk(a.field(i), f"{prefix}.{f.name}" if prefix else f.name)
        else:
            try:
                out[prefix] = a.to_numpy(zero_copy_only=False)
            except Exception:  # noqa: BLE001 -- non-numeric leaves are not needed
                pass

    walk(pa_arr, "")
    return out


def _pick_param(flat, *names):
    for name in names:
        for k, v in flat.items():
            if k == name or k.endswith("." + name):
                return v
    return None


def logz_gen_df(lc, cfg, detected_snids):
    """All generated objects of a flat-log-z run: redshift, attenuation (MW and host) and detection flag."""
    flat = _flat_params(lc)
    n = len(lc)
    nan = np.full(n, np.nan)
    hp = cfg.get("host_av")
    gen = pd.DataFrame({
        "SNID": lc["id"].astype(int).astype(str).to_numpy(), "REDSHIFT_HELIO": lc["z"].to_numpy(),
        "PEAKMJD": lc["t0"].to_numpy(), "RA": lc["ra"].to_numpy(), "DEC": lc["dec"].to_numpy(),
        "NOBS": lc["nobs"].to_numpy() if "nobs" in lc else nan,
        "MWEBV": _pick_param(flat, "ebv.function_node_result"),
        "HOST_AV": _pick_param(flat, "host_av.function_node_result") if hp else np.zeros(n),
        "HOST_RV": np.full(n, hp["r_v"]) if hp else nan,
        "SALT2_x1": _pick_param(flat, "x1.function_node_result"),
        "SALT2_c": _pick_param(flat, "c.function_node_result"),
    })
    for col in ("MWEBV", "SALT2_x1", "SALT2_c"):
        if gen[col].isna().all() and not (col.startswith("SALT2") and cfg.get("model") != "salt2"):
            print(f"  ! logz gen_df: {col} not found among {sorted(flat)[:40]}")
    if hp and gen["HOST_AV"].isna().all():
        print(f"  ! logz gen_df: HOST_AV not found among {sorted(flat)[:40]}")
    gen["DETECTED"] = gen["SNID"].isin(set(detected_snids))
    return gen
'''

DNDZ_BRANCH = '''    elif dndz_kind == "logz_piecewise":
        # flat-log-z mode: density piecewise constant in ln z with the given per-bin weights; CDF on a fine ln-z grid
        e = np.asarray(dndz_params["edges"], dtype=float)
        wts = np.asarray(dndz_params["weights"], dtype=float) + 1e-12      # strictly increasing CDF
        cdf_e = np.concatenate([[0.0], np.cumsum(wts)]) / wts.sum()
        lnz = np.linspace(np.log(e[0]), np.log(e[-1]), 40001)
        z_grid, cdf = np.exp(lnz), np.interp(lnz, np.log(e), cdf_e)
    else:
        raise ValueError(f"dndz_kind desconocido: {dndz_kind}")'''

MAIN_CHECK = '''    cfg = CLASS_CONFIGS[class_key]
    if cfg.get("logz") and (cfg["logz"]["mode"] == "WFD") != bool(wfd):
        raise ValueError(f"{class_key}: flat-log-z class for {cfg['logz']['mode']} run with wfd={wfd}")'''

WRITE = '''    head_df["DETECTED"] = head_df["SNID"].isin(detected_snids)
    if cfg.get("keep_detected_only"):
        # flat-log-z mode: all generated objects (z, attenuation, detection) in gen_df; photometry of detected only
        gen_df = logz_gen_df(lc, cfg, detected_snids)
        gen_df.to_parquet(out_dir / "gen_df.parquet", index=False)
        extra = gen_df[["SNID", "MWEBV", "HOST_AV", "HOST_RV", "SALT2_x1", "SALT2_c"]]
        head_df = head_df[head_df["DETECTED"]].merge(extra, on="SNID", how="left").reset_index(drop=True)
        phot_df = phot_df[phot_df["SNID"].isin(set(detected_snids))].reset_index(drop=True)
        print(f"[{time.time()-t_start:.1f}s] logz: gen_df.parquet ({len(gen_df)} generated, "
              f"{int(gen_df.DETECTED.sum())} detected); head/phot restricted to detected")
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)'''

patch("run_simsed_poc.py", [
    ("\n}\n\n\ndef snana_noise_columns", "\n}" + REGISTRY + "\n\ndef snana_noise_columns"),
    ('''    else:
        raise ValueError(f"dndz_kind desconocido: {dndz_kind}")''', DNDZ_BRANCH),
    ("    cfg = CLASS_CONFIGS[class_key]\n    # la mayoria de las clases DDF", MAIN_CHECK + "\n    # la mayoria de las clases DDF"),
    ('''    head_df["DETECTED"] = head_df["SNID"].isin(detected_snids)
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)''', WRITE),
])
