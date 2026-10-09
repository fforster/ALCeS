"""
Fase 1 -- PoC SNIa_DDF con LightCurveLynx, parametros reales de SNANA.

Basado en bench_snia.py (Fase 0) pero:
  - Filtra el OpSim a los 6 campos DDF oficiales (target_name contiene 'ddf_').
  - NGENTOT_LC=2000 (igual que SNANA para DDF, ver pipeline/models.yaml).
  - SALT2 real: modelo H17 cargado DIRECTO de los archivos de SNANA
    (run_SNANA/plasticc_models/SALT2.WFIRST-H17), no del mirror remoto de
    sncosmo.github.io (esta caido -- 404 confirmado). El color law se
    reconstruyo a mano desde SALT2.INFO::COLORCOR_PARAMS (mismos 4
    coeficientes que usa snlc_sim.exe).
  - GENRANGE_REDSHIFT, SALT2c/x1 bifurcados, DNDZ real (ver snana_params.py).
  - RA/Dec muestreadas de las posiciones reales de pointings DDF
    (ObsTableRADECSampler, visit-weighted) -- no una caja uniforme de cielo
    (con eso casi todos los objetos caian fuera del footprint DDF real,
    nobs=0).
  - SIGMA_INT=0.090 (de SALT2.INFO) como dispersion acromatica coherente
    por evento -- aproximacion aceptada del modelo G10 completo (que
    correlaciona la dispersion con x1/c via una covarianza espectral; fuera
    de alcance para un PoC, ver NOTES.md Fase 0 punto 1).
  - Eficiencia de deteccion real (searcheff.py) aplicada como post-proceso
    sobre flux/fluxerr, no el escalon SNR>5 que trae LightCurveLynx nativo.
  - Extincion MW real (ExtinctionEffect, frame='observer', modelo O94/CCM89-
    like, R_V=3.1 -- misma familia que usa SNANA segun OPT_MWCOLORLAW): un
    E(B-V) por evento segun el campo DDF donde cae (6 campos, valores reales
    consultados al servicio IRSA Dust Extinction de NASA/IPAC -- el mapa SFD
    remoto de `dustmaps`/`sfdmap2` esta inalcanzable desde NLHPC via su
    mecanismo de descarga habitual, asi que se consulto por coordenadas
    via la API REST de IRSA en vez de bajar el mapa completo).
    RESULTADO: la extincion casi no cambio la eficiencia (59.95% -> 57.2%,
    la primera corrida sin extincion ya reportaba ~2x la eficiencia real de
    SNANA -- 29.85%) -- los 6 campos DDF tienen E(B-V) muy bajo por diseno
    (0.006-0.025, elegidos asi justamente), asi que no era la explicacion
    principal de la brecha. El diagnostico real: el SNR simulado
    (flux/fluxerr, TODAS las observaciones, no solo detectadas) sale
    sistematicamente mas alto que el SNR real de SNANA para la misma
    campana (mediana LCL=1.008 vs SNANA=0.78; p90 LCL=5.68 vs SNANA=2.26,
    ~2.5x en la cola alta) -- el modelo de ruido fotometrico de
    LightCurveLynx (derivado de profundidad/PSF/cielo del OpSim) subestima
    el ruido por-epoca real que usa SNANA para esta campana. Esto, no la
    poblacion de brillo/color/redshift, es la explicacion mas probable de
    la eficiencia de deteccion ~2x mas alta -- ver NOTES.md Fase 1 para el
    detalle completo. Queda como brecha abierta para Fase 2 (no resuelta
    en este PoC): calibrar o reemplazar el modelo de ruido de
    LightCurveLynx contra el de SNANA antes de usar esto para conclusiones
    cuantitativas, no solo cualitativas/de forma.

Uso (dentro de un job sbatch, nunca en el login node):
    python3 run_snia_ddf_poc.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sncosmo

from lightcurvelynx.astro_utils.mag_flux import mag2flux
from lightcurvelynx.astro_utils.passbands import PassbandGroup
from lightcurvelynx.astro_utils.snia_utils import DistModFromRedshift, X0FromDistMod
from lightcurvelynx.effects.extinction import ExtinctionEffect
from lightcurvelynx.math_nodes.np_random import NumpyRandomFunc
from lightcurvelynx.math_nodes.ra_dec_sampler import ObsTableRADECSampler
from lightcurvelynx.models.sncosmo_models import SncosmoWrapperModel
from lightcurvelynx.obstable.opsim import OpSim
from lightcurvelynx.simulate import simulate_lightcurves
from lightcurvelynx.survey_info import SurveyInfo
from lightcurvelynx.utils.extrapolate import LinearDecay, ZeroPadding

# Fase 74: REPO_ROOT/SNANA_HOME resueltos por local_env.py (portabilidad --
# antes hardcodeado a "/home/mvalenzuela"/"/home/mvalenzuela/AUTOSIM", ver
# ese archivo para el porqué).
from local_env import SNANA_HOME, REPO_ROOT
sys.path.insert(0, str(REPO_ROOT))
from pipeline.simlib.formatobs import format_obs  # noqa: E402

from snana_params import (
    build_dndz_powerlaw2_cdf, make_dndz_sampler, make_bifurcated_normal_sampler,
    make_mwebv_ratio_scatter, make_wfd_ebv_lookup, read_salt2_info,
    SizeAwareFunctionNode,
)
from searcheff import (
    parse_searcheff_pipeline, parse_pipeline_logic, apply_detection_efficiency, object_level_detected,
)
# Fase 68/69: panel de curvas de luz estilo notebook oficial -- compartido con
# run_simsed_poc.py/run_non1ased_poc.py (ver qc_lightcurves_notebook.py).
from qc_lightcurves_notebook import plot_notebook_style_lightcurves

HERE = Path(__file__).resolve().parent
# OPSIM_DB vive dentro del repo real (data/opsim/), no bajo SNANA_HOME --
# REPO_ROOT ya resuelve a la raíz real sin importar el nombre de carpeta.
OPSIM_DB = REPO_ROOT / "data/opsim/baseline_v5.3.1_10yrs.db"
SALT2_LOCAL_DIR = HERE / "salt2_h17_local"
SEARCHEFF_PIPELINE_FILE = SNANA_HOME / "run_SNANA/LSST_SEARCHEFF_PIPELINE.DAT"
SEARCHEFF_LOGIC_FILE = SNANA_HOME / "run_SNANA/LSST_PIPELINE_LOGIC.DAT"
OUT_DIR = HERE / "poc_output"

NGENTOT_LC = 2000  # igual que SNANA DDF (pipeline/models.yaml: ngen_ddf)
SEED_BASE = 20260812

# --- parametros reales de SIMGEN_INCLUDE_SNIa-SALT2.INPUT ---
GENRANGE_REDSHIFT = (0.011, 1.2)
SALT2C = dict(peak=-0.054, sigma_lo=0.043, sigma_hi=0.101, lo=-0.3, hi=0.5)
SALT2X1 = dict(peak=0.973, sigma_lo=1.472, sigma_hi=0.222, lo=-3.0, hi=2.0)
ALPHA, BETA = 0.14, 3.1
SIGMA_INT = 0.090  # SALT2.INFO -- aproximacion coherente de G10 (ver docstring)
DNDZ_SEGMENTS = [(2.5e-5, 1.5, 0.0, 1.0), (9.7e-5, -0.5, 1.0, 3.0)]

# E(B-V) real por campo DDF (mapa SFD, consultado via IRSA Dust Extinction
# Service -- https://irsa.ipac.caltech.edu/applications/DUST/ -- en los 6
# centros de campo reales calculados desde baseline_v5.3.1_10yrs.db). Estos
# 6 campos fueron elegidos por el survey precisamente por su baja extincion
# (todos < 0.03 mag), consistente con lo esperado para deep fields
# extragalacticos.
DDF_FIELD_EBV = {
    "cosmos": 0.0182, "ecdfs": 0.0084, "edfs_a": 0.0062,
    "edfs_b": 0.0152, "elaiss1": 0.0080, "xmm_lss": 0.0251,
}
MW_RV = 3.1  # promedio Galaxia estandar, misma familia que OPT_MWCOLORLAW de SNANA
GENSIGMA_MWEBV_RATIO = 0.16  # Fase 10: real, activo en toda la campana (templates.py)
PIXSIZE = 0.2  # arcsec/pixel, LSSTCam
# Fase 17: ver run_simsed_poc.py -- WFD no tiene campos fijos, E(B-V) real
# por nearest-neighbor angular contra esta grilla.
WFD_MWEBV_GRID = HERE / "wfd_mwebv_grid.csv"


def snana_noise_columns(df_ddf: pd.DataFrame) -> pd.DataFrame:
    """Deriva zp/psf_footprint/sky_bg_e con la formula REAL de SNANA
    (pipeline.simlib.formatobs.format_obs(), ya en produccion, Capa 1) en
    vez de dejar que LightCurveLynx las aproxime con sus propias constantes
    (zp_per_sec/ext_coeff simplificados). Ver NOTES.md Fase 2 parte A:
    psf_footprint ya coincidia exactamente entre ambos sistemas; sky_bg_e y
    zp explicaban ~20% del gap de SNR mediana -- esto los fuerza a
    coincidir por construccion en vez de aproximarlos."""
    snana = format_obs(df_ddf, pixsize=PIXSIZE)
    sig_psf_arcsec = df_ddf["seeingFwhmEff"].to_numpy() / (2 * np.sqrt(2 * np.log(2)))
    noise_area_arcsec2 = 4 * np.pi * sig_psf_arcsec ** 2

    out = df_ddf.copy()
    out["sky_bg_e"] = snana["SKYSIG"].to_numpy() ** 2
    out["psf_footprint"] = noise_area_arcsec2 / PIXSIZE ** 2
    out["zp"] = mag2flux(snana["ZPT"].to_numpy())
    return out


# Fase 99: GENRANGE_TREST real de SIMGEN_INCLUDE_SNIa-SALT2.INPUT (-100/300,
# leido en NLHPC). Solo con real_trest=True; el default sigue siendo la
# ventana historica de los ratios de Fase 70 (NOTES.md Fase 99).
GENRANGE_TREST_REAL = (-100.0, 300.0)
HISTORICAL_TREST = (-30, 100)


def main(seed_index: int = 0, wfd: bool = False, out_dir_override: Path | str | None = None,
         real_trest: bool = False):
    # Fase 5: seed_index != 0 corre una realizacion independiente con
    # semilla real distinta, en un directorio de salida separado -- mismo
    # patron que run_simsed_poc.py (ver comentario ahi).
    seed_base = SEED_BASE + seed_index * 1_000_000
    seed_suffix = f"_seed{seed_index}" if seed_index else ""
    wfd_suffix = "_wfd" if wfd else ""
    trest_suffix = "_realtrest" if real_trest else ""
    if out_dir_override is not None:
        out_dir = Path(out_dir_override)
    elif not (seed_suffix or wfd_suffix or trest_suffix):
        out_dir = OUT_DIR
    else:
        out_dir = HERE / f"poc_output{seed_suffix}{wfd_suffix}{trest_suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    trest_range = GENRANGE_TREST_REAL if real_trest else HISTORICAL_TREST
    t_start = time.time()

    con = sqlite3.connect(str(OPSIM_DB))
    df = pd.read_sql_query("SELECT * FROM observations", con)
    if wfd:
        # Fase 17: ver run_simsed_poc.py -- WFD es "todo lo que no es DDF"
        # en el mismo .db, sin columna "field" (no hay campos fijos).
        df_ddf = df[~df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
    else:
        df_ddf = df[df["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
        # etiqueta de campo por fila (primer match ddf_<campo> en target_name) --
        # se usa para asignar el E(B-V) real correcto a cada objeto simulado
        # segun en que pointing cayo (ver ObsTableRADECSampler mas abajo).
        df_ddf["field"] = df_ddf["target_name"].str.extract(r"ddf_(\w+)")
    # LightCurveLynx default zp_err_mag=1e-4 es ~50x mas chico que el
    # ZEROPT_ERR real de SNANA para esta campana (mediana=0.005, std=7.5e-5,
    # confirmado contra el phot_df real de SNIa_DDF) -- ese termino escala
    # con bandflux^2 (ver noise_models/noise_utils.py::poisson_bandflux_std),
    # asi que domina justo en las epocas de mayor SNR, que son las que mas
    # pesan en el trigger de deteccion. Ver NOTES.md Fase 1 punto 7.
    # inyecta zp/psf_footprint/sky_bg_e derivados de la formula real de
    # SNANA en vez de dejar que OpSim las derive con sus propias constantes
    # simplificadas (ver snana_noise_columns() arriba, NOTES.md Fase 2 A).
    df_ddf = snana_noise_columns(df_ddf)
    # Fase 16/42: snana_noise_columns() nunca pasaba read_noise/dark_current
    # explicitos -- OpSim caia en sus defaults genericos de LSSTCam
    # (read_noise=8.8 e-, dark_current=0.2 e-/s, smtn-002.lsst.io), NO en los
    # valores reales y mucho mas chicos de esta campana (read_noise=0.25,
    # dark_current=0, WriterParams.ccd_noise del SIMLIB real, confirmado en
    # Fase 16 Paso 1). Recalculado en Fase 42 con condiciones DDF r-band
    # reales (mediana sky_bg_e=811 e-/pix^2, psf_footprint=55 pix^2): el
    # exceso de varianza por los defaults es ~10.3% de sky_variance, que
    # equivale a ~+5% de SNR si se corrige -- EN LA DIRECCION CONTRARIA a
    # explicar el exceso de deteccion (LightCurveLynx ya sale MAS brillante
    # que SNANA; sacarle ruido de mas lo hace aun mas sensible). Se corrige
    # de todas formas por fidelidad real con el SIMLIB (mismo criterio que
    # el fix de Om0 en Fase 34, que tambien empeoro el residuo).
    obs_table = OpSim(df_ddf, zp_err_mag=0.005, read_noise=0.25, dark_current=0.0)
    print(f"[{time.time()-t_start:.1f}s] OpSim {'WFD' if wfd else 'DDF'}: {len(df_ddf):,} / "
          f"{len(df):,} obs totales (zp_err_mag=0.005, calibrado contra ZEROPT_ERR real de SNANA)")

    passband_group = PassbandGroup.from_preset(preset="LSST")
    print(f"[{time.time()-t_start:.1f}s] passbands cargados")

    local_src = sncosmo.SALT2Source(modeldir=str(SALT2_LOCAL_DIR), name="salt2-h17-local")
    print(f"[{time.time()-t_start:.1f}s] SALT2.WFIRST-H17 local cargado "
          f"(mismo modelo que SNIa_DDF de SNANA, no el mirror remoto)")

    z_grid, cdf = build_dndz_powerlaw2_cdf(
        segments=DNDZ_SEGMENTS, z_min=GENRANGE_REDSHIFT[0], z_max=GENRANGE_REDSHIFT[1],
    )
    redshift_func = SizeAwareFunctionNode(
        make_dndz_sampler(z_grid, cdf, seed=seed_base + 1), node_label="redshift"
    )
    c_func = SizeAwareFunctionNode(
        make_bifurcated_normal_sampler(**SALT2C, seed=seed_base + 2), node_label="c"
    )
    x1_func = SizeAwareFunctionNode(
        make_bifurcated_normal_sampler(**SALT2X1, seed=seed_base + 3), node_label="x1"
    )
    # H0=70 (no 73, el placeholder heredado de bench_snia.py/Fase 0) -- SNANA
    # no fija cosmologia en ningun .INPUT de la campana (grep sin resultados
    # en run_SNANA/*.INPUT ni en pipeline/), asi que corre con su default
    # interno real: H0_SALT2=70.0 (sntools.h). H0=73 introduce un ~0.1 mag de
    # brillo sistematico de mas -- ver NOTES.md Fase 2 parte A.
    # Fase 34: Omega_M=0.3 (asumido desde Fase 2A) NO es el default real de
    # SNANA -- es OMEGA_MATTER_DEFAULT=0.315 (sntools.h), nunca sobreescrito
    # en el .INPUT real. Confirmado ajustando Om0 contra el MU real del
    # .DUMP: optimo 0.3144, coincide con 0.315.
    distmod_func = DistModFromRedshift(redshift_func, H0=70.0, Omega_m=0.315)
    # Fase 20: -19.3 (Fases 0-19) era un valor de la literatura general, nunca
    # verificado contra la convencion real de SNANA -- -19.365 es el valor
    # exacto (no una aproximacion) que hace que X0FromDistMod produzca el
    # MISMO x0/flujo fisico que SALT2x0calc() real de SNANA para el mismo
    # distmod/x1/c/alpha/beta, verificado numericamente con los archivos SALT2
    # reales (byte-identicos a los de SNANA, confirmado via md5sum) y el
    # codigo real de sncosmo.SALT2Source._flux(): con -19.365 el x0 calculado
    # coincide con el de SNANA a 6 cifras significativas y el flujo generado
    # (x0 * SCALE_FACTOR * M0_crudo) coincide exacto (razon 1.000000, Δmag=
    # -0.0000) -- con -19.3 sale 0.065 mag mas TENUE que la convencion real de
    # SNANA (ver fase20_verify_mabs.py, no versionado, y NOTES.md Fase 20).
    # Importante: corregir esto NO cierra el residuo de brillo de Fase 16-17
    # (LightCurveLynx ~0.12-0.24 mag mas brillante que SNANA) -- va en
    # direccion CONTRARIA (mas brillante todavia, no mas tenue), asi que el
    # residuo real sigue sin explicarse; este cambio es una correccion de
    # calibracion real, no un intento de cerrar la brecha.
    #
    # Fase 37: el residuo SI queda explicado, y no estaba en la cadena SALT2
    # sino en un archivo que sncosmo nunca lee. El SALT2.INFO real del modelo
    # (SALT2.WFIRST-H17, el mismo directorio que se le pasa a SALT2Source)
    # declara `MAG_OFFSET: 0.27`, dos lineas arriba del `SIGMA_INT: 0.090` que
    # este script ya citaba. SNANA lo aplica a TODA magnitud del modelo
    # (`genmag_SALT2.c:2257`: `magobs = ZP - 2.5*log10(flux) + MAG_OFFSET`);
    # `sncosmo.SALT2Source` no lee SALT2.INFO en absoluto. Sumarlo a m_abs es
    # exactamente equivalente (x0 ~ 10^(-0.4*m_abs) -> atenua las 6 bandas por
    # igual). Medido pareado objeto-a-objeto contra el _HEAD.FITS real:
    # -0.2722 mag, plano en banda y en z. Ver NOTES.md Fase 37.
    salt2_mag_offset = read_salt2_info(SALT2_LOCAL_DIR)["MAG_OFFSET"]
    m_abs_func = NumpyRandomFunc(
        "normal", loc=-19.365 + salt2_mag_offset, scale=SIGMA_INT, seed=seed_base + 4
    )
    x0_func = X0FromDistMod(
        distmod=distmod_func, x1=x1_func, c=c_func, alpha=ALPHA, beta=BETA, m_abs=m_abs_func,
    )
    # Fase 5: radius=0.0 explicito -- evita el jitter de posicion sub-FOV no
    # reproducible de ObsTableRADECSampler (usa np.random.default_rng() sin
    # seed cuando self.radius>0, bug de la libreria, ver run_simsed_poc.py).
    radec_sampler = ObsTableRADECSampler(
        obs_table, extra_cols=[] if wfd else ["field"], seed=seed_base + 5, radius=0.0,
    )
    # Segundo bug de la libreria: TableSampler.__init__ crea su muestreador
    # de indice de fila via NumpyRandomFunc("integers", ...) SIN seed= --
    # el seed del constructor nunca llega a ese nodo hijo. Fijarlo aqui
    # directamente (mismo patron que el fix de SIMSEDModel en Fase 4).
    radec_sampler.setters["selected_table_index"].dependency.set_seed(seed_base + 5)
    t0_func = NumpyRandomFunc(
        "uniform", low=float(obs_table["time"].min()), high=float(obs_table["time"].max()),
        seed=seed_base + 6,
    )

    # Fase 10: GENSIGMA_MWEBV_RATIO=0.16 real y activo (ver
    # snana_params.make_mwebv_ratio_scatter para la formula, verificada
    # contra snlc_sim.c::gen_MWEBV()).
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
    # Fase 24: OPT_MWCOLORLAW=99 real (Fitzpatrick99 exacto, confirmado en
    # include_model_SNIa.INPUT -- ver NOTES.md) -- corregido de O94 a F99.
    # Diferencia numerica O94-vs-F99 confirmada <0.005 mag a estos E(B-V)
    # (campos DDF 0.006-0.025), no explica el patron cromatico de Fase 23.
    mw_extinction = ExtinctionEffect(
        extinction_model="F99", ebv=ebv_func, r_v=MW_RV, frame="observer", backend="dust_extinction",
    )

    source = SncosmoWrapperModel(
        local_src, t0=t0_func, x0=x0_func, x1=x1_func, c=c_func,
        ra=radec_sampler.ra, dec=radec_sampler.dec, redshift=redshift_func,
        node_label="source", time_extrapolation=LinearDecay(50.0), wave_extrapolation=ZeroPadding(),
    )
    source.add_effect(mw_extinction)
    survey_info = SurveyInfo(obstable=obs_table, passbands=passband_group, survey_name="LSST")
    print(f"[{time.time()-t_start:.1f}s] modelo armado, simulando {NGENTOT_LC} objetos...")

    t_sim0 = time.time()
    # Fase 5: rng= explicito -- simulate_lightcurves() propaga este generador
    # a cualquier nodo del grafo sin seed propio (p.ej. ruido fotometrico),
    # que sin esto cae en un default no reproducible (ver run_simsed_poc.py).
    lc = simulate_lightcurves(
        source, NGENTOT_LC, survey_info, rest_time_window_offset=trest_range, rng=np.random.default_rng(seed_base + 8),
    )
    sim_wall_time = time.time() - t_sim0
    print(f"[{time.time()-t_start:.1f}s] simulacion terminada: {len(lc)} objetos, "
          f"{sim_wall_time:.1f}s ({sim_wall_time/len(lc)*1000:.2f} ms/objeto)")

    # -- aplanar a phot_df + head_df --
    head_rows = []
    phot_rows = []
    for _, row in lc.iterrows():
        sub = row["lightcurve"]
        if sub is None or len(sub) == 0:
            continue
        snid = str(int(row["id"]))
        head_rows.append({
            "SNID": snid, "SNTYPE": 1, "RA": row["ra"], "DEC": row["dec"],
            "REDSHIFT_HELIO": row["z"], "PEAKMJD": row["t0"], "NOBS": len(sub),
        })
        for _, obs in sub.iterrows():
            # normaliza 'y' -> 'Y' para calzar con la convencion de banda de
            # SNANA que ya usa pipeline/postproc/qc.py (bands=[...,"Y"]).
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
    # LightCurveLynx usa flujo en nJy (no el FLUXCAL/ZEROPT=27.5 de SNANA) --
    # zeropoint AB estandar para nJy: mag = 8.9 + 2.5*9 - 2.5*log10(flux_njy)
    # (misma constante que lightcurvelynx.astro_utils.mag_flux.MAG_AB_ZP_NJY).
    MAG_AB_ZP_NJY = 8.9 + 2.5 * 9
    positive = phot_df["FLUXCAL"] > 0
    phot_df["MAG"] = np.where(positive, MAG_AB_ZP_NJY - 2.5 * np.log10(phot_df["FLUXCAL"].where(positive)), np.nan)
    print(f"[{time.time()-t_start:.1f}s] aplanado: {len(head_df)} objetos con obs, "
          f"{len(phot_df)} filas de fotometria")

    # -- diagnostico de SNR simulado (todas las obs, antes del corte SEARCHEFF) --
    # mismo metodo usado para diagnosticar la brecha de eficiencia vs SNANA real
    # (ver NOTES.md Fase 1 punto 7) -- se deja permanente para que cada corrida
    # reporte esto sin necesidad de recalcularlo aparte.
    snr_sim = (phot_df["FLUXCAL"] / phot_df["FLUXCALERR"]).abs()
    print(f"[{time.time()-t_start:.1f}s] SNR simulado (todas las obs): "
          f"mediana={snr_sim.median():.3f}, p90={snr_sim.quantile(0.9):.3f} "
          f"(referencia SNANA real SNIa_DDF: mediana=0.78, p90=2.26)")

    # -- eficiencia de deteccion real (SEARCHEFF) --
    band_curves = parse_searcheff_pipeline(SEARCHEFF_PIPELINE_FILE)
    min_epochs = parse_pipeline_logic(SEARCHEFF_LOGIC_FILE)
    # Fase 70: trigger real usa SNR_CALC (flujo verdadero/error), no SNR_OBS
    # (observado/error) -- mismo fix de Fase 64, portado aca.
    detected_mask = apply_detection_efficiency(
        phot_df, band_curves, flux_col="FLUXTRUE", seed=seed_base + 7,
    )
    phot_df["PHOTFLAG"] = np.where(detected_mask, 4096, 0)
    # Fase 4: agrupar en epocas reales (NEWMJD_DIF=0.007d) antes del trigger
    # ">=2 epocas" -- contar observaciones individuales infla el trigger,
    # ver searcheff.group_into_epochs() y NOTES.md.
    detected_snids = object_level_detected(phot_df, min_epochs=min_epochs)
    print(f"[{time.time()-t_start:.1f}s] SEARCHEFF aplicado: {len(detected_snids)}/{len(head_df)} "
          f"objetos detectados (>= {min_epochs} epocas reales, agrupadas)")

    # dump_df-equivalente: TODOS los NGENTOT_LC generados (no solo los con obs)
    all_ids = lc["id"].astype(int).astype(str)
    dump_df = pd.DataFrame({
        "CID": all_ids, "ZHELIO": lc["z"].to_numpy(), "ZCMB": lc["z"].to_numpy(),
    })
    # marcar detectados en head_df (subconjunto que paso SEARCHEFF)
    head_df_detected = head_df[head_df["SNID"].isin(detected_snids)].reset_index(drop=True)

    # Fase 5: persistir head_df/phot_df reales (ver run_simsed_poc.py) -- no
    # se versiona en git, solo vive en el output dir de NLHPC/local.
    head_df["DETECTED"] = head_df["SNID"].isin(detected_snids)
    head_df.to_parquet(out_dir / "head_df.parquet", index=False)
    phot_df.to_parquet(out_dir / "phot_df.parquet", index=False)
    print(f"[{time.time()-t_start:.1f}s] tablas persistidas: head_df.parquet "
          f"({len(head_df)} filas), phot_df.parquet ({len(phot_df)} filas)")

    (out_dir / "summary.json").write_text(json.dumps({
        "strategy": "WFD" if wfd else "DDF",
        "seed_index": seed_index,
        "ngentot_lc": NGENTOT_LC,
        "n_with_obs": len(head_df),
        "n_detected": len(detected_snids),
        "n_total_dump": len(dump_df),
        "sim_wall_time_s": sim_wall_time,
        "detection_efficiency_pct": 100.0 * len(detected_snids) / NGENTOT_LC,
        # Fase 38: se imprimian al log (linea ~343) pero nunca se guardaban en
        # summary.json pese a que HOWTO.md Sec.5-6 los documenta como parte del
        # resumen -- ver NOTES.md Fase 38.
        "snr_median": float(snr_sim.median()),
        "snr_p90": float(snr_sim.quantile(0.9)),
        "snr_median_snana_ref": 0.78,
        "snr_p90_snana_ref": 2.26,
        "rest_time_window": list(trest_range),
        "real_trest": real_trest,
    }, indent=2))

    # -- QC reusando pipeline.postproc.qc sin modificar --
    sys.path.insert(0, str(REPO_ROOT))
    from pipeline.postproc import qc

    qc_dir = out_dir / "qc"
    paths = qc.run_all_qc(
        head_df_detected, phot_df, qc_dir,
        f"LightCurveLynx_SNIa_{'WFD' if wfd else 'DDF'}_poc", dump_df=dump_df,
    )
    print(f"[{time.time()-t_start:.1f}s] QC generado: {list(paths.keys())}")
    # Fase 68/69: reemplaza SOLO el panel de curvas de luz con el estilo real
    # del notebook oficial de LightCurveLynx -- no toca pipeline/.
    if "lightcurves" in paths:
        lc_ok = plot_notebook_style_lightcurves(
            source, lc, passband_group, detected_snids, paths["lightcurves"],
            "SNIa", "WFD" if wfd else "DDF",
        )
        print(f"[{time.time()-t_start:.1f}s] Fase 68/69: panel de curvas de luz "
              f"estilo notebook oficial {'regenerado' if lc_ok else 'omitido (sin candidatos)'}")

    print(f"[{time.time()-t_start:.1f}s] TOTAL")


if __name__ == "__main__":
    # Fase 17: --wfd en cualquier posicion (ver run_simsed_poc.py).
    _args = sys.argv[1:]
    _wfd = "--wfd" in _args
    # Fase 99: --real-trest usa el GENRANGE_TREST real del .INPUT (opcional).
    _real_trest = "--real-trest" in _args
    _args = [a for a in _args if a not in ("--wfd", "--real-trest")]
    _seed_index = int(_args[0]) if len(_args) == 1 else 0
    main(seed_index=_seed_index, wfd=_wfd, real_trest=_real_trest)
