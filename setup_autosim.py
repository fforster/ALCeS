#!/usr/bin/env python
"""
setup_autosim.py — Diagnostico y reparacion completa del pipeline.

Correr desde DENTRO de la carpeta AUTOSIM:

    python setup_autosim.py

Que hace:
  1. Crea toda la estructura de carpetas esperada.
  2. Reescribe los 6 __init__.py con su contenido correcto (el error mas
     comun: los __init__.py de las distintas capas se confunden al copiar
     a mano).
  3. Reescribe los 4 archivos de CONFIGURACION (opsims.yaml, simlib.yaml,
     models.yaml, campaigns/full_v5.3.yaml) con su contenido correcto,
     por si no se copiaron o quedaron incompletos.
  4. Verifica que el resto de los archivos .py (la logica de cada capa)
     esten presentes; si falta alguno, te dice exactamente cual copiar
     y desde que carpeta Capa# original.
  5. Corre los self-tests de las capas 1, 2, 4 y 5.

Es seguro correrlo varias veces: los __init__.py y los YAML de config
siempre se sobrescriben con la version correcta; los .py de logica de
cada capa NO se tocan si ya existen (para no perder tus posibles ajustes).
"""

import sys
from pathlib import Path

HERE = Path(".").resolve()
print("=" * 66)
print("  setup_autosim.py - Diagnostico y reparacion del pipeline")
print(f"  Directorio: {HERE}")
print("=" * 66)
print()

YAML_CONTENTS = {}

