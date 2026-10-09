"""
Diagnostico de la confusion KN-K17 <-> KN-BULLA19 reportada por el equipo
externo que entrena los clasificadores (etiqueta = class_key). Separa tres
hipotesis:

  1. fisica      -- las dos grillas SED producen curvas casi iguales en ugrizy
  2. observacion -- LSST muestrea pocas epocas de un transiente de dias y borra
                    los rasgos que si las separan (color temprano, caida)
  3. datos       -- pocas detecciones por clase, misma config de z/tasa/polvo

Subcomandos (todos corren en NLHPC, dentro de SLURM -- ver
kn_confusion_diag.sbatch):

  templates  Nivel A: fotometria sintetica AB absoluta (10 pc) en reposo de
             CADA template de la grilla SIMSED real, rasgos por template, y
             un kNN leave-one-out K17 vs BULLA19 = techo de separabilidad con
             datos perfectos.
  observed   Nivel B: los mismos tipos de rasgos, pero sobre los objetos
             DETECTADOS de corridas reales de run_simsed_poc.main() con
             head_df/phot_df (ver kn_confusion_gen.sbatch), mas la accuracy
             del mismo kNN segun numero de detecciones.
  report     Junta los JSON de ambos niveles en kn_confusion_report.md.

El kNN es deliberadamente simple (numpy puro, sin sklearn -- el venv de
NLHPC no lo trae): no pretende reproducir el clasificador externo, solo
medir si la informacion para separar las clases EXISTE en cada nivel. La
clase de control (CaRT por defecto) valida el metodo: contra KN-K17 tiene
que dar accuracy alta, si no el problema es el metodo y no la fisica.

Uso:
    python3 kn_confusion_diag.py templates --out-dir kn_confusion_diag [--control CaRT]
    python3 kn_confusion_diag.py observed  --runs-dir kn_confusion_diag/runs --out-dir kn_confusion_diag
    python3 kn_confusion_diag.py report    --out-dir kn_confusion_diag
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PASSBAND_DIR = HERE / "lsst_passbands_local" / "LSST"
BANDS = ["u", "g", "r", "i", "z", "y"]
KN_CLASSES = ["KN-K17", "KN-BULLA19"]
C_AA_S = 2.99792458e18
FINE_WAVE = np.arange(3000.0, 11200.0, 5.0)
# Grilla comun de fase relativa al pico bolometrico (dias, reposo) para las
# bandas de curvas medianas de las figuras.
PHASE_GRID = np.arange(-2.0, 15.01, 0.25)
COLOR_PAIRS = [("g", "r"), ("r", "i"), ("i", "z")]
KNN_K = 5
M_FAINT_CUT = -5.0  # M_AB absoluta; mas debil = indetectable a z>=0.011 por ~10 mag


# --------------------------------------------------------------------------
# Nivel A: templates
# --------------------------------------------------------------------------

def load_passbands() -> dict[str, tuple[np.ndarray, float]]:
    """Transmision de cada banda interpolada a FINE_WAVE (A), y la integral
    de normalizacion AB  int T(l) c/l dl  sobre esa grilla. Mismos archivos
    locales que run_simsed_poc.py (u truncado a 4134 A, Fase 55)."""
    out = {}
    for b in BANDS:
        tab = np.loadtxt(PASSBAND_DIR / f"{b}.dat", comments="#")
        trans = np.interp(FINE_WAVE, tab[:, 0] * 10.0, tab[:, 1], left=0.0, right=0.0)
        norm = np.trapezoid(trans * C_AA_S / FINE_WAVE, FINE_WAVE)
        out[b] = (trans, norm)
    return out


def read_simsed_info(simsed_dir: Path) -> tuple[list[str], list[str], np.ndarray, float]:
    """Lineas SED: del SED.INFO real -> (archivos, nombres de parametros sin
    KN_INDEX, matriz de parametros, FLUX_SCALE)."""
    files, rows, parnames, flux_scale = [], [], [], 1.0
    for line in (simsed_dir / "SED.INFO").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("PARNAMES:"):
            parnames = line.split()[1:]
        elif line.startswith("FLUX_SCALE:"):
            flux_scale = float(line.split()[1])
        elif line.startswith("SED:"):
            tok = line.split()
            files.append(tok[1])
            rows.append([float(x) for x in tok[2:2 + len(parnames)]])
    params = np.array(rows)
    # KN_INDEX/primer parametro es solo un indice -- no es fisica.
    return files, parnames[1:], params[:, 1:], flux_scale


def read_sed_file(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not path.exists():
        path = path.with_name(path.name + ".gz")
    df = pd.read_csv(path, sep=r"\s+", comment="#", header=None, usecols=[0, 1, 2],
                     names=["day", "wave", "flux"], dtype=float)
    df = df.sort_values(["day", "wave"], kind="stable")
    days = np.unique(df["day"].to_numpy())
    waves = np.unique(df["wave"].to_numpy())
    if len(days) * len(waves) == len(df):
        flux = df["flux"].to_numpy().reshape(len(days), len(waves))
    else:
        flux = df.pivot_table(index="day", columns="wave", values="flux").to_numpy()
        flux = np.nan_to_num(flux, nan=0.0)
    return days, waves, np.clip(flux, 0.0, None)


def interp_matrix(x_src: np.ndarray, x_dst: np.ndarray) -> np.ndarray:
    """Matriz (len(x_dst), len(x_src)) de interpolacion lineal, 0 fuera de rango."""
    m = np.zeros((len(x_dst), len(x_src)))
    idx = np.searchsorted(x_src, x_dst) - 1
    ok = (idx >= 0) & (idx < len(x_src) - 1)
    i = idx[ok]
    w = (x_dst[ok] - x_src[i]) / (x_src[i + 1] - x_src[i])
    rows = np.nonzero(ok)[0]
    m[rows, i] = 1.0 - w
    m[rows, i + 1] = w
    return m


def template_lightcurves(path: Path, flux_scale: float, passbands) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Fase relativa al pico bolometrico (misma definicion que
    T0shiftPeak_SEDMODEL de SNANA: suma simple de flujo sobre lambda) y
    magnitud AB absoluta por banda (los SED de ambas grillas estan a 10 pc)."""
    days, waves, flux = read_sed_file(path)
    t0 = days[np.argmax(flux.sum(axis=1))]
    fine = flux_scale * flux @ interp_matrix(waves, FINE_WAVE).T
    mags = {}
    for b, (trans, norm) in passbands.items():
        # <f_nu> = int f_l T l dl / int T c/l dl
        fnu = np.trapezoid(fine * trans * FINE_WAVE, FINE_WAVE, axis=1) / norm
        with np.errstate(divide="ignore", invalid="ignore"):
            m = np.where(fnu > 0, -2.5 * np.log10(fnu) - 48.6, np.nan)
        # Flujo residual numerico (K17 trae valores ~1e-105 tarde) daria M~+600;
        # mas debil que M_FAINT_CUT es "sin flujo" para cualquier fin practico.
        mags[b] = np.where(m < M_FAINT_CUT, m, np.nan)
    return days - t0, mags


