"""
Fase 2 parte B -- version generalizada de run_simsed_91bg_ddf_poc.py que
corre cualquiera de las clases SIMSED del catalogo via una config por
clase, en vez de un script separado por clase. Reusa exactamente el mismo
patron ya validado (H0=70 + ruido real de SNANA inyectado desde Fase 2
parte A, extincion MW real, SEARCHEFF real, QC de pipeline.postproc sin
modificar).

Clases nuevas en esta ronda (elegidas por complejidad variada, ver
NOTES.md Fase 2 parte B): KN-K17 (peso uniforme, DNDZ POWERLAW sin
dependencia de z, redshift bajo), CaRT/CART-MOSFIT (peso uniforme, DNDZ
MD14), SLSN-I/SLSN-I-MOSFIT (peso uniforme, DNDZ MD14, rango de redshift
mucho mas amplio 0.02-9.7 -- prueba de escala/extrapolacion).

Simplificacion deliberada y documentada (no un descuido): estas 3 clases
declaran extincion de galaxia anfitriona (WV07 AV/RV o similar,
GENAV_WV07/GENRANGE_AV/GENPEAK_RV en su .INPUT real) que NO se implementa
aqui. Se investigo el codigo fuente real de SNANA
(~/github/SNANA_src/src/sntools_genExpHalfGauss.c) y el propio codigo trae
un historial de bugs documentados en esa formula ("WV07 AV flag was never
refactored to use this function, so this might be a harmless bug" --
comentario real de Dic 2023 en el codigo), lo que hace riesgoso
reimplementarla de memoria sin una referencia mas solida. Se omite (AV=0)
en vez de adivinar mal la formula -- mismo criterio que la aproximacion de
G10 en Fase 1. Queda como brecha adicional documentada, no una que se
descubrio por accidente.

Ronda 2 (ver NOTES.md Fase 2 parte B, continuacion 2): SNIax, TDE-MOSFIT,
SNII-NMF. A diferencia de la ronda 1, aqui SI se implementa extincion de
host cuando el .INPUT real declara el modelo exponencial puro
(`GENTAU_AV`, sin componente WV07/Gaussiana) -- se encontro la formula
real en el codigo fuente de SNANA (snlc_sim.c, funciones
`SFRfun_MD14`/`INDEX_RATEMODEL_CCS15`/`INDEX_RATEMODEL_TDE`) para los
modelos de tasa CC_S15/TDE tambien, que en la ronda 1 se habian evitado
por parecer "nombres propios" sin formula obvia -- resultaron ser
formulas simples y bien documentadas una vez revisado el codigo real, no
las supuestas complejas de PISN_PLK12 (esa sigue sin implementarse, no
se encontro razon para reconsiderarla en esta ronda).

Uso (dentro de un job sbatch, nunca en el login node):
    python3 run_simsed_poc.py <clave_clase>
    (claves validas: ver CLASS_CONFIGS)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from lightcurvelynx.astro_utils.passbands import PassbandGroup
from lightcurvelynx.math_nodes.np_random import NumpyRandomFunc
from lightcurvelynx.math_nodes.ra_dec_sampler import ObsTableRADECSampler
from lightcurvelynx.models.sed_template_model import SIMSEDModel, SEDTemplate
from lightcurvelynx.obstable.opsim import OpSim
from lightcurvelynx.simulate import simulate_lightcurves
from lightcurvelynx.survey_info import SurveyInfo
from lightcurvelynx.utils.extrapolate import LinearDecay, ZeroPadding

from snana_params import (
    build_dndz_powerlaw2_cdf, build_dndz_md14_cdf, build_dndz_ccs15_cdf, build_dndz_tde_cdf,
    build_dndz_pisn_cdf, make_dndz_sampler, make_exp_av_sampler, make_exp_halfgauss_av_sampler,
    make_wv07_av_sampler, make_correlated_normal_weights, make_mwebv_ratio_scatter,
    make_wfd_ebv_lookup,
    SizeAwareFunctionNode, ClippedExtinctionEffect,
)
from searcheff import (
    parse_searcheff_pipeline, parse_pipeline_logic, apply_detection_efficiency, object_level_detected,
)
# Fase 68/69: panel de curvas de luz estilo notebook oficial -- compartido con
# run_non1ased_poc.py/run_snia_ddf_poc.py (ver qc_lightcurves_notebook.py), no
# copiado 3 veces.
from qc_lightcurves_notebook import plot_notebook_style_lightcurves

# Fase 74: REPO_ROOT/SNANA_HOME resueltos por local_env.py (portabilidad --
# antes hardcodeado a "/home/mvalenzuela"/"/home/mvalenzuela/AUTOSIM", ver
# ese archivo para el porqué).
from local_env import SNANA_HOME, REPO_ROOT
sys.path.insert(0, str(REPO_ROOT))
from pipeline.simlib.formatobs import format_obs  # noqa: E402
from lightcurvelynx.astro_utils.mag_flux import mag2flux  # noqa: E402

HERE = Path(__file__).resolve().parent
OPSIM_DB = REPO_ROOT / "data/opsim/baseline_v5.3.1_10yrs.db"
SEARCHEFF_PIPELINE_FILE = SNANA_HOME / "run_SNANA/LSST_SEARCHEFF_PIPELINE.DAT"
SEARCHEFF_LOGIC_FILE = SNANA_HOME / "run_SNANA/LSST_PIPELINE_LOGIC.DAT"
PIXSIZE = 0.2
# Colocacion uniforme en el campo de vision (2026-09-25): cada objeto se ubica uniforme en area dentro
# del FOV (radio 1.75 deg, el mismo de OpSim/range_search) de una visita elegida al azar, en vez de
# exactamente en su centro (radius=0.0). El desplazamiento usa el rng compartido que simulate_lightcurves()
# pasa a sample_parameters() -> reproducible. Densidad de muestreo = proporcional al numero de visitas que
# cubren cada posicion (no solo en los centros de apuntado: en DDF el dither <=0.2 deg concentraba todo).
RADEC_SAMPLER_RADIUS_DEG = 1.75
# Fase 55: copia local versionada de los 6 filtros reales LSST (mismo
# total_{u,g,r,i,z,y}.dat que descarga PassbandGroup.from_preset("LSST") por
# defecto) -- solo u.dat difiere, truncado a 413.4nm/4134A, el corte real
# que usa el kcor de SNANA (LSST_u.dat real en
# $SNDATA_ROOT/filters/LSST/baseline_1.9/, confirmado byte-identico a
# total_u.dat hasta ese corte). El preset por defecto de LightCurveLynx
# nunca trunca -- incluye una fuga fuera de banda hacia el rojo (T~4e-5,
# hasta 1150nm) que SNANA real nunca ve, ~0.07-0.10 mag de mas brillo
# espurio en banda u, 0.000 en las otras 5 (ver NOTES.md Fase 52/55).
LSST_PASSBAND_TABLE_DIR = HERE / "lsst_passbands_local"
NGENTOT_LC = 2000  # igual para las 3 clases (pipeline/models.yaml: ngen_ddf)
SEED_BASE = 20260813

DDF_FIELD_EBV = {
    "cosmos": 0.0182, "ecdfs": 0.0084, "edfs_a": 0.0062,
    "edfs_b": 0.0152, "elaiss1": 0.0080, "xmm_lss": 0.0251,
}
MW_RV = 3.1
GENSIGMA_MWEBV_RATIO = 0.16  # Fase 10: real, activo en toda la campana (templates.py)
# Fase 17: WFD no tiene campos fijos como DDF -- E(B-V) real por
# nearest-neighbor angular contra esta grilla (ver
# build_wfd_mwebv_grid.py/snana_params.make_wfd_ebv_lookup).
WFD_MWEBV_GRID = HERE / "wfd_mwebv_grid.csv"

# Fase 13: rango observado real de cada banda LSST -- extraido del propio
# kcor_LSST.fits real (HDU FilterTrans, primer/ultimo bin con transmision no
# nula), no un valor generico. Usado para replicar el "bail if any part of
# filter trans is outside model range" real de SNANA (genmag_SEDtools.c,
# funcion prep_filter_SEDMODEL(), comentario "Mar 22 2017"): si el rango
# COMPLETO de la banda, corrido a marco de reposo (lambda_obs/(1+z)), no cabe
# dentro del RESTLAMBDA_RANGE declarado del SED, SNANA nunca genera esa
# observacion -- ni siquiera con flujo indefinido, directamente no la cuenta
# (ver NOBS_UNDEFINED, variable real y distinta de NOBS en el dump).
BAND_RANGES_OBS = {
    "u": (3200.0, 4090.0), "g": (3760.0, 5760.0), "r": (5240.0, 7150.0),
    "i": (6600.0, 8440.0), "z": (7900.0, 9490.0), "Y": (8980.0, 10980.0),
}


def restlambda_gate(z: float, filt: str, restlambda_range: tuple[float, float]) -> bool:
    """True si la banda `filt` a redshift `z` SI cabe dentro de
    restlambda_range en marco de reposo (replica exacta de la condicion real
    de snlc_sim.c/genmag_SEDtools.c) -- False si SNANA la habria suprimido."""
    lam_lo, lam_hi = BAND_RANGES_OBS[filt]
    z1 = 1.0 + z
    rlo, rhi = restlambda_range
    if lam_lo / z1 < rlo:
        return False
    if lam_hi / z1 > rhi:
        return False
    return True


def restlambda_gate_vec(z: np.ndarray, filt: np.ndarray, restlambda_range: tuple[float, float]) -> np.ndarray:
    """Version vectorizada de restlambda_gate() -- mismo resultado exacto fila
    a fila (keep = lam_lo/z1 >= rlo AND lam_hi/z1 <= rhi, algebraicamente
    identico a las 2 condiciones de rechazo de arriba), sin loop de Python.
    Usada por main() en el paso de aplanado (Fase 59-perf, ver NOTES.md)."""
    rlo, rhi = restlambda_range
    z1 = 1.0 + np.asarray(z, dtype=float)
    lam_lo = np.array([BAND_RANGES_OBS[f][0] for f in filt])
    lam_hi = np.array([BAND_RANGES_OBS[f][1] for f in filt])
    return (lam_lo / z1 >= rlo) & (lam_hi / z1 <= rhi)


# --- SNIa-SALT2 (LSST_sim_lcs 2026-09-30, docs/SNIa_SALT2.md): SALT2 inside the sweep system ------------------------
# GENMODEL_EXTRAP_LATETIME of SIMGEN_INCLUDE_SNIa-SALT2.INPUT (SNIa_Extrap_LateTime_2expon.TEXT, K. Mandel 2018):
# columns rest wavelength [A], TAU1 [d], TAU2 [d], EXPRATIO; applied after EXTRAP_DAYMIN rest-frame days.
SALT2_LATE_DAYMIN = 45.0

# --- common observation window (LSST_sim_lcs 2026-10-07, docs/common_window.md) -------------------------------------
# The kept photometry of a detected object is [first detection - LC_PRE_DAYS, last detection + LC_POST_DAYS] in
# OBSERVER-frame days, identical for every class and redshift. The simulation itself covers each class's full model
# time range plus SIM_MARGIN_REST rest-frame days (>= LC_PRE/POST observer days at any z), so the cut never reaches
# the simulated span; MODEL_END_REST closes models without a finite end (SALT2 late-time, 56Co tails).
WINDOW_MODE = "detcut_v1"
LC_PRE_DAYS = 365.0
LC_POST_DAYS = 365.0
SIM_MARGIN_REST = LC_PRE_DAYS + 35.0
MODEL_END_REST = 1000.0

_sed_template_evaluate = SEDTemplate.evaluate_sed


def _evaluate_sed_zero_outside_grid(self, times, wavelengths):
    """SEDTemplate.evaluate_sed with zero flux outside the template's wavelength grid (no spline extrapolation)."""
    values = _sed_template_evaluate(self, times, wavelengths)
    w = np.asarray(wavelengths, dtype=float)
    out = (w < self.wavelengths[0]) | (w > self.wavelengths[-1])
    if out.any():
        values = np.array(values, copy=True)
        values[:, out] = 0.0
    return values


SEDTemplate.evaluate_sed = _evaluate_sed_zero_outside_grid



# --- non-transient LCLIB classes (LSST_sim_lcs 2026-10-16, docs/nontransients.md) ------------------------------------
from lightcurvelynx.models.lightcurve_template_model import LightcurveBandData, MultiLightcurveTemplateModel
LCLIB_DIR = Path(os.environ.get("ALCES_LCLIB_DIR", str(Path.home() / "lclib_subsets")))   # ~/lclib_full: full libraries
# A_b / E(B-V) for the LSST bands, R_V = 3.1 (Schlafly & Finkbeiner 2011, Table 6)
LSST_RB = {"u": 4.145, "g": 3.237, "r": 2.273, "i": 1.684, "z": 1.323, "y": 1.088}
SURVEY_SPAN_D = 3700.0          # periodic sources: simulate the whole 10-yr survey whatever the phase zero
LCLIB_TEMPLATE_DAYS = 30.0      # SNANA DAYBACK_TEMPLATE_LCLIB: template = flux average over 30 d (periodic sources)
# long libraries (ALCES_LCLIB_LONG=1, patch v7): whole-survey AGN, M-dwarf and dwarf-nova light curves
LCLIB_LONG_KIND = {"LCLIB_AGN-LSST": "drw", "LCLIB_Mdwarf-LSST": "segments", "LCLIB_dwarf-nova-LSST": "recur"}
LONG_MDW_BLOCK_D = 100.0        # M dwarf: target segment length
LONG_MDW_QUIET = 0.01           # M dwarf: quiescent = every band within 1% of the quiescent flux
LONG_DN_CV = 0.4                # dwarf nova: coefficient of variation of the outburst intervals (OGLE-IV photometry)
LONG_DN_FILE = "dn_recurrence_mroz2015.json"