YAML_CONTENTS['pipeline/opsims.yaml'] = """# ============================================================================
# opsims.yaml — Registro curado de bases OpSim / ObSim (Vera C. Rubin / LSST)
# ----------------------------------------------------------------------------
# Capa 0 del pipeline. Agregar una base nueva = agregar una entrada aqui.
# fetch_opsim.py construye la URL como:
#   {s3df_base}/sims_featureScheduler_runs{release}/{family}/{filename}
#
# Campos por run:
#   release       (obligatorio)  "5.0" | "5.3" | ...
#   family        (obligatorio)  "baseline" | "ddf_sd" | "roll_mash" | ...
#   filename      (obligatorio)  nombre exacto del .db en el indice S3DF
#   survey_years                 anhos de survey (10, 11, ...)
#   label                        descripcion legible
#   footprint                    resumen de cobertura
#   status                       verified | registered | archived
#   n_obs                        nro de observaciones (chequeo de sanidad)
#   size_bytes                   tamanho del .db confirmado en el indice (chequeo de sanidad)
#   sha256                       si se fija, fetch_opsim EXIGE que coincida
#   notes                        comentarios libres
#
# Fuentes:
#   Post oficial v5.3: community.lsst.org/t/release-of-v5-3-simulations/12032
#   Indice (verificado en vivo, Jul-2026):
#     https://s3df.slac.stanford.edu/data/rubin/sim-data/sims_featureScheduler_runs5.3/
#   MAF: https://usdf-maf.slac.stanford.edu/
#
# NOTA: los filenames y tamanhos de este archivo fueron confirmados listando
# el indice S3DF directamente (no solo el texto del post del foro), porque el
# post decia "_11years" y el archivo real en el servidor es "_11yrs".
# ============================================================================

defaults:
  s3df_base: "https://s3df.slac.stanford.edu/data/rubin/sim-data"
  data_dir: "data/opsim"          # relativo a la raiz del repo (o usar $RUBIN_OPSIM_DIR)

runs:

  # -------------------------------------------------------------- VERIFICADAS
  # (descargadas y analizadas en los notebooks — n_obs confirmado)
  baseline_v5.0.0_10yrs:
    release: "5.0"
    family: "baseline"
    filename: "baseline_v5.0.0_10yrs.db"
    survey_years: 10
    label: "Baseline v5.0.0 — estrategia de referencia (campanha del poster)"
    footprint: "WFD + 5 DDF; estrategia 'ocean' en DDF"
    status: "verified"
    n_obs: 2048612                 # analysis_simlib_filev5_LSST.ipynb
    size_bytes: 762941440          # confirmado en el indice, 30-Jul-2025
    sha256: null                   # se registra tras la primera descarga verificada
    notes: >
      Version usada en las simulaciones previas (WFD/DDF, input_files_v6).
      Inicio del survey: 2025-11-01. Tambien existe baseline_v5.0.1_10yrs.db
      (patch posterior, no registrado aqui todavia).

  baseline_v5.3.1_10yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.1_10yrs.db"
    survey_years: 10
    label: "Baseline v5.3.1 — ~10% menos visitas, template tier Y1, dithering DDF"
    footprint: "WFD + 5 DDF; mismo footprint que v5.0"
    status: "verified"
    n_obs: 1844189                 # analysis_simlib_filev5_3_LSST.ipynb
    size_bytes: 742952960          # confirmado en el indice, 31-May-2026
    sha256: null
    notes: >
      Compatibilidad de Capa 1 confirmada: OpSimSummaryV2 lo lee sin cambios de
      esquema. Verificado -9.98% de visitas vs v5.0; aparecen notas 'templates'
      (Y1) y 'pair_33 ... bs NN' (bloques). Inicio del survey: 2026-06-17.
      Nuevas familias de scheduler_note requieren el filtrado por prefijo (Capa 1).
      NO es la version mas reciente del patch — existen v5.3.2 y v5.3.3 (ver abajo).

  # --------------------------------------------------- BASELINE v5.3.0 (release original)
  baseline_v5.3.0_10yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Baseline v5.3.0 — release original de v5.3 (pre-patches .1/.2/.3)"
    footprint: "WFD + 5 DDF; mismo footprint y rolling cadence que v5.0"
    status: "registered"
    size_bytes: 743002112          # confirmado en el indice, 16-May-2026
    notes: >
      Filename y tamanho confirmados listando el indice S3DF directamente
      (no solo el texto del post del foro). Sigue las recomendaciones SCOC
      Phase 3 (PSTN-056). Sin snaps: cada visita es una exposicion unica de
      30s (38s en u) en grizy. Dithering intra-noche en DDF ademas del
      dithering entre noches.

  baseline_v5.3.0_11yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.0_11yrs.db"
    survey_years: 11
    label: "Baseline v5.3.0 — extension a 11 anhos (para evaluar recuperacion cientifica)"
    footprint: "WFD + 5 DDF; igual que baseline_v5.3.0_10yrs"
    status: "registered"
    size_bytes: 819699712          # confirmado en el indice, 16-May-2026
    notes: >
      CORRECCION DE NOMBRE: el post del foro escribe "baseline_v5.3.0_11years.db"
      pero el archivo REAL en el indice S3DF se llama "_11yrs" (sin "years").
      Confirmado listando el directorio directamente. Anho 11 no aprobado;
      sirve para evaluar como se recuperaria la ciencia del impacto de mas
      tiempo de ingenieria con un anho adicional de survey.

  # ----------------------------------------- BASELINE v5.3.2 / v5.3.3 (mas recientes)
  # Patches posteriores al v5.3.1 que ya tenias analizado. No documentados en
  # el post original del foro (son mas nuevos que ese post). Si vas a simular
  # con la estrategia mas actualizada, estas son las candidatas.
  baseline_v5.3.2_10yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.2_10yrs.db"
    survey_years: 10
    label: "Baseline v5.3.2 — patch mas reciente que v5.3.1 (sin release notes propio)"
    footprint: "WFD + 5 DDF; mismo footprint que v5.3.x"
    status: "registered"
    size_bytes: 742952960          # confirmado en el indice, 02-Jul-2026
    notes: >
      Confirmado en el indice S3DF (02-Jul-2026), NO en el post del foro
      (ese post solo describe hasta v5.3.0/variantes). Mismo tamanho que
      v5.3.1_10yrs — posiblemente un ajuste menor de scheduler/metadata.
      Recomendado verificar contra MAF antes de adoptarlo como baseline.

  baseline_v5.3.2_11yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.2_11yrs.db"
    survey_years: 11
    label: "Baseline v5.3.2 — extension a 11 anhos"
    status: "registered"
    size_bytes: 819449856          # confirmado en el indice, 02-Jul-2026
    notes: "Ver baseline_v5.3.2_10yrs. Confirmado en el indice, no en el foro."

  baseline_v5.3.3_10yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.3_10yrs.db"
    survey_years: 10
    label: "Baseline v5.3.3 — patch MAS RECIENTE disponible (03-Jul-2026)"
    footprint: "WFD + 5 DDF; mismo footprint que v5.3.x"
    status: "registered"
    size_bytes: 746434560          # confirmado en el indice, 03-Jul-2026
    notes: >
      La version mas reciente de la baseline v5.3 al momento de escribir este
      registro. Confirmado en el indice S3DF, no documentado aun en un post
      propio del foro. Candidata natural si quieres la estrategia mas
      actualizada; recomendado repetir el analisis de compatibilidad de la
      Capa 1 (como se hizo para v5.3.1) antes de usarla en produccion.

  baseline_v5.3.3_11yrs:
    release: "5.3"
    family: "baseline"
    filename: "baseline_v5.3.3_11yrs.db"
    survey_years: 11
    label: "Baseline v5.3.3 — extension a 11 anhos (mas reciente)"
    status: "registered"
    size_bytes: 823803904          # confirmado en el indice, 03-Jul-2026
    notes: "Ver baseline_v5.3.3_10yrs."

  # ------------------------------------------------- OTRAS VARIANTES v5.3.0
  # Filenames y tamanhos confirmados listando cada carpeta del indice.
  comp_survey_v5.3.0_10yrs:
    release: "5.3"
    family: "comp_survey"
    filename: "comp_survey_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Comparacion 1-a-1 — estrategia v5.3 con el modelo de tiempo on-sky de v5.0"
    status: "registered"
    size_bytes: 787922944          # confirmado en el indice, 02-May-2026
    notes: >
      Implementa la estrategia v5.3 pero con el modelo de disponibilidad de
      v5.0, para aislar el efecto de la estrategia del efecto del recorte de
      tiempo on-sky.

  roll_mash_v5.3.0_10yrs:
    release: "5.3"
    family: "roll_mash"
    filename: "roll_mash_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Rolling cadence retrasada — data releases uniformes en Y1,Y2,Y7,Y10"
    status: "registered"
    size_bytes: 713883648          # confirmado en el indice, 02-May-2026
    notes: "Retrasa el inicio de la rolling cadence a Y2 para extender el template tier."

  roll_u5_v5.3.0_10yrs:
    release: "5.3"
    family: "roll_u5"
    filename: "roll_u5_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Rolling cadence retrasada — data releases uniformes en Y1,Y2,Y5,Y10"
    status: "registered"
    size_bytes: 713990144          # confirmado en el indice, 08-May-2026
    notes: "Variante de roll_mash con el release uniforme en Y5 en vez de Y7."

  faster_templates_v5.3.0_10yrs:
    release: "5.3"
    family: "faster_templates"
    filename: "faster_templates_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Template tier con exposiciones mas cortas (20s/25s grizy/u)"
    status: "registered"
    size_bytes: 728723456          # confirmado en el indice, 02-May-2026
    notes: >
      Variante EXPERIMENTAL, aun no validada para uso on-sky ni para los
      pipelines de Data Management (implicaciones de calibracion pendientes).
      Reduce el duty cycle y lleva u-band a regimen dominado por read-noise.

  ddf_sd_v5.3.0_10yrs:
    release: "5.3"
    family: "ddf_sd"
    filename: "ddf_sd_v5.3.0_10yrs.db"
    survey_years: 10
    label: "DDF short-deep — 1-2 visitas extra en bandas azules (monitoreo AGN)"
    footprint: "Variante DDF; relevante para AGN"
    status: "registered"
    size_bytes: 713924608          # confirmado en el indice, 06-May-2026
    notes: >
      Empuja la fraccion de tiempo DDF por sobre el 8% (SCOC recomienda
      contener el programa en 7%, PSTN-055/PSTN-056). Relevante porque ya
      simulas AGN.

  # NOTA: la carpeta real en el indice es "desi/" (no "desi_3040/" como se
  # habia registrado antes por error de transcripcion del nombre del archivo).
  desi_3040_v5.3.0_10yrs:
    release: "5.3"
    family: "desi"
    filename: "desi_3040_v5.3.0_10yrs.db"
    survey_years: 10
    label: "Prioriza u/g en Y1-Y4 en el norte del footprint (soporte a DESI)"
    status: "registered"
    size_bytes: 714588160          # confirmado en el indice, 03-May-2026
    notes: >
      CORRECCION: la carpeta del indice es 'desi/', no 'desi_3040/' (el
      '3040' es parte del nombre del archivo, no de la carpeta). Impacto
      fuerte en cadencia u/g del norte los anhos siguientes a Y4; la
      uniformidad se empareja recien al final del survey.

  desi_3040_v5.3.1_10yrs:
    release: "5.3"
    family: "desi"
    filename: "desi_3040_v5.3.1_10yrs.db"
    survey_years: 10
    label: "Prioriza u/g en Y1-Y4 en el norte — patch v5.3.1"
    status: "registered"
    size_bytes: 714821632          # confirmado en el indice, 31-May-2026
    notes: "Version actualizada de desi_3040 sobre el patch v5.3.1."

  # --------------------------------------------------------- v5.3.1 (variantes heredadas)
  # Filename no confirmado aun contra el indice para estas dos — quedan
  # marcadas para verificar antes de descargar.
  ddf_sd_v5.3.1_10yrs:
    release: "5.3"
    family: "ddf_sd"
    filename: "ddf_sd_v5.3.1_10yrs.db"
    survey_years: 10
    label: "DDF short-deep (patch .1) — orientada a monitoreo (AGN)"
    footprint: "Variante DDF; relevante para AGN"
    status: "registered"
    notes: "Confirmar filename exacto en el indice antes de descargar (solo v5.3.0 confirmado)."

  roll_mash_v5.3.1_10yrs:
    release: "5.3"
    family: "roll_mash"
    filename: "roll_mash_v5.3.1_10yrs.db"
    survey_years: 10
    label: "Rolling 'mash' (patch .1) — cadencia rotativa alternativa"
    status: "registered"
    notes: "Confirmar filename exacto en el indice antes de descargar (solo v5.3.0 confirmado)."
"""

