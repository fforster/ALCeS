"""
Fase 6 -- primer PoC de LightCurveLynx para GENMODEL: NON1ASED (las 14
clases previas, Fase 0-5, son todas SIMSED o SALT2, ver NOTES.md). Reusa
exactamente el mismo patron ya validado de run_simsed_poc.py (H0=70 + ruido
real de SNANA, extincion MW real, SEARCHEFF real, QC de pipeline.postproc
sin modificar) -- lo unico que cambia es la construccion del source_model,
via non1ased.load_non1ased_model() en vez de SIMSEDModel.from_dir(), porque
los directorios NON1ASED reales no traen SED.INFO (confirmado via ssh
nlhpc, ver non1ased.py).

Primera clase (Fase 6 original): SNIa-91bg, 35 templates, elegida por ser
la mas chica de las 5 clases NON1ASED ya convertidas y validadas del lado
SNANA (NEXT_SESSION.md, 2026-08-06: SNIax, SNIa-91bg, TDE, SLSN-I,
KN-BULLA-BNS-M2COMP). Ratio con SNANA: 2.254x +/- 0.081 (5 semillas).

Nota real descubierta al preparar ese PoC (no asumir el mismo rango que la
clase SIMSED equivalente ya corrida en Fase 2B/4): el .INPUT real NON1ASED
de cada clase (elastic/model_config/SIMGEN_INCLUDE_<clase>_NON1ASED.INPUT)
casi siempre usa un GENRANGE_REDSHIFT mas ancho que el que usa la entrada
SIMSED ya corrida de la misma clase en run_simsed_poc.py -- confirmado que
son dos generaciones de config distintas en NLHPC (`run_SNANA/model_config/`
vs `run_SNANA/elastic/model_config/`), mismos templates fisicos, .INPUT de
campana distinto. Este PoC siempre usa el rango real de SU PROPIO .INPUT
NON1ASED, asi que su ratio vs SNANA es valido comparado contra la corrida
SNANA real de esa misma campana NON1ASED -- pero no es directamente
comparable al ratio ya publicado de la clase SIMSED equivalente sin un
bake-off explicito al mismo rango (ver `SNIa-91bg-elastic`/`SNIax-elastic`
en run_simsed_poc.py, Fase 6/7).

Fase 7 agrego `SNIax` (1001 templates, misma familia fisica que su SIMSED
ya cubierto -- bake-off de codificacion en clase de peso uniforme) y
extendio cobertura a `TDE`, `SLSN-I` (familia fisica *-BBFIT, DISTINTA de
la *-MOSFIT ya cubierta via SIMSED -- sin comparacion SIMSED previa
posible, params reales tomados de su propio .INPUT NON1ASED) y
`KN-BULLA-BNS-M2COMP` (misma sub-variante fisica que ya usa la entrada
SIMSED `KN-BULLA19`).

Uso (dentro de un job sbatch, nunca en el login node):
    python3 run_non1ased_poc.py <clave_clase>
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
from lightcurvelynx.obstable.opsim import OpSim
from lightcurvelynx.simulate import simulate_lightcurves
from lightcurvelynx.survey_info import SurveyInfo

from non1ased import load_non1ased_model
from snana_params import (
    build_dndz_powerlaw2_cdf, build_dndz_md14_cdf, build_dndz_tde_cdf, make_dndz_sampler,
    make_exp_av_sampler, make_exp_halfgauss_av_sampler, make_wv07_av_sampler,
    make_mwebv_ratio_scatter, make_wfd_ebv_lookup,
    SizeAwareFunctionNode, ClippedExtinctionEffect,
)
from searcheff import (
    parse_searcheff_pipeline, parse_pipeline_logic, apply_detection_efficiency, object_level_detected,
)
# Fase 68/69: panel de curvas de luz estilo notebook oficial -- compartido con
# run_simsed_poc.py/run_snia_ddf_poc.py (ver qc_lightcurves_notebook.py).
from qc_lightcurves_notebook import plot_notebook_style_lightcurves

# Fase 74: REPO_ROOT/SNANA_HOME resueltos por local_env.py (portabilidad --
# antes hardcodeado a "/home/mvalenzuela"/"/home/mvalenzuela/AUTOSIM", ver
# ese archivo para el porqué).
from local_env import SNANA_HOME, REPO_ROOT
sys.path.insert(0, str(REPO_ROOT))
from pipeline.simlib.formatobs import format_obs  # noqa: E402
from lightcurvelynx.astro_utils.mag_flux import mag2flux  # noqa: E402

HERE = Path(__file__).resolve().parent
# OPSIM_DB vive dentro del repo real (data/opsim/), no bajo SNANA_HOME --
# REPO_ROOT ya resuelve a la raíz real sin importar el nombre de carpeta.
OPSIM_DB = REPO_ROOT / "data/opsim/baseline_v5.3.1_10yrs.db"
SEARCHEFF_PIPELINE_FILE = SNANA_HOME / "run_SNANA/LSST_SEARCHEFF_PIPELINE.DAT"
SEARCHEFF_LOGIC_FILE = SNANA_HOME / "run_SNANA/LSST_PIPELINE_LOGIC.DAT"
PIXSIZE = 0.2
NGENTOT_LC = 2000  # igual que la mayoria de las clases SIMSED (pipeline/models.yaml: ngen_ddf)
SEED_BASE = 20260814

DDF_FIELD_EBV = {
    "cosmos": 0.0182, "ecdfs": 0.0084, "edfs_a": 0.0062,
    "edfs_b": 0.0152, "elaiss1": 0.0080, "xmm_lss": 0.0251,
}
MW_RV = 3.1
GENSIGMA_MWEBV_RATIO = 0.16  # Fase 10: real, activo en toda la campana (templates.py)
# Fase 17: ver run_simsed_poc.py -- WFD no tiene campos fijos, E(B-V) real
# por nearest-neighbor angular contra esta grilla.
WFD_MWEBV_GRID = HERE / "wfd_mwebv_grid.csv"

# --- config por clase, parametros reales del .INPUT NON1ASED real ---
CLASS_CONFIGS = {
    "SNIa-91bg": dict(
        non1ased_dir=SNANA_HOME / "run_SNANA/elastic/model_libs_updates/NON1ASED.SNIa-91bg",
        input_path=SNANA_HOME / "run_SNANA/elastic/model_config/SIMGEN_INCLUDE_SNIa-91bg_NON1ASED.INPUT",
        genrange_redshift=(0.011, 1.2),
        dndz=("powerlaw", [(3.0e-6, 1.5, 0.011, 1.2)]),
        sntype=13,
        # sin extincion de host en el .INPUT real (mismo que la variante
        # SIMSED) -- no se agrega ClippedExtinctionEffect de host aqui.
    ),
    # Fase 7: bake-off de codificacion en clase de peso uniforme
    # (SIMSED_GRIDONLY) -- a diferencia de SNIa-91bg (SIMSED_REDCOR), para
    # ver si el efecto de codificacion (~1.15x en SNIa-91bg) es especifico
    # de clases con pesos correlacionados o mas general. Mismos templates
    # fisicos que la entrada SIMSED "SNIax" ya corrida (confirmado por
    # listado de directorio), mismos parametros reales de host extinction
    # (GENTAU_AV=1.7/GENSIG_AV=0.6/GENRATIO_AV0=4.0, identicos en el
    # .INPUT elastic SIMSED y elastic NON1ASED) -- solo cambia el rango de
    # z real de este .INPUT (0.011-1.5, vs 0.011-0.7 de la entrada SIMSED
    # ya publicada) y el esquema de peso (NON1A_KEYS uniforme 1/1001 vs
    # peso uniforme nativo de SIMSED_GRIDONLY -- en este caso ambos son
    # uniformes, la comparacion real es contra "SNIax-elastic" en
    # run_simsed_poc.py, no contra la entrada SIMSED original).
    "SNIax": dict(
        non1ased_dir=SNANA_HOME / "run_SNANA/elastic/model_libs_updates/NON1ASED.SNIax",
        input_path=SNANA_HOME / "run_SNANA/elastic/model_config/SIMGEN_INCLUDE_SNIax_NON1ASED.INPUT",
        genrange_redshift=(0.011, 1.5),
        dndz=("md14", 6.0e-6),
        sntype=12,
        host_av=dict(kind="exp_halfgauss", tau=1.7, sig=0.6, ratio=4.0,
                      av_range=(0.001, 3.0), r_v=3.1),
    ),
    # Fase 7: cobertura nueva -- familia fisica *-BBFIT, DISTINTA de la
    # *-MOSFIT que ya cubre la entrada SIMSED "TDE-MOSFIT" (confirmado:
    # PATH_NON1ASED real apunta a NON1ASED.TDE-BBFIT, no a una conversion
    # de SIMSED.TDE-MOSFIT) -- sin bake-off de codificacion posible aqui
    # (no hay contraparte SIMSED de la misma familia fisica ya corrida).
    # Confirmado via ssh nlhpc (NON1A.LIST + .INPUT real): un SOLO template
    # -- fit de blackbody a un evento real especifico (2019qiz, Nicholl+2020/
    # Hung+2021), no un ensemble como TDE-MOSFIT. GENRANGE_REDSHIFT/DNDZ/
    # host_av del .INPUT real resultaron identicos a los ya usados para
    # TDE-MOSFIT (mismo GENTAU_AV=0.4, GENAV_WV07 comentado/deshabilitado).
    # Bug real de dato encontrado (ver setup_tdebbfit_local.py): la segunda
    # linea del .sed real ("phase wavelength flux") le falta el prefijo "#"
    # -- typo de un solo caracter, confirmado comparando contra el archivo
    # hermano de SLSN-I-BBFIT que SI lo tiene. Se usa copia local saneada.
    "TDE": dict(
        non1ased_dir=HERE / "tdebbfit_local",
        input_path=SNANA_HOME / "run_SNANA/elastic/model_config/SIMGEN_INCLUDE_TDE_NON1ASED.INPUT",
        genrange_redshift=(0.01, 2.9),
        dndz=("tde", 1.0e-6),
        sntype=51,
        host_av=dict(kind="exp", tau=0.4, av_max=3.0, r_v=3.1),
    ),
    # Fase 7: idem TDE -- familia fisica *-BBFIT distinta de la *-MOSFIT ya
    # cubierta via SIMSED "SLSN-I". Tambien un SOLO template real (fit de
    # blackbody a 2016apd, Yan+2017/Kangas+2017/Guillochon+2017), confirmado
    # via ssh nlhpc. GENRANGE_REDSHIFT real 0.02-2.95 (NO 0.02-9.7 como la
    # entrada SIMSED "SLSN-I" -- comentario real en el .INPUT: "stay within
    # hostlib range"), SNTYPE real 41 (no 40, confirmado en el bloque
    # NON1A_KEYS real, distinto del SNTYPE=40 que usa la entrada SIMSED).
    "SLSN-I": dict(
        non1ased_dir=SNANA_HOME / "run_SNANA/elastic/model_libs_updates/NON1ASED.SLSN-I-BBFIT",
        input_path=SNANA_HOME / "run_SNANA/elastic/model_config/SIMGEN_INCLUDE_SLSN-I_NON1ASED.INPUT",
        genrange_redshift=(0.02, 2.95),
        dndz=("md14", 2.0e-8),
        sntype=41,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
    ),
    # Fase 7: misma sub-variante fisica (BNS-M2-2COMP) que ya usa la
    # entrada SIMSED "KN-BULLA19" -- candidata a bake-off de codificacion
    # si SNANA muestra detecciones no triviales en la campana real (la
    # validacion previa de 300 objetos dio 0 detectados, ver NOTES.md;
    # confirmar con el NGENLC_WRITE real de la campana completa antes de
    # sacar conclusiones). Directorio/nombre de .INPUT real confirmados via
    # ssh nlhpc: "BULLA-BNS-M2-2COMP", sin prefijo "KN-" ni sufijo
    # "_NON1ASED" en el nombre de archivo (inconsistente con TDE/SLSN-I,
    # pero GENMODEL: NON1ASED confirma que es la variante correcta).
    # GENRANGE_REDSHIFT real 0.011-0.5 (NO 0.011-0.28 como KN-BULLA19
    # SIMSED), SNTYPE real 62 (no 52, confirmado en NON1A_KEYS real), 549
    # templates (vs. 550 nominales de KN-BULLA19 SIMSED -- diferencia de 1,
    # sin investigar, no bloquea la corrida). Mismo bug real de Fase 2B
    # ronda 4 (setup_knbulla19_local.py): los *.txt.gz reales son ZIP mal
    # etiquetados (firma PK), heredado del mismo dato fisico que
    # KN-BULLA19 SIMSED. Se usa copia local saneada (ver
    # setup_bullansed_local.py).
    "KN-BULLA-BNS-M2COMP": dict(
        non1ased_dir=HERE / "bullansed_local",
        input_path=SNANA_HOME / "run_SNANA/elastic/model_config/SIMGEN_INCLUDE_BULLA-BNS-M2-2COMP.INPUT",
        genrange_redshift=(0.011, 0.5),
        dndz=("powerlaw", [(320e-9, 0.0, 0.011, 0.5)]),
        sntype=62,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=0.5, r_v=3.1),
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


# Fase 99: GENRANGE_TREST real de cada .INPUT NON1ASED (leido en NLHPC,
# run_SNANA/elastic/model_config/SIMGEN_INCLUDE_*: las 5 declaran -100/500).
# Solo se usa con real_trest=True -- el default sigue siendo la ventana
# historica (-30, 100) con la que se midieron los ratios de Fase 70, hasta
# que el profesor apruebe el cambio (NOTES.md Fase 99).
GENRANGE_TREST_REAL = {
    "SNIa-91bg": (-100.0, 500.0),
    "SNIax": (-100.0, 500.0),
    "TDE": (-100.0, 500.0),
    "SLSN-I": (-100.0, 500.0),
    "KN-BULLA-BNS-M2COMP": (-100.0, 500.0),
}
HISTORICAL_TREST = (-30, 100)


def main(class_key: str, ngentot_override: int | None = None, seed_index: int = 0, wfd: bool = False,
         out_dir_override: Path | str | None = None, real_trest: bool = False):
    cfg = CLASS_CONFIGS[class_key]
    # Fase 17: WFD usa el mismo NGENTOT que DDF (ver run_simsed_poc.py).
    ngentot = ngentot_override if ngentot_override is not None else cfg.get("ngentot_lc", NGENTOT_LC)
    seed_base = SEED_BASE + seed_index * 1_000_000
    seed_suffix = f"_seed{seed_index}" if seed_index else ""
    wfd_suffix = "_wfd" if wfd else ""
    trest_suffix = "_realtrest" if real_trest else ""
    if out_dir_override is not None:
        out_dir = Path(out_dir_override)
    else:
        out_dir = HERE / f"poc_output_non1ased_{class_key.lower().replace('-', '')}{seed_suffix}{wfd_suffix}{trest_suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    trest_range = GENRANGE_TREST_REAL[class_key] if real_trest else HISTORICAL_TREST
    t_start = time.time()

    con = sqlite3.connect(str(OPSIM_DB))
    df = pd.read_sql_query("SELECT * FROM observations", con)
    if wfd:
        # Fase 17: ver run_simsed_poc.py -- WFD es "todo lo que no es DDF"
        # en el mismo .db, sin columna "field" (no hay campos fijos).
        df_ddf = df[~df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
    else:
        df_ddf = df[df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
        df_ddf["field"] = df_ddf["target_name"].str.extract(r"ddf_(\w+)")
    df_ddf = snana_noise_columns(df_ddf)
    obs_table = OpSim(df_ddf, zp_err_mag=0.005)
    print(f"[{time.time()-t_start:.1f}s] [{class_key}] OpSim {'WFD' if wfd else 'DDF'}: "
          f"{len(df_ddf):,} obs, ruido real de SNANA inyectado")

    # Fase 55: mismo fix real que run_simsed_poc.py -- u.dat local trunca a
    # 413.4nm/4134A, el corte real que usa el kcor de SNANA (ver NOTES.md).
    passband_group = PassbandGroup.from_preset(preset="LSST", table_dir=str(HERE / "lsst_passbands_local"))
    print(f"[{time.time()-t_start:.1f}s] passbands cargados (Fase 55: u truncado a 4134A real)")

    z_min, z_max = cfg["genrange_redshift"]
    dndz_kind, dndz_params = cfg["dndz"]
    if dndz_kind == "powerlaw":
        z_grid, cdf = build_dndz_powerlaw2_cdf(segments=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "md14":
        z_grid, cdf = build_dndz_md14_cdf(rate0=dndz_params, z_min=z_min, z_max=z_max)
    elif dndz_kind == "tde":
        z_grid, cdf = build_dndz_tde_cdf(rate0=dndz_params, z_min=z_min, z_max=z_max)
    else:
        raise ValueError(f"dndz_kind desconocido: {dndz_kind}")
    redshift_func = SizeAwareFunctionNode(make_dndz_sampler(z_grid, cdf, seed=seed_base + 1), node_label="redshift")
    # radius=0.0 explicito (mismo fix de Fase 5 que run_simsed_poc.py --
    # ver comentario alli): campos DDF son pointings fijos, evita el
    # jitter sub-FOV sin seed de ObsTableRADECSampler.compute().
    radec_sampler = ObsTableRADECSampler(
        obs_table, extra_cols=[] if wfd else ["field"], seed=seed_base + 5, radius=0.0,
    )
    # mismo segundo fix de Fase 5: TableSampler.__init__ crea su propio
    # muestreador de indice de fila sin heredar el seed del constructor.
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

    # Fase 10: GENSIGMA_MWEBV_RATIO=0.16 real y activo (ver snana_params.py
    # make_mwebv_ratio_scatter para la formula, verificada linea por linea
    # contra snlc_sim.c::gen_MWEBV()) -- antes de esta fase _field_to_ebv
    # devolvia el EBV nominal por campo sin scatter alguno.
    if wfd:
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
    # Fase 24: OPT_MWCOLORLAW=99 real (Fitzpatrick99 exacto, ver run_simsed_poc.py) -- corregido
    # de O94 a F99. Diferencia numerica confirmada <0.005 mag a estos E(B-V), no explica Fase 23.
    mw_extinction = ClippedExtinctionEffect(
        extinction_model="F99", ebv=ebv_func, r_v=MW_RV, frame="observer", backend="dust_extinction",
    )

    source_model = load_non1ased_model(
        cfg["non1ased_dir"], cfg["input_path"],
        ra=radec_sampler.ra, dec=radec_sampler.dec,
        redshift=redshift_func, distance=distance_func, t0=t0_func,
    )
    # mismo bug de Fase 4 que SIMSEDModel: MultiSEDTemplateModel.__init__
    # nunca pasa seed a su GivenValueSampler interno -- fijarlo aqui para
    # que la seleccion de template sea reproducible.
    source_model._sampler_node.set_seed(seed_base + 9)
    source_model.add_effect(mw_extinction)

    if "host_av" in cfg:
        # extincion de host real -- mismas 3 variantes que run_simsed_poc.py
        # (ver comentarios alli, verificadas linea por linea contra
        # snlc_sim.c): "exp" = exponencial pura, "exp_halfgauss" = mezcla
        # exponencial+semi-Gaussiana (GENPROFILE_AV), "wv07" = ESSENCE-WV07 real.
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

        def _av_to_ebv(size=None, host_av=None, **_kwargs):
            return np.asarray(host_av) / hp["r_v"]

        host_ebv_func = SizeAwareFunctionNode(_av_to_ebv, node_label="host_ebv", host_av=av_func)
        # Fase 51: mismo fix que run_simsed_poc.py (ver ClippedExtinctionEffect
        # en snana_params.py y NOTES.md) -- extinction_model="O94" (GALextinct
        # real usa OPT=94 fijo, no CCM89) y ebv_param_name="host_ebv" (evita la
        # colision de nombre "ebv" con mw_extinction que dejaba la extincion de
        # host efectivamente apagada, ~2-8% de la nominal).
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

    print(f"[{time.time()-t_start:.1f}s] NON1ASED cargado ({len(source_model)} templates, "
          f"pesos reales de NON1A_KEYS)")

    t_sim0 = time.time()
    lc = simulate_lightcurves(source_model, ngentot, survey_info=SurveyInfo(
        obstable=obs_table, passbands=passband_group, survey_name="LSST",
    ), rest_time_window_offset=trest_range, rng=np.random.default_rng(seed_base + 2))
    sim_wall_time = time.time() - t_sim0
    print(f"[{time.time()-t_start:.1f}s] simulacion terminada: {len(lc)} objetos, "
          f"{sim_wall_time:.1f}s ({sim_wall_time/max(len(lc),1)*1000:.2f} ms/objeto)")

    head_rows, phot_rows = [], []
    for _, row in lc.iterrows():
        sub = row["lightcurve"]
        if sub is None or len(sub) == 0:
            continue
        snid = str(int(row["id"]))
        head_rows.append({
            "SNID": snid, "SNTYPE": cfg["sntype"], "RA": row["ra"], "DEC": row["dec"],
            "REDSHIFT_HELIO": row["z"], "PEAKMJD": row["t0"], "NOBS": len(sub),
        })
        for _, obs in sub.iterrows():
            flt = str(obs["filter"])
            flt = "Y" if flt == "y" else flt
            phot_rows.append({
                "SNID": snid, "MJD": obs["mjd"], "FLT": flt,
                "FLUXCAL": obs["flux"], "FLUXCALERR": obs["fluxerr"],
                # Fase 70: retiene flux_perfect (flujo verdadero, sin ruido) --
                # mismo fix de Fase 64 que ya tiene run_simsed_poc.py, nunca
                # portado aca. Necesario para que el trigger real use SNR_CALC
                # (flujo verdadero/error) en vez de SNR_OBS (observado/error).
                "FLUXTRUE": obs["flux_perfect"],
            })

    head_df = pd.DataFrame(head_rows)
    phot_df = pd.DataFrame(phot_rows)
    MAG_AB_ZP_NJY = 8.9 + 2.5 * 9
    positive = phot_df["FLUXCAL"] > 0
    phot_df["MAG"] = np.where(positive, MAG_AB_ZP_NJY - 2.5 * np.log10(phot_df["FLUXCAL"].where(positive)), np.nan)
    print(f"[{time.time()-t_start:.1f}s] aplanado: {len(head_df)} objetos con obs, "
          f"{len(phot_df)} filas de fotometria")

    snr_sim = (phot_df["FLUXCAL"] / phot_df["FLUXCALERR"]).abs()
    print(f"[{time.time()-t_start:.1f}s] SNR simulado (todas las obs): "
          f"mediana={snr_sim.median():.3f}, p90={snr_sim.quantile(0.9):.3f}")

    band_curves = parse_searcheff_pipeline(SEARCHEFF_PIPELINE_FILE)
    min_epochs = parse_pipeline_logic(SEARCHEFF_LOGIC_FILE)
    # Fase 70: trigger real usa SNR_CALC (flujo verdadero/error), no SNR_OBS
    # (observado/error) -- mismo fix de Fase 64, portado aca.
    detected_mask = apply_detection_efficiency(
        phot_df, band_curves, flux_col="FLUXTRUE", seed=seed_base + 7,
    )
    phot_df["PHOTFLAG"] = np.where(detected_mask, 4096, 0)
    detected_snids = object_level_detected(phot_df, min_epochs=min_epochs)
    print(f"[{time.time()-t_start:.1f}s] SEARCHEFF aplicado: {len(detected_snids)}/{len(head_df)} "
          f"objetos detectados (>= {min_epochs} epocas reales, agrupadas)")

    all_ids = lc["id"].astype(int).astype(str)
    dump_df = pd.DataFrame({"CID": all_ids, "ZHELIO": lc["z"].to_numpy(), "ZCMB": lc["z"].to_numpy()})
    head_df_detected = head_df[head_df["SNID"].isin(detected_snids)].reset_index(drop=True)

    head_df["DETECTED"] = head_df["SNID"].isin(detected_snids)
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)
    phot_df.to_parquet(out_dir / "phot_df.parquet", index=False)
    print(f"[{time.time()-t_start:.1f}s] tablas persistidas: head_df.parquet "
          f"({len(head_df)} filas), phot_df.parquet ({len(phot_df)} filas)")

    (out_dir / "summary.json").write_text(json.dumps({
        "class_key": class_key,
        "model_class": "NON1ASED",
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
        "rest_time_window": list(trest_range),
        "real_trest": real_trest,
    }, indent=2))

    sys.path.insert(0, str(REPO_ROOT))
    from pipeline.postproc import qc
    qc_dir = out_dir / "qc"
    if len(head_df_detected) > 0:
        paths = qc.run_all_qc(
            head_df_detected, phot_df, qc_dir,
            f"LightCurveLynx_{class_key}_NON1ASED_{'WFD' if wfd else 'DDF'}_poc", dump_df=dump_df,
        )
        print(f"[{time.time()-t_start:.1f}s] QC generado: {list(paths.keys())}")
        # Fase 68/69: reemplaza SOLO el panel de curvas de luz con el estilo
        # real del notebook oficial de LightCurveLynx -- no toca pipeline/.
        if "lightcurves" in paths:
            lc_ok = plot_notebook_style_lightcurves(
                source_model, lc, passband_group, detected_snids, paths["lightcurves"],
                f"{class_key} (NON1ASED)", "WFD" if wfd else "DDF",
            )
            print(f"[{time.time()-t_start:.1f}s] Fase 68/69: panel de curvas de luz "
                  f"estilo notebook oficial {'regenerado' if lc_ok else 'omitido (sin candidatos)'}")
    else:
        print(f"[{time.time()-t_start:.1f}s] ! 0 objetos detectados, QC omitido")
    print(f"[{time.time()-t_start:.1f}s] TOTAL")


if __name__ == "__main__":
    # Fase 17: ver run_simsed_poc.py -- --wfd en cualquier posicion.
    _args = sys.argv[1:]
    _wfd = "--wfd" in _args
    # Fase 99: --real-trest usa el GENRANGE_TREST real del .INPUT (opcional).
    _real_trest = "--real-trest" in _args
    _args = [a for a in _args if a not in ("--wfd", "--real-trest")]
    if len(_args) not in (1, 2) or _args[0] not in CLASS_CONFIGS:
        print(f"uso: python3 run_non1ased_poc.py <clase> [seed_index] [--wfd] [--real-trest]  "
              f"(opciones: {list(CLASS_CONFIGS)})")
        sys.exit(1)
    _seed_index = int(_args[1]) if len(_args) == 2 else 0
    main(_args[0], seed_index=_seed_index, wfd=_wfd, real_trest=_real_trest)