def _long_drw(lc, tau, sf, seed, span):
    """AGN: Ornstein-Uhlenbeck continuation of the library realisation to [-span-1, span+1] d (daily)."""
    from lightcurvelynx.astro_utils.mag_flux import flux2mag
    bands = list(lc.lightcurves)
    t = lc.lightcurves[bands[0]][:, 0]
    m = np.column_stack([flux2mag(lc.lightcurves[b][:, 1]) for b in bands])
    mean = m.mean(axis=0)
    sfb = np.array([sf[b] for b in bands])
    z = ((m - mean) / sfb).mean(axis=1)              # one walk in units of SF (bands agree to 1e-3)
    rng = np.random.default_rng([int(seed), 20261022])
    a, sig = np.exp(-1.0 / tau), np.sqrt(0.5 * (1.0 - np.exp(-2.0 / tau)))

    def walk(z0, n):                                 # x_k = a x_(k-1) + sig e_k, x_0 = z0
        from scipy.signal import lfilter
        return lfilter([sig], [1.0, -a], rng.standard_normal(n), zi=[a * z0])[0]
    nb, nf = int(np.ceil(t[0] + span + 1)), int(np.ceil(span + 1 - t[-1]))
    tb, tf = t[0] - np.arange(1, nb + 1), t[-1] + np.arange(1, nf + 1)
    zb, zf = walk(z[0], nb), walk(z[-1], nf)          # the OU process is time-reversible
    tt = np.concatenate([tb[::-1], t, tf])
    new = {}
    for k, b in enumerate(bands):
        mb = np.concatenate([(mean[k] + sfb[k] * zb)[::-1], m[:, k], mean[k] + sfb[k] * zf])
        new[b] = np.column_stack([tt, mag2flux(mb)])
    return LightcurveBandData(new, 0.0, periodic=False, baseline=dict(lc.baseline))


def _long_cuts(lc):
    """M dwarf: segment boundaries at quiescent epochs, about LONG_MDW_BLOCK_D apart."""
    bands = list(lc.lightcurves)
    t = lc.lightcurves[bands[0]][:, 0]
    tg = np.arange(t[0], t[-1], 0.05)
    F = np.column_stack([np.interp(tg, lc.lightcurves[b][:, 0], lc.lightcurves[b][:, 1]) for b in bands])
    quiet = np.all(np.abs(F / np.median(F, axis=0) - 1.0) < LONG_MDW_QUIET, axis=1)
    cand = tg[quiet]
    if len(cand) < 2:
        return np.array([t[0], t[-1]])
    tgt = np.arange(cand[0], cand[-1] + LONG_MDW_BLOCK_D / 2, LONG_MDW_BLOCK_D)
    cuts = np.unique(cand[np.clip(np.searchsorted(cand, tgt), 0, len(cand) - 1)])
    return cuts if len(cuts) >= 2 else np.array([t[0], t[-1]])


def _long_map(kind, info, span, t_rel, seed, ind):
    """Library time (relative to the light curve's lc_data_t0) of each model time t_rel in [-span, span]."""
    rng = np.random.default_rng([int(seed), int(ind)])
    lo = -span - 1.0
    if kind == "segments":
        cuts = info[ind]
        seg = np.diff(cuts)
        k = rng.integers(0, len(seg), size=int(np.ceil((2 * span + 2) / seg.min())) + 1)
        st = lo + np.concatenate([[0.0], np.cumsum(seg[k])[:-1]])
        n = int(np.searchsorted(st, span + 1.0)) + 1
        st, k = st[:n], k[:n]
        j = np.clip(np.searchsorted(st, t_rel, side="right") - 1, 0, n - 1)
        return cuts[k[j]] + (t_rel - st[j])
    trec, dur = info[ind]                               # recur: stationary renewal process of outbursts
    shape = 1.0 / LONG_DN_CV ** 2
    scale = trec / shape
    first = max(rng.gamma(shape + 1.0, scale), dur + 1.0)      # length-biased first interval, uniform phase
    on = [lo - rng.uniform(0.0, first)]
    while on[-1] <= span + 1.0:
        on.append(on[-1] + max(rng.gamma(shape, scale), dur + 1.0))
    on = np.asarray(on)
    j = np.clip(np.searchsorted(on, t_rel, side="right") - 1, 0, len(on) - 1)
    return t_rel - on[j]                                # beyond the outburst: the baseline (quiescent) flux


class LCLIBDiffModel(MultiLightcurveTemplateModel):
    """LCLIB light curves as difference-imaging fluxes: model flux minus the event's template flux, with optional
    Milky Way extinction (parameter 'ebv', LSST_RB coefficients)."""

    def __init__(self, lightcurves, passbands=None, *, template_flux=None, apply_mw=False, long_map=None, **kwargs):
        super().__init__(lightcurves, passbands, **kwargs)
        self._template_flux = template_flux
        self._apply_mw = apply_mw
        self._long_map = long_map                   # (kind, info, span) of a long library (patch v7) or None

    def compute_bandflux(self, times, filter, state, **kwargs):
        params = self.get_local_params(state)
        ind = int(params["selected_lightcurve"])
        lc = self.lightcurves[ind]
        if lc.period is not None:
            # SNANA (genmag_LCLIB.c magTemplate_LCLIB): flux average over the template epochs of the
            # DAYBACK_TEMPLATE_LCLIB = 30 d before the search window, at a random phase -> mean flux over 30 d
            tt = params["template_day"] + np.linspace(0.0, LCLIB_TEMPLATE_DAYS, 61)
            tmpl = float(np.mean(lc.evaluate_bandfluxes(tt, filter)))
        else:
            tmpl = self._template_flux[ind].get(filter, 0.0)       # the library's template (T:) row
        t_rel = np.asarray(times, float) - params["t0"]
        if self._long_map is not None and self._long_map[0] != "drw":
            kind, info, span = self._long_map
            t_rel = _long_map(kind, info, span, t_rel, params["long_seed"], ind)
        f = lc.evaluate_bandfluxes(t_rel, filter) - tmpl
        if self._apply_mw:
            f = f * 10.0 ** (-0.4 * LSST_RB[filter] * params["ebv"])
        return f


def _dndb_weight(b, kind, coefs):
    x = np.abs(b) if kind == "BPOLY" else np.cos(np.radians(b))
    grid = np.arange(0.0, 90.0, 1.0)
    xg = grid if kind == "BPOLY" else np.cos(np.radians(grid))
    poly = lambda v: np.clip(sum(c * v ** k for k, c in enumerate(coefs)), 0.0, None)
    return poly(x) / poly(xg).max()


def build_lclib_model(cfg, obs_table, seed_base, t_start, wfd=False):
    """LCLIBDiffModel for a CLASS_CONFIGS entry with model="lclib" (docs/nontransients.md)."""
    from lightcurvelynx.utils.io_utils import read_lclib_data
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    tables = read_lclib_data(str(LCLIB_DIR / cfg["lclib"]) + ".TEXT")
    par = pd.read_parquet(str(LCLIB_DIR / cfg["lclib"]) + ".parquet")
    assert len(par) == len(tables), (len(par), len(tables))
    lcs, tmpl, dur = [], [], []
    for t in tables:
        if "Y" in t.colnames:
            t.rename_column("Y", "y")
        if np.any(np.diff(np.asarray(t["time"], float)) <= 0):   # not time-ordered (PLAsTiCC M-dwarf events)
            t.sort("time")
            keep = np.concatenate([[True], np.diff(np.asarray(t["time"], float)) > 0])
            t = t[keep]
        lc = LightcurveBandData.from_lclib_table(t)
        lcs.append(lc)
        if lc.period is not None:      # periodic: template = first epoch (no T: rows in these libraries)
            tmpl.append({f: float(v[0, 1]) for f, v in lc.lightcurves.items()})
        else:                          # non-recurring: template = first T: row (LCL stores it as the baseline)
            tmpl.append({f: float(lc.baseline.get(f, 0.0)) for f in lc.lightcurves})
        dur.append(max(float(v[-1, 0]) for v in lc.lightcurves.values()))
    periodic = all(lc.period is not None for lc in lcs)
    long_kind = LCLIB_LONG_KIND.get(cfg["lclib"]) if os.environ.get("ALCES_LCLIB_LONG") else None
    if os.environ.get("ALCES_LCLIB_LONG") and long_kind is None:
        sys.exit(f"ALCES_LCLIB_LONG: no long version of {cfg['lclib']}")
    long_map = None
    if long_kind == "drw":
        sfc = {"u": "SFU", "g": "SFG", "r": "SFR", "i": "SFI", "z": "SFZ", "y": "SFY"}
        for k in range(len(lcs)):
            lcs[k] = _long_drw(lcs[k], float(par["TAU"].iloc[k]), {b: float(par[c].iloc[k]) for b, c in sfc.items()},
                               par["SEED"].iloc[k], SURVEY_SPAN_D)
        long_map = (long_kind, None, SURVEY_SPAN_D)
    elif long_kind == "segments":
        cuts = [_long_cuts(lc) for lc in lcs]
        nseg = np.array([len(c) - 1 for c in cuts])
        long_map = (long_kind, cuts, SURVEY_SPAN_D)
        print(f"LCLIB long M dwarf: segments per event median {np.median(nseg):.0f}, min {nseg.min()}, "
              f"events with one segment {int((nseg == 1).sum())}")
    elif long_kind == "recur":
        rec = json.loads((LCLIB_DIR / LONG_DN_FILE).read_text())["trec_d"]
        info = [(float(rec[str(int(o))]), float(max(v[-1, 0] for v in lc.lightcurves.values())))
                for o, lc in zip(par["OGLE_ID"], lcs)]
        long_map = (long_kind, info, SURVEY_SPAN_D)
        print(f"LCLIB long dwarf nova: recurrence {min(i[0] for i in info):.0f}-{max(i[0] for i in info):.0f} d, "
              f"CV {LONG_DN_CV}")
    whole = periodic or long_kind is not None
    span = (-SURVEY_SPAN_D, SURVEY_SPAN_D) if whole else (0.0, float(max(dur)))
    print(f"[{time.time()-t_start:.1f}s] LCLIB {cfg['lclib']}: {len(lcs)} events, periodic={periodic}, "
          f"model span {span[0]:.0f}/{span[1]:.0f} d, MW dust {'applied' if cfg['apply_mw'] else 'in the library'}")

    radec_sampler = ObsTableRADECSampler(
        obs_table, extra_cols=[] if wfd else ["field"], seed=seed_base + 5, radius=RADEC_SAMPLER_RADIUS_DEG,
    )
    radec_sampler.setters["selected_table_index"].dependency.set_seed(seed_base + 5)

    def _glat(size=None, ra=None, dec=None, **_kw):
        return SkyCoord(ra=np.atleast_1d(ra) * u.deg, dec=np.atleast_1d(dec) * u.deg).galactic.b.deg

    glat = SizeAwareFunctionNode(_glat, node_label="glat", ra=radec_sampler.ra, dec=radec_sampler.dec)
    bcol = "b" if "b" in par else ("GLAT" if "GLAT" in par else None)
    ev_b = np.abs(par[bcol].to_numpy(float)) if bcol else None     # SNANA matches |b| (keep_ANGLEMATCH_LCLIB)
    am = par["ANGLEMATCH_b"].to_numpy(float) if "ANGLEMATCH_b" in par else None
    no_bmatch = bool(os.environ.get("ALCES_LCLIB_NO_BMATCH"))     # every event eligible (EB DDF, docs/nontransients.md)
    if no_bmatch:
        print("LCLIB latitude matching OFF (ALCES_LCLIB_NO_BMATCH)")
    rng_sel = np.random.default_rng(seed_base + 9)
    bal = json.loads(Path(os.environ["ALCES_LCLIB_BAL"]).read_text()) if os.environ.get("ALCES_LCLIB_BAL") else None
    if bal is not None:                    # balanced waves: D0 per event in library order
        d0t = pd.read_parquet(bal["d0_file"]).astype({"event_id": str}).set_index("event_id")
        d0 = d0t.reindex(par["event_id"].astype(str)).D0.to_numpy(float)
        b_edges, b_w = np.asarray(bal["edges"], float), np.asarray(bal["weights"], float)
        print(f"LCLIB balanced: {np.isfinite(d0).sum()}/{len(d0)} events with D0, dust_coef {bal['dust_coef']}, "
              f"{len(b_w)} bins [{b_edges[0]:.2f}, {b_edges[-1]:.2f}]")
    sel_cache = {}

    def _event_w(ok, ebv_k):
        if bal is None:
            return np.ones(len(ok))
        D = d0[ok] + bal["dust_coef"] * ebv_k
        j = np.searchsorted(b_edges, D, side="right") - 1
        inr = np.isfinite(D) & (j >= 0) & (j < len(b_w))
        w = np.zeros(len(ok))
        w[inr] = b_w[j[inr]]
        return w

    def _select(size=None, glat=None, ebv=None, **_kw):
        b = np.abs(np.atleast_1d(glat))
        e = np.broadcast_to(np.atleast_1d(ebv).astype(float), b.shape)
        out, sw = np.empty(len(b), int), np.ones(len(b))
        allidx = np.arange(len(lcs))
        for k, bk in enumerate(b):
            if ev_b is None or am is None or no_bmatch:
                ok = allidx
            else:
                ok = np.flatnonzero(np.abs(ev_b - bk) <= am)
                if not len(ok):
                    ok = np.array([int(np.argmin(np.abs(ev_b - bk)))])
            w = _event_w(ok, e[k])
            if w.sum() > 0:
                c = rng_sel.choice(len(ok), p=w / w.sum())
                sw[k] = (1.0 / len(ok)) / (w[c] / w.sum())
            else:
                c = rng_sel.integers(0, len(ok))
            out[k] = ok[c]
        sel_cache["last"] = (out.copy(), sw.copy())
        return out
    kind, coefs = cfg["dndb"]
    dndb = SizeAwareFunctionNode(lambda size=None, glat=None, **_kw: _dndb_weight(np.atleast_1d(glat), kind, coefs),
                                 node_label="dndb_weight", glat=glat)
    lo, hi = float(obs_table["time"].min()), float(obs_table["time"].max())
    if whole and hi - lo > SURVEY_SPAN_D:
        sys.exit(f"survey longer than SURVEY_SPAN_D: {hi - lo:.0f} d")
    t0_func = NumpyRandomFunc("uniform", low=lo - (0.0 if whole else float(max(dur))), high=hi, seed=seed_base + 6)
    if cfg["apply_mw"]:
        if wfd:
            ebv_func = SizeAwareFunctionNode(make_wfd_ebv_lookup(WFD_MWEBV_GRID, GENSIGMA_MWEBV_RATIO, seed=seed_base + 10),
                                             node_label="ebv", ra=radec_sampler.ra, dec=radec_sampler.dec)
        else:
            _scatter = make_mwebv_ratio_scatter(GENSIGMA_MWEBV_RATIO, seed=seed_base + 10)
            ebv_func = SizeAwareFunctionNode(
                lambda size=None, field=None, **_kw: _scatter(np.array([DDF_FIELD_EBV.get(f, 0.0)
                                                                       for f in np.atleast_1d(field)])),
                node_label="ebv", field=radec_sampler.field)
    else:
        ebv_func = SizeAwareFunctionNode(lambda size=None, **_kw: np.zeros(size or 1), node_label="ebv")
    selected = SizeAwareFunctionNode(_select, node_label="lclib_index", glat=glat, ebv=ebv_func)
    selw = SizeAwareFunctionNode(lambda size=None, lclib_index=None, **_kw: sel_cache["last"][1].copy(),
                                 node_label="sel_weight", lclib_index=selected)
    zero = SizeAwareFunctionNode(lambda size=None, **_kw: np.zeros(size or 1), node_label="redshift")
    model = LCLIBDiffModel(lcs, None, template_flux=tmpl, apply_mw=cfg["apply_mw"], indices=selected,
                           ra=radec_sampler.ra, dec=radec_sampler.dec, t0=t0_func, redshift=zero, long_map=long_map)
    if long_map is not None:
        model.add_parameter("long_seed", NumpyRandomFunc("integers", low=0, high=2 ** 31 - 1, seed=seed_base + 12),
                            allow_gradient=False)
    model.add_parameter("template_day", NumpyRandomFunc("uniform", low=0.0, high=1.0e5, seed=seed_base + 11),
                        allow_gradient=False)          # random start of the 30-d template window (periodic sources)
    model.add_parameter("ebv", ebv_func, allow_gradient=False)
    model.add_parameter("glat", glat, allow_gradient=False)
    model.add_parameter("dndb_weight", dndb, allow_gradient=False)
    model.add_parameter("sel_weight", selw, allow_gradient=False)
    model.lclib_bal = (bal, d0 if bal is not None else None)
    model.lclib_span = span
    model.lclib_event_id = par["event_id"].astype(str).to_numpy()
    return model, radec_sampler