def _interp_mag(phase: np.ndarray, mag: np.ndarray, t: float) -> float:
    ok = np.isfinite(mag)
    if ok.sum() < 2 or t < phase[ok][0] or t > phase[ok][-1]:
        return np.nan
    return float(np.interp(t, phase[ok], mag[ok]))


def template_features(phase: np.ndarray, mags: dict[str, np.ndarray]) -> dict[str, float]:
    f: dict[str, float] = {}
    for b in BANDS:
        m = mags[b]
        if not np.isfinite(m).any():
            continue
        k = int(np.nanargmin(m))
        f[f"Mpk_{b}"] = float(m[k])
        f[f"tpk_{b}"] = float(phase[k])
        for dt in (3, 7):
            f[f"dm{dt}_{b}"] = _interp_mag(phase, m, phase[k] + dt) - m[k]
        above = phase[np.isfinite(m) & (m <= m[k] + 1.0)]
        f[f"dur1mag_{b}"] = float(above[-1] - above[0]) if len(above) else np.nan
    for b1, b2 in COLOR_PAIRS:
        for dt in (0, 3, 7):
            f[f"{b1}-{b2}@{dt}"] = _interp_mag(phase, mags[b1], dt) - _interp_mag(phase, mags[b2], dt)
    return f


def _featurize_one(args):
    path, flux_scale, passbands = args
    phase, mags = template_lightcurves(path, flux_scale, passbands)
    curves = np.array([[_interp_mag(phase, mags[b], t) for t in PHASE_GRID] for b in BANDS])
    return template_features(phase, mags), curves


