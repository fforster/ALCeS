# Cómo instalar y correr LightCurveLynx en una máquina local (sin NLHPC)

Instructivo práctico para instalar solo la parte de **generación de simulaciones +
automatización** de este proyecto en un computador propio — sin cuenta NLHPC, sin SLURM, sin
acceso a la campaña real de SNANA. Es un documento hermano de `HOWTO.md` (que sigue siendo la
referencia real del flujo en NLHPC) — este cubre el camino nuevo, validado de punta a punta en
Windows real en las Fases 74-77 (ver `NOTES.md` para el detalle de cada bug real encontrado y
corregido en el camino).

## 1. Qué incluye este camino, y qué NO

**Incluye**: los 3 scripts de producción (`run_simsed_poc.py`, `run_non1ased_poc.py`,
`run_snia_ddf_poc.py`), el sistema de sweeps sin SLURM (`sweep_run_local.py`), y el mecanismo para
agregar clases nuevas (`vendor_snana_class.py`) — es decir, todo lo necesario para **generar
datasets de simulación reales, en `parquet`, con historial reproducible (`run_hash.json`)**.

**NO incluye**:

- **La comparación contra SNANA** (Fases 0-73, cerrada) — necesita el `.DUMP`/FITS reales de una
  campaña ya corrida (decenas de GB, específicos de NLHPC). Ese camino sigue siendo exclusivo de
  NLHPC, documentado en `HOWTO.md`.
- **Las 16 clases del catálogo sin vendorizar todavía** — solo 3 clases piloto
  (`SNIa`/SALT2, `SNIa-91bg`, `PISN-STELLA-HECORE`) tienen datos empaquetados listos para usar acá.
  Agregar una clase nueva es un solo comando (sección 6), no requiere código nuevo.
- **Un conversor a formato de entrenamiento de ML ni una interfaz gráfica** — quedó identificado
  como pendiente en la reunión con el profesor, es una decisión aparte de "instalar esto
  localmente".

## 2. Requisitos reales (verificados, no supuestos)

- **Python 3.12 o 3.14** — probado en 3.14.6 en Windows nativo (Fase 77). NLHPC usa 3.12.3; no se
  encontró ninguna incompatibilidad real de código con 3.14, solo el gotcha de compilación de la
  sección 3.
- **~750MB libres de disco** solo para el `.db` de OpSim, más ~50-100MB para el bundle de datos +
  dependencias de Python. **Esto es real e insoslayable** — LightCurveLynx lee el `.db` de OpSim
  vía `sqlite3` directamente, no hay forma de generar simulaciones sin una copia local completa.