YAML_CONTENTS['pipeline/simlib.yaml'] = """# ============================================================================
# simlib.yaml — Config declarativa del constructor de SIMLIB (Capa 1)
# ----------------------------------------------------------------------------
# Todo lo que cambia entre estrategias o versiones es dato, no codigo.
# ============================================================================

defaults:
  nside: 256
  pixsize: 0.2            # arcsec/pixel (LSST)
  radius_deg: 1.75        # radio de agrupamiento por campo (query_radius)
  ccd_gain: 1.0
  ccd_noise: 0.25
  zpt_err: 0.005
  seed: 42
  bands: "ugrizY"
  author: "Mauricio Valenzuela C"

# Numero de campos muestreados y corte de visitas minimas por estrategia.
strategies:
  WFD:
    n_fields: 20000
    min_visits: 250
  DDF:
    n_fields: 1000
    min_visits: 500

# --- AISLAMIENTO DE ESQUEMA: clasificacion de scheduler_note por prefijo ---
# Cubre v5.0 y v5.3. Si una version futura agrega familias, se editan aqui.
classification:
  ddf_prefixes: ["DD:"]
  wfd_prefixes: ["pair_", "blob_long", "blob", "long", "greedy", "templates"]
  twilight_prefixes: ["twilight_near_sun"]

# Recorte temporal (2 temporadas WFD). date_* en ISO; o usar mjd_* directo.
temporal_cut:
  date_min: null          # null = inicio del survey
  date_max: "2029-12-31"
  mjd_min: null
  mjd_max: null
"""