def lclib_truth(lc, model):
    """Per-object LCLIB truth columns from the simulated parameters."""
    flat = _flat_params(lc)
    ind = np.asarray(_pick_param(flat, "selected_lightcurve"), dtype=int)
    return pd.DataFrame({"SNID": lc["id"].astype(int).astype(str).to_numpy(), "LCLIB_INDEX": ind,
                         "LCLIB_EVENT_ID": model.lclib_event_id[ind], "GLAT": _pick_param(flat, "glat"),
                         "MWEBV": _pick_param(flat, "ebv"), "DNDB_WEIGHT": _pick_param(flat, "dndb_weight"),
                         **_nt_bal_cols(model, ind, np.asarray(_pick_param(flat, "ebv"), float),
                                        np.asarray(_pick_param(flat, "sel_weight"), float))})


def _nt_bal_cols(model, ind, ebv, sw):
    """NT_D, NT_BIN and SEL_WEIGHT of the balanced non-transient waves (docs/nontransients.md)."""
    bal, d0 = model.lclib_bal
    if bal is None:
        return {"SEL_WEIGHT": np.ones(len(ind))}
    D = d0[ind] + bal["dust_coef"] * ebv
    e = np.asarray(bal["edges"], float)
    j = np.searchsorted(e, D, side="right") - 1
    j[~np.isfinite(D) | (j < 0) | (j >= len(e) - 1)] = -1
    return {"NT_D": D, "NT_BIN": j, "SEL_WEIGHT": sw}


def model_rest_span(source_model, cfg):
    """(first, last) rest-frame day of the class's model relative to t0: SIMSED template grids (all templates);
    SALT2 from its first phase and tail models to MODEL_END_REST."""
    if cfg.get("model") == "lclib":
        return source_model.lclib_span
    if cfg.get("model") == "salt2":
        return float(source_model.minphase()), MODEL_END_REST
    first = min(float(t.times[0]) for t in source_model.templates)
    last = max(float(t.times[-1]) for t in source_model.templates)
    return first, (MODEL_END_REST if "tail" in cfg else last)
SALT2_LATE_TABLE = np.array([[3590, 33.0, 59.9, 1.01], [4380, 57.1, 91.7, 0.30], [5490, 31.0, 84.0, 0.31],
                             [6520, 28.6, 56.2, 0.35], [8030, 20.6, 84.0, 0.25], [11000, 18.3, 147.0, 0.06],
                             [12500, 16.9, 100.0, 0.14]])


def _salt2_latetime_class():
    from lightcurvelynx.models.sncosmo_models import SncosmoWrapperModel

    class SALT2LateTimeModel(SncosmoWrapperModel):
        """SALT2 (sncosmo source) + SNANA's two-exponential late-time extrapolation after 45 rest-frame days:
        F(t, lam) = F(45, lam) g(t)/g(45), g(t) = exp(-t/tau1) + rho exp(-t/tau2), parameters linear in rest lam.
        maxphase() is None so the generic time extrapolation of PhysicalModel is not used after the model range."""

        def maxphase(self, **kwargs):
            return None

        def compute_sed(self, times, wavelengths, graph_state=None, **kwargs):
            params = self.get_local_params(graph_state)
            times = np.asarray(times, dtype=float)
            phase = times - params["t0"]
            late = phase > SALT2_LATE_DAYMIN
            flux = np.zeros((len(times), len(wavelengths)))
            if (~late).any():
                flux[~late] = super().compute_sed(times[~late], wavelengths, graph_state, **kwargs)
            if late.any():
                f45 = super().compute_sed(np.array([params["t0"] + SALT2_LATE_DAYMIN]), wavelengths, graph_state,
                                          **kwargs)[0]
                tab = SALT2_LATE_TABLE
                tau1, tau2, rho = (np.interp(wavelengths, tab[:, 0], tab[:, k]) for k in (1, 2, 3))
                g = lambda t: np.exp(-t / tau1) + rho * np.exp(-t / tau2)
                flux[late] = f45[None, :] * g(phase[late][:, None]) / g(SALT2_LATE_DAYMIN)[None, :]
            return flux

    return SALT2LateTimeModel


def build_salt2_model(cfg, seed_base, redshift_func, radec_sampler, t0_func, t_start):
    """SALT2 source model for a CLASS_CONFIGS entry with model="salt2" (same physics as run_snia_ddf_poc.py)."""
    import sncosmo
    from lightcurvelynx.astro_utils.snia_utils import DistModFromRedshift, X0FromDistMod
    from snana_params import make_bifurcated_normal_sampler, read_salt2_info

    salt2_dir = Path(cfg["salt2_dir"])
    src = sncosmo.SALT2Source(modeldir=str(salt2_dir), name="salt2-h17-local")
    c_func = SizeAwareFunctionNode(make_bifurcated_normal_sampler(**cfg["salt2c"], seed=seed_base + 13), node_label="c")
    x1_func = SizeAwareFunctionNode(make_bifurcated_normal_sampler(**cfg["salt2x1"], seed=seed_base + 14),
                                    node_label="x1")
    distmod_func = DistModFromRedshift(redshift_func, H0=70.0, Omega_m=0.315)
    mag_offset = read_salt2_info(salt2_dir)["MAG_OFFSET"]
    m_abs_func = NumpyRandomFunc("normal", loc=-19.365 + mag_offset, scale=cfg["sigma_int"], seed=seed_base + 15)
    x0_func = X0FromDistMod(distmod=distmod_func, x1=x1_func, c=c_func, alpha=cfg["alpha"], beta=cfg["beta"],
                            m_abs=m_abs_func)
    model = _salt2_latetime_class()(
        src, t0=t0_func, x0=x0_func, x1=x1_func, c=c_func,
        ra=radec_sampler.ra, dec=radec_sampler.dec, redshift=redshift_func,
        node_label="source", time_extrapolation=ZeroPadding(), wave_extrapolation=ZeroPadding(),
    )
    print(f"[{time.time()-t_start:.1f}s] SALT2 (H17 local, MAG_OFFSET {mag_offset}) + late-time 2-exponential "
          f"extrapolation after {SALT2_LATE_DAYMIN:g} d")
    return model