- **En Windows**: Visual Studio Build Tools (el compilador de C/C++, "Desktop development with
  C++") — `sncosmo` (dependencia dura de `lightcurvelynx`, no opcional) no publica wheels
  precompilados en PyPI, así que `pip` lo compila desde el código fuente en la instalación. En
  Linux/Mac esto normalmente no requiere nada adicional (`gcc`/`clang` ya suelen estar instalados).
- Acceso a internet (para el `.db` de OpSim, público, y el bundle de datos de clases — ver sección
  4).

## 3. Instalar las dependencias de Python

```bash
git clone https://github.com/mauriciovalenzuela742/ALCeS.git
cd ALCeS/exploration/lightcurvelynx
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Gotcha real de Windows (encontrado y corregido en Fase 77)

Si `pip install` falla compilando `sncosmo` con el error `Unable to find a compatible Visual
Studio installation` **pese a tener Visual Studio Build Tools instalado con el compilador real**,
la causa no es que falte el compilador — es que `vswhere.exe` (la herramienta que usa
`vcvarsall.bat` para auto-detectarse) no está en el `PATH` del proceso que corre `pip`. El fix es
agregarlo al `PATH` antes de instalar:

```powershell
$env:PATH = "C:\Program Files (x86)\Microsoft Visual Studio\Installer;$env:PATH"
pip install -r requirements.txt
```

(la ruta exacta puede variar si Visual Studio está instalado en otro lado — buscar
`vswhere.exe` con `Get-ChildItem -Recurse -Filter vswhere.exe "C:\Program Files*"` si el `pip
install` sigue fallando después de este fix).

Verificar la instalación:

```bash
python3 -c "import lightcurvelynx, sncosmo, pandas, pyarrow, matplotlib, yaml; print('OK')"
```

## 4. Descargar los datos de las clases piloto

Tres clases ya tienen sus plantillas SED reales de SNANA empaquetadas (ver `NOTES.md` Fase 75 para
cómo se generaron con `vendor_snana_class.py`): `SNIa` (SALT2), `SNIa-91bg` (SIMSED), y
`PISN-STELLA-HECORE` (SIMSED). Pedir el bundle de datos a quien tenga acceso a NLHPC (`ssh nlhpc`)
— **no se distribuye por git** (son datos de configuración de SNANA, no código, ver
`.gitignore`):

```
lightcurvelynx_local_data_pilot.zip   (~35MB) -- extraer DENTRO de exploration/lightcurvelynx/
run_SNANA_pilot.zip                   (~2KB)  -- extraer en el HOME del usuario
```

```bash
cd exploration/lightcurvelynx
unzip lightcurvelynx_local_data_pilot.zip -d .
unzip run_SNANA_pilot.zip -d ~
```

(Si tienes `ALCES_DATA` definida, extrae `run_SNANA_pilot.zip` ahí y no en `~`: los scripts
buscan `run_SNANA/` en `$ALCES_DATA` y, si no está definida, en tu home. Ver `INSTALL.md` §2.5.)

Verificar que quedaron 3 carpetas `*_local/` no vacías: `salt2_h17_local/`, `simsed_91bg_local/`,
`simsed_pisnstellahecore_local/`, y `~/run_SNANA/{LSST_SEARCHEFF_PIPELINE.DAT,
LSST_PIPELINE_LOGIC.DAT}`.

Si el disco de esta máquina tiene poco espacio libre (menos de ~1GB), **no** dejar el bundle `.zip`
descargado después de extraerlo — no hace falta conservarlo, se puede volver a pedir.

## 5. Descargar el OpSim real (público, sin cuenta NLHPC)

```bash
python -m pipeline.fetch_opsim --run baseline_v5.3.1_10yrs
```

~709MB, descarga directa desde `s3df.slac.stanford.edu` (público). Si la conexión se corta a
mitad de camino, **el script retoma solo desde donde quedó** (deja un archivo `.db.part`) — basta
con volver a correr el mismo comando.

Nota real de Windows (Fase 77): si el proceso termina con `UnicodeEncodeError` al imprimir un
`✓` justo después de confirmar el hash, **el archivo ya se descargó y verificó completo** — el
error es solo de la consola (`cp1252` no puede imprimir ese carácter), no del archivo. Para
evitarlo, correr con `PYTHONIOENCODING=utf-8` seteado antes.

## 6. Probar el mecanismo con un smoke test (paso de confianza, no opcional la primera vez)

```bash
cd exploration/lightcurvelynx
python3 sweep_run_local.py sweeps/_smoke_local.yaml
```

Compila el sweep (`sweep_compile.py`, sin SLURM), corre las 2 corridas piloto en paralelo real vía
`ProcessPoolExecutor` (no `sbatch`), y termina con `status=done` en `run_hash.json` para ambas si
todo está bien instalado. Confirmar con:

```bash
python3 sweep_monitor.py _smoke_local     # debe decir "resumen: done=2"
```

Este paso confirma que el venv, los datos de la sección 4 y el `.db` de la sección 5 están todos
bien colocados **antes** de gastar cómputo real en un barrido grande.

## 7. Correr un barrido real

Copiar `sweeps/_smoke_local.yaml` como plantilla, cambiar `classes`/`ngentot_overrides` a lo que se
necesite (solo las 3 clases piloto tienen datos disponibles — ver sección 8 para agregar otra), y
correr:

```bash
python3 sweep_run_local.py sweeps/<mi_barrido>.yaml --workers N
```

`--workers N` limita cuántas corridas van en paralelo (por defecto usa `max_concurrent` del YAML)
— en un laptop, `N` = número de núcleos reales, no más. Igual que en NLHPC (`HOWTO.md` sección
5-bis), seguir con:

```bash
python3 sweep_monitor.py <mi_barrido>       # progreso, repetir hasta done=N
python3 sweep_aggregate.py <mi_barrido>     # consolida el parquet final
```

La salida (`sweep_runs/<mi_barrido>/runs/<hash>/`) tiene exactamente el mismo formato que en
NLHPC: `head_df.parquet`/`phot_df.parquet`/`summary.json`/`qc/*.png` + `run_hash.json` con la
procedencia real (`code_hash`, timestamps — sin `slurm_job_id`, que queda `null` en corridas
locales).

## 8. Agregar una clase nueva

Cada clase adicional del catálogo (16 de 19 no vendorizadas todavía) requiere un acceso puntual a
NLHPC (una sola vez por clase, no por corrida) para empaquetar sus templates reales:

```bash
ssh nlhpc
cd ~/AUTOSIM/exploration/lightcurvelynx
python3 vendor_snana_class.py <clase>          # o --salt2 / --searcheff según el caso
```

Esto genera `<clase>_local/` en NLHPC — empaquetarlo (`zip -r`) y traerlo a la máquina local, igual
que el bundle de la sección 4. No requiere escribir código nuevo — mismo mecanismo que ya empaquetó
las 3 clases piloto (`NOTES.md` Fase 75).

## 9. Para profundizar

- `HOWTO.md` — el flujo real de NLHPC (SLURM, la comparación contra SNANA, todas las 19 clases).
- `NOTES.md`, Fases 74-77 — el detalle real de cada decisión y cada bug encontrado portando esto:
  `local_env.py` (portabilidad de rutas), `vendor_snana_class.py` (datos), `sweep_run_local.py`
  (sin SLURM), y la validación real en Windows (2 bugs encontrados corriendo, no supuestos: el
  `PATH` de `vswhere.exe`, y `OPSIM_DB` de `run_simsed_poc.py`).
- `docs/index.html`, pestaña "06 LightCurveLynx" — el resumen curado, con las fases 74-77
  explicadas en una línea cada una.