def class_simsed_dir(class_key: str) -> Path:
    # Import diferido: run_simsed_poc arrastra lightcurvelynx (solo existe en
    # el venv de NLHPC); el nivel B y el report no lo necesitan.
    from run_simsed_poc import CLASS_CONFIGS
    return Path(CLASS_CONFIGS[class_key]["simsed_dir"])


M_LIM_SINGLE_VISIT = 24.0  # aproximado, visita DDF tipica en g/r/i


def detectable_volume_weight(df: pd.DataFrame) -> np.ndarray:
    """Fraccion del volumen comovil de generacion (GENRANGE_REDSHIFT real de
    la clase, H0=70/Om=0.3) donde el pico del template en su mejor banda
    g/r/i queda sobre M_LIM_SINGLE_VISIT. Aproximacion gruesa -- sin
    k-correccion, sin cadencia ni trigger -- solo para no pesar igual un
    template de M=-9 que nunca se detecta y uno de M=-16. El nivel B mide
    la seleccion real."""
    from astropy.cosmology import FlatLambdaCDM
    from run_simsed_poc import CLASS_CONFIGS
    cosmo = FlatLambdaCDM(H0=70, Om0=0.3)
    zgrid = np.linspace(0.0, 1.5, 3001)
    mu = np.concatenate([[-np.inf], cosmo.distmod(zgrid[1:]).value])
    vc = cosmo.comoving_volume(zgrid).value
    m_best = df[["Mpk_g", "Mpk_r", "Mpk_i"]].min(axis=1).to_numpy()
    out = np.zeros(len(df))
    for i, (cls, mabs) in enumerate(zip(df["class_key"], m_best)):
        zlo, zhi = CLASS_CONFIGS[cls]["genrange_redshift"]
        if not np.isfinite(mabs):
            continue
        z_lim = float(np.interp(M_LIM_SINGLE_VISIT - mabs, mu[1:], zgrid[1:]))
        z_eff = np.clip(z_lim, zlo, zhi)
        v = lambda z: np.interp(z, zgrid, vc)  # noqa: E731
        out[i] = (v(z_eff) - v(zlo)) / (v(zhi) - v(zlo))
    return out


