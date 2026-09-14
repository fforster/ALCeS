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


# --- config por clase, parametros reales de cada SIMGEN_INCLUDE_*.INPUT ---
CLASS_CONFIGS = {
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
        genrange_redshift=(0.011, 0.28),
        dndz=("powerlaw", [(320e-9, 0.0, 0.011, 0.28)]),
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
    # Fase 2B ronda 3: 3 clases SIMSED que declaran WV07 real (confirmado
    # `GENAV_WV07: 1` en su .INPUT, no el camino GENPROFILE_AV de SNIax).
    # ILOT-MOSFIT y SNIIn-MOSFIT reusan DNDZ: CC_S15 (ya validado en
    # SNII-NMF); PISN-MOSFIT usa el polinomio PISN_PLK12 real. Host
    # extinction real agregada en Fase 3, ver comentario arriba.
    "ILOT-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.ILOT-MOSFIT",
        genrange_redshift=(0.011, 0.30),
        dndz=("ccs15", 0.06),
        sntype=61,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 43: GENRANGE_TREST real del .INPUT es -100/1000 (Fase 40) --
        # el peor caso de las 14 clases, el hardcode global (-30,100) cubria
        # solo 11.8% de esa ventana ("Intermediate Luminosity Optical
        # Transient", evolucion mas lenta que una SN estandar).
        trest_range=(-100.0, 1000.0),
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
        genrange_redshift=(0.011, 0.28),
        dndz=("powerlaw", [(320e-9, 0.0, 0.011, 0.28)]),  # identico a KN-K17
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
        genrange_redshift=(0.02, 2.2),
        dndz=("pisn", 1.0),
        sntype=71,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        # Fase 59: GENRANGE_TREST real -50/300 (ver NOTES.md, mismo hueco
        # de Fase 40/43 nunca remedido para esta clase).
        trest_range=(-50.0, 300.0),
    ),
    "PISN-STELLA-HYDROGENIC": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/elastic/model_libs_updates/SIMSED.PISN-STELLA-HYDROGENIC",
        genrange_redshift=(0.02, 2.2),
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
    simsed_dir = cfg["simsed_dir"]
    file_names, _ = SIMSEDModel._read_simsed_info_file(simsed_dir)
    if "redcor_params" in cfg:
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
        obs_table, extra_cols=[] if wfd else ["field"], seed=seed_base + 5, radius=0.0,
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

    if simsed_t0_mode == "bolometric_peak":
        templates, flux_scale = load_simsed_templates_bolometric(simsed_dir)
        source_model = SIMSEDModel(
            templates, flux_scale=flux_scale, weights=weights,
            ra=radec_sampler.ra, dec=radec_sampler.dec,
            redshift=redshift_func, distance=distance_func, t0=t0_func,
        )
    else:
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

    print(f"[{time.time()-t_start:.1f}s] SIMSEDModel cargado ({len(source_model)} templates)")

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
    trest_range = cfg.get("trest_range", (-30.0, 100.0))
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
    restlambda_range = cfg.get("restlambda_range")
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
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)
    phot_df.to_parquet(out_dir / "phot_df.parquet", index=False)
    print(f"[{time.time()-t_start:.1f}s] tablas persistidas: head_df.parquet "
          f"({len(head_df)} filas), phot_df.parquet ({len(phot_df)} filas)")

    # Fase 90: import movido antes del write de summary.json (antes vivia
    # despues, solo para qc.run_all_qc) -- se necesita aca para
    # redshift_zmax_stats(), que calcula el z real alcanzado (dump_df/
    # head_df_detected ya existen en este scope) con la MISMA logica que
    # usa qc.py::redshift_distribution para el texto quemado en el PNG, sin
    # duplicar el calculo.
    sys.path.insert(0, str(REPO_ROOT))
    from pipeline.postproc import qc
    z_min_nominal, z_max_nominal = cfg["genrange_redshift"]
    zmax_stats = qc.redshift_zmax_stats(dump_df, head_df_detected)

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
        # Fase 90: z_min/max_nominal = GENRANGE_REDSHIFT de la clase (limite
        # duro del sampler, run_simsed_poc.py::CLASS_CONFIGS); z_max_simulado/
        # detectado = lo que realmente salio del sampler en esta corrida
        # (dump_df completo vs subconjunto detectado), via qc.redshift_zmax_stats.
        "z_min_nominal": z_min_nominal,
        "z_max_nominal": z_max_nominal,
        "z_max_simulado": zmax_stats.get("z_max_simulado"),
        "z_max_detectado": zmax_stats.get("z_max_detectado"),
    }, indent=2))

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