# --- config por clase, parametros reales de cada SIMGEN_INCLUDE_*.INPUT ---
CLASS_CONFIGS = {
    # SNIa-SALT2 (LSST_sim_lcs 2026-09-30, docs/SNIa_SALT2.md): normal SNe Ia in the sweep system, parameters of
    # run_SNANA/model_config/SIMGEN_INCLUDE_SNIa-SALT2.INPUT (same as run_snia_ddf_poc.py), model built by
    # build_salt2_model(); RESTLAMBDA_RANGE from SALT2.WFIRST-H17/SALT2.INFO.
    "SNIa-SALT2": dict(
        model="salt2",
        salt2_dir=HERE / "salt2_h17_local",
        genrange_redshift=(0.011, 1.8),
        dndz=("powerlaw", [(2.5e-5, 1.5, 0.0, 1.0), (9.7e-5, -0.5, 1.0, 1.8)]),
        sntype=1,
        salt2c=dict(peak=-0.054, sigma_lo=0.043, sigma_hi=0.101, lo=-0.3, hi=0.5),
        salt2x1=dict(peak=0.973, sigma_lo=1.472, sigma_hi=0.222, lo=-3.0, hi=2.0),
        alpha=0.14,
        beta=3.1,
        sigma_int=0.090,
        trest_range=(-100.0, 300.0),
        restlambda_range=(2000.0, 23000.0),
    ),
    # Fase 3: modelo de host extinction real ESSENCE-WV07 (Wood-Vasey+2007),
    # ver make_wv07_av_sampler() en snana_params.py -- reemplaza la omision
    # (AV=0) de las rondas 1-4 de Fase 2B. GENRANGE_AV=0-3 real en las 9
    # clases que lo declaran; KN-K17/KN-BULLA19 son las 2 unicas con
    # WV07_REWGT_EXPAV=0.5 (confirmado en su .INPUT real), las demas 7 no
    # lo declaran (rewgt_expav=None -> AEXP sin modificar).
    # Fase 4: SNIa-91bg migrada aqui desde run_simsed_91bg_ddf_poc.py (Fase 2B
    # ronda 1, script historico dedicado) para reusar el fix del trigger de
    # SEARCHEFF (ver NOTES.md) sin duplicar logica -- mismos parametros reales
    # de SIMGEN_INCLUDE_SNIa-91bg.INPUT, sin cambios.
    "SNIa-91bg": dict(
        simsed_dir=HERE / "simsed_91bg_local",
        genrange_redshift=(0.011, 0.6),
        dndz=("powerlaw", [(3.0e-6, 1.5, 0.011, 0.6)]),
        sntype=13,
        redcor_params=dict(
            peaks=dict(stretch=0.975, color=0.557),
            sigmas=dict(stretch=0.096, color=0.175),
            redcor={("stretch", "color"): -0.656},
        ),
        # Fase 59: GENRANGE_TREST real (~run_SNANA/model_config/
        # SIMGEN_INCLUDE_SNIa-91bg.INPUT) es -100/400, no el hardcode global
        # (-30,100) -- mismo hueco que encontro Fase 40/43 para SLSN-I/
        # ILOT-MOSFIT, nunca remedido para las otras 12 clases (ver NOTES.md).
        # No afecta las comparaciones de brillo verdadero (Fase 56 en
        # adelante evalua un unico punto Trest=0, no depende de trest_range)
        # -- si afecta la ventana real de generacion/deteccion de main().
        trest_range=(-100.0, 400.0),
    ),
    # Fase 6: mismos 35 templates fisicos que "SNIa-91bg" de arriba
    # (simsed_91bg_local -- confirmado por diff de listado de directorio
    # que run_SNANA/elastic/model_libs_updates/SIMSED.SNIa-91bg/ trae los
    # mismos archivos .SED que plasticc_models/SIMSED.SNIa-91bg/, mas
    # NON1A.LIST/SED.BINARY), pero con GENRANGE_REDSHIFT del .INPUT real
    # "elastic" (0.011-1.2, run_SNANA/elastic/model_config/
    # SIMGEN_INCLUDE_SNIa-91bg.INPUT) -- el mismo .INPUT del que se
    # convirtio SNIa-91bg_NON1ASED. No hay corrida SNANA de este .INPUT
    # SIMSED-elastic en la campana real (solo se uso como fuente para la
    # conversion a NON1ASED) -- esta clase no tiene ratio propio vs SNANA,
    # es solo para comparar LCL-SIMSED vs LCL-NON1ASED al mismo rango de z
    # y aislar si la codificacion del modelo (no la fisica ni el rango)
    # afecta el resultado (ver run_non1ased_poc.py).
    "SNIa-91bg-elastic": dict(
        simsed_dir=HERE / "simsed_91bg_local",
        genrange_redshift=(0.011, 1.2),
        dndz=("powerlaw", [(3.0e-6, 1.5, 0.011, 1.2)]),
        sntype=13,
        redcor_params=dict(
            peaks=dict(stretch=0.975, color=0.557),
            sigmas=dict(stretch=0.096, color=0.175),
            redcor={("stretch", "color"): -0.656},
        ),
    ),
    "KN-K17": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.KN-K17",
        genrange_redshift=(0.011, 0.42),
        dndz=("powerlaw", [(320e-9, 0.0, 0.011, 0.42)]),
        sntype=51,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=0.5, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/300 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 300.0),
    ),
    "CaRT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.CART-MOSFIT",
        genrange_redshift=(0.012, 1.4),
        dndz=("md14", 2.3e-6),
        sntype=87,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/500 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 500.0),
    ),
    "SLSN-I": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SLSN-I-MOSFIT",
        genrange_redshift=(0.02, 9.7),
        dndz=("md14", 2.0e-8),
        sntype=40,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 13: RESTLAMBDA_RANGE real declarado en SED.INFO (1000-11000 A).
        # A GENRANGE_REDSHIFT[1]=9.7, TODAS las bandas caen fuera de rango en
        # marco de reposo -- y el 46% de la poblacion completa (ponderada por
        # dndz MD14) ya esta en z>=2.2, donde la banda u empieza a quedar
        # fuera. Primera clase de prueba de esta fase (ver NOTES.md).
        restlambda_range=(1000.0, 11000.0),
        # Fase 43: GENRANGE_TREST real del .INPUT es -100/500 (Fase 40) --
        # el hardcode global (-30,100) cubria solo 21.7% de esa ventana.
        trest_range=(-100.0, 500.0),
    ),
    "SNIax": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIax",
        genrange_redshift=(0.011, 0.7),
        dndz=("md14", 6.0e-6),
        sntype=12,
        # Fase 2B ronda 3: el .INPUT real de SNIax declara ADEMAS de
        # GENTAU_AV=1.7 los parametros GENSIG_AV=0.6/GENRATIO_AV0=4.0 --
        # NO es pura exponencial (la ronda 2 lo trato como tal por error,
        # sin leer esas dos lineas). Es la mezcla exponencial+semi-Gaussiana
        # de make_exp_halfgauss_av_sampler(), via GENPROFILE_AV en
        # snlc_sim.c::gen_AV() -- un camino de codigo real y distinto del
        # flag GENAV_WV07 (ese SI sigue bugueado/omitido, confirmado que
        # SNIax no lo declara). GENRANGE_AV real: 0.001-3.0.
        host_av=dict(kind="exp_halfgauss", tau=1.7, sig=0.6, ratio=4.0,
                      av_range=(0.001, 3.0), r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/400 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 400.0),
    ),
    # Fase 7: bake-off de codificacion en clase de peso uniforme
    # (SIMSED_GRIDONLY), contraparte diagnostica de "SNIax" al rango de z
    # real del .INPUT elastic (0.011-1.5, el mismo que se convirtio a
    # NON1ASED) -- ver run_non1ased_poc.py CLASS_CONFIGS["SNIax"]. Mismos
    # 1001 templates fisicos (confirmado por listado de directorio), mismos
    # parametros reales de host extinction (GENTAU_AV/GENSIG_AV/GENRATIO_AV0
    # identicos entre el .INPUT elastic y no-elastic). Sin corrida SNANA real
    # de este .INPUT SIMSED-elastic (el elastic solo se uso como fuente para
    # la conversion a NON1ASED) -- misma logica que SNIa-91bg-elastic.
    "SNIax-elastic": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIax",
        genrange_redshift=(0.011, 1.5),
        dndz=("md14", 6.0e-6),
        sntype=12,
        host_av=dict(kind="exp_halfgauss", tau=1.7, sig=0.6, ratio=4.0,
                      av_range=(0.001, 3.0), r_v=3.1),
    ),
    "TDE-MOSFIT": dict(
        # SED.INFO real trae una linea suelta invalida ("tde_384.json",
        # sin prefijo "SED:" ni ':') que rompe el parser YAML de
        # LightCurveLynx (no el de SNANA, que no es YAML estricto) -- ver
        # setup_simsed_local.py. Se usa una copia local saneada (SED.INFO
        # reescrito, templates symlinkeados, archivo real no tocado).
        simsed_dir=HERE / "simsed_tdemosfit_local",
        genrange_redshift=(0.01, 2.9),
        dndz=("tde", 1.0e-6),
        sntype=51,
        # GENAV_WV07 esta comentado (deshabilitado) en el .INPUT real de
        # esta clase -- usa GENTAU_AV=0.4 puro (comentario real: "expon
        # component only, no Gauss core"), no el modelo WV07 mixto.
        host_av=dict(kind="exp", tau=0.4, av_max=3.0, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/500 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 500.0),
    ),
    "SNII-NMF": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNII-NMF",
        genrange_redshift=(0.011, 1.0),
        dndz=("ccs15", 0.162),
        sntype=42,
        # sin extincion de host declarada en el .INPUT real -- comparacion
        # limpia, igual que SNIa/SNIa-91bg.
        redcor_params=dict(
            peaks=dict(pc1=0.0854, pc2=0.0199, pc3=0.0250),
            sigmas=dict(pc1=0.075, pc2=0.021, pc3=0.017),
            redcor={("pc1", "pc2"): 0.241, ("pc1", "pc3"): 0.052, ("pc2", "pc3"): -0.074},
        ),
        # Fase 59: GENRANGE_TREST real -100/400 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 400.0),
    ),
    # SNII_NMF_tail (2026-09-28, LSST_sim_lcs/docs/SNII_NMF_tail.md): SNII-NMF + parametrized 56Co tail
    # (snii_tail.SIMSEDTailModel). The SNII-NMF templates stop at +150.5 d from peak; this class continues them
    # smoothly and adds a nebular tail built from SN 2012aw spectra, scaled by the 56Ni deposition luminosity
    # with per-object m_ni and gamma-ray trapping time t0_trap. Priors from docs/snii_tail_literature_review.md.
    "SNII_NMF_tail": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNII-NMF",
        genrange_redshift=(0.011, 1.0),
        dndz=("ccs15", 0.162),
        sntype=42,
        redcor_params=dict(
            peaks=dict(pc1=0.0854, pc2=0.0199, pc3=0.0250),
            sigmas=dict(pc1=0.075, pc2=0.021, pc3=0.017),
            redcor={("pc1", "pc2"): 0.241, ("pc1", "pc3"): 0.052, ("pc2", "pc3"): -0.074},
        ),
        trest_range=(-100.0, 600.0),     # tail observable to ~600 rest-frame days (SNII-NMF: 400)
        tail=dict(
            template="snii_tail/sn2012aw_nebular_template.npz",
            cap=False,   # v4 (2026-09-29, user): no tail-brightness cap
            # v5 (2026-09-29, user): 56Ni masses follow Rodriguez+21 (quantile-mapped from the plateau relation)
            m_ni_map=dict(source=(-1.6276, 0.3136), target=(-1.50, 0.35), bounds=(0.001, 0.3)),   # v6: was (0.005, 0.18) (pile-up at the bounds)
            # v2: 56Ni tied to the template plateau, log10 M_Ni = -7.708 - 0.3755 M_V(50 d) + m_ni_dex
            # (Rodriguez+21 eq. 29, scatter 0.21 dex); M_Ni bounded to 0.001-0.3 Msun in snii_tail.py.
            # (v1 independent prior, for reference: m_ni=("lognormal", 0.0324, 0.806, 0.004, 0.2))
            m_ni_dex=("normal", 0.0, 0.21, -0.63, 0.63),
            # 70% ~full trapping (T0 400-1000 d, Sharon & Kushnir 2020); 30% leaking, log-normal around 200 d
            # (0.18 dex, clipped 85-550 d; Rodriguez+21 median 222 d)
            t0_trap=("mixture", [(0.7, ("uniform", 400.0, 1000.0)), (0.3, ("lognormal", 200.0, 0.414, 85.0, 550.0))]),
        ),
    ),
    # SNII_NMF_tail_lowz: SNII_NMF_tail restricted to z <= 0.3 (tail statistics), 2026-09-29
    "SNII_NMF_tail_lowz": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNII-NMF",
        genrange_redshift=(0.011, 0.3),   # tails undetectable beyond z ~ 0.25-0.3
        dndz=("ccs15", 0.162),
        sntype=42,
        redcor_params=dict(
            peaks=dict(pc1=0.0854, pc2=0.0199, pc3=0.0250),
            sigmas=dict(pc1=0.075, pc2=0.021, pc3=0.017),
            redcor={("pc1", "pc2"): 0.241, ("pc1", "pc3"): 0.052, ("pc2", "pc3"): -0.074},
        ),
        trest_range=(-100.0, 600.0),     # tail observable to ~600 rest-frame days (SNII-NMF: 400)
        tail=dict(
            template="snii_tail/sn2012aw_nebular_template.npz",
            cap=False,   # v4 (2026-09-29, user): no tail-brightness cap
            # v5 (2026-09-29, user): 56Ni masses follow Rodriguez+21 (quantile-mapped from the plateau relation)
            m_ni_map=dict(source=(-1.6276, 0.3136), target=(-1.50, 0.35), bounds=(0.001, 0.3)),   # v6: was (0.005, 0.18) (pile-up at the bounds)
            # v2: 56Ni tied to the template plateau, log10 M_Ni = -7.708 - 0.3755 M_V(50 d) + m_ni_dex
            # (Rodriguez+21 eq. 29, scatter 0.21 dex); M_Ni bounded to 0.001-0.3 Msun in snii_tail.py.
            # (v1 independent prior, for reference: m_ni=("lognormal", 0.0324, 0.806, 0.004, 0.2))
            m_ni_dex=("normal", 0.0, 0.21, -0.63, 0.63),
            # 70% ~full trapping (T0 400-1000 d, Sharon & Kushnir 2020); 30% leaking, log-normal around 200 d
            # (0.18 dex, clipped 85-550 d; Rodriguez+21 median 222 d)
            t0_trap=("mixture", [(0.7, ("uniform", 400.0, 1000.0)), (0.3, ("lognormal", 200.0, 0.414, 85.0, 550.0))]),
        ),
    ),
    # SNII_NMF_tail_div (2026-09-28): tail-luminosity diversity experiment = SNII_NMF_tail with m_ni_dex uniform
    # in [-1, +1] dex and z <= 0.3 (see LSST_sim_lcs/docs/SNII_NMF_tail.md, section 11).
    "SNII_NMF_tail_div": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNII-NMF",
        genrange_redshift=(0.011, 0.3),   # experiment: tails only observable at low z
        dndz=("ccs15", 0.162),
        sntype=42,
        redcor_params=dict(
            peaks=dict(pc1=0.0854, pc2=0.0199, pc3=0.0250),
            sigmas=dict(pc1=0.075, pc2=0.021, pc3=0.017),
            redcor={("pc1", "pc2"): 0.241, ("pc1", "pc3"): 0.052, ("pc2", "pc3"): -0.074},
        ),
        trest_range=(-100.0, 600.0),     # tail observable to ~600 rest-frame days (SNII-NMF: 400)
        tail=dict(
            template="snii_tail/sn2012aw_nebular_template.npz",
            # v2: 56Ni tied to the template plateau, log10 M_Ni = -7.708 - 0.3755 M_V(50 d) + m_ni_dex
            # (Rodriguez+21 eq. 29, scatter 0.21 dex); M_Ni bounded to 0.001-0.3 Msun in snii_tail.py.
            # (v1 independent prior, for reference: m_ni=("lognormal", 0.0324, 0.806, 0.004, 0.2))
            m_ni_dex=("uniform", -1.0, 1.0),   # experiment: tail luminosity diversity, +-1 dex about the relation
            # 70% ~full trapping (T0 400-1000 d, Sharon & Kushnir 2020); 30% leaking, log-normal around 200 d
            # (0.18 dex, clipped 85-550 d; Rodriguez+21 median 222 d)
            t0_trap=("mixture", [(0.7, ("uniform", 400.0, 1000.0)), (0.3, ("lognormal", 200.0, 0.414, 85.0, 550.0))]),
        ),
    ),
    # Fase 2B ronda 3: 3 clases SIMSED que declaran WV07 real (confirmado
    # `GENAV_WV07: 1` en su .INPUT, no el camino GENPROFILE_AV de SNIax).
    # ILOT-MOSFIT y SNIIn-MOSFIT reusan DNDZ: CC_S15 (ya validado en
    # SNII-NMF); PISN-MOSFIT usa el polinomio PISN_PLK12 real. Host
    # extinction real agregada en Fase 3, ver comentario arriba.
    "ILOT-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.ILOT-MOSFIT",
        genrange_redshift=(0.011, 0.45),
        dndz=("ccs15", 0.06),
        sntype=61,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 43: GENRANGE_TREST real del .INPUT es -100/1000 (Fase 40) --
        # el peor caso de las 14 clases, el hardcode global (-30,100) cubria
        # solo 11.8% de esa ventana ("Intermediate Luminosity Optical
        # Transient", evolucion mas lenta que una SN estandar).
        trest_range=(-100.0, 1000.0),
    ),
    # SNIbc-MOSFIT (LSST_sim_lcs 2026-10-06): MOSFIT SNe Ib/c (Guillochon & Villar), no SNANA SIMGEN_INCLUDE uses it,
    # settings chosen in LSST_sim_lcs/tools/snibc/patch_alces_snibc.py (rate from SED.INFO, window/dust as SNIIn-MOSFIT).
    "SNIbc-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIbc-MOSFIT",
        genrange_redshift=(0.011, 1.0),
        dndz=("md14", 1.5e-5),
        sntype=62,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        restlambda_range=(1000.0, 11000.0),
        trest_range=(-50.0, 300.0),
    ),
    "SNIIn-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIIn-MOSFIT",
        genrange_redshift=(0.03, 2.0),
        dndz=("ccs15", 0.0235),
        sntype=45,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -50/300 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-50.0, 300.0),
    ),
    "PISN-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.PISN-MOSFIT",
        genrange_redshift=(0.02, 2.4),
        dndz=("pisn", 1.0),
        sntype=70,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/300 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 300.0),
    ),
    # Fase 2B ronda 4: cierra el catalogo. KN-BULLA19 es la ultima de las
    # 11 clases SIMSED originales (su estructura de 3 sub-variantes
    # anidadas -- SIMSED.BULLA-BHNS-M1-2COMP, -BNS-M2-2COMP, -BNS-M3-3COMP
    # -- quedo sin investigar desde Fase 2B ronda 1; el .INPUT real usa
    # solo BNS-M2-2COMP via GENMODEL). PISN-STELLA-HECORE/-HYDROGENIC son
    # 2 clases mas alla de las 11 originales, encontradas al re-revisar
    # pipeline/models.yaml -- mismo GENMODEL:.../SIMSED.* que las demas,
    # nunca corridas.
    #
    # KN-BULLA19 usa `WV07_REWGT_EXPAV: 0.5` (no `GENAV_WV07: 1` directo) --
    # confirmado leyendo snlc_sim.c (linea ~7887): cualquier valor real de
    # WV07_REWGT_EXPAV activa `INPUTS.WV07_GENAV_FLAG = DO_WV07 = 1`, el
    # mismo flag que usan KN-K17/CaRT/SLSN-I. PISN-STELLA-HECORE/-HYDROGENIC
    # declaran `GENAV_WV07: 1` directo, igual que PISN-MOSFIT.
    "KN-BULLA19": dict(
        # los 550 "*.txt.gz" reales no son gzip -- son ZIP mal etiquetados
        # (firma PK, confirmado con `file`), cada uno con 1 miembro interno
        # del mismo nombre. Ver setup_knbulla19_local.py: copia local con
        # cada archivo descomprimido del ZIP y re-comprimido como gzip real
        # (SED.INFO no necesita fix, ya parsea limpio). Archivo real no
        # tocado.
        simsed_dir=HERE / "simsed_knbulla19_local",
        genrange_redshift=(0.011, 0.42),
        dndz=("powerlaw", [(320e-9, 0.0, 0.011, 0.42)]),  # identico a KN-K17
        sntype=52,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=0.5, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -100/500 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-100.0, 500.0),
    ),
    "PISN-STELLA-HECORE": dict(
        # Fase 75: copia local propia (mismo patrón que SNIa-91bg/KN-BULLA19)
        # -- una de las 3 clases piloto para instalación local (ver
        # vendor_snana_class.py, NOTES.md Fase 75). Antes leía directo de
        # SNANA_HOME / "run_SNANA/elastic/...", solo disponible en NLHPC.
        simsed_dir=HERE / "simsed_pisnstellahecore_local",
        genrange_redshift=(0.02, 3.3),
        dndz=("pisn", 1.0),
        sntype=71,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -50/300 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-50.0, 300.0),
    ),
    "PISN-STELLA-HYDROGENIC": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/elastic/model_libs_updates/SIMSED.PISN-STELLA-HYDROGENIC",
        genrange_redshift=(0.02, 3.3),
        dndz=("pisn", 1.0),
        sntype=72,
        # unica clase del catalogo con ngen_ddf != 2000 (pipeline/models.yaml:
        # 20000) -- confirmado, no un valor por defecto sin verificar.
        ngentot_lc=20000,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -50/300 (ver NOTES.md -- la clase que
        # motivo esta auditoria: empeoro +20.6% en Fase 58 con el hardcode
        # global -30/100, mismo hueco de Fase 40/43 nunca remedido para esta
        # clase y para casi todo el resto del catalogo).
        trest_range=(-50.0, 300.0),
    ),
}


