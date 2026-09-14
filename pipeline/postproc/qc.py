"""
qc.py — Control de calidad automatico (los 4 graficos del poster).

Cada funcion recibe head_df / phot_df y genera un grafico guardado en disco.
Usa matplotlib con el tema nocturno LSST y los colores de banda ugrizY.

    1. redshift_distribution    — z simulado vs z detectado, por clase
    2. magnitude_histograms     — histograma de mag A-B por banda
    3. detection_distribution   — nro de detecciones por objeto
    4. sample_lightcurves       — curvas de luz de los objetos mas brillantes (FLUXCAL pico mas alto)

Ademas:
    5. run_all_qc               — corre los 4 y devuelve las rutas
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# lazy matplotlib (no se importa a nivel de modulo para no forzar backend)
_MPL_LOADED = False

# colores LSST por banda
BAND_COLORS = {
    "u": "#8a6df0", "g": "#38b6a0", "r": "#e0b23c",
    "i": "#e07b3c", "z": "#d9525f", "Y": "#a83a55", "y": "#a83a55",
}
_BG = "#070a18"
_PANEL = "#111834"
_LINE = "#24305c"
_INK = "#eaeefb"
_INK_DIM = "#9aa4cc"
_ACCENT = "#5ed6cd"


def _setup_style():
    global _MPL_LOADED
    if _MPL_LOADED:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": _BG,
        "axes.facecolor": _PANEL,
        "axes.edgecolor": _LINE,
        "axes.labelcolor": _INK_DIM,
        "text.color": _INK,
        "xtick.color": _INK_DIM,
        "ytick.color": _INK_DIM,
        "grid.color": _LINE,
        "grid.alpha": 0.5,
        "font.family": "sans-serif",
        "font.size": 10,
        "legend.facecolor": _PANEL,
        "legend.edgecolor": _LINE,
        "legend.fontsize": 8,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.facecolor": _BG,
    })
    _MPL_LOADED = True


# ------------------------------------------------------------------ 1. redshift
def redshift_zmax_stats(
    dump_df: pd.DataFrame | None,
    head_df: pd.DataFrame,
    *,
    snid_col: str = "SNID",
) -> dict:
    """Fase 90: mismo calculo de columna ZCMB + filtro de centinela -9 que
    ya usa `redshift_distribution()` para el texto quemado en el PNG
    (z_max simulado/detectado) -- extraido aca para que el grafico y
    `summary.json` usen EXACTAMENTE el mismo numero, sin duplicar la
    deteccion de columna. Pura (sin matplotlib, sin I/O) a proposito: la
    llama `run_simsed_poc.py::main` antes de escribir `summary.json`.

    Devuelve {} si no hay `dump_df` utilizable (p.ej. SELECTION != NONE,
    el unico caso real donde existe el .DUMP completo de eventos
    generados) -- el llamador decide que hacer con un dict vacio."""
    zcmb_col = next((c for c in (dump_df.columns if dump_df is not None else []) if "ZCMB" in c.upper()
                      and "SMEAR" not in c.upper()), None)
    if dump_df is None or dump_df.empty or not zcmb_col or "CID" not in dump_df.columns:
        return {}

    # SNANA usa -9 como centinela de "no definido" -- se descarta antes de
    # medir (son ~0.1% de los eventos, no una senal real).
    dump_df = dump_df[dump_df[zcmb_col] > -1]
    if dump_df.empty:
        return {}
    detected_cids = set(head_df[snid_col].astype(str)) if snid_col in head_df.columns else set()
    detected_mask = dump_df["CID"].astype(str).isin(detected_cids)
    n_det = int(detected_mask.sum())

    return {
        "z_max_simulado": float(dump_df[zcmb_col].max()),
        "n_simulado": int(len(dump_df)),
        "z_max_detectado": float(dump_df.loc[detected_mask, zcmb_col].max()) if n_det else None,
        "n_detectado": n_det,
    }


def redshift_distribution(
    head_df: pd.DataFrame,
    out_path: str | Path,
    *,
    dump_df: pd.DataFrame | None = None,
    z_sim_col: str = "REDSHIFT_HELIO",
    z_det_col: str = "REDSHIFT_FINAL",
    type_col: str = "SNTYPE",
    bins: int = 40,
) -> Path:
    """Distribución de redshift simulado vs detectado (coloreado por clase).

    Si se pasa `dump_df` (el .DUMP de SNANA, que trae TODOS los eventos
    generados cuando el .INPUT pide SELECTION: NONE — no solo los que
    pasaron a HEAD.FITS), la comparacion es real y en el mismo estilo que el
    analisis de referencia del equipo (histograma ZCMB superpuesto, escala
    log, caja de estadisticas): ZCMB de dump_df completo ("todos los
    simulados", paso negro) vs el subconjunto de dump_df cuyo CID aparece en
    head_df.SNID ("detectados", relleno rojo). head_df solo contiene eventos
    YA detectados, asi que sin dump_df no hay forma real de contrastar
    contra la poblacion completa — se usa como fallback (dos paneles con la
    misma columna de head_df, menos informativo pero mejor que nada)."""
    _setup_style()
    import matplotlib.pyplot as plt

    out_path = Path(out_path)

    zcmb_col = next((c for c in (dump_df.columns if dump_df is not None else []) if "ZCMB" in c.upper()
                      and "SMEAR" not in c.upper()), None)
    if dump_df is not None and not dump_df.empty and zcmb_col and "CID" in dump_df.columns:
        # Fase 90: mismo numero que va a summary.json (redshift_zmax_stats),
        # calculado sobre el dump_df original -- evita que el grafico y el
        # JSON puedan divergir por duplicar el calculo en dos lados.
        stats = redshift_zmax_stats(dump_df, head_df)
        # SNANA usa -9 como centinela de "no definido" -- se descarta antes
        # de graficar (son ~0.1% de los eventos, no una senal real).
        dump_df = dump_df[dump_df[zcmb_col] > -1]
        detected_cids = set(head_df["SNID"].astype(str)) if "SNID" in head_df.columns else set()
        detected_mask = dump_df["CID"].astype(str).isin(detected_cids)
        n_sim, n_det = stats.get("n_simulado", 0), stats.get("n_detectado", 0)

        fig, ax = plt.subplots(figsize=(10, 6.5))
        ax.hist(dump_df[zcmb_col], bins=35, color="#c8ccd8", histtype="step",
                linewidth=2, label="Todos los eventos simulados", log=True)
        if n_det:
            ax.hist(dump_df.loc[detected_mask, zcmb_col], bins=40, color="#e0525f",
                    alpha=0.75, label="Eventos detectados", log=True)
        ax.set_xlabel(f"Redshift CMB ({zcmb_col})", fontsize=12)
        ax.set_ylabel("Frecuencia (log)", fontsize=12)
        ax.set_title("Distribución de Redshifts CMB (Simulado vs Detectado)",
                     color=_ACCENT, fontsize=13)
        ax.legend()
        ax.grid(True, alpha=0.3)

        if n_det:
            stats_text = (
                f"Estadísticas:\n"
                f"• Simulados: {n_sim:,}\n"
                f"• Detectados: {n_det:,}\n"
                f"• Eficiencia: {n_det / n_sim * 100:.1f}%\n"
                f"• z_max simulado: {stats['z_max_simulado']:.3f}\n"
                f"• z_max detectado: {stats['z_max_detectado']:.3f}"
            )
            ax.annotate(stats_text, xy=(0.02, 0.98), xycoords="axes fraction",
                        verticalalignment="top", fontsize=10, color=_INK,
                        bbox=dict(boxstyle="round,pad=0.3", facecolor=_PANEL, edgecolor=_LINE, alpha=0.9))

            print("  eficiencia por bin de redshift:")
            z_bins = np.linspace(0, stats["z_max_simulado"], 6)
            for i in range(len(z_bins) - 1):
                bin_mask = (dump_df[zcmb_col] >= z_bins[i]) & (dump_df[zcmb_col] < z_bins[i + 1])
                bin_det = detected_mask & bin_mask
                eff = bin_det.sum() / bin_mask.sum() * 100 if bin_mask.sum() > 0 else 0
                print(f"    z = [{z_bins[i]:.2f}, {z_bins[i+1]:.2f}): {eff:.1f}%")

        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    for ax, col, label in zip(axes, [z_sim_col, z_det_col], ["z simulado", "z detectado"]):
        if col not in head_df.columns:
            ax.set_title(f"{label} (columna ausente)")
            continue
        types = sorted(head_df[type_col].unique()) if type_col in head_df.columns else [0]
        cmap = plt.cm.viridis(np.linspace(0.2, 0.9, len(types)))
        for t, c in zip(types, cmap):
            sub = head_df[head_df[type_col] == t][col] if type_col in head_df.columns else head_df[col]
            sub = sub.dropna()
            ax.hist(sub, bins=bins, alpha=0.65, color=c, label=f"tipo {t}", histtype="stepfilled")
        ax.set_xlabel(label)
        ax.set_title(label, fontsize=11)
        ax.legend(loc="upper right", fontsize=7)
    axes[0].set_ylabel("N objetos")
    fig.suptitle("Distribución de redshift", color=_ACCENT, fontsize=13, y=1.02)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------ 2. magnitudes
def magnitude_histograms(
    phot_df: pd.DataFrame,
    out_path: str | Path,
    *,
    mag_col: str = "MAG",
    band_col: str = "FLT",
    bands: list[str] | None = None,
    bins: int = 50,
) -> Path:
    """Histograma de magnitud A-B por banda."""
    _setup_style()
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    bands = bands or ["u", "g", "r", "i", "z", "Y"]
    # SNANA suele prefijar la banda (p.ej. "LSST-r") en vez del caracter
    # suelto ("r") — se compara por el sufijo tras el ultimo "-".
    band_short = phot_df[band_col].astype(str).str.strip().str.rsplit("-", n=1).str[-1]
    present = [b for b in bands if b in band_short.unique()]

    ncols = min(3, len(present)) or 1
    nrows = max(1, (len(present) + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.5 * nrows), squeeze=False)

    for idx, b in enumerate(present):
        ax = axes[idx // ncols][idx % ncols]
        sub = phot_df.loc[band_short == b, mag_col].dropna()
        sub = sub[(sub > 15) & (sub < 30)]  # rango razonable
        ax.hist(sub, bins=bins, color=BAND_COLORS.get(b, _ACCENT), alpha=0.8, histtype="stepfilled")
        ax.set_xlabel("mag AB")
        ax.set_title(f"banda {b}  (N={len(sub):,})", fontsize=10)
        ax.grid(True, alpha=0.3)
    # ocultar ejes sobrantes
    for idx in range(len(present), nrows * ncols):
        axes[idx // ncols][idx % ncols].set_visible(False)
    fig.suptitle("Histogramas de magnitud A-B", color=_ACCENT, fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------ 3. detecciones
def detection_distribution(
    phot_df: pd.DataFrame,
    out_path: str | Path,
    *,
    snid_col: str = "SNID",
    photflag_col: str = "PHOTFLAG",
    detected_flags: tuple[int, ...] = (4096, 6144),
    bins: int = 50,
) -> Path:
    """Distribución del número de detecciones reales (no todas las épocas
    observadas — PHOTFLAG=0 es una no-deteccion/upper-limit, no una
    deteccion) por objeto. PHOTFLAG 4096/6144 son los valores estandar de
    SNANA para deteccion (ver readme de cada GENVERSION)."""
    _setup_style()
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    valid = phot_df[phot_df[snid_col] != ""] if snid_col in phot_df.columns else phot_df.iloc[0:0]
    if photflag_col in valid.columns:
        valid = valid[valid[photflag_col].isin(detected_flags)]
    if snid_col not in phot_df.columns or valid.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"columna '{snid_col}' no encontrada", transform=ax.transAxes,
                ha="center", color=_INK_DIM)
        fig.savefig(out_path); plt.close(fig); return out_path

    counts = valid.groupby(snid_col).size()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(counts, bins=bins, color=_ACCENT, alpha=0.85, histtype="stepfilled", edgecolor=_LINE)
    ax.axvline(counts.median(), color="#e0b23c", ls="--", lw=1.2, label=f"mediana = {counts.median():.0f}")
    ax.set_xlabel("Nº de detecciones reales por objeto (PHOTFLAG ∈ {4096, 6144})")
    ax.set_ylabel("N objetos")
    ax.set_title("Distribución de detecciones", color=_ACCENT, fontsize=13)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------ 4. curvas de muestra
def sample_lightcurves(
    phot_df: pd.DataFrame,
    head_df: pd.DataFrame,
    out_path: str | Path,
    *,
    n_samples: int = 6,
    snid_col: str = "SNID",
    mjd_col: str = "MJD",
    flux_col: str = "FLUXCAL",
    fluxerr_col: str = "FLUXCALERR",
    band_col: str = "FLT",
    photflag_col: str = "PHOTFLAG",
    detected_flags: tuple[int, ...] = (4096, 6144),
    title: str = "Curvas de luz mas brillantes",
) -> Path:
    """Curvas de luz de los objetos mas brillantes (flujo vs MJD, multibanda).

    Selecciona los `n_samples` objetos con el FLUXCAL pico mas alto (la
    observacion individual mas brillante que alcanza cada objeto, sobre
    todas sus bandas) -- no una muestra aleatoria. `title` permite marcar
    explicitamente la fuente de los datos (p.ej. si vienen de LightCurveLynx
    en vez de SNANA real) -- nunca dejar el titulo generico si la fuente no
    es la real esperada para ese slot."""
    _setup_style()
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    valid = phot_df[phot_df[snid_col] != ""] if snid_col in phot_df.columns else phot_df.iloc[0:0]
    if snid_col not in phot_df.columns or valid.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"columna '{snid_col}' no encontrada", transform=ax.transAxes,
                ha="center", color=_INK_DIM)
        fig.savefig(out_path); plt.close(fig); return out_path
    phot_df = valid

    peak_flux = phot_df.groupby(snid_col)[flux_col].max().sort_values(ascending=False)
    n = min(n_samples, len(peak_flux))
    chosen = peak_flux.head(n).index.to_numpy()

    ncols = min(3, n)
    nrows = max(1, (n + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.5 * nrows), squeeze=False)

    for idx, snid in enumerate(chosen):
        ax = axes[idx // ncols][idx % ncols]
        sub = phot_df[phot_df[snid_col] == snid].copy()
        # tipo del objeto
        label_extra = ""
        if snid_col in head_df.columns and "SNTYPE" in head_df.columns:
            match = head_df[head_df[snid_col] == snid]
            if len(match):
                label_extra = f"  tipo={match.iloc[0]['SNTYPE']}"

        has_photflag = photflag_col in sub.columns
        for b in sub[band_col].unique():
            b_short = str(b).rsplit("-", 1)[-1]
            bsub = sub[sub[band_col] == b].sort_values(mjd_col)
            color = BAND_COLORS.get(b_short, _INK_DIM)
            det = bsub[bsub[photflag_col].isin(detected_flags)] if has_photflag else bsub
            nondet = bsub[~bsub[photflag_col].isin(detected_flags)] if has_photflag else bsub.iloc[0:0]
            if not det.empty:
                ax.errorbar(det[mjd_col], det[flux_col],
                            yerr=det[fluxerr_col] if fluxerr_col in det else None,
                            fmt="o", ms=3, color=color, ecolor=color, alpha=0.85,
                            label=f"{b_short} det", elinewidth=0.8, capsize=0)
            if not nondet.empty:
                ax.errorbar(nondet[mjd_col], nondet[flux_col],
                            yerr=nondet[fluxerr_col] if fluxerr_col in nondet else None,
                            fmt="v", ms=3, color=color, ecolor=color, alpha=0.3,
                            label=f"{b_short} no det", elinewidth=0.6, capsize=0)
        ax.set_title(f"SNID {snid}{label_extra}", fontsize=9)
        ax.set_xlabel("MJD")
        ax.set_ylabel("FLUXCAL")
        ax.legend(fontsize=7, ncol=3, loc="upper right")
        ax.grid(True, alpha=0.2)

    for idx in range(n, nrows * ncols):
        axes[idx // ncols][idx % ncols].set_visible(False)
    fig.suptitle(title, color=_ACCENT, fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------ run all
def run_all_qc(
    head_df: pd.DataFrame,
    phot_df: pd.DataFrame,
    out_dir: str | Path,
    genversion: str = "",
    *,
    dump_df: pd.DataFrame | None = None,
) -> dict[str, Path]:
    """Corre los 4 QC y devuelve las rutas generadas."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{genversion}_" if genversion else ""

    paths = {}
    paths["redshift"] = redshift_distribution(
        head_df, out_dir / f"{prefix}qc_redshift.png", dump_df=dump_df)
    paths["magnitudes"] = magnitude_histograms(
        phot_df, out_dir / f"{prefix}qc_magnitudes.png")
    paths["detections"] = detection_distribution(
        phot_df, out_dir / f"{prefix}qc_detections.png")
    paths["lightcurves"] = sample_lightcurves(
        phot_df, head_df, out_dir / f"{prefix}qc_lightcurves.png")

    return paths