YAML_CONTENTS['pipeline/models.yaml'] = """# ============================================================================
# models.yaml — Catalogo de modelos de transientes para SNANA
# ----------------------------------------------------------------------------
# Cada entrada declara GENMODEL, GENTYPE/SNTYPE, DNDZ, rango de redshift,
# rango de TREST y (si aplica) la ruta al INPUT_FILE_INCLUDE de SNANA
# (p.ej. NON1ASED, SIMSED, SALT2).
#
# Convencion:
#   genmodel_key:   identificador corto del modelo (usado en campaign.yaml)
#   genmodel:       valor literal de la clave GENMODEL de SNANA
#   genmodel_path:  ruta $SNDATA_ROOT/... al directorio del modelo (o "")
#   input_include:  ruta al SIMGEN_INCLUDE_*.INPUT (si aplica)
#   gentype:        SNTYPE numerico para SNANA
#   dndz:           string literal de la clave DNDZ (puede ser multilinea)
#   zrange:         [zmin, zmax]  de GENRANGE_REDSHIFT
#   trest:          [tmin, tmax]  de GENRANGE_TREST
#   ngen:           NGEN_LC por defecto (ajustable en la campanha)
#   notes:          comentarios libres
#
# Organizacion: tres familias, siguiendo el poster.
# ============================================================================

# ------------------------------------------------------------------
# PLAsTiCC / estándar
# ------------------------------------------------------------------
SNIa:
  genmodel: "SALT2.WFIRST-H17"
  genmodel_path: "$SNDATA_ROOT/models/SALT2/SALT2.WFIRST-H17"
  gentype: 1
  dndz: "POWERLAW2  2.6E-5  1.5  0.0  1.0"
  zrange: [0.01, 1.2]
  trest: [-40, 100]
  ngen: 50000

SNIa-91bg:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIa-91bg"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIa-91bg/SIMGEN_INCLUDE.INPUT"
  gentype: 10
  dndz: "POWERLAW2  3.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 80]
  ngen: 10000

SNIax:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIax"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIax/SIMGEN_INCLUDE.INPUT"
  gentype: 11
  dndz: "POWERLAW2  3.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.6]
  trest: [-20, 80]
  ngen: 10000

SNII:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNII-Templates"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNII-Templates/SIMGEN_INCLUDE.INPUT"
  gentype: 20
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 200]
  ngen: 50000

SNII-NMF:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNII-NMF"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNII-NMF/SIMGEN_INCLUDE.INPUT"
  gentype: 21
  dndz: "POWERLAW2  5.0E-5  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 200]
  ngen: 20000

SNIIn-MOSFIT:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIIn-MOSFIT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIIn-MOSFIT/SIMGEN_INCLUDE.INPUT"
  gentype: 22
  dndz: "POWERLAW2  5.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.6]
  trest: [-20, 150]
  ngen: 10000

SNIbc:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIbc-Templates"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIbc-Templates/SIMGEN_INCLUDE.INPUT"
  gentype: 30
  dndz: "POWERLAW2  2.5E-5  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 100]
  ngen: 20000

SLSN-I:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SLSN-I"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SLSN-I/SIMGEN_INCLUDE.INPUT"
  gentype: 40
  dndz: "POWERLAW2  2.0E-8  1.5  0.0  1.0"
  zrange: [0.01, 2.0]
  trest: [-50, 200]
  ngen: 10000

TDE:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.TDE"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.TDE/SIMGEN_INCLUDE.INPUT"
  gentype: 50
  dndz: "POWERLAW2  1.0E-7  1.5  0.0  1.0"
  zrange: [0.01, 1.0]
  trest: [-30, 200]
  ngen: 10000

KN-K17:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.KN-K17"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.KN-K17/SIMGEN_INCLUDE.INPUT"
  gentype: 60
  dndz: "POWERLAW2  1.0E-7  1.5  0.0  0.5"
  zrange: [0.01, 0.3]
  trest: [-5, 30]
  ngen: 5000

KN-BULLA19:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.KN-BULLA19"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.KN-BULLA19/SIMGEN_INCLUDE.INPUT"
  gentype: 61
  dndz: "POWERLAW2  1.0E-7  1.5  0.0  0.5"
  zrange: [0.01, 0.3]
  trest: [-5, 30]
  ngen: 5000

AGN:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.AGN"
  gentype: 80
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  2.0"
  zrange: [0.01, 2.0]
  trest: [-100, 500]
  ngen: 20000

RRL:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.RRL"
  gentype: 81
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.5"
  zrange: [0.001, 0.2]
  trest: [-50, 200]
  ngen: 10000

Mira:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.Mira"
  gentype: 82
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.2"
  zrange: [0.001, 0.1]
  trest: [-100, 600]
  ngen: 10000

M-dwarf:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.Mdwarf"
  gentype: 83
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.1"
  zrange: [0.001, 0.05]
  trest: [-20, 50]
  ngen: 10000

EB:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.EB"
  gentype: 84
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.2"
  zrange: [0.001, 0.1]
  trest: [-100, 400]
  ngen: 10000

uLens:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.uLens"
  gentype: 85
  dndz: "POWERLAW2  1.0E-6  1.5  0.0  0.5"
  zrange: [0.001, 0.3]
  trest: [-50, 200]
  ngen: 5000

ILOT:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.ILOT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.ILOT/SIMGEN_INCLUDE.INPUT"
  gentype: 70
  dndz: "POWERLAW2  1.0E-6  1.5  0.0  0.5"
  zrange: [0.01, 0.3]
  trest: [-20, 100]
  ngen: 5000

CaRT:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.CaRT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.CaRT/SIMGEN_INCLUDE.INPUT"
  gentype: 71
  dndz: "POWERLAW2  1.0E-6  1.5  0.0  0.5"
  zrange: [0.01, 0.3]
  trest: [-20, 80]
  ngen: 5000

PISN:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.PISN"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.PISN/SIMGEN_INCLUDE.INPUT"
  gentype: 90
  dndz: "POWERLAW2  1.0E-9  1.5  0.0  2.0"
  zrange: [0.01, 3.0]
  trest: [-50, 300]
  ngen: 5000

# ------------------------------------------------------------------
# Extensiones ELASTiCC  (Vincenzi+ 2019)
# ------------------------------------------------------------------
V19_SNIb:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIb"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIb/SIMGEN_INCLUDE.INPUT"
  gentype: 31
  dndz: "POWERLAW2  1.0E-5  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 100]
  ngen: 10000

V19_SNIc:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIc"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIc/SIMGEN_INCLUDE.INPUT"
  gentype: 32
  dndz: "POWERLAW2  5.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 100]
  ngen: 10000

V19_SNIcBL:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIcBL"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIcBL/SIMGEN_INCLUDE.INPUT"
  gentype: 33
  dndz: "POWERLAW2  2.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.6]
  trest: [-20, 80]
  ngen: 5000

V19_SNII:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNII"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNII/SIMGEN_INCLUDE.INPUT"
  gentype: 23
  dndz: "POWERLAW2  5.0E-5  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 200]
  ngen: 20000

V19_SNIIb:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIIb"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIIb/SIMGEN_INCLUDE.INPUT"
  gentype: 24
  dndz: "POWERLAW2  5.0E-6  1.5  0.0  0.8"
  zrange: [0.01, 0.6]
  trest: [-20, 150]
  ngen: 10000

V19_SNIIn:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIIn"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.V19_SNIIn/SIMGEN_INCLUDE.INPUT"
  gentype: 25
  dndz: "POWERLAW2  5.0E-6  1.5  0.0  0.6"
  zrange: [0.01, 0.6]
  trest: [-20, 150]
  ngen: 10000

Cepheid:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.Cepheid"
  gentype: 86
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.1"
  zrange: [0.001, 0.05]
  trest: [-100, 400]
  ngen: 10000

d-Scuti:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.dScuti"
  gentype: 87
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.1"
  zrange: [0.001, 0.05]
  trest: [-50, 200]
  ngen: 10000

Dwarf_nova:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.DwarfNova"
  gentype: 88
  dndz: "POWERLAW2  1.0E-5  1.5  0.0  0.2"
  zrange: [0.001, 0.1]
  trest: [-20, 100]
  ngen: 5000

Mdwarf-flare:
  genmodel: "SIMSED"
  genmodel_path: "$SNDATA_ROOT/models/SIMSED/SIMSED.MdwarfFlare"
  gentype: 89
  dndz: "POWERLAW2  1.0E-4  1.5  0.0  0.05"
  zrange: [0.001, 0.02]
  trest: [-5, 20]
  ngen: 10000

# ------------------------------------------------------------------
# NON1ASED en desarrollo (transporte optico, Ramirez+ 2024)
# ------------------------------------------------------------------
SNIax_NON1ASED:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIax_OT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIax_OT/SIMGEN_INCLUDE.INPUT"
  gentype: 12
  dndz: "POWERLAW2  3.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.6]
  trest: [-20, 80]
  ngen: 10000
  notes: "Transporte optico sobre plantillas Vincenzi+2019"

SNIa-91bg_NON1ASED:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SNIa-91bg_OT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SNIa-91bg_OT/SIMGEN_INCLUDE.INPUT"
  gentype: 13
  dndz: "POWERLAW2  3.0E-6  1.5  0.0  1.0"
  zrange: [0.01, 0.8]
  trest: [-20, 80]
  ngen: 10000

TDE_NON1ASED:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.TDE_OT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.TDE_OT/SIMGEN_INCLUDE.INPUT"
  gentype: 51
  dndz: "POWERLAW2  1.0E-7  1.5  0.0  1.0"
  zrange: [0.01, 1.0]
  trest: [-30, 200]
  ngen: 10000

SLSN-I_NON1ASED:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.SLSN-I_OT"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.SLSN-I_OT/SIMGEN_INCLUDE.INPUT"
  gentype: 41
  dndz: "POWERLAW2  2.0E-8  1.5  0.0  1.0"
  zrange: [0.01, 2.0]
  trest: [-50, 200]
  ngen: 10000

KN-BULLA-BNS-M2COMP:
  genmodel: "NON1ASED"
  genmodel_path: "$SNDATA_ROOT/snsed/NON1ASED.KN-BULLA-BNS-M2COMP"
  input_include: "$SNDATA_ROOT/snsed/NON1ASED.KN-BULLA-BNS-M2COMP/SIMGEN_INCLUDE.INPUT"
  gentype: 62
  dndz: "POWERLAW2  1.0E-7  1.5  0.0  0.5"
  zrange: [0.01, 0.3]
  trest: [-5, 30]
  ngen: 5000
"""