_PL_B = ("BPOLY", [20383, -1757.7, 65.293, -1.1885, 0.10405e-01, -0.35119e-04])   # PLAsTiCC Galactic classes
_EL_B = ("BPOLY", [1.001, -5.55555556e-02, 1.23456790e-03, -1.37174211e-05, 7.62078951e-08, -1.69350878e-10])
for _name, _lib, _dndb, _mw, _type in [
        ("AGN", "LCLIB_AGN-LSST", ("COSBPOLY", [1.0]), True, 80),
        ("RRL", "LCLIB_RRL-LSST", _PL_B, True, 81),
        ("Mira", "LCLIB_MIRA_ISW2011", _PL_B, True, 82),
        ("EB", "LCLIB_EB-PHOEBE", _PL_B, True, 83),
        ("Mdwarf", "LCLIB_Mdwarf-LSST", ("COSBPOLY", [0.1, 1.0, 1.0, 1.0]), True, 84),
        ("uLens-Binary", "LCLIB_uLens-Binary", _PL_B, True, 85),
        ("uLens-GenLens", "LCLIB_uLens-Single-GenLens", _PL_B, True, 86),
        ("uLens-PyLIMA", "LCLIB_uLens-Single-PyLIMA", _PL_B, True, 87),
        ("uLens-String", "LCLIB_uLens-String", _PL_B, True, 88),     # no SNANA include: PLAsTiCC uLens density
        ("Cepheid", "LCLIB_Cepheid-LSST", _EL_B, False, 89),
        ("dSct", "LCLIB_d-Sct-LSST", _EL_B, False, 90),
        ("DwarfNova", "LCLIB_dwarf-nova-LSST", _EL_B, False, 91),
        ("Mdwarf-flare", "LCLIB_Mdwarf-flare-LSST", ("BPOLY", [-3.28230212e-03, 3.01446333e-02, -4.65144034e-03,
            3.16808686e-04, -1.20480381e-05, 2.76898385e-07, -3.92467157e-09, 3.34750950e-11, -1.57113870e-13,
            3.10724077e-16]), False, 92)]:
    CLASS_CONFIGS[_name] = dict(model="lclib", lclib=_lib, dndb=_dndb, apply_mw=_mw, sntype=_type,
                                genrange_redshift=(0.0, 0.0), dndz=("none", 0.0))


for _c in CLASS_CONFIGS.values():          # common observation window (docs/common_window.md)
    _c.pop("trest_range", None)
    _c.pop("restlambda_range", None)
    _c["window"] = WINDOW_MODE


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


def snana_noise_columns(df_ddf: pd.DataFrame) -> pd.DataFrame:
    snana = format_obs(df_ddf, pixsize=PIXSIZE)
    sig_psf_arcsec = df_ddf["seeingFwhmEff"].to_numpy() / (2 * np.sqrt(2 * np.log(2)))
    noise_area_arcsec2 = 4 * np.pi * sig_psf_arcsec ** 2
    out = df_ddf.copy()
    out["sky_bg_e"] = snana["SKYSIG"].to_numpy() ** 2
    out["psf_footprint"] = noise_area_arcsec2 / PIXSIZE ** 2
    out["zp"] = mag2flux(snana["ZPT"].to_numpy())
    return out


def passband_mean_wavelengths(passband_group, bands):
    """Fase 53: meanlam_obs por banda = sum(lambda*T)/sum(T) sobre la tabla
    real de transmision -- misma formula que usa SNANA real para el "central
    wavelength of filter" que aplica en la extincion escalar de host
    (genmag_SEDtools.c:335, confirmado en Fase 52)."""
    out = {}
    for b in bands:
        pb = passband_group[b]
        wave = pb.transmission_table[:, 0]
        trans = pb.transmission_table[:, 1]
        out[b] = float(np.trapezoid(wave * trans, wave) / np.trapezoid(trans, wave))
    return out


def host_extinction_mag_offset(z, host_av, r_v, meanlam_obs_band):
    """Fase 53: replica `GALextinct(RV_host, AV_host, meanlam_rest, 94, ...)`
    real de SNANA (`genmag_SIMSED.c:1554-1567`) -- un escalar de magnitud POR
    BANDA, evaluado en la longitud de onda media REST-FRAME del filtro
    (`meanlam_obs_band/(1+z)`), no una extincion aplicada punto a punto sobre
    el SED completo (lo que hacia `ClippedExtinctionEffect` con frame="rest"
    hasta Fase 52 -- ver `host_extinction_mode` en `build_source_model()`).
    O94 = OPT=94 real (O'Donnell 1994), ver Fase 51.

    z/host_av: arrays, uno por objeto. meanlam_obs_band: escalar (una banda
    fija por llamada). Devuelve un array de Δmag, mismo largo que z."""
    from dust_extinction.parameter_averages import O94
    import astropy.units as u
    ext = O94(Rv=r_v)
    x_min, x_max = ext.x_range
    lam_min_aa, lam_max_aa = 1e4 / x_max, 1e4 / x_min
    z_arr = np.atleast_1d(np.asarray(z, dtype=float))
    av_arr = np.atleast_1d(np.asarray(host_av, dtype=float))
    meanlam_rest = np.clip(meanlam_obs_band / (1.0 + z_arr), lam_min_aa, lam_max_aa)
    ebv_arr = av_arr / r_v
    factor = np.array([
        ext.extinguish(lam * u.angstrom, Ebv=e) for lam, e in zip(meanlam_rest, ebv_arr)
    ])
    return -2.5 * np.log10(factor)


def load_simsed_templates_bolometric(simsed_dir):
    """Fase 56: replica `T0shiftPeak_SEDMODEL()` real de SNANA
    (`genmag_SEDtools.c:2825-2884`), activo por defecto para SIMSED via
    `OPTMASK_T0SHIFT_PEAKMAG` (`genmag_SIMSED.c:226-230`, "shift T=0 to
    peak"). SNANA shiftea la grilla `DAY` de CADA template para que el dia
    con mayor flujo bolometrico (suma simple de flujo sobre todos los bins
    de lambda del archivo, sin ponderar por dlambda -- formula real
    confirmada linea por linea) quede en `DAY=0`. `Trest=0` real de SNANA
    es entonces el pico bolometrico del template, NO la fase nativa 0 del
    archivo `.SED` (que en `SNIa-91bg` vale `+1`/`+2` dias segun el
    template, y en `CaRT` hasta `+33` dias -- ver NOTES.md Fase 56).

    Fase 62: la Fase 56 declaro esto "activo sin excepcion en las 12 clases
    SIMSED" -- FALSO, un error de auditoria (solo se revisaron los
    `SED.INFO` bajo `plasticc_models/`, no las rutas alternativas
    `elastic/model_libs_updates/` ni el `SED.INFO` anidado bajo
    `SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP/`). Los `SED.INFO` reales
    de `KN-BULLA19`/`PISN-STELLA-HECORE`/`PISN-STELLA-HYDROGENIC`
    declaran `OPTFLAG_T0SHIFT_PEAKMAG: 0` ("do NOT time-shift PEAKMAG to
    DAY=0") -- las UNICAS 3 excepciones reales del catalogo (confirmado
    barriendo las 13 clases). Esto explica de punta a punta el hallazgo de
    Fase 60 (esas 3 clases tienen `PEAKMAG_{u..Y}` = `99`/`-9` en el 100%
    de los objetos del `.DUMP` real de SNANA -- no un problema de la
    referencia, sino la consecuencia esperada de evaluar en fase nativa 0
    un modelo cuyo dia 0 real es "tiempo de fusion"/explosion, sin brillo
    -- ver NOTES.md Fase 62). Respetar el flag real evita que
    `simsed_t0_mode="bolometric_peak"` (default de produccion desde Fase
    57) le aplique a estas 3 clases un shift que la propia SNANA nunca
    aplica -- sin este fix, LightCurveLynx y SNANA quedarian usando
    referencias de tiempo distintas para las 3.

    Devuelve (templates, flux_scale) en el MISMO orden que
    `SIMSEDModel.from_dir()` (orden real de las lineas `SED:` en
    `SED.INFO`) -- `selected_template` indexa ese mismo orden
    (`MultiSEDTemplateModel.__init__`, confirmado leyendo la fuente real
    del paquete instalado)."""
    simsed_dir = Path(simsed_dir)
    file_names, simsed_params = SIMSEDModel._read_simsed_info_file(simsed_dir)
    flux_scale = float(simsed_params.get("FLUX_SCALE", 1.0))
    # Fase 62: default real de SNANA es "shiftear" (OPTMASK_T0SHIFT_PEAKMAG
    # activo por defecto, genmag_SIMSED.c:226-230) -- solo se desactiva si
    # el SED.INFO real de la clase declara la clave explicita en 0.
    do_shift = int(simsed_params.get("OPTFLAG_T0SHIFT_PEAKMAG", 1)) != 0
    templates = []
    for file_name in file_names:
        path = Path(file_name)
        if not path.exists() and path.suffix != ".gz":
            path = path.with_suffix(path.suffix + ".gz")
        data = np.loadtxt(path, comments="#")
        if do_shift:
            # Fase 58: suma de flujo por fase vectorizada (sort +
            # np.add.reduceat) -- el loop original (mascara booleana por
            # cada fase unica) es O(N_fases x N_filas); para templates con
            # grilla de fase muy fina (p.ej. KN-K17, kilonovas con cientos
            # de fases) tardaba minutos por archivo. Mismo resultado,
            # mismo orden de magnitud mas rapido.
            order = np.argsort(data[:, 0], kind="stable")
            phase_sorted = data[order, 0]
            flux_sorted = data[order, 2]
            phases, start_idx = np.unique(phase_sorted, return_index=True)
            fluxsum = np.add.reduceat(flux_sorted, start_idx)
            t0_bolo = float(phases[np.argmax(fluxsum)])
        else:
            t0_bolo = 0.0
        templates.append(SEDTemplate(
            data, sed_data_t0=t0_bolo, interpolation_type="linear", periodic=False,
        ))
    return templates, flux_scale