def run_templates(out_dir: Path, classes: list[str], workers: int, limit: int | None) -> None:
    passbands = load_passbands()
    frames, curves_by_class = [], {}
    for cls in classes:
        simsed_dir = class_simsed_dir(cls)
        files, parnames, params, flux_scale = read_simsed_info(simsed_dir)
        if limit:
            sel = np.linspace(0, len(files) - 1, min(limit, len(files))).astype(int)
            files, params = [files[i] for i in sel], params[sel]
        jobs = [(simsed_dir / f, flux_scale, passbands) for f in files]
        print(f"[templates] {cls}: {len(jobs)} templates desde {simsed_dir}", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_featurize_one, jobs, chunksize=4))
        feats = pd.DataFrame([r[0] for r in results])
        feats.insert(0, "class_key", cls)
        feats.insert(1, "template", files)
        for j, name in enumerate(parnames):
            feats[f"par_{name}"] = params[:, j]
        frames.append(feats)
        curves_by_class[cls] = np.stack([r[1] for r in results])
    df = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / "templates_curves.npz", phase=PHASE_GRID, bands=BANDS,
                        **{c.replace("-", "_"): v for c, v in curves_by_class.items()})

    df["vol_weight"] = detectable_volume_weight(df)
    feat_cols = [c for c in df.columns
                 if c not in ("class_key", "template", "vol_weight") and not c.startswith("par_")]
    summary = {"n_templates": df["class_key"].value_counts().to_dict(),
               "pairs": separability_pairs(df, feat_cols, classes),
               "pairs_volume_weighted": separability_pairs(df, feat_cols, classes, weight_col="vol_weight"),
               "frac_templates_vol_weight_gt_0.05": df.groupby("class_key")["vol_weight"]
                   .apply(lambda w: round(float((w > 0.05).mean()), 3)).to_dict(),
               "feature_auc_kn": feature_auc(df, feat_cols, *KN_CLASSES)}
    df.to_csv(out_dir / "templates_features.csv", index=False)
    (out_dir / "templates_summary.json").write_text(json.dumps(summary, indent=2))
    plot_templates(df, curves_by_class, out_dir)
    print(json.dumps(summary["pairs"], indent=2))


# --------------------------------------------------------------------------
# Separabilidad (numpy puro)
# --------------------------------------------------------------------------