YAML_CONTENTS['campaigns/full_v5.3.yaml'] = """# ============================================================================
# campaign.yaml — Campanha de simulacion completa v5.3.1 WFD + DDF
# ============================================================================
# Declara: que runs/estrategias combinar con que clases. compile_campaign.py
# lo materializa en archivos .INPUT concretos, listos para submit_batch_jobs.
#
# Agregar una nueva version = nueva entrada en 'runs'.
# Agregar una nueva clase   = nueva entrada en 'classes' (o en models.yaml).
# ============================================================================

name: "full_v5.3"
description: "Campanha PLAsTiCC completa sobre baseline_v5.3.1, WFD y DDF"

# Referencia al catalogo de modelos (relativo a pipeline/)
models_catalog: "pipeline/models.yaml"

# --- Combinaciones run × estrategia ---
# Cada run x estrategia genera un include_survey distinto.
runs:
  - run: baseline_v5.3.1_10yrs          # nombre del registro Capa 0
    strategies: [WFD, DDF]

  # Descomentar cuando esten verificadas:
  # - run: baseline_v5.0.0_10yrs
  #   strategies: [WFD, DDF]
  # - run: ddf_sd_v5.3.1_10yrs
  #   strategies: [DDF]

# --- Clases a simular ---
# Referencia modelos por su clave en models.yaml. Pueden sobreescribir ngen.
classes:
  # PLAsTiCC core
  - model: SNIa
  - model: SNIa-91bg
  - model: SNIax
  - model: SNII
  - model: SNII-NMF
  - model: SNIIn-MOSFIT
  - model: SNIbc
  - model: SLSN-I
  - model: TDE
  - model: KN-K17
  - model: KN-BULLA19
  - model: AGN
  - model: RRL
  - model: Mira
  - model: M-dwarf
  - model: EB
  - model: uLens
  - model: ILOT
  - model: CaRT
  - model: PISN

  # Extensiones ELASTiCC (Vincenzi+2019)
  - model: V19_SNIb
  - model: V19_SNIc
  - model: V19_SNIcBL
  - model: V19_SNII
  - model: V19_SNIIb
  - model: V19_SNIIn
  - model: Cepheid
  - model: d-Scuti
  - model: Dwarf_nova
  - model: Mdwarf-flare

  # NON1ASED en desarrollo (OT, Ramirez+ 2024)
  - model: SNIax_NON1ASED
  - model: SNIa-91bg_NON1ASED
  - model: TDE_NON1ASED
  - model: SLSN-I_NON1ASED
  - model: KN-BULLA-BNS-M2COMP

  # --- Overrides por clase (opcional) ---
  # - model: SNIa
  #   ngen: 100000          # mas eventos para Ia

# --- Defaults globales (si un modelo no los define) ---
defaults:
  format_mask: 48              # FITS + RANDOM
  ranseed: 12945
  ngen_season: 0               # 0 = NGEN_LC (no por temporada)
  # SEARCHEFF: se deriva automaticamente del SIMLIB
  kcor_file: "${ALCES_REPO}/pipeline/kcor/kcor_LSST.fits"
  searcheff_pipeline_logic_file: "$SNDATA_ROOT/models/searcheff/SEARCHEFF_PIPELINE_LOGIC.DAT"
  searcheff_pipeline_file: "SEARCHEFF_PIPELINE_LSST.DAT"
  # PEAKMJD se calcula del SIMLIB range
  peakmjd_pad: 50              # dias de padding respecto al SIMLIB

# --- SLURM / submit_batch_jobs ---
batch:
  system: "SBATCH"
  partition: "general"
  walltime: "04:00:00"
  mem: "8G"
  ncores: 1
  snana_login_setup: |
    module load snana/11.05
    module load gsl/2.7
    export SNDATA_ROOT=$HOME/soft/SNDATA_ROOT
"""