def build_source_model(cfg: dict, obs_table: OpSim, seed_base: int, t_start: float, wfd: bool = False,
                        host_extinction_mode: str = "sed", simsed_t0_mode: str = "raw"):
    """Arma el SIMSEDModel real (pesos SIMSED_REDCOR o uniformes, dndz,
    radec/t0/distancia, extincion MW+host, fixes de semilla) para una clase
    de CLASS_CONFIGS -- bloque compartido entre main() (14 clases,
    produccion) y compare_brightness_truth.py (Fase 50: medir brillo
    verdadero sin duplicar parametros a mano en un segundo script, el mismo
    duplicado que hizo que el fix de Fase 22 tardara 25 fases en llegar a
    ese archivo -- ver NOTES.md). Devuelve (source_model, radec_sampler);
    trest_range/restlambda_range se leen directo de cfg por el llamador,
    no dependen de la construccion del modelo.

    host_extinction_mode (Fase 53): "sed" (default, produccion -- main())
    aplica la extincion de host punto a punto sobre el SED completo
    (ClippedExtinctionEffect, frame="rest") -- comportamiento historico, sin
    cambios de comportamiento desde Fase 51. "scalar" (usado por
    compare_brightness_truth.py) NO aplica el efecto sobre el SED -- solo
    registra `host_av` como parametro real del modelo (sampleado, mismo seed
    de siempre), para que el llamador aplique la correccion escalar por banda
    que replica el `GALextinct(...)` real de SNANA (ver
    `host_extinction_mag_offset()` mas arriba en este archivo, y NOTES.md
    Fase 52/53: SNANA aplica un escalar de magnitud evaluado en la longitud
    de onda media REST-FRAME del filtro, no una extincion sobre el SED
    completo -- Fase 52 midio que esa diferencia de convencion, no la ley de
    polvo, es el mecanismo dominante detras del residuo que crece con z en
    SNIax/CaRT). El default se deja en "sed" para no alterar en silencio los
    resultados de produccion/deteccion ya reportados por main() -- extender
    el modo "scalar" a produccion queda pendiente de una fase separada
    (requiere resolver si FLUXCALERR debe re-escalarse junto con FLUXCAL).

    simsed_t0_mode (Fase 56/57): "raw" (default de esta funcion) arma los
    templates con `SIMSEDModel.from_dir()`, que fija `sed_data_t0=0.0` -- la
    fase nativa 0 del archivo `.SED`, sin verificar si coincide con el pico
    real. "bolometric_peak" arma los templates con
    `load_simsed_templates_bolometric()` -- cada uno shifteado a su propio
    pico bolometrico real, replicando el `T0shiftPeak_SEDMODEL()` real de
    SNANA (ver docstring de esa funcion y NOTES.md Fase 56). El default de
    ESTA funcion se deja en "raw" (compatibilidad hacia atras para cualquier
    llamador que no lo especifique) -- pero `main()` (produccion, Fase 57) ya
    lo pasa como "bolometric_peak" por defecto: un piloto real (`CaRT`, la
    clase con mayor shift del catalogo) midio impacto minimo en deteccion, ver
    NOTES.md Fase 57."""
    if cfg.get("model") == "lclib":                 # non-transient LCLIB classes (docs/nontransients.md)
        return build_lclib_model(cfg, obs_table, seed_base, t_start, wfd=wfd)
    is_salt2 = cfg.get("model") == "salt2"          # SNIa-SALT2: no SIMSED templates (build_salt2_model)
    simsed_dir = cfg.get("simsed_dir")
    file_names = [] if is_salt2 else SIMSEDModel._read_simsed_info_file(simsed_dir)[0]
    if is_salt2:
        weights = None
    elif "redcor_params" in cfg:
        # peso real via bivariada/multivariada normal correlacionada
        # (SIMSED_REDCOR), no uniforme -- parsear los valores propios de
        # cada template desde SED.INFO (mismo orden que PARNAMES).
        sed_info_text = (simsed_dir / "SED.INFO").read_text()
        param_names = None
        for line in sed_info_text.splitlines():
            if line.strip().upper().startswith("PARNAMES:"):
                param_names = line.split()[1:]
                break
        param_rows = [
            line.split()[2:] for line in sed_info_text.splitlines()
            if line.strip().upper().startswith("SED:")
        ]
        rc = cfg["redcor_params"]
        # PARNAMES puede traer columnas extra que no son parametros fisicos
        # correlacionados (p.ej. "II_INDEX" antes de pc1/pc2/pc3 en
        # SNII-NMF) -- solo se usan las columnas que aparecen en
        # redcor_params["peaks"], el resto se ignora.
        values = {
            name: np.array([float(r[i]) for r in param_rows])
            for i, name in enumerate(param_names)
            if name in rc["peaks"]
        }
        weights = make_correlated_normal_weights(values, rc["peaks"], rc["sigmas"], rc["redcor"])
        print(f"[{time.time()-t_start:.1f}s] {len(file_names)} templates SIMSED, "
              f"pesos via SIMSED_REDCOR real ({list(values.keys())})")
    else:
        # peso uniforme (SIMSED_GRIDONLY en el .INPUT real) -- None hace
        # que MultiSEDTemplateModel pese todos los templates igual.
        weights = None
        print(f"[{time.time()-t_start:.1f}s] {len(file_names)} templates SIMSED "
              f"(peso uniforme, SIMSED_GRIDONLY)")

    z_min, z_max = cfg["genrange_redshift"]
    dndz_kind, dndz_params = cfg["dndz"]
    if dndz_kind == "powerlaw":
        z_grid, cdf = build_dndz_powerlaw2_cdf(segments=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "md14":
        z_grid, cdf = build_dndz_md14_cdf(rate0=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "ccs15":
        z_grid, cdf = build_dndz_ccs15_cdf(scale=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "tde":
        z_grid, cdf = build_dndz_tde_cdf(rate0=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "pisn":
        z_grid, cdf = build_dndz_pisn_cdf(scale=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "logz_piecewise":
        # flat-log-z mode: density piecewise constant in ln z with the given per-bin weights; CDF on a fine ln-z grid
        e = np.asarray(dndz_params["edges"], dtype=float)
        wts = np.asarray(dndz_params["weights"], dtype=float) + 1e-12      # strictly increasing CDF
        cdf_e = np.concatenate([[0.0], np.cumsum(wts)]) / wts.sum()
        lnz = np.linspace(np.log(e[0]), np.log(e[-1]), 40001)
        z_grid, cdf = np.exp(lnz), np.interp(lnz, np.log(e), cdf_e)
    else:
        raise ValueError(f"dndz_kind desconocido: {dndz_kind}")
    redshift_func = SizeAwareFunctionNode(make_dndz_sampler(z_grid, cdf, seed=seed_base + 1), node_label="redshift")
    # Fase 5: radius=0.0 explicito -- ObsTableRADECSampler.compute() aplica
    # un jitter de posicion dentro del FOV usando np.random.default_rng()
    # SIN seed cuando self.radius>0 (heredado del radius real de OpSim,
    # bug de la libreria, confirmado leyendo ra_dec_sampler.py). Los campos
    # DDF son pointings fijos, no requieren jitter sub-FOV -- radius=0.0
    # evita ese codepath entero.
    # Fase 17: "field" solo existe para DDF (6 pointings fijos) -- WFD no
    # tiene esa columna, asi que no se pide como extra_cols.
    radec_sampler = ObsTableRADECSampler(
        obs_table, extra_cols=[] if wfd else ["field"], seed=seed_base + 5, radius=RADEC_SAMPLER_RADIUS_DEG,
    )
    # Segundo bug de la libreria, mas profundo: TableSampler.__init__
    # (clase base de ObsTableRADECSampler) crea su propio muestreador de
    # indice de fila via `NumpyRandomFunc("integers", low=0, high=N)` SIN
    # pasarle seed= (confirmado leyendo given_sampler.py) -- el seed=
    # que se le pasa al constructor de ObsTableRADECSampler nunca llega a
    # este nodo hijo, asi que la fila/pointing real elegida para cada
    # objeto (y por lo tanto que observaciones reales le corresponden)
    # segui siendo no reproducible incluso despues del fix de radius=0.0
    # de arriba. Mismo patron que el bug de SIMSEDModel de Fase 4: fijar
    # el seed del nodo interno directamente via .setters[...].dependency.
    radec_sampler.setters["selected_table_index"].dependency.set_seed(seed_base + 5)
    t0_func = NumpyRandomFunc(
        "uniform", low=float(obs_table["time"].min()), high=float(obs_table["time"].max()), seed=seed_base + 6,
    )

    def _luminosity_distance_pc(size=None, redshift=None, **_kwargs):
        from astropy.cosmology import FlatLambdaCDM
        import astropy.units as u
        # Fase 34/35: Om0=0.315 es OMEGA_MATTER_DEFAULT real de SNANA (sntools.h),
        # no 0.3 -- ver NOTES.md Fase 34.
        cosmo = FlatLambdaCDM(H0=70.0, Om0=0.315)
        z = np.asarray(redshift)
        return cosmo.luminosity_distance(z).to(u.pc).value

    distance_func = SizeAwareFunctionNode(_luminosity_distance_pc, node_label="distance", redshift=redshift_func)

    # Fase 10: GENSIGMA_MWEBV_RATIO=0.16 real y activo (ver
    # snana_params.make_mwebv_ratio_scatter para la formula, verificada
    # contra snlc_sim.c::gen_MWEBV()).
    if wfd:
        # Fase 17: sin campos fijos, nearest-neighbor angular contra la
        # grilla real de E(B-V) (ver snana_params.make_wfd_ebv_lookup) usando
        # el RA/DEC exacto de cada objeto en vez del nombre de campo.
        _wfd_ebv_lookup = make_wfd_ebv_lookup(WFD_MWEBV_GRID, GENSIGMA_MWEBV_RATIO, seed=seed_base + 10)
        ebv_func = SizeAwareFunctionNode(
            _wfd_ebv_lookup, node_label="ebv", ra=radec_sampler.ra, dec=radec_sampler.dec,
        )
    else:
        _mwebv_scatter = make_mwebv_ratio_scatter(GENSIGMA_MWEBV_RATIO, seed=seed_base + 10)

        def _field_to_ebv(size=None, field=None, **_kwargs):
            arr = np.asarray(field)
            nominal = np.array([DDF_FIELD_EBV.get(f, 0.0) for f in arr.ravel()]).reshape(arr.shape)
            return _mwebv_scatter(nominal)

        ebv_func = SizeAwareFunctionNode(_field_to_ebv, node_label="ebv", field=radec_sampler.field)
    # Fase 24: el .INPUT real de esta campana (inyectado por clase, confirmado
    # identico para SNIa/SLSN-I/SNIa-91bg) usa OPT_MWCOLORLAW=99 (Fitzpatrick
    # 1999 EXACTO, MWgaldust.h), no O94/CCM89 -- nunca antes verificado contra
    # el valor numerico real (la Fase 1 solo asumio "misma familia"). Corregido
    # a "F99" (dust_extinction.F99, misma familia real). Verificado numerica-
    # mente que la diferencia O94-vs-F99 es <0.005 mag incluso a E(B-V)=0.10
    # (los 6 campos DDF reales estan en 0.006-0.025) -- descartado como causa
    # del patron cromatico de Fase 23, pero es una correccion real igual.
    mw_extinction = ClippedExtinctionEffect(
        extinction_model="F99", ebv=ebv_func, r_v=MW_RV, frame="observer", backend="dust_extinction",
    )

    if is_salt2:
        source_model = build_salt2_model(cfg, seed_base, redshift_func, radec_sampler, t0_func, t_start)
    elif simsed_t0_mode == "bolometric_peak":
        templates, flux_scale = load_simsed_templates_bolometric(simsed_dir)
        if "tail" in cfg:
            # SNII_NMF_tail: SIMSEDModel + template continuation + parametrized 56Co tail (snii_tail.py)
            from snii_tail import SIMSEDTailModel, make_tail_sampler
            tail_cfg = cfg["tail"]
            ni_key = "m_ni_dex" if "m_ni_dex" in tail_cfg else "m_ni"
            ni_func = SizeAwareFunctionNode(make_tail_sampler(tail_cfg[ni_key], seed_base + 11), node_label=ni_key)
            t0_trap_func = SizeAwareFunctionNode(make_tail_sampler(tail_cfg["t0_trap"], seed_base + 12),
                                                 node_label="t0_trap")
            source_model = SIMSEDTailModel(
                templates, flux_scale=flux_scale, weights=weights,
                t0_trap=t0_trap_func, tail_template=HERE / tail_cfg["template"], **{ni_key: ni_func},
                tail_cap=tail_cfg.get("cap", True),
                m_ni_map=tail_cfg.get("m_ni_map"),
                ra=radec_sampler.ra, dec=radec_sampler.dec,
                redshift=redshift_func, distance=distance_func, t0=t0_func,
            )
            print(f"[{time.time()-t_start:.1f}s] SIMSEDTailModel: {ni_key} {tail_cfg[ni_key]}, "
                  f"t0_trap {tail_cfg['t0_trap']}")
        else:
            source_model = SIMSEDModel(
                templates, flux_scale=flux_scale, weights=weights,
                ra=radec_sampler.ra, dec=radec_sampler.dec,
                redshift=redshift_func, distance=distance_func, t0=t0_func,
            )
    else:
        if "tail" in cfg:
            raise ValueError("tail classes (SNII_NMF_tail) require simsed_t0_mode='bolometric_peak'")
        source_model = SIMSEDModel.from_dir(
            simsed_dir, weights=weights,
            ra=radec_sampler.ra, dec=radec_sampler.dec,
            redshift=redshift_func, distance=distance_func, t0=t0_func,
        )
    # Fase 4: SIMSEDModel.from_dir() nunca pasa un seed a su
    # GivenValueSampler interno (confirmado leyendo sed_template_model.py:
    # `self._sampler_node = GivenValueSampler(all_inds, weights=weights)`,
    # sin `seed=`) -- NumpyRandomFunc con seed=None cae a
    # `os.urandom()` (math_nodes/np_random.py), es decir la seleccion de
    # template real de SIMSED **nunca fue reproducible** entre corridas en
    # ninguna ronda anterior de Fase 2B/3, pese a SEED_BASE. Fijar el seed
    # aqui para que corridas futuras sean reproducibles -- no se re-corrio
    # el catalogo completo de nuevo solo por esto (ver NOTES.md Fase 4).
    if not is_salt2:
        source_model._sampler_node.set_seed(seed_base + 9)
    source_model.add_effect(mw_extinction)

    if "host_av" in cfg:
        # extincion de host real -- tres variantes reales de SNANA, todas
        # verificadas linea por linea contra snlc_sim.c (ver NOTES.md):
        # "exp" = solo componente exponencial (TDE-MOSFIT); "exp_halfgauss"
        # = mezcla exponencial+semi-Gaussiana via GENPROFILE_AV (SNIax);
        # "wv07" = modelo ESSENCE-WV07 real (GENAV_WV07(), Fase 3) --
        # funcion autonoma con constantes fijas (tau=0.4, sqsigma=0.01),
        # NO la que tenia el bug historico (esa es getRan_GEN_EXP_HALFGAUSS,
        # nunca llamada por GENAV_WV07).
        hp = cfg["host_av"]
        kind = hp.get("kind", "exp")
        if kind == "exp_halfgauss":
            av_sampler_fn = make_exp_halfgauss_av_sampler(
                tau=hp["tau"], sig=hp["sig"], ratio=hp["ratio"],
                av_range=hp["av_range"], seed=seed_base + 8,
            )
            av_desc = f"GENTAU_AV={hp['tau']}"
        elif kind == "wv07":
            av_sampler_fn = make_wv07_av_sampler(
                av_range=hp["av_range"], rewgt_expav=hp.get("rewgt_expav"), seed=seed_base + 8,
            )
            av_desc = f"WV07_REWGT_EXPAV={hp.get('rewgt_expav')}"
        else:
            av_sampler_fn = make_exp_av_sampler(tau=hp["tau"], av_max=hp["av_max"], seed=seed_base + 8)
            av_desc = f"GENTAU_AV={hp['tau']}"
        av_func = SizeAwareFunctionNode(av_sampler_fn, node_label="host_av")

        if host_extinction_mode == "scalar":
            # Fase 53: sin efecto sobre el SED -- solo se registra host_av
            # como parametro real del modelo (sampleado, mismo seed de
            # siempre) para que el llamador (compare_brightness_truth.py)
            # aplique la correccion escalar por banda que replica el
            # GALextinct(..., meanlam_rest, 94, ...) real de SNANA.
            source_model.add_parameter("host_av", av_func)
            assert "host_av" in source_model.setters, (
                "host_av no se registro como parametro del modelo (Fase 53)"
            )
            print(f"[{time.time()-t_start:.1f}s] extincion de host: parametro host_av "
                  f"registrado (kind={kind}, {av_desc}, R_V={hp['r_v']}) -- SIN aplicar al "
                  f"SED, correccion escalar por banda a cargo del llamador (Fase 53)")
        else:
            def _av_to_ebv(size=None, host_av=None, **_kwargs):
                return np.asarray(host_av) / hp["r_v"]

            host_ebv_func = SizeAwareFunctionNode(_av_to_ebv, node_label="host_ebv", host_av=av_func)
            # Fase 51: extinction_model="O94" (no "CCM89") -- GALextinct() real
            # (genmag_SIMSED.c:1567) llama siempre con OPT=94 (O'Donnell 1994,
            # MWgaldust.h:27) para host, ignorando INPUTS.OPT_SNXT/GENSNXT="CCM89"
            # (esa variable solo se usa para modelos rest-frame tipo MLCS2K2, no
            # para SIMSED -- confirmado, ver NOTES.md). ebv_param_name="host_ebv"
            # evita la colision de nombre "ebv" con mw_extinction (ver docstring
            # de ClippedExtinctionEffect).
            host_extinction = ClippedExtinctionEffect(
                extinction_model="O94", ebv=host_ebv_func, r_v=hp["r_v"], frame="rest", backend="dust_extinction",
                ebv_param_name="host_ebv",
            )
            source_model.add_effect(host_extinction)
            assert "host_ebv" in source_model.setters, (
                "host_extinction no registro un setter propio -- colision de "
                "nombre de parametro con mw_extinction sin resolver (Fase 51)"
            )
            print(f"[{time.time()-t_start:.1f}s] extincion de host real aplicada "
                  f"(kind={kind}, {av_desc}, R_V={hp['r_v']})")

    print(f"[{time.time()-t_start:.1f}s] " + ("SALT2 model cargado" if is_salt2 else
                                                f"SIMSEDModel cargado ({len(source_model)} templates)"))

    return source_model, radec_sampler


def main(class_key: str, ngentot_override: int | None = None, seed_index: int = 0, wfd: bool = False,
         simsed_t0_mode: str = "bolometric_peak", out_dir_override: Path | str | None = None):
    # Fase 57: default de PRODUCCION cambia a "bolometric_peak" (Fase 56) --
    # piloto real (CaRT, 1 semilla, la clase con mayor shift del catalogo)
    # midio impacto minimo en deteccion (167->164 de 1998 objetos, SNR
    # mediana identica 0.682->0.682) porque la ventana de generacion real
    # (-30/100 dias) ya era mas ancha que el shift tipico (1-33 dias) y
    # seguia cubriendo el pico real en ambos modos -- el fix corrige la
    # fidelidad de brillo/alineacion temporal sin invalidar de forma
    # importante los ratios de deteccion ya medidos. build_source_model()
    # mantiene su propio default "raw" (sin cambios) -- este override es
    # especifico de main()/produccion, ver NOTES.md Fase 57.
    cfg = CLASS_CONFIGS[class_key]
    if cfg.get("logz") and (cfg["logz"]["mode"] == "WFD") != bool(wfd):
        raise ValueError(f"{class_key}: flat-log-z class for {cfg['logz']['mode']} run with wfd={wfd}")
    # la mayoria de las clases DDF usan NGENTOT_LC=2000 (pipeline/models.yaml:
    # ngen_ddf), pero PISN-STELLA-HYDROGENIC es la excepcion real (ngen_ddf:
    # 20000) -- cfg["ngentot_lc"] la overridea; ngentot_override (usado por
    # los smoke tests) tiene prioridad sobre ambas. Fase 17: WFD usa el
    # mismo NGENTOT que DDF (misma excepcion incluida) -- el usuario eligio
    # "NGENTOT chico, tipo DDF" en vez de la escala real de produccion
    # (200.000/clase) para no volver a agotar la cuota de NLHPC.
    ngentot = ngentot_override if ngentot_override is not None else cfg.get("ngentot_lc", NGENTOT_LC)
    # Fase 5: seed_index != 0 corre una realizacion independiente (semilla
    # real distinta, offset grande para no chocar con los sub-offsets +1..+9
    # ya usados abajo) en un directorio de salida separado -- no pisa el
    # resultado "principal" (seed_index=0) ya reportado en el dashboard/
    # NOTES.md, para poder cuantificar varianza entre semillas sin invalidar
    # las comparaciones ya publicadas.
    seed_base = SEED_BASE + seed_index * 1_000_000
    seed_suffix = f"_seed{seed_index}" if seed_index else ""
    wfd_suffix = "_wfd" if wfd else ""
    # Fase 57: sufijo separado cuando se prueba simsed_t0_mode="bolometric_peak"
    # (Fase 56) en produccion -- no pisa los directorios "raw" ya reportados,
    # para poder comparar antes de decidir si cambiar el default.
    t0_suffix = "_bolopeak" if simsed_t0_mode != "raw" else ""
    # Fase 66: out_dir_override permite que un llamador externo (sweep_worker.py)
    # elija el directorio de salida (nombrado por hash de corrida, ver
    # sweep_hash.py) en vez del nombre posicional de siempre -- necesario
    # porque ese nombre no incluye ngentot, asi que dos corridas con el
    # mismo (class_key, seed_index, wfd, simsed_t0_mode) pero distinto
    # ngentot_override podrian pisarse. Default None preserva el
    # comportamiento exacto de siempre: el CLI interactivo (bloque
    # __main__ mas abajo) nunca pasa este argumento.
    if out_dir_override is not None:
        out_dir = Path(out_dir_override)
    else:
        out_dir = HERE / f"poc_output_{class_key.lower().replace('-', '')}{seed_suffix}{wfd_suffix}{t0_suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    con = sqlite3.connect(str(OPSIM_DB))
    df = pd.read_sql_query("SELECT * FROM observations", con)
    if wfd:
        # Fase 17: mismo patron ya establecido de leer directo del .db en vez
        # del SIMLIB pre-construido (minimiza riesgo de una ruta de datos
        # nueva sin probar) -- WFD es simplemente "todo lo que no es DDF" en
        # el mismo baseline_v5.3.1_10yrs.db (confirmado: 1,698,844/1,844,189
        # filas, 92.1%, ver NOTES.md Fase 17). Sin campos fijos, asi que no
        # hay columna "field" que extraer.
        df_ddf = df[~df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
    else:
        df_ddf = df[df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
        df_ddf["field"] = df_ddf["target_name"].str.extract(r"ddf_(\w+)")
    df_ddf = snana_noise_columns(df_ddf)
    obs_table = OpSim(df_ddf, zp_err_mag=0.005)
    print(f"[{time.time()-t_start:.1f}s] [{class_key}] OpSim {'WFD' if wfd else 'DDF'}: "
          f"{len(df_ddf):,} obs, ruido real de SNANA inyectado")

    passband_group = PassbandGroup.from_preset(preset="LSST", table_dir=str(LSST_PASSBAND_TABLE_DIR))
    print(f"[{time.time()-t_start:.1f}s] passbands cargados (Fase 55: u truncado a 4134A real)")

    source_model, radec_sampler = build_source_model(
        cfg, obs_table, seed_base, t_start, wfd=wfd, simsed_t0_mode=simsed_t0_mode,
    )

    t_sim0 = time.time()
    # Fase 5: rng= explicito -- simulate_lightcurves() acepta un
    # numpy.random.Generator opcional que se propaga a cualquier nodo del
    # grafo sin seed propio (p.ej. la aplicacion de ruido fotometrico), y
    # que si no se pasa cae en un generador default no reproducible. Los
    # otros nodos (redshift, radec, t0, host_av, template) ya tienen su
    # propio seed explicito arriba -- este cierra el ultimo hueco.
    # Fase 43: rest_time_window_offset real por clase (antes hardcodeado
    # (-30,100) e identico para las 14, pese a que GENRANGE_TREST real varia
    # de -50/300 a -100/1000 -- ver NOTES.md Fase 40/43). Default (-30,100)
    # para las clases que no declaran trest_range explicito en CLASS_CONFIGS
    # (no re-medidas en esta fase, ver NOTES.md Fase 43 para el alcance).
    model_span = model_rest_span(source_model, cfg)
    trest_range = (model_span[0] - SIM_MARGIN_REST, model_span[1] + SIM_MARGIN_REST)   # internal span (common window)
    print(f"[{time.time()-t_start:.1f}s] common window {WINDOW_MODE}: model {model_span[0]:.0f}/{model_span[1]:.0f} d "
          f"rest -> simulated {trest_range[0]:.0f}/{trest_range[1]:.0f} d rest; kept: first detection - "
          f"{LC_PRE_DAYS:g} d to last detection + {LC_POST_DAYS:g} d (observer frame)")
    lc = simulate_lightcurves(source_model, ngentot, survey_info=SurveyInfo(
        obstable=obs_table, passbands=passband_group, survey_name="LSST",
    ), rest_time_window_offset=trest_range, rng=np.random.default_rng(seed_base + 2))
    sim_wall_time = time.time() - t_sim0
    print(f"[{time.time()-t_start:.1f}s] simulacion terminada: {len(lc)} objetos, "
          f"{sim_wall_time:.1f}s ({sim_wall_time/max(len(lc),1)*1000:.2f} ms/objeto)")

    # Fase 13: replica el "bail if any part of filter trans is outside model
    # range" real de SNANA -- si la clase declara restlambda_range, cualquier
    # observacion cuya banda no quepa COMPLETA en marco de reposo dentro de
    # ese rango se descarta antes de aplanar (SNANA nunca la genera; LCL por
    # defecto seguia devolviendo un flujo extrapolado/clampeado no-cero via
    # RectBivariateSpline sin ningun chequeo de rango de longitud de onda,
    # confirmado leyendo SEDTemplate.evaluate_sed() -- ver NOTES.md).
    restlambda_range = None        # common window: no per-class band cuts (zero flux outside each SED grid instead)
    n_gated_total = 0

    # Fase 59-perf: aplanado vectorizado (antes: doble iterrows anidado --
    # boxeaba CADA fila de fotometria en un pandas.Series, ~57us/fila medido
    # real en NLHPC independiente de la clase, dominado por Series.__init__/
    # sanitize_array segun cProfile -- para PISN-STELLA-HYDROGENIC (119M
    # filas) esto solo tomaba ~1h54min, mas que la simulacion misma. Ahora:
    # una unica pd.concat() de las sub-tablas ya tabulares que devuelve
    # simulate_lightcurves(), sin ningun loop de Python por fila. Verificado
    # equivalente fila a fila contra la version anterior (pd.testing.
    # assert_frame_equal, datos sinteticos con la forma real) -- 362x mas
    # rapido en el benchmark local, mismo resultado exacto. Ver NOTES.md.
    valid_mask = lc["lightcurve"].apply(lambda s: s is not None and len(s) > 0)
    valid = lc[valid_mask]

    if valid.empty:
        head_df = pd.DataFrame(columns=["SNID", "SNTYPE", "RA", "DEC", "REDSHIFT_HELIO", "PEAKMJD", "NOBS"])
        phot_df = pd.DataFrame(columns=["SNID", "MJD", "FLT", "FLUXCAL", "FLUXCALERR", "FLUXTRUE"])
    else:
        snids = valid["id"].astype(int).astype(str)
        phot_df = pd.concat(
            valid["lightcurve"].tolist(), keys=snids.tolist(), names=["SNID", None],
        ).reset_index(level="SNID")
        flt_str = phot_df["filter"].astype(str)
        phot_df["FLT"] = flt_str.where(flt_str != "y", "Y")

        if restlambda_range is not None:
            z_by_snid = pd.Series(valid["z"].to_numpy(), index=snids.to_numpy())
            z_per_row = phot_df["SNID"].map(z_by_snid).to_numpy()
            keep_mask = restlambda_gate_vec(z_per_row, phot_df["FLT"].to_numpy(), restlambda_range)
            n_gated_total = int((~keep_mask).sum())
            phot_df = phot_df[keep_mask]

        # Fase 64: se retiene "flux_perfect" (flujo sin ruido, ya calculado y
        # antes descartado por simulate_lightcurves() -- ver NOTES.md) como
        # FLUXTRUE, en la MISMA escala fisica (nJy) que FLUXCAL -- necesario
        # para que el trigger real de SEARCHEFF use SNR_CALC (flujo
        # verdadero/error), no SNR_OBS (flujo observado/error, el "wrong SNR"
        # real de SNANA que este proyecto calculaba desde la Fase 4).
        phot_df = phot_df.rename(columns={
            "mjd": "MJD", "flux": "FLUXCAL", "fluxerr": "FLUXCALERR", "flux_perfect": "FLUXTRUE",
        })
        phot_df = phot_df[["SNID", "MJD", "FLT", "FLUXCAL", "FLUXCALERR", "FLUXTRUE"]].reset_index(drop=True)

        nobs = phot_df.groupby("SNID").size()
        head_df = pd.DataFrame({
            "SNID": snids.to_numpy(), "SNTYPE": cfg["sntype"], "RA": valid["ra"].to_numpy(),
            "DEC": valid["dec"].to_numpy(), "REDSHIFT_HELIO": valid["z"].to_numpy(),
            "PEAKMJD": valid["t0"].to_numpy(),
        })
        head_df["NOBS"] = head_df["SNID"].map(nobs).fillna(0).astype(int)
        # replica el "continue" real de la version anterior: un objeto que
        # pierde TODAS sus observaciones por el gate de RESTLAMBDA_RANGE
        # tampoco entraba a head_rows -- se descarta del todo, no solo su
        # fotometria.
        head_df = head_df[head_df["NOBS"] > 0].reset_index(drop=True)

    if restlambda_range is not None:
        print(f"[{time.time()-t_start:.1f}s] Fase 13: {n_gated_total} observaciones suprimidas "
              f"por caer fuera de RESTLAMBDA_RANGE={restlambda_range} en marco de reposo")

    MAG_AB_ZP_NJY = 8.9 + 2.5 * 9
    positive = phot_df["FLUXCAL"] > 0
    phot_df["MAG"] = np.where(positive, MAG_AB_ZP_NJY - 2.5 * np.log10(phot_df["FLUXCAL"].where(positive)), np.nan)
    print(f"[{time.time()-t_start:.1f}s] aplanado: {len(head_df)} objetos con obs, "
          f"{len(phot_df)} filas de fotometria")

    snr_sim = (phot_df["FLUXCAL"] / phot_df["FLUXCALERR"]).abs()
    print(f"[{time.time()-t_start:.1f}s] SNR observado (todas las obs, solo informativo): "
          f"mediana={snr_sim.median():.3f}, p90={snr_sim.quantile(0.9):.3f}")

    band_curves = parse_searcheff_pipeline(SEARCHEFF_PIPELINE_FILE)
    min_epochs = parse_pipeline_logic(SEARCHEFF_LOGIC_FILE)
    # Fase 64: el trigger real de SNANA calcula el SNR sobre el flujo
    # VERDADERO sin ruido (SNR_CALC, snlc_sim.c:24495-24497 -- SNANA llama
    # "wrong SNR" al SNR sobre flujo observado, y lo evita para LSST), no
    # sobre FLUXCAL/FLUXCALERR (SNR_OBS) como este proyecto calculaba desde
    # la Fase 4. Validado epoca a epoca contra el PHOTFLAG&4096 real de
    # SNANA (ver NOTES.md): la formula anterior sobre-estimaba la tasa de
    # deteccion real en +17.1%; esta la reproduce casi exacta (+0.04%).
    detected_mask = apply_detection_efficiency(
        phot_df, band_curves, flux_col="FLUXTRUE", seed=seed_base + 7,
    )
    phot_df["PHOTFLAG"] = np.where(detected_mask, 4096, 0)
    # Fase 4: agrupar observaciones en epocas reales (NEWMJD_DIF=0.007d, ver
    # searcheff.group_into_epochs) antes de aplicar el trigger ">=2 epocas" --
    # contar observaciones individuales (como hacian las Fases 0-3) infla el
    # trigger, ver NOTES.md.
    detected_snids = object_level_detected(phot_df, min_epochs=min_epochs)
    print(f"[{time.time()-t_start:.1f}s] SEARCHEFF aplicado: {len(detected_snids)}/{len(head_df)} "
          f"objetos detectados (>= {min_epochs} epocas reales, agrupadas)")

    # common observation window: [first detection - LC_PRE_DAYS, last detection + LC_POST_DAYS] observer days
    det_mjd = phot_df.loc[phot_df["PHOTFLAG"] == 4096].groupby("SNID")["MJD"]
    lc_lo = (det_mjd.min() - LC_PRE_DAYS).reindex(list(detected_snids))
    lc_hi = (det_mjd.max() + LC_POST_DAYS).reindex(list(detected_snids))
    keep = (phot_df["SNID"].isin(detected_snids) & (phot_df["MJD"] >= phot_df["SNID"].map(lc_lo))
            & (phot_df["MJD"] <= phot_df["SNID"].map(lc_hi)))
    n_rows_before = len(phot_df)
    phot_df = phot_df[keep].reset_index(drop=True)
    head_df["LC_MJD_START"] = head_df["SNID"].map(lc_lo)
    head_df["LC_MJD_END"] = head_df["SNID"].map(lc_hi)
    z1 = 1.0 + head_df["REDSHIFT_HELIO"]
    head_df["SIMWIN_TRUNC"] = ((head_df["LC_MJD_START"] < head_df["PEAKMJD"] + trest_range[0] * z1)
                               | (head_df["LC_MJD_END"] > head_df["PEAKMJD"] + trest_range[1] * z1))
    head_df["NOBS"] = head_df["SNID"].map(phot_df.groupby("SNID").size()).fillna(0).astype(int)
    n_trunc = int(head_df["SIMWIN_TRUNC"].sum())
    print(f"[{time.time()-t_start:.1f}s] common window: kept {len(phot_df):,} of {n_rows_before:,} rows "
          f"({len(detected_snids)} detected objects); cut reaching the simulated span: {n_trunc}"
          + ("  <-- WARNING" if n_trunc else ""))

    all_ids = lc["id"].astype(int).astype(str)
    dump_df = pd.DataFrame({"CID": all_ids, "ZHELIO": lc["z"].to_numpy(), "ZCMB": lc["z"].to_numpy()})
    head_df_detected = head_df[head_df["SNID"].isin(detected_snids)].reset_index(drop=True)

    # Fase 5: persistir la tabla real (head_df/phot_df), no solo el resumen
    # agregado -- hasta ahora el pipeline nunca escribia a disco los datos
    # crudos de la simulacion (ni FITS/DUMP estilo SNANA, LightCurveLynx no
    # tiene un writer nativo para eso, confirmado revisando la documentacion
    # oficial -- ni ninguna otra tabla), solo las imagenes QC y el JSON de
    # metricas agregadas. Parquet (via pyarrow) por tamano -- phot_df puede
    # tener millones de filas para NGENTOT completo. No se versiona en git
    # (ver .gitignore), solo vive en el output dir de NLHPC/local.
    head_df["DETECTED"] = head_df["SNID"].isin(detected_snids)
    if cfg.get("model") == "lclib":
        head_df = head_df.merge(lclib_truth(lc, source_model), on="SNID", how="left")
    if cfg.get("keep_detected_only"):
        # flat-log-z mode: all generated objects (z, attenuation, detection) in gen_df; photometry of detected only
        gen_df = logz_gen_df(lc, cfg, detected_snids)
        gen_df.to_parquet(out_dir / "gen_df.parquet", index=False)
        extra = gen_df[["SNID", "MWEBV", "HOST_AV", "HOST_RV", "SALT2_x1", "SALT2_c"]]
        head_df = head_df[head_df["DETECTED"]].merge(extra, on="SNID", how="left").reset_index(drop=True)
        phot_df = phot_df[phot_df["SNID"].isin(set(detected_snids))].reset_index(drop=True)
        print(f"[{time.time()-t_start:.1f}s] logz: gen_df.parquet ({len(gen_df)} generated, "
              f"{int(gen_df.DETECTED.sum())} detected); head/phot restricted to detected")
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)
    if not os.environ.get("ALCES_NO_PHOT"):          # distribution runs: head_df only (docs/nontransients.md)
        phot_df.to_parquet(out_dir / "phot_df.parquet", index=False)
    print(f"[{time.time()-t_start:.1f}s] tablas persistidas: head_df.parquet "
          f"({len(head_df)} filas), phot_df.parquet ({len(phot_df)} filas)")

    (out_dir / "summary.json").write_text(json.dumps({
        "class_key": class_key,
        "strategy": "WFD" if wfd else "DDF",
        "seed_index": seed_index,
        "ngentot_lc": ngentot,
        "n_with_obs": len(head_df),
        "n_detected": len(detected_snids),
        "n_total_dump": len(dump_df),
        "sim_wall_time_s": sim_wall_time,
        "detection_efficiency_pct": 100.0 * len(detected_snids) / ngentot,
        "snr_median": float(snr_sim.median()),
        "snr_p90": float(snr_sim.quantile(0.9)),
        "window_mode": WINDOW_MODE, "lc_pre_days": LC_PRE_DAYS, "lc_post_days": LC_POST_DAYS,
        "model_rest_span": list(model_span), "sim_rest_span": list(trest_range), "n_simwin_trunc": n_trunc,
    }, indent=2))

    sys.path.insert(0, str(REPO_ROOT))
    from pipeline.postproc import qc
    qc_dir = out_dir / "qc"
    if len(head_df_detected) > 0:
        paths = qc.run_all_qc(
            head_df_detected, phot_df, qc_dir,
            f"LightCurveLynx_{class_key}_{'WFD' if wfd else 'DDF'}_poc", dump_df=dump_df,
        )
        print(f"[{time.time()-t_start:.1f}s] QC generado: {list(paths.keys())}")
        # Fase 68: reemplaza SOLO el panel de curvas de luz (paths["lightcurves"])
        # con el estilo real del notebook oficial de LightCurveLynx
        # (plot_lightcurves() + BAND_COLORS) -- no toca pipeline/, los otros 3
        # graficos (detecciones/magnitudes/redshift) quedan igual que siempre.
        if "lightcurves" in paths:
            lc_ok = plot_notebook_style_lightcurves(
                source_model, lc, passband_group, detected_snids, paths["lightcurves"],
                class_key, "WFD" if wfd else "DDF",
            )
            print(f"[{time.time()-t_start:.1f}s] Fase 68: panel de curvas de luz "
                  f"estilo notebook oficial {'regenerado' if lc_ok else 'omitido (sin candidatos)'}")
    else:
        print(f"[{time.time()-t_start:.1f}s] ! 0 objetos detectados, QC omitido")
    print(f"[{time.time()-t_start:.1f}s] TOTAL")


if __name__ == "__main__":
    # Fase 17: --wfd en cualquier posicion selecciona la estrategia WFD en
    # vez de DDF (ver NOTES.md) -- se extrae de sys.argv antes de parsear
    # los posicionales para no romper el uso existente <clase> [seed_index].
    _args = sys.argv[1:]
    _wfd = "--wfd" in _args
    if _wfd:
        _args = [a for a in _args if a != "--wfd"]
    if len(_args) not in (1, 2) or _args[0] not in CLASS_CONFIGS:
        print(f"uso: python3 run_simsed_poc.py <clase> [seed_index] [--wfd]  (opciones: {list(CLASS_CONFIGS)})")
        sys.exit(1)
    _seed_index = int(_args[1]) if len(_args) == 2 else 0
    main(_args[0], seed_index=_seed_index, wfd=_wfd)