def _prepare_matrix(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Estandariza; NaN -> mediana + indicador de faltante (la falta de un
    rasgo, p.ej. color sin pares en la misma noche, tambien es informacion)."""
    x = df[cols].to_numpy(dtype=float)
    miss = ~np.isfinite(x)
    med = np.nanmedian(np.where(miss, np.nan, x), axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    x = np.where(miss, med, x)
    sd = x.std(axis=0)
    x = (x - x.mean(axis=0)) / np.where(sd > 0, sd, 1.0)
    miss_cols = miss[:, miss.any(axis=0) & ~miss.all(axis=0)].astype(float)
    return np.hstack([x, miss_cols]) if miss_cols.size else x


def knn_loo_balanced_accuracy(x: np.ndarray, y: np.ndarray, k: int = KNN_K) -> tuple[float, np.ndarray]:
    """kNN leave-one-out con voto ponderado por el inverso del tamano de
    clase (las grillas no tienen el mismo numero de templates). Devuelve
    (balanced accuracy, prediccion por fila)."""
    classes, y_idx = np.unique(y, return_inverse=True)
    w_class = 1.0 / np.bincount(y_idx)
    d2 = ((x[:, None, :] - x[None, :, :]) ** 2).sum(-1) if len(x) <= 4000 else None
    pred = np.empty(len(x), dtype=int)
    for i in range(len(x)):
        di = d2[i] if d2 is not None else ((x - x[i]) ** 2).sum(-1)
        di = di.copy()
        di[i] = np.inf
        nn = np.argpartition(di, k)[:k]
        votes = np.bincount(y_idx[nn], weights=w_class[y_idx[nn]], minlength=len(classes))
        pred[i] = int(np.argmax(votes))
    recall = [np.mean(pred[y_idx == c] == c) for c in range(len(classes))]
    return float(np.mean(recall)), classes[pred]


def separability_pairs(df: pd.DataFrame, cols: list[str], classes: list[str],
                       weight_col: str | None = None) -> dict:
    """KN-K17 vs cada otra clase: balanced accuracy kNN y matriz de confusion.
    Con weight_col, el kNN se entrena igual pero el recall de cada clase se
    pondera por esa columna (p.ej. volumen detectable del template)."""
    out = {}
    ref = classes[0]
    for other in classes[1:]:
        sub = df[df["class_key"].isin([ref, other])].reset_index(drop=True)
        usable = [c for c in cols if sub[c].notna().mean() > 0.2]
        x = _prepare_matrix(sub, usable)
        y = sub["class_key"].to_numpy()
        bacc, pred = knn_loo_balanced_accuracy(x, y)
        w = sub[weight_col].to_numpy() if weight_col else np.ones(len(sub))
        cm = (pd.DataFrame({"true": y, "pred": pred, "w": w})
              .pivot_table(index="true", columns="pred", values="w", aggfunc="sum", fill_value=0.0))
        cm = cm.div(cm.sum(axis=1), axis=0)
        if weight_col:
            bacc = float(np.mean([cm.at[c, c] if c in cm.columns else 0.0 for c in cm.index]))
        out[f"{ref} vs {other}"] = {"balanced_accuracy": round(bacc, 3), "n": len(sub),
                                    "confusion_row_norm": cm.round(3).to_dict(orient="index")}
    return out


def feature_auc(df: pd.DataFrame, cols: list[str], a: str, b: str) -> dict[str, float]:
    """AUC univariada (Mann-Whitney) de cada rasgo para a vs b, ordenada por
    |AUC-0.5|. 0.5 = el rasgo no separa nada; 0/1 = separa perfecto."""
    out = {}
    for c in cols:
        xa = df.loc[df["class_key"] == a, c].dropna().to_numpy()
        xb = df.loc[df["class_key"] == b, c].dropna().to_numpy()
        if len(xa) < 5 or len(xb) < 5:
            continue
        ranks = pd.Series(np.concatenate([xa, xb])).rank().to_numpy()
        auc = (ranks[:len(xa)].sum() - len(xa) * (len(xa) + 1) / 2) / (len(xa) * len(xb))
        out[c] = round(float(auc), 3)
    return dict(sorted(out.items(), key=lambda kv: -abs(kv[1] - 0.5)))


# --------------------------------------------------------------------------
# Nivel B: objetos detectados de corridas reales
# --------------------------------------------------------------------------

RUN_DIR_RE = re.compile(r"^(?P<cls>.+)_seed(?P<seed>\d+)$")


def load_runs(runs_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    heads, phots = [], []
    for run in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        m = RUN_DIR_RE.match(run.name)
        if not m or not (run / "phot_df.parquet").exists():
            continue
        uid = run.name
        h = pd.read_parquet(run / "head_df.parquet")
        p = pd.read_parquet(run / "phot_df.parquet")
        h = h[h["DETECTED"]].copy()
        p = p[p["SNID"].isin(h["SNID"])].copy()
        h["class_key"], h["run"] = m["cls"], uid
        p["run"] = uid
        heads.append(h)
        phots.append(p)
        print(f"[observed] {uid}: {len(h)} detectados", flush=True)
    return pd.concat(heads, ignore_index=True), pd.concat(phots, ignore_index=True)


def object_features(p: pd.DataFrame) -> dict[str, float]:
    snr = p["FLUXCAL"] / p["FLUXCALERR"]
    det = (p["PHOTFLAG"].to_numpy() & 4096) > 0
    good = (snr > 3).to_numpy() & np.isfinite(p["MAG"].to_numpy())
    # DDF toma secuencias de muchas exposiciones por noche: n_det cuenta
    # exposiciones, n_det_nights cuenta noches distintas (la "epoca" real).
    nights = np.floor(p.loc[det, "MJD"].to_numpy() - 0.5)
    f = {"n_obs": len(p), "n_det": int(det.sum()), "n_det_nights": int(len(np.unique(nights))),
         "n_snr3": int(good.sum()),
         "n_det_bands": int(p.loc[det, "FLT"].nunique()),
         "det_span_d": float(np.ptp(p.loc[det, "MJD"])) if det.any() else 0.0,
         "max_snr": float(snr.max())}
    g = p[good]
    if len(g):
        kbest = g["MAG"].idxmin()
        f["mag_brightest"] = float(g.at[kbest, "MAG"])
        t_best = g.at[kbest, "MJD"]
        # Pendiente post-maximo (mag/dia) por banda, promediada entre bandas
        # con >=2 puntos SNR>3 despues del punto mas brillante.
        slopes = []
        for _, gb in g[g["MJD"] >= t_best - 0.5].groupby("FLT"):
            if len(gb) >= 2 and np.ptp(gb["MJD"]) > 0.5:
                slopes.append(np.polyfit(gb["MJD"], gb["MAG"], 1)[0])
        f["decline_mag_per_d"] = float(np.mean(slopes)) if slopes else np.nan
        # Colores con pares SNR>3 de la misma noche (|dMJD| < 0.1 d).
        for b1, b2 in COLOR_PAIRS:
            g1 = g[g["FLT"] == b1.replace("y", "Y")]
            g2 = g[g["FLT"] == b2.replace("y", "Y")]
            vals = []
            for _, r1 in g1.iterrows():
                dt = (g2["MJD"] - r1["MJD"]).abs()
                if len(dt) and dt.min() < 0.1:
                    vals.append(r1["MAG"] - g2.loc[dt.idxmin(), "MAG"])
            f[f"obs_{b1}-{b2}"] = float(np.mean(vals)) if vals else np.nan
    return f


def run_observed(runs_dir: Path, out_dir: Path) -> None:
    head, phot = load_runs(runs_dir)
    feats = []
    for (run, snid), p in phot.groupby(["run", "SNID"], sort=False):
        f = object_features(p.sort_values("MJD"))
        f["run"], f["SNID"] = run, snid
        feats.append(f)
    df = head[["run", "SNID", "class_key", "REDSHIFT_HELIO", "PEAKMJD"]].merge(
        pd.DataFrame(feats), on=["run", "SNID"], how="left")
    # PEAKMJD significa cosas distintas por clase: K17 = pico bolometrico
    # (shift de SNANA), BULLA19 = t de fusion (OPTFLAG_T0SHIFT_PEAKMAG: 0).
    # Se reporta, pero NO entra como rasgo.
    first_det = phot[(phot["PHOTFLAG"] & 4096) > 0].groupby(["run", "SNID"])["MJD"].min().rename("first_det_mjd")
    df = df.merge(first_det.reset_index(), on=["run", "SNID"], how="left")
    df["first_det_minus_PEAKMJD"] = df["first_det_mjd"] - df["PEAKMJD"]
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "observed_features.csv", index=False)

    classes = [c for c in KN_CLASSES if c in set(df["class_key"])]
    classes += sorted(set(df["class_key"]) - set(KN_CLASSES))
    lc_cols = ["n_det", "n_det_nights", "n_snr3", "n_det_bands", "det_span_d", "max_snr", "mag_brightest",
               "decline_mag_per_d"] + [f"obs_{a}-{b}" for a, b in COLOR_PAIRS]
    summary = {
        "n_detected": df["class_key"].value_counts().to_dict(),
        "pairs_lc_only": separability_pairs(df, lc_cols, classes),
        "pairs_lc_plus_z": separability_pairs(df, lc_cols + ["REDSHIFT_HELIO"], classes),
        "feature_auc_kn": feature_auc(df, lc_cols + ["REDSHIFT_HELIO"], *KN_CLASSES),
        "by_n_det_kn": accuracy_by_n_det(df, lc_cols, KN_CLASSES),
        "medians": df.groupby("class_key")[lc_cols + ["REDSHIFT_HELIO", "first_det_minus_PEAKMJD"]]
                     .median().round(3).to_dict(orient="index"),
        "frac_missing": df.groupby("class_key")[lc_cols].apply(lambda g: g.isna().mean())
                          .round(3).to_dict(orient="index"),
    }
    (out_dir / "observed_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    plot_observed(df, lc_cols, out_dir)
    print(json.dumps({k: summary[k] for k in ("n_detected", "pairs_lc_only", "by_n_det_kn")}, indent=2))


def accuracy_by_n_det(df: pd.DataFrame, cols: list[str], classes: list[str]) -> dict:
    """kNN entrenado con TODOS los objetos KN, accuracy evaluada por bin de
    noches distintas con deteccion (cuanto mejora al haber mas epocas)."""
    sub = df[df["class_key"].isin(classes)].reset_index(drop=True)
    if sub["class_key"].nunique() < 2:
        return {}
    usable = [c for c in cols if sub[c].notna().mean() > 0.2]
    _, pred = knn_loo_balanced_accuracy(_prepare_matrix(sub, usable), sub["class_key"].to_numpy())
    sub["correct"] = pred == sub["class_key"].to_numpy()
    bins = pd.cut(sub["n_det_nights"], [0, 1, 2, 3, 5, 1e9], labels=["1", "2", "3", "4-5", "6+"])
    out = {}
    for label, g in sub.groupby(bins, observed=True):
        rec = g.groupby("class_key")["correct"].mean()
        out[str(label)] = {"n": len(g), "balanced_accuracy": round(float(rec.mean()), 3),
                           **{f"recall_{c}": round(float(v), 3) for c, v in rec.items()}}
    return out


# --------------------------------------------------------------------------
# Figuras
# --------------------------------------------------------------------------

COLORS = {"KN-K17": "#2a6fdb", "KN-BULLA19": "#e0592a"}


def _color(cls: str) -> str:
    return COLORS.get(cls, "#666666")


def plot_templates(df: pd.DataFrame, curves: dict[str, np.ndarray], out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(13, 7), sharex=True)
    for ax, b in zip(axes.flat, BANDS):
        j = BANDS.index(b)
        for cls in KN_CLASSES:
            if cls not in curves:
                continue
            c = curves[cls][:, j, :]
            lo, med, hi = np.nanpercentile(c, [10, 50, 90], axis=0)
            ax.fill_between(PHASE_GRID, lo, hi, color=_color(cls), alpha=0.25)
            ax.plot(PHASE_GRID, med, color=_color(cls), label=cls)
        ax.set_title(f"banda {b}")
        ax.invert_yaxis()
    axes[0, 0].legend()
    for ax in axes[1]:
        ax.set_xlabel("dias desde pico bolometrico (reposo)")
    for ax in axes[:, 0]:
        ax.set_ylabel("M_AB")
    fig.suptitle("Templates: mediana y banda 10-90% por grilla")
    fig.tight_layout()
    fig.savefig(out_dir / "A_template_lightcurves.png", dpi=120)
    plt.close(fig)

    kn = df[df["class_key"].isin(KN_CLASSES)]
    pairs = [("Mpk_r", "dm7_r"), ("g-r@0", "r-i@3"), ("Mpk_i", "dur1mag_i"), ("g-r@3", "dm3_g")]
    fig, axes = plt.subplots(1, len(pairs), figsize=(4.2 * len(pairs), 4))
    for ax, (xc, yc) in zip(axes, pairs):
        for cls, g in kn.groupby("class_key"):
            ax.scatter(g[xc], g[yc], s=8, alpha=0.5, color=_color(cls), label=cls)
        ax.set_xlabel(xc)
        ax.set_ylabel(yc)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(out_dir / "A_template_feature_planes.png", dpi=120)
    plt.close(fig)


def plot_observed(df: pd.DataFrame, cols: list[str], out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    show = cols + ["REDSHIFT_HELIO", "first_det_minus_PEAKMJD"]
    ncol = 4
    nrow = int(np.ceil(len(show) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 3 * nrow))
    for ax, c in zip(axes.flat, show):
        vals = df[c].dropna()
        if vals.empty:
            ax.set_visible(False)
            continue
        # recorte al percentil 1-99: unas pocas CaRT con miles de exposiciones
        # aplastaban el resto del histograma
        edges = np.histogram_bin_edges(vals.clip(*vals.quantile([0.01, 0.99])), bins=25)
        for cls, g in df.groupby("class_key"):
            ax.hist(g[c].dropna().clip(edges[0], edges[-1]), bins=edges, density=True, histtype="step", lw=1.5,
                    color=_color(cls), label=cls)
        ax.set_title(c, fontsize=9)
    for ax in list(axes.flat)[len(show):]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "B_observed_feature_hists.png", dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------

def run_report(out_dir: Path) -> None:
    lines = ["# Diagnostico KN-K17 vs KN-BULLA19", ""]
    a_path, b_path = out_dir / "templates_summary.json", out_dir / "observed_summary.json"
    if a_path.exists():
        a = json.loads(a_path.read_text())
        lines += ["## A. Templates (sin observacion)", "",
                  f"Templates por clase: {a['n_templates']}", "",
                  "| par | bal. acc. kNN (LOO), grilla uniforme | idem, ponderado por volumen detectable | n |",
                  "|---|---|---|---|"]
        lines += [f"| {k} | {v['balanced_accuracy']} | "
                  f"{a['pairs_volume_weighted'][k]['balanced_accuracy']} | {v['n']} |"
                  for k, v in a["pairs"].items()]
        lines += ["", f"Fraccion de templates con peso de volumen > 0.05: "
                      f"{a['frac_templates_vol_weight_gt_0.05']}"]
        lines += ["", "Rasgos mas discriminantes K17 vs BULLA19 (AUC univariada, 0.5 = no separa):", ""]
        lines += [f"- `{k}`: {v}" for k, v in list(a["feature_auc_kn"].items())[:10]]
        lines += ["", "![](A_template_lightcurves.png)", "", "![](A_template_feature_planes.png)", ""]
    if b_path.exists():
        b = json.loads(b_path.read_text())
        lines += ["## B. Objetos detectados (corridas reales)", "",
                  f"Detectados por clase: {b['n_detected']}", "",
                  "| par | bal. acc. (curva) | bal. acc. (curva + z) |", "|---|---|---|"]
        for k, v in b["pairs_lc_only"].items():
            lines.append(f"| {k} | {v['balanced_accuracy']} | "
                         f"{b['pairs_lc_plus_z'][k]['balanced_accuracy']} |")
        lines += ["", "K17 vs BULLA19 segun noches distintas con deteccion:", "",
                  "| noches | n | bal. acc. |", "|---|---|---|"]
        lines += [f"| {k} | {v['n']} | {v['balanced_accuracy']} |" for k, v in b["by_n_det_kn"].items()]
        lines += ["", "Rasgos observados mas discriminantes (AUC):", ""]
        lines += [f"- `{k}`: {v}" for k, v in list(b["feature_auc_kn"].items())[:8]]
        lines += ["", "Medianas por clase:", "", "```", json.dumps(b["medians"], indent=1), "```",
                  "", "![](B_observed_feature_hists.png)", ""]
    (out_dir / "kn_confusion_report.md").write_text("\n".join(lines))
    print(f"-> {out_dir / 'kn_confusion_report.md'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("templates")
    t.add_argument("--out-dir", type=Path, required=True)
    t.add_argument("--control", nargs="*", default=["CaRT"])
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--limit", type=int, default=None, help="submuestra de templates por clase (prueba)")
    o = sub.add_parser("observed")
    o.add_argument("--runs-dir", type=Path, required=True)
    o.add_argument("--out-dir", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "templates":
        run_templates(args.out_dir, KN_CLASSES + args.control, args.workers, args.limit)
    elif args.cmd == "observed":
        run_observed(args.runs_dir, args.out_dir)
    else:
        run_report(args.out_dir)


if __name__ == "__main__":
    main()