INIT_CONTENTS = {}

INIT_CONTENTS['pipeline/__init__.py'] = """'''
Pipeline config-driven para simulaciones de curvas de luz (Vera C. Rubin / SNANA).
'''

__version__ = "0.1.0"

from .registry import Registry, OpSimRun, RegistryError  # noqa: F401

__all__ = ["Registry", "OpSimRun", "RegistryError", "__version__"]
"""

INIT_CONTENTS['pipeline/simlib/__init__.py'] = """'''Capa 1 — Constructor de SIMLIB parametrizado y version-agnostico.'''

from .config import SimlibConfig, StrategyConfig, TemporalCut  # noqa: F401
from .classify import ClassificationRules, classify_field_type  # noqa: F401
from .formatobs import format_obs  # noqa: F401
from .coverage import coverage_report, coverage_to_frame  # noqa: F401

__all__ = [
    "SimlibConfig", "StrategyConfig", "TemporalCut",
    "ClassificationRules", "classify_field_type",
    "format_obs", "coverage_report", "coverage_to_frame",
]
"""

INIT_CONTENTS['pipeline/campaign/__init__.py'] = """'''Capa 2 — Config declarativa de campanha y compilacion a .INPUT SNANA.'''

from .compiler import compile_campaign, CampaignPlan  # noqa: F401

__all__ = ["compile_campaign", "CampaignPlan"]
"""

INIT_CONTENTS['pipeline/orchestrate/__init__.py'] = """'''Capa 3 — Orquestacion: validacion, lanzamiento y monitoreo de campanhas SNANA.'''

from .preflight import preflight_check  # noqa: F401
from .launcher import launch_campaign   # noqa: F401
from .monitor import campaign_status    # noqa: F401

__all__ = ["preflight_check", "launch_campaign", "campaign_status"]
"""

INIT_CONTENTS['pipeline/postproc/__init__.py'] = """'''Capa 4 — Post-proceso: FITS -> tablas ML + control de calidad automatico.'''

from .converter import convert_genversion, read_head, read_phot  # noqa: F401
from .qc import run_all_qc  # noqa: F401

__all__ = ["convert_genversion", "read_head", "read_phot", "run_all_qc"]
"""

INIT_CONTENTS['pipeline/provenance/__init__.py'] = """'''Capa 5 — Procedencia: tagging, manifiesto y reproducibilidad de cada corrida.'''

from .tagger import RunTag, tag_run, collect_campaign_tags  # noqa: F401

__all__ = ["RunTag", "tag_run", "collect_campaign_tags"]
"""

# ============================================================
# ARCHIVOS .py DE LOGICA ESPERADOS POR CARPETA (no se auto-generan;
# deben venir de las carpetas Capa0..Capa5 originales)
# ============================================================

EXPECTED_PY = {
    "pipeline": [
        "paths.py", "registry.py", "fetch_opsim.py", "requirements.txt",
        "build_simlib.py",
        "compile_campaign.py",
        "run_campaign.py",
        "postprocess.py",
        "tag_campaign.py",
    ],
    "pipeline/simlib": [
        "classify.py", "config.py", "coverage.py",
        "formatobs.py", "hprep.py", "timeutil.py", "writer.py",
    ],
    "pipeline/campaign": [
        "compiler.py", "templates.py",
    ],
    "pipeline/orchestrate": [
        "preflight.py", "launcher.py", "monitor.py",
    ],
    "pipeline/postproc": [
        "converter.py", "qc.py",
    ],
    "pipeline/provenance": [
        "tagger.py", "environment.py",
    ],
    "tests": [
        "test_simlib_core.py",
    ],
}

SOURCE_HINT = {
    "pipeline": "Capa0 (paths/registry/fetch_opsim/requirements) + Capa1 (build_simlib) "
                "+ Capa2 (compile_campaign) + Capa3 (run_campaign) + Capa4 (postprocess) "
                "+ Capa5 (tag_campaign)",
    "pipeline/simlib": "Capa1",
    "pipeline/campaign": "Capa2",
    "pipeline/orchestrate": "Capa3",
    "pipeline/postproc": "Capa4",
    "pipeline/provenance": "Capa5",
    "tests": "Capa1",
}

print("PASO 1: Estructura de carpetas\n")
for d in list(EXPECTED_PY.keys()) + ["campaigns", "data/opsim"]:
    dp = HERE / d
    dp.mkdir(parents=True, exist_ok=True)
    print(f"  ok {d}/")

print("\nPASO 2: Reescribiendo __init__.py (siempre se sobrescriben)\n")
for path, content in INIT_CONTENTS.items():
    fp = HERE / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    print(f"  ok {path}")

print("\nPASO 3: Reescribiendo archivos de CONFIGURACION (YAML)\n")
for path, content in YAML_CONTENTS.items():
    fp = HERE / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    print(f"  ok {path}")

print("\nPASO 4: Verificando archivos de LOGICA (.py de cada capa)\n")
missing_py = []
for d, files in EXPECTED_PY.items():
    for f in files:
        fp = HERE / d / f
        if fp.exists():
            print(f"  ok {d}/{f}")
        else:
            print(f"  FALTA {d}/{f}  <- copiar desde {SOURCE_HINT[d]}")
            missing_py.append(f"{d}/{f}")

# gitignore
gi = HERE / "data" / "opsim" / ".gitignore"
if not gi.exists():
    gi.write_text("*.db\n*.db.part\n*.provenance.json\n", encoding="utf-8")
gi_root = HERE / ".gitignore"
if not gi_root.exists():
    gi_root.write_text(
        "__pycache__/\n*.pyc\ndist/\nbuild/\n"
        "data/opsim/*.db\ndata/opsim/*.db.part\ndata/simlib/\n"
        "pipeline/opsims.local.yaml\n.DS_Store\n",
        encoding="utf-8",
    )

print("\nPASO 5: Verificacion de import\n")
ok = True
try:
    for mod in list(sys.modules):
        if mod.startswith("pipeline"):
            del sys.modules[mod]
    sys.path.insert(0, str(HERE))
    from pipeline import __version__
    print(f"  ok import pipeline (v{__version__})")
except Exception as e:
    print(f"  FALLO import pipeline: {e}")
    ok = False

if missing_py:
    print(f"\n  Faltan {len(missing_py)} archivo(s) de logica (ver PASO 4 arriba).")
    print(f"  Copialos desde tus carpetas Capa# y vuelve a correr este script.")
    ok = False

if ok:
    print("\nPASO 6: Self-tests\n")
    import subprocess
    for name, mod in [
        ("Capa 1", "pipeline.build_simlib"),
        ("Capa 2", "pipeline.compile_campaign"),
        ("Capa 4", "pipeline.postprocess"),
        ("Capa 5", "pipeline.tag_campaign"),
    ]:
        try:
            r = subprocess.run(
                [sys.executable, "-m", mod, "--self-test"],
                capture_output=True, text=True, timeout=60, cwd=str(HERE),
            )
            lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
            last = lines[-1] if lines else ""
            if r.returncode == 0 and "OK" in last:
                print(f"  ok {name} self-test OK")
            else:
                print(f"  FALLO {name} (rc={r.returncode})")
                if r.stderr:
                    print("    " + r.stderr.strip()[:300].replace("\n", "\n    "))
                if lines:
                    print("    ultima linea:", last)
        except Exception as e:
            print(f"  FALLO {name}: {e}")

print()
print("=" * 66)
if ok:
    print("  Pipeline listo. Prueba: python -m pipeline.fetch_opsim --list")
else:
    print("  Quedan pasos pendientes (ver arriba).")
print("  Nota Windows: usa 'python', no 'python3'.")
print("=" * 66)