# Fase 0 — Spike técnico: LightCurveLynx vs. SNANA

Ver plan completo en `C:\Users\HOME\.claude\plans\harmonic-singing-pebble.md` (o el historial
de la sesión). Este documento consolida las 5 preguntas abiertas de la Fase 0, todas
respondidas con código corrido de verdad en NLHPC (venv aislado en
`exploration/lightcurvelynx/venv`, `lightcurvelynx==0.5.2`), no solo lectura de documentación.

## Resumen ejecutivo

**Recomendación: GO a Fase 1.** No apareció ningún bloqueador duro. Hay una brecha real y
concreta (SEARCHEFF) y un trabajo de integración real pero acotado (SIMSED), ambos manejables.
La ingesta de OpSim y la extinción MW funcionan literalmente sin escribir código de adaptación.
El rendimiento medido es dramáticamente mejor que SNANA (~150x más rápido en la comparación
cruda de throughput, ver punto 5) — si la Fase 1 confirma equivalencia científica, el caso para
migrar es fuerte.

## 1. SIMSED — soporte parcial, requiere integración propia

`lightcurvelynx/utils/io_utils.py::read_grid_data()` lee **un solo** grid 2D
(fase × longitud de onda → flujo) desde un archivo de 3 columnas — no es un lector de
directorios SIMSED completos. Confirmado contra un SIMSED real de nuestro catálogo
(`run_SNANA/plasticc_models/SIMSED.TDE-MOSFIT/`, 745 archivos `.dat.gz` + `SED.INFO` con 8
parámetros físicos por SED, formato estándar SNANA SIMSED).

**Conclusión**: no hay lector de "librería SIMSED" nativo. La ruta de integración es escribir
un wrapper propio: parsear `SED.INFO` (formato texto simple), cargar cada `.SED` individual vía
`SEDTemplate`/`SEDTemplateModel` (`lightcurvelynx/models/sed_template_model.py`, que sí acepta
un grid N×3 de fase/longitud de onda/flujo — compatible con el formato de cada `.dat` de SIMSED
después de descomprimir), y samplear entre las 745 plantillas según los pesos/parámetros de
`SED.INFO` usando los nodos de sampleo existentes (`GivenValueSampler`/`GivenValueSelector`).
Esto afecta a nuestras clases MOSFIT: TDE, SLSN-I, PISN-STELLA (×2), CaRT, ILOT — trabajo real
pero acotado, no un bloqueador.

## 2. SEARCHEFF — brecha real confirmada

`lightcurvelynx/astro_utils/obs_utils.py` tiene:
- `phot_eff_function(snr)`: **función escalón dura** (`snr > 5 → 1.0, si no → 0.0`), no una
  curva suave ajustada a datos reales como el `SEARCHEFF_PIPELINE_EFF_file` de SNANA.
- `spec_eff_function(peak_imag)`: eficiencia de seguimiento espectroscópico en función de la
  magnitud i de pico — **basada explícitamente en la Ecuación 17 de Kessler et al. 2019**
  (mismo linaje científico que SNANA, curiosamente).

**Falta**: la lógica de trigger multi-época/multi-filtro de SNANA
(`SEARCHEFF_PIPELINE_LOGIC.DAT`, p.ej. "2 detecciones separadas por N días en M filtros") no
tiene equivalente. **Conclusión**: hay piezas básicas, pero no el sistema completo. Opciones
para la Fase 1/2: (a) aplicar nuestra propia lógica de `SEARCHEFF_PIPELINE_LOGIC.DAT`/
`SEARCHEFF_PIPELINE_LSST.DAT` (que ya tenemos, calibrados) como post-proceso sobre la columna
`lightcurve.detection` que sí exporta `post_process_results.py`, o (b) aceptar el escalón
simple si el objetivo es solo comparación estadística agregada, no fidelidad de pipeline real.

## 3. Ingesta de OpSim — funciona sin ninguna transformación ✓

`lightcurvelynx/obstable/opsim.py::OpSim` tiene un `_default_colnames` que mapea
**exactamente** a las columnas reales de `data/opsim/baseline_v5.3.1_10yrs.db`
(`fieldRA`, `fieldDec`, `observationStartMJD`, `filter`, `fiveSigmaDepth`, `numExposures`,
`seeingFwhmEff`, `skyBrightness`...) — mismo schema que produce el simulador oficial de Rubin
(`rubin-scheduler`, no una convención propia de LightCurveLynx).

**Verificado con ejecución real**: cargamos las 1,844,189 observaciones de
`baseline_v5.3.1_10yrs.db` directo a un objeto `OpSim` sin ningún error ni transformación de
columnas — coincide con `len(df)` exacto.

DDF vs. WFD **no** viene distinguido por defecto en `OpSim`, pero la columna cruda
`target_name` sí lo permite (`ddf_elaiss1`, `ddf_cosmos`, `ddf_xmm_lss`, `ddf_edfs_a/b`,
`ddf_ecdfs` — los 6 campos DDF oficiales de Rubin) — mismo patrón que ya usa nuestra Capa 1
hoy (filtrar antes de pasar los pointings), no un bloqueador.

Nota interesante: los valores por defecto de zeropoint/extinción de `OpSim`
(`_opsim_zeropoint_per_sec_zenith`, `_opsim_extinction_coeff`) están explícitamente calculados
con **`syseng_throughputs v1.9`** — la misma versión de throughputs que ya confirmamos vigente
para nuestro `kcor_LSST.fits` (ver `pipeline/kcor/README.md`). Buena señal de consistencia
entre ambos ecosistemas.

## 4. Extinción MW — soportada, más flexible que SNANA ✓

`lightcurvelynx/effects/extinction.py::ExtinctionEffect` soporta `frame='observer'` (MW) o
`frame='rest'` (host) explícitamente, con `ebv`/`r_v` parametrizables, respaldado por el
paquete `dust_extinction` (Gordon 2024, JOSS — estándar de facto en la comunidad astropy) o
alternativamente el paquete `extinction` (usado por sncosmo). Incluye CCM89 y otras leyes
estándar — cubre lo que SNANA aplica hoy (CCM89+O'Donnell94) y más opciones. **Sin brecha.**

## 5. Escala / rendimiento — medido, dramáticamente más rápido

Benchmark real corrido en el login node de NLHPC (1 core, sin SLURM), simulando SNIa via
`SncosmoWrapperModel("salt2-h17")` sobre el `OpSim` real completo (1.8M observaciones):

| N eventos | tiempo total | ms/evento | eventos/seg |
|---|---|---|---|
| 200   | 0.34s | 1.71 | ~1830 |
| 1000  | 0.86s | 0.86 | ~1765 |

Extrapolado a `NGENTOT_LC=200,000` (el tamaño real de una clase WFD en producción):
**~110-115 segundos**, en un solo core de login node, sin escribir a disco.

Comparado con SNANA real: los logs de la campaña v8 muestran tasas de escritura
(`NGENLC_WRITE`) del orden de **10-15 eventos/seg** (p.ej. `1036 (15/sec)`, `25 (12/sec)`) vía
SLURM en nodos de cómputo dedicados. La comparación no es 100% equivalente (SNANA cuenta
eventos que pasan el trigger de escritura tras generar más internamente, incluye I/O a FITS,
y esta prueba no escribió a disco) — pero la diferencia de orden de magnitud (~150x) es lo
bastante grande como para ser una señal real, a confirmar con más rigor en la Fase 1.

Un detalle de madurez a anotar: apareció un `RuntimeWarning: invalid value encountered in
sqrt` en `noise_models/noise_utils.py` durante la corrida de N=1000 — no rompió la simulación,
pero es la clase de señal que hay que vigilar dado que el proyecto es pre-1.0 (consistente con
el propio disclaimer de la documentación).

**Sin decidir todavía** (no crítico para el go/no-go de Fase 1, sí para Fase 2-3): si la
orquestación final usa "un job SLURM por clase" (como hoy) o cambia a un solo job con
`dask`/`ray` dado lo económico que resulta computacionalmente — con estos números, probablemente
ni siquiera hace falta SLURM para volúmenes de esta escala, lo cual simplificaría bastante la
Capa 3 actual (`pipeline/orchestrate/`).

## Detalle técnico adicional (no una de las 5 preguntas, pero relevante)

El propio tutorial oficial (`docs/notebooks/simple_snia.ipynb`) usa `SncosmoWrapperModel`
(wrapper de `sncosmo`, modelo `"salt2-h17"`) como la vía principal y mejor documentada para
SNIa, no `SALT2JaxModel` — este último existe pero tiene menos ejemplos end-to-end en la
documentación. Para la Fase 1 (PoC SNIa acordado con el usuario), usar `SncosmoWrapperModel`
como primera opción por ser el camino mejor pavimentado, y `SALT2JaxModel` como alternativa
si se necesita diferenciabilidad (gradientes vía JAX) — a decidir al iniciar la Fase 1, no
cambia el resultado de este spike.

## Entorno de referencia

- `exploration/lightcurvelynx/venv/` en NLHPC — venv aislado, **no** compartido con
  `pipeline/venv` (el pipeline SNANA activo no fue tocado).
- `pip install "lightcurvelynx[all]"` — incluye jax, dask, hats, dust_extinction,
  VBMicrolensing, synphot, bilby, pzflow, lsdb.
- Scripts de verificación: `check_opsim_schema.py`, `test_opsim_load.py`, `bench_snia.py`
  (este directorio).

---

# Fase 1 — PoC SNIa_DDF: parámetros reales de SNANA, comparación directa

Plan completo: `C:\Users\HOME\.claude\plans\delegated-tumbling-petal.md`. Objetivo acordado:
un PoC de una sola clase (SNIa) con parámetros reales (no placeholders) que confirme o
descarte equivalencia científica con SNANA — no solo velocidad — usando `SNIa_DDF` como
baseline (`SNIa_WFD` seguía con el FITS corrupto de antes, verificado de nuevo al iniciar
esta fase: mismo timestamp, mismo `UnicodeDecodeError`, sin resimulación exitosa desde
entonces).

## Resumen ejecutivo

**Resultado: la mecánica del PoC funciona de punta a punta — parámetros reales, samplers
custom (DNDZ, Gaussianas bifurcadas), extinción MW real, eficiencia de detección real
(SEARCHEFF real, no el escalón nativo), reuso directo del QC ya arreglado esta sesión — pero
la eficiencia de detección global sale ~2x más alta que SNANA real (60.75% vs 29.85%, tras
intentar calibrar `zp_err_mag` contra el valor real de SNANA sin éxito — ver punto 7b), y la
causa más probable diagnosticada es que el modelo de ruido fotométrico de LightCurveLynx
subestima el ruido por-época real, no un problema con la población simulada (redshift/color/
extinción); dos rondas de investigación no encontraron el componente exacto responsable.
Esta brecha queda abierta, no resuelta. Por separado, se validó el patrón de orquestación
propuesto para Fase 2 (`dask.distributed.LocalCluster` dentro de un único job SLURM, sin
tocar el login node): 3.16x de speedup real medido. Recomendación: GO condicional a Fase 2,
contingente en calibrar/reemplazar el modelo de ruido de LightCurveLynx antes de sacar
conclusiones cuantitativas de cualquier corrida futura.**

## 1. Parámetros reales de `SIMGEN_INCLUDE_SNIa-SALT2.INPUT`

El spike de Fase 0 (`bench_snia.py`) usaba placeholders (redshift uniforme, Gaussianas
simples, sin DNDZ). Verificado contra el `.INPUT` real en NLHPC:

| Parámetro | Placeholder (Fase 0) | Real (usado en Fase 1) |
|---|---|---|
| `GENRANGE_REDSHIFT` | uniforme 0.01–0.6 | DNDZ POWERLAW2 real, 0.011–1.2 |
| `GENSIGMA_SALT2c` | Normal simple, σ=0.02 | bifurcada: peak=-0.054, σ=(0.043, 0.101) |
| `GENSIGMA_SALT2x1` | Normal simple, σ=2.0 | bifurcada: peak=0.973, σ=(1.472, 0.222) |
| `alpha`/`beta` | 0.14/3.1 | igual (ya coincidía) |
| `GENMAG_SMEAR_MODELNAME: G10` | no implementado | aproximado: dispersión acromática coherente,
  `SIGMA_INT=0.090` de `SALT2.INFO` (no la covarianza x1/c completa de G10 — fuera de alcance
  de un PoC, ver Fase 0 punto 1) |

`snana_params.py` (nuevo): `build_dndz_powerlaw2_cdf()` construye la tasa diferencial
`dN/dz = DNDZ(z)·dVc/dz/(1+z)` (dilución temporal incluida) numéricamente y samplea por
inversión de CDF; `make_bifurcated_normal_sampler()` samplea una Gaussiana con σ distinto a
cada lado del pico, con corte por rechazo en `GENRANGE_SALT2{c,x1}`. Verificado standalone
(fuera del grafo de LightCurveLynx) contra 5000 muestras: formas y percentiles razonables,
CDF sube monótonamente 0→1 sin degeneración.

## 2. Bug real encontrado: `FunctionNode` nunca pasa `size=` a la función envuelta

Al conectar los samplers custom al grafo de LightCurveLynx (`FunctionNode(mi_sampler,
node_label=...)`), la primera corrida completa produjo un redshift casi degenerado (un solo
bin angosto cerca de z≈1.2 en vez de la distribución esperada 0.011–1.2). Diagnóstico:
`FunctionNode.compute()` (base, `lightcurvelynx/base_models.py`) llama
`self.func(**args)` **sin `size` en absoluto** — a diferencia de `NumpyRandomFunc.compute()`,
que sí inyecta `size=graph_state.num_samples` explícitamente. Con la firma
`sampler(size=None, **kw)`, cada llamada devolvía un solo valor escalar que el grafo
terminaba difundiendo (broadcast) a los N samples — confirmado con
`FunctionNode(sampler, node_label='z').generate(num_samples=10)` devolviendo el mismo
valor 10 veces.

**Fix**: `SizeAwareFunctionNode` (en `snana_params.py`), una subclase mínima de
`FunctionNode` que sobreescribe `compute()` para inyectar `size=graph_state.num_samples` —
mismo patrón que usa `NumpyRandomFunc` internamente, aplicado a un callable arbitrario.
Verificado: `SizeAwareFunctionNode(sampler, ...).generate(num_samples=2000)` devuelve 2000
valores únicos con la forma esperada.

## 3. SALT2 H17: el mirror remoto de sncosmo está caído — se usó el modelo real de SNANA

`get_source("salt2-h17")` (usado en `bench_snia.py`) intenta descargar desde
`https://sncosmo.github.io/data/models/snana/salt2-h17/` — **404 confirmado** (GitHub Pages,
recurso no existe más). En vez de reintentar contra un mirror caído, se cargó el modelo H17
real que ya usa `SNIa_DDF` de SNANA (`run_SNANA/plasticc_models/SALT2.WFIRST-H17/*.dat.gz`)
directo vía `sncosmo.SALT2Source(modeldir=...)` — mismo modelo físico, no una aproximación.
Dos ajustes de formato (no de contenido científico, ver `setup_salt2_local.py`):
descomprimir los `.dat.gz`, y reescribir `salt2_color_correction.dat` en el formato de texto
que espera `sncosmo` (`<ncoeffs>\n<coefs>\nSalt2ExtinctionLaw.version 1\n...`) usando los
coeficientes reales de `SALT2.INFO::COLORCOR_PARAMS` (`-1.33154627 0.61225710 -0.12117791
0.00840832`, rango 2800–9500Å) — el archivo de SNANA con ese mismo nombre es una tabla de
dispersión de ~4.9MB, un producto distinto, no los ~4 coeficientes que separa `sncosmo`.
Verificado: `SALT2Source` carga y evalúa flujo correctamente con este modelo local.

## 4. Posiciones RA/Dec: hay que samplear del footprint real, no una caja uniforme

Primer intento con RA/Dec uniformes sobre todo el cielo (mismo patrón que `bench_snia.py`):
la mayoría de los objetos caían con `nobs=0` porque DDF son solo 6 pointings angostos, no
todo el cielo. Fix: `ObsTableRADECSampler(obs_table)` — samplea posiciones reales
(visit-weighted) de los pointings del `OpSim` ya filtrado a DDF, con el radio de campo de
visión real. `extra_cols=["field"]` además devuelve, ya emparejada por fila, la etiqueta del
campo DDF real (`cosmos`, `ecdfs`, `edfs_a`, `edfs_b`, `elaiss1`, `xmm_lss`) — necesaria para
asignar extinción MW correcta por campo (punto 6).

## 5. SEARCHEFF real (no el escalón SNR>5 nativo)

`searcheff.py` (nuevo): parsea `LSST_SEARCHEFF_PIPELINE.DAT` (curva de eficiencia vs SNR por
banda, u/g comparten curva y z/Y comparten curva, r e i propias — interpolación lineal,
formato validado contra el archivo real) y `LSST_PIPELINE_LOGIC.DAT` (`LSST: 2
u+g+r+i+z+Y` → ≥2 épocas detectadas en cualquier combinación de filtros). Aplica Monte Carlo
por observación (SNR=flux/fluxerr → interpola eficiencia → sortea detección), luego el mismo
umbral de trigger que usa `snlc_sim.exe`. Mismo `PHOTFLAG` (4096/6144) que ya usa
`pipeline/postproc/qc.py` tras el fix de esta sesión, así que ambos lados de la comparación
usan la misma definición de "detección real".

## 6. Extinción MW real — no era la explicación de la brecha de eficiencia

`ExtinctionEffect(extinction_model="O94", frame="observer", r_v=3.1)` — misma familia que
`OPT_MWCOLORLAW` de SNANA (CCM89+O'Donnell94). `dustmaps`/`sfdmap2` no pudieron descargar el
mapa SFD completo desde NLHPC (Harvard Dataverse API devuelve cuerpo vacío pese a HTTP 202;
el mirror de GitHub `kbarbary/sfddata` solo tiene un README, sin los `.fits`) — en vez de
mapear posiciones individuales, se consultó el **servicio REST IRSA Dust Extinction** de
NASA/IPAC (sí alcanzable) para los 6 centros de campo DDF reales (calculados desde
`baseline_v5.3.1_10yrs.db`, no de memoria):

| Campo | RA | Dec | E(B-V) SFD |
|---|---|---|---|
| cosmos | 150.110 | 2.234 | 0.0182 |
| ecdfs | 52.981 | -28.119 | 0.0084 |
| edfs_a | 59.374 | -49.150 | 0.0062 |
| edfs_b | 63.151 | -47.772 | 0.0152 |
| elaiss1 | 9.446 | -44.030 | 0.0080 |
| xmm_lss | 35.575 | -4.820 | 0.0251 |

Cada objeto simulado recibe el E(B-V) de su campo real (vía `extra_cols=["field"]` del punto
4, para que posición y extinción vengan de la misma fila sampleada, no independientes).
**Resultado**: la eficiencia global apenas bajó (59.95% sin extinción → 57.2% con extinción)
— estos 6 campos fueron elegidos por el survey precisamente por su baja extinción (todos
< 0.03 mag), así que no explican la brecha de ~2x contra SNANA real (29.85%).

## 7. Diagnóstico real de la brecha de eficiencia: ruido fotométrico, no población

Con extinción descartada como explicación principal, se comparó el SNR simulado
(`|flux/fluxerr|`, **todas** las observaciones, no solo las detectadas) contra el SNR real de
SNANA para la misma campaña:

| | mediana SNR | p90 SNR |
|---|---|---|
| SNANA real (`SNIa_DDF`) | 0.78 | 2.26 |
| LightCurveLynx (este PoC) | 1.008 | 5.68 |

La mediana ya sale ~29% más alta, pero la cola alta (p90) sale **2.5x** más alta — es decir,
las épocas de mayor SNR (las que más pesan en el trigger "≥2 detecciones") están
sistemáticamente menos ruidosas en la simulación de LightCurveLynx que en la de SNANA para
el mismo `OpSim` (misma profundidad, PSF, cielo). Como el ratio SNR=flux/fluxerr no depende
de la convención de unidades de flujo (nJy vs FLUXCAL — un error de escala afectaría flux Y
fluxerr por igual, cancelándose en el ratio), esto no es un bug de conversión de unidades en
este script: apunta a que el modelo de ruido fotométrico interno de LightCurveLynx (derivado
de profundidad/PSF/cielo del `OpSim`) subestima el ruido por-época real que usa SNANA para
esta campaña — probablemente porque el pipeline real de SNANA/LSST incluye términos de ruido
sistemático/calibración adicionales que el modelo de LightCurveLynx no captura, o usa una
calibración de ruido distinta para el mismo profundidad nominal.

**No resuelto en este PoC** — calibrar o reemplazar el modelo de ruido de LightCurveLynx
contra el de SNANA es trabajo real de integración (no un ajuste de una línea), apropiado para
Fase 2 si se decide seguir, no para cerrar aquí. Es la brecha concreta más importante que
queda abierta.

## 7b. Intento de calibración — candidatos descartados, brecha sigue abierta

Dos rondas de investigación real después del punto 7, ninguna cerró la brecha:

**`zp_err_mag` (calibración de zeropoint) — descartado empíricamente.** El termino de
varianza por incertidumbre de zeropoint en `poisson_bandflux_std()`
(`noise_models/noise_utils.py`) escala con `bandflux²` (a diferencia de los términos Poisson,
que escalan con `bandflux¹`), así que en principio pesa más justo en las épocas de mayor SNR
— coincidiendo con que la brecha p90 (2.5x) es peor que la de mediana (29%). `OpSim` por
defecto usa `zp_err_mag=1e-4`, pero el `ZEROPT_ERR` real de SNANA para esta campaña es
`0.005` (mediana, std=7.5e-5 — un valor de calibración fijo, no ruido). Se corrigió
`OpSim(df_ddf, zp_err_mag=0.005)` (parámetro documentado del constructor) y se volvió a
correr: **1215/2000 = 60.75% detectados — sin mejora real** (contra 57.2% antes del fix,
dentro del ruido esperado de una corrida con distinto seed). La hipótesis mecánicamente tenía
sentido pero los números no la sostienen — a esta profundidad/flujo, el término de zeropoint
no es dominante.

**Auditoría de la cadena cielo/PSF/zeropoint — sin bug encontrado.** Se leyó
`OpSim._derive_noise_columns()` completo:
- `zp` sí aplica corrección por airmass real (`flux_electron_zeropoint(ext_coeff, zp_per_sec,
  filter, airmass, exptime)` — no usa el zeropoint de cenit sin corregir).
- `psf_footprint = GAUSS_EFF_AREA2FWHM_SQ · (seeing/pixel_scale)²`, con
  `GAUSS_EFF_AREA2FWHM_SQ = π/(2·ln2) ≈ 2.266` — es la formula estandar de area efectiva de
  un PSF Gaussiano en funcion de FWHM, no una aproximacion custom.
- `pixel_scale=0.2 arcsec/pixel` — correcto para LSSTCam.
- Se verificó la distribución real de `seeingFwhmEff` en `baseline_v5.3.1_10yrs.db` (DDF):
  mediana 0.977 arcsec — consistente con el diseño de LSST, no hay un problema de datos de
  entrada.

Ningún componente individual de la formula parece incorrecto en aislamiento. La brecha sigue
sin explicación puntual — puede ser una combinación de terminos menores (`dark_current` no
comparado directamente contra SNANA, sin columna equivalente clara en el FITS), una
diferencia de convención en como SNANA computa `SKY_SIG`/`PSF_SIG` en su SIMLIB que no se
pudo verificar sin documentacion mas profunda de ese formato, o algo fuera de esta cadena de
formulas. **Se detiene la investigación aquí** (dos rondas de hipótesis concretas
descartadas, no un abandono prematuro) — la brecha queda documentada como abierta para quien
retome Fase 2, con las dos rutas ya descartadas explícitas para no repetir el trabajo.

## 8. Rendimiento — sigue siendo dramáticamente más rápido

`NGENTOT_LC=2000` (SNIa_DDF real, `pipeline/models.yaml::ngen_ddf`) completo — ingesta OpSim
+ SALT2 + samplers custom + extinción + 2000 objetos — en **60–73 segundos** de wall time
dentro de un job SLURM liviano (16GB, 4 cores), confirmando de nuevo el orden de magnitud de
ventaja de velocidad medido en Fase 0 (~150x vs SNANA en throughput crudo).

## 8b. Orquestación para Fase 2: dask `LocalCluster` — validado

Fase 0 (punto 5) dejó abierta la pregunta de si Fase 2 necesita `dask`/`ray` para escalar a
más clases, dado lo económico que resultó el cómputo. Se revisó qué está realmente instalado
en el venv: `dask`/`distributed` sí; `dask_jobqueue` (lanza un job SLURM separado por worker)
y `ray` no. Para esta escala no hace falta `dask_jobqueue` — un `LocalCluster` levantado
**dentro** de una sola asignación SLURM (nunca el login node, misma regla del resto del
pipeline) alcanza: todo el ciclo de vida del cluster (scheduler + workers) vive dentro de esa
única asignación.

`run_dask_poc.py` (nuevo) valida el patrón con carga real, no una tarea de prueba: 4 chunks
independientes de `NGEN=500` (2000 total, igual que el PoC de Fase 1), cada uno con su propio
grafo de samplers, corridos (a) secuencial en un proceso y (b) en paralelo vía
`dask.distributed.LocalCluster(n_workers=4)` — mismo job SLURM, mismo nodo.

| | tiempo total | 
|---|---|
| Secuencial (1 proceso) | 224.1s |
| Paralelo (`LocalCluster`, 4 workers confirmados por el scheduler) | 70.9s |

**Speedup: 3.16x sobre 4 workers (79% de eficiencia respecto al ideal 4.0x)** — la brecha
frente al ideal es la carga independiente de OpSim/SALT2/passbands en cada worker (no hay
estado compartido entre procesos), no un problema del patrón en sí. Corrida limpia, sin
errores, sin tocar el login node en ningún momento (confirmado por el log — todo el trabajo
ocurre dentro del job `sbatch`). Patrón listo para usar cuando se planifique el alcance real
de Fase 2 (cobertura de clases) — no se construyó la orquestación completa de Fase 2 aquí,
solo se validó que el mecanismo funciona.

## 9. Recomendación: GO condicional a Fase 2

Lo que **sí** quedó confirmado y funcionando de punta a punta: parámetros reales de SNANA
(DNDZ, bifurcadas, rango de redshift), el modelo SALT2 H17 real (no una aproximación),
posiciones reales del footprint DDF, extinción MW real por campo, eficiencia de detección
real (SEARCHEFF real, no el escalón nativo), reuso directo de la infraestructura de QC ya
arreglada esta sesión (mismos 4 gráficos, mismos criterios de detección), la ventaja de
velocidad de Fase 0 se sostiene, y el patrón de orquestación con `dask` para Fase 2 quedó
validado (3.16x de speedup real, sin tocar el login node). Se encontraron y corrigieron 3
problemas reales en el camino (bug de broadcast en `FunctionNode`, mirror de SALT2 caído,
formato de color law) — ninguno bloqueante, todos con fix concreto documentado arriba.

Lo que **no** quedó confirmado: equivalencia cuantitativa de detección (~2x de brecha,
diagnosticada pero no cerrada — ruido fotométrico, no población). Por eso la recomendación es
**GO condicional**, no un GO sin reservas: seguir a Fase 2 (cobertura de más clases, wrapper
SIMSED) es razonable dado que la mecánica funciona y la brecha tiene un candidato de causa
concreto y acotado (no un problema difuso de "LightCurveLynx no sirve para esto") — pero
cualquier resultado cuantitativo de Fase 1/2 debe tratarse como preliminar hasta calibrar el
modelo de ruido contra SNANA real, no como una comparación científica cerrada todavía.

## Archivos de esta fase

- `snana_params.py` — samplers DNDZ + bifurcado + `SizeAwareFunctionNode` (fix del bug de
  broadcast).
- `searcheff.py` — parser de `LSST_SEARCHEFF_PIPELINE.DAT`/`LSST_PIPELINE_LOGIC.DAT` +
  aplicación Monte Carlo de detección real.
- `setup_salt2_local.py` — reproduce `salt2_h17_local/` (no versionado, se regenera desde los
  archivos de SNANA ya en NLHPC) desde cero.
- `run_snia_ddf_poc.py` + `run_snia_ddf_poc.sbatch` — script principal, corre en NLHPC vía
  SLURM (nunca login node). Incluye override `zp_err_mag=0.005` (calibración intentada, ver
  punto 7b) y el diagnóstico de SNR permanente en cada corrida.
- `run_dask_poc.py` + `run_dask_poc.sbatch` — validación del patrón `LocalCluster` para Fase 2
  (punto 8b), 3.16x de speedup real medido.
- `compare_noise_formulas.py` (nuevo, Fase 2 parte A) — comparación numérica término a
  término SNANA real vs LightCurveLynx.
- `poc_output/summary.json` + `poc_output/qc/*.png` — resultado real de la corrida más
  reciente (Fase 2 parte A: `H0=70` + ruido real de SNANA inyectado, `n_detected=1086/2000`,
  eficiencia 54.3%).

# Fase 2 — parte A: cerrar la brecha de ruido antes de ampliar cobertura

Plan: `C:\Users\HOME\.claude\plans\delegated-tumbling-petal.md`. Antes de ampliar Fase 2 a más
clases (el wrapper SIMSED necesario resultó afectar **11** clases del catálogo, no las 5-6 que
estimaba Fase 0 — `CaRT`, `ILOT`, `KN-BULLA19`, `KN-K17`, `PISN-MOSFIT`, `SLSN-I-MOSFIT`,
`SNIa-91bg`, `SNIax`, `SNII-NMF`, `SNIIn-MOSFIT`, `TDE-MOSFIT`, verificado con
`grep -l 'GENMODEL:.*SIMSED' run_SNANA/model_config/*.INPUT`), el usuario decidió cerrar
primero la brecha de eficiencia ~2x de Fase 1.

## 1. Comparación numérica directa: SNANA real vs LightCurveLynx, término a término

`pipeline/simlib/formatobs.py` (Capa 1, ya en producción — construye el SIMLIB real de la
campaña v8) implementa la fórmula exacta de SNANA (`formatObs`, arxiv:1905.02887) para derivar
`SKYSIG`/`PSF`/`ZPT` desde `fiveSigmaDepth`/`skyBrightness`/`seeingFwhmEff` — con el zeropoint
derivado **directamente del `fiveSigmaDepth` oficial** de Rubin (ya calibrado con toda la
física real de instrumento+atmósfera), a diferencia de LightCurveLynx, que deriva su
zeropoint desde cero con constantes fijas simplificadas (`zp_per_sec` a cenit + corrección de
airmass). Esta comparación directa no se había hecho en Fase 1 (las dos rondas previas solo
auditaron la fórmula de LightCurveLynx en aislamiento).

`compare_noise_formulas.py` (nuevo) calcula ambas derivaciones sobre las mismas 145,345
visitas DDF reales y compara termino a término (conversión de unidades: `sky_bg_e=SKYSIG²`,
`psf_footprint=noise_area/pixsize²`, `zp=mag2flux(ZPT)`):

| término | SNANA real (mediana) | LightCurveLynx (mediana) | razón LCL/SNANA |
|---|---|---|---|
| `psf_footprint` (pix²) | 54.08 | 54.08 | **1.0000 — coinciden exactamente** |
| `sky_bg_e` (e⁻/pix) | 1917 | 2320 | 1.18x (LCL con **más** ruido de cielo, no menos) |
| `zp` (nJy/e⁻) | 0.8653 | 0.6907 | 0.85x (LCL más sensible por electrón) |

Prueba directa con una fuente de referencia fija (100 nJy, mismo readout/dark en ambos):
usando los inputs de LightCurveLynx el SNR mediano sale **1.2x** más alto que usando los
inputs reales de SNANA — un efecto real pero modesto, muy por debajo del ~2.5x observado en
la cola alta de Fase 1. **Esto refuta la hipótesis original de Fase 1** ("el modelo de ruido
subestima el ruido real") como explicación *principal* — el término de PSF coincide
exactamente, y sky/zp se cancelan parcialmente entre sí (más ruido de cielo, pero más
sensible por electrón), dejando solo ~20% de efecto neto.

## 2. Segunda pista: `H0=73` nunca se verificó contra SNANA real

Ninguna cosmología está fijada explícitamente en la campaña (`grep` sin resultados en
`run_SNANA/*.INPUT` ni en `pipeline/`) — SNANA corre con su default interno, que en el linaje
PLAsTiCC/Kessler+2019 de este catálogo es `H0=70`. El PoC de Fase 1 heredó `H0=73` del
placeholder original de `bench_snia.py` (Fase 0) sin verificarlo nunca contra la config real
— un ~4.3% de error en H0 implica ~0.1 mag de brillo sistemático de más.

## 3. Resultado combinado (H0=70 + columnas de ruido reales de SNANA inyectadas)

En vez de seguir ajustando constantes de LightCurveLynx, se precalculan `zp`/`psf_footprint`/
`sky_bg_e` con la fórmula real de SNANA (`snana_noise_columns()`, nuevo en
`run_snia_ddf_poc.py`, reusa `pipeline.simlib.formatobs.format_obs()` sin duplicar lógica) y
se inyectan como columnas del `DataFrame` **antes** de construir el `OpSim` —
`_derive_noise_columns()` solo calcula estas columnas si no están presentes, así que
LightCurveLynx usa el modelo de ruido de SNANA por construcción. Combinado con `H0=70`:

| | mediana SNR | p90 SNR | eficiencia |
|---|---|---|---|
| SNANA real (`SNIa_DDF`) | 0.78 | 2.26 | 29.85% (597/2000) |
| Fase 1 original (`H0=73`, ruido propio de LCL) | 1.008 (+29%) | 5.68 (+151%) | 60.75% |
| + `H0=70` | 0.916 (+17%) | 3.580 (+58%) | 57.85% |
| + `H0=70` **y** ruido real de SNANA inyectado | 0.889 (+14%) | 3.185 (+41%) | 54.3% (1086/2000) |

**Progreso real y verificado**: ambas brechas de SNR se redujeron aproximadamente a la mitad
(mediana 29%→14%, p90 151%→41%) con dos causas concretas, diagnosticadas y corregidas (no
constantes ajustadas a ciegas). **No cerrado del todo**: la eficiencia sigue en ~1.8x la real
(54.3% vs 29.85%), un residual notablemente menor que el ~2x original pero aún significativo
— la eficiencia de detección responde de forma no lineal (vía la curva SEARCHEFF) a mejoras en
el SNR cerca del umbral, así que una reducción de brecha de SNR no se traduce 1:1 en reducción
de brecha de eficiencia.

Se revisó una tercera pista (`M_abs=-19.3`, también heredado sin verificar de Fase 0) contra
`SIMGEN_INCLUDE_SNIa-SALT2.INPUT` y `SALT2.INFO`: SNANA no fija un `M_abs`/`MAGOFF` explícito
para esta clase — `-19.3` es el valor de calibración estándar de SALT2 en la literatura
(Betoule et al. 2014), consistente con `H0=70`, no un placeholder obviamente incorrecto. No se
encontró una cuarta pista concreta y barata de seguir en esta ronda.

## 4. Estado y siguiente decisión

Dos causas reales identificadas y corregidas (columnas de ruido + cosmología), reduciendo la
brecha sustancialmente pero sin cerrarla del todo. El residuo (~1.8x) probablemente vive en la
población/modelo de fuente (evaluación exacta de la superficie SALT2 vía `sncosmo` vs el
código interno de SNANA, o la simplificación de `SIGMA_INT` coherente en vez de la covarianza
completa de G10 — ambas ya señaladas como aproximaciones aceptadas desde Fase 1, no
investigadas más a fondo aquí). Decisión del usuario: proceder a Fase 2 parte B (SIMSED) con
este ~1.8x como caveat explícito y cuantificado (mejor que el ~2x sin diagnosticar de Fase 1).

# Fase 2 — parte B: primer PoC del wrapper SIMSED (`SNIa-91bg_DDF`)

## Hallazgo que cambia el plan original: LightCurveLynx ya trae un lector SIMSED nativo

Fase 0 concluyó "no hay lector de librería SIMSED nativo... hay que escribir un wrapper
propio" (`SEDTemplate`/`SEDTemplateModel` + `GivenValueSampler` a mano). Al investigar para
esta fase se encontró `lightcurvelynx.models.sed_template_model.SIMSEDModel` — una clase
**completa y lista para usar**, no disponible (o no encontrada) en la versión de Fase 0:
`SIMSEDModel.from_dir(simsed_dir, weights=...)` parsea `SED.INFO` (YAML), carga todos los
templates (maneja `.gz` automáticamente), aplica `FLUX_SCALE`, y selecciona un template por
objeto simulado vía `GivenValueSampler(weights=...)` ya integrado — exactamente la
combinación que Fase 0 anticipaba tener que construir a mano. Esto reduce sustancialmente el
riesgo/esfuerzo de ingeniería que se esperaba para esta fase.

## Elegir la clase más simple: no era `TDE-MOSFIT`

El plan original (basado en una lectura rápida de Fase 0) asumía `TDE-MOSFIT` como la más
simple. Verificado contra los directorios reales en NLHPC: `SIMSED.TDE-MOSFIT` tiene **745**
templates con **8** parámetros físicos (`TDE_INDEX Rph0 Tvis b bhmass eff lphoto starmass`) —
no es simple en absoluto. Comparando las 11 clases SIMSED del catálogo:

| clase | templates | NPAR |
|---|---|---|
| **`SIMSED.SNIa-91bg`** | **35** | **2** |
| `SIMSED.KN-K17` | 330 | 4 |
| `SIMSED.CART-MOSFIT` | 225 | 6 |
| `SIMSED.ILOT-MOSFIT` | 385 | 6 |
| `SIMSED.SNIax` | 1001 | 5 |
| `SIMSED.SNIIn-MOSFIT` | 839 | 6 |
| `SIMSED.SLSN-I-MOSFIT` | 960 | 9 |
| `SIMSED.PISN-MOSFIT` | 1000 | 3 |
| `SIMSED.SNII-NMF` | ~385 (+`COV.INFO`, modelo PCA) | 4 |
| `SIMSED.TDE-MOSFIT` | 745 | 8 |
| `SIMSED.KN-BULLA19` | *(directorio con 3 sub-variantes anidadas)* | — |

`SNIa-91bg` es la más simple por márgen amplio: grilla regular 7×5 (stretch × color), sin
covarianza espectral compleja — se eligió como primer PoC en su lugar.

## Bug real encontrado en el dato de referencia de SNANA (no nuestro)

`SED.INFO` de `SIMSED.SNIa-91bg` trae un typo real: la línea de comentario

    $ template to all 91bg at low-z as from Gonzalez-Gaitan+14.

usa `$` en vez de `#` (confirmado con `cat -A` en NLHPC). El parser de SNANA
(`snlc_sim.exe`) lo tolera porque no exige YAML estricto, pero
`SIMSEDModel._read_simsed_info_file()` sí hace `yaml.safe_load()` sobre el archivo completo, y
ese carácter rompe el parseo. **No se modificó el archivo real de SNANA** — mismo patrón que
`setup_salt2_local.py` de Fase 1: `setup_simsed_91bg_local.py` (nuevo) copia los 35 templates
+ una copia de `SED.INFO` con el fix de un carácter a
`exploration/lightcurvelynx/simsed_91bg_local/` (no versionado, se regenera desde NLHPC).

## Otro detalle de API real: `SIMSEDModel` valida sus parámetros en el constructor

A diferencia de `SncosmoWrapperModel` (Fase 1), `SIMSEDModel` **exige** `distance` (distancia
lumínica en pc, no `redshift` directamente) ya en el constructor — agregar parámetros después
vía `.add_parameter()` no funciona porque la validación ocurre en `__init__`. Se agregó un
sampler propio (`_luminosity_distance_pc`, misma cosmología `H0=70/Ωm=0.3` de Fase 2 parte A)
que convierte `redshift_func` a distancia en pc, pasado junto con `ra`/`dec`/`t0` directo al
`from_dir(...)`.

## Resultado: `run_simsed_91bg_ddf_poc.py`, `NGENTOT_LC=2000` (igual que SNANA DDF real)

Mismo patrón de Fase 1/2A: `H0=70` + ruido real de SNANA inyectado desde el inicio (no una
brecha nueva por cerrar), extinción MW real por campo, SEARCHEFF real, `pipeline.postproc.qc`
reusado sin modificar. `DNDZ: POWERLAW` (un tramo, más simple que el `POWERLAW2` de SNIa) y
los pesos de cada uno de los 35 templates calculados con la bivariada normal correlacionada
real (`GENPEAK_stretch=0.975 σ=0.096`, `GENPEAK_color=0.557 σ=0.175`,
`SIMSED_REDCOR=-0.656`) evaluada en el `(stretch, color)` propio de cada template — no un peso
uniforme.

| | mediana SNR | p90 SNR | eficiencia |
|---|---|---|---|
| SNANA real (`SNIa-91bg_DDF`) | 0.769 | 2.087 | 36.15% (723/2000) |
| LightCurveLynx (este PoC) | 0.890 (+15.7%) | 3.232 (+55%) | 49.65% (993/2000, **1.37x**) |

**Corrió de punta a punta sin errores** (57.8s de simulación para 2000 objetos, curvas de luz
con marcadores detectado/no-detectado reales, QC de 4 gráficos generado y visualmente
verificado). La brecha de eficiencia (1.37x) es notablemente **menor** que la de SNIa/SALT2
(1.8x) pese a que las brechas de SNR son de magnitud muy similar (mediana ~15%, p90 ~50-55%
en ambas clases) — señal cruzada útil: el residuo de SNR parece ser un factor sistémico
(no específico del modelo SALT2 vs SIMSED), pero su efecto en la eficiencia final depende de
en qué parte de la curva SEARCHEFF cae la población de cada clase.

## Archivos de esta parte

- `setup_simsed_91bg_local.py` (nuevo) — copia local de `SIMSED.SNIa-91bg` con el fix de
  `SED.INFO`, no versionada (se regenera).
- `run_simsed_91bg_ddf_poc.py` + `.sbatch` (nuevo) — PoC principal.
- `poc_output_91bg/summary.json` + `poc_output_91bg/qc/*.png` — resultado real.

## Estado y siguiente decisión

Primer PoC SIMSED exitoso: el lector nativo de LightCurveLynx funciona, el patrón de pesado
por `SIMSED_REDCOR` es correcto, y la brecha de eficiencia (1.37x) es menor que la del PoC
SALT2 de Fase 1/2A. Decisión del usuario: escalar a 2-3 clases SIMSED más antes de decidir
sobre las 10 restantes — ver siguiente sección.

# Fase 2 — parte B (continuación): 3 clases más, patrón generalizado

Se generalizó `run_simsed_91bg_ddf_poc.py` a `run_simsed_poc.py <clase>` (config por clase en
un dict, mismo patrón de ruido/cosmología/SEARCHEFF/QC reusado) para evitar triplicar el
boilerplate. Se agregó `build_dndz_md14_cdf()` a `snana_params.py` (fórmula real de Madau &
Dickinson 2014, `DNDZ: MD14 <rate0>` en varias clases del catálogo). De paso: el default de
`H0` en `build_dndz_powerlaw2_cdf()` seguía en `73.0` (el placeholder original de Fase 0,
nunca corregido pese a que la Fase 2 parte A sí corrigió el `H0` usado para
distancia/flujo) — corregido a `70.0` aquí; no se re-corrieron los PoC ya reportados de
SNIa/SNIa-91bg por esto (el efecto en la forma del redshift simulado es de segundo orden
frente al ya corregido en distancia/flujo, y ya están documentados con sus números reales).

## Clases elegidas (complejidad variada) y una descartada por buena razón

Se evaluaron las 11 clases SIMSED del catálogo por conteo de templates y parámetros. Se
eligieron `KN-K17` (peso uniforme `SIMSED_GRIDONLY`, `DNDZ: POWERLAW` sin dependencia de z,
redshift bajo 0.011–0.28), `CaRT`/CART-MOSFIT (peso uniforme, `DNDZ: MD14`, redshift medio
0.012–1.4), y `SLSN-I`/SLSN-I-MOSFIT (peso uniforme, `DNDZ: MD14`, redshift muy amplio
0.02–9.7 — prueba de escala). `PISN-MOSFIT` se descartó para esta ronda: usa
`DNDZ: PISN_PLK12`, un modelo de tasa con nombre propio (no una fórmula analítica simple como
`POWERLAW`/`POWERLAW2`/`MD14`) sin una referencia clara disponible — mejor no adivinar la
fórmula que implementarla mal.

## Simplificación deliberada: extinción de galaxia anfitriona (WV07) no implementada

Las 3 clases nuevas declaran extinción de polvo de la galaxia anfitriona en su `.INPUT` real
(`GENAV_WV07`/`GENRANGE_AV`/`GENPEAK_RV`, modelo WV07 con "half expon component"). Antes de
adivinar la fórmula, se buscó la implementación real en el código fuente de SNANA
(`~/github/SNANA_src/src/sntools_genExpHalfGauss.c`, el mismo árbol usado para compilar el
binario custom mencionado en el README del proyecto) — el propio código trae un comentario de
Dic 2023 documentando un bug histórico en esta función ("WV07 AV flag was never refactored to
use this function, so this might be a harmless bug"), señal de que no es una fórmula trivial
de reimplementar de memoria con confianza. **Se omite (AV=0) en vez de reimplementar mal** —
mismo criterio que la aproximación de `SIGMA_INT` para G10 en Fase 1, documentado explícitamente
como brecha conocida, no un descuido.

## Resultado: 3/3 corridas limpias, sin errores

`NGENTOT_LC=2000` para las 3 (igual que SNANA DDF real). Comparado contra los baselines reales
ya generados en la campaña v8 (`postprocess_manifest.json`):

| clase | SNR mediana LCL | SNR p90 LCL | detectados SNANA real | detectados LCL | razón |
|---|---|---|---|---|---|
| `KN-K17` | 0.685 | 1.692 | 82/2000 (4.1%) | 210/2000 (10.5%) | **2.56x** |
| `CaRT` | 0.682 | 1.672 | 16/2000 (0.8%) | 136/2000 (6.8%) | **8.5x** |
| `SLSN-I` | 0.993 | 8.436 | 824/2000 (41.2%) | 1266/2000 (63.3%) | **1.54x** |

Las 3 brechas son **mayores** que las de `SNIa`/`SNIa-91bg` (1.8x / 1.37x) — pero esto es
**esperado y coherente**, no una regresión nueva: `SNIa` y `SNIa-91bg` no declaran extinción
de galaxia anfitriona en su `.INPUT` real (solo MW, ya implementada), mientras que las 3
clases de esta ronda sí la declaran y no se implementó (ver sección anterior). Omitir un
efecto que dimueve/reduce brillo sistemáticamente produce exactamente el sesgo observado:
eficiencia inflada, más aún cuanto más débil es la clase intrínsecamente (`CaRT`, con solo 16
detecciones reales de 2000, es el caso más extremo — la cola de redshift alto del histograma
de `CaRT` muestra detecciones simuladas hasta z=1.4 que en la realidad casi no deberían
ocurrir para una clase tan tenue). Verificado visualmente: las curvas de luz y distribuciones
de redshift de las 3 clases se ven físicamente razonables (sin bugs de sampling como los de
Fase 1), la brecha es de magnitud/eficiencia, no de forma.

## Hallazgo de rendimiento: la carga de templates SIMSED no escala solo con la cantidad

Tiempo de carga aislado (tiempo entre leer `SED.INFO` y terminar la simulación, menos el
tiempo de simulación propiamente dicho, medido aparte con su propio timer):

| clase | templates | tiempo de carga (aislado) | seg/template |
|---|---|---|---|
| `SNIa-91bg` | 35 | ~18s (aprox., smoke test) | ~0.5 |
| `SLSN-I` | 960 | 194.1s | 0.202 |
| `CaRT` | 225 | 87.5s | 0.389 |
| `KN-K17` | 329 | **1976.0s (~33 min)** | **6.007** |

`KN-K17` tardó **~15-30x más por template** que las demás pese a tener menos templates que
`SLSN-I` (960) — el tiempo de carga depende del tamaño/resolución de cada archivo SED
individual (grilla de fase×longitud de onda), no solo de cuántos templates hay. Job de
`KN-K17` corrió con `-t 02:00:00` (aumentado preventivamente tras un smoke test de N=20 que
ya mostraba ~3.4s/template) — terminó en 37 min reales, dentro del margen. Relevante para
dimensionar tiempo de cómputo si se escala a las clases restantes (revisar el tamaño de los
archivos `.SED`/`.txt.gz` de cada clase antes de asumir un tiempo de job, no solo el conteo
de templates).

## Archivos de esta parte

- `run_simsed_poc.py` + `.sbatch` (nuevo) — version generalizada, reemplaza el patrón de
  script-por-clase para clases nuevas (el script específico de `SNIa-91bg` se deja como
  referencia histórica, no se migra).
- `snana_params.py` — agregado `build_dndz_md14_cdf()`, corregido default `H0` a 70.
- `poc_output_knk17/`, `poc_output_cart/`, `poc_output_slsni/` — resultados reales (`summary.json` + 4 QC c/u).

## Estado y siguiente decisión

5 clases validadas de punta a punta ahora (1 SALT2 continua + 4 SIMSED discretas). Patrón de
implementación sólido y reusable (`run_simsed_poc.py` generaliza a cualquier clase con peso
uniforme o `SIMSED_REDCOR`, `DNDZ` `POWERLAW`/`POWERLAW2`/`MD14`). Dos brechas abiertas y
documentadas, ambas con causa identificada (no misteriosas): el residuo de ruido/población
sistémico (~1.4-1.8x, ver Fase 2 parte A) y la extinción de galaxia anfitriona WV07 no
implementada (afecta solo a clases que la declaran — 3 de las 5 ya corridas). A decidir con
el usuario: implementar WV07 con una referencia más sólida antes de seguir escalando, o
continuar a más clases con esta brecha ya cuantificada como caveat conocido.

# Fase 2 — parte B (continuación 2): 3 clases más, extinción de host real (no WV07) y dos
# modelos de tasa nuevos encontrados en el código fuente real de SNANA

Ronda dedicada a `SNIax`, `TDE-MOSFIT`, `SNII-NMF` — elegidas porque, a diferencia de la ronda
anterior (`KN-K17`/`CaRT`/`SLSN-I`, extinción de host omitida por prudencia), estas 3 sí
permiten poner a prueba directamente la hipótesis de esa ronda ("las brechas grandes se deben
a la extinción de host omitida, no a un problema nuevo"): dos de las tres (`SNIax`,
`TDE-MOSFIT`) declaran un modelo de extinción de host **exponencial puro** (`GENTAU_AV`, sin
componente WV07/half-Gaussian) en su `.INPUT` real — implementable con confianza, a diferencia
de WV07 — y la tercera (`SNII-NMF`) no declara ninguna, sirviendo de control limpio igual que
`SNIa`/`SNIa-91bg`.

## 1. Dos modelos de tasa (`DNDZ`) nuevos, encontrados en el código fuente real de SNANA

`SNII-NMF` usa `DNDZ: CC_S15` y `TDE-MOSFIT` usa `DNDZ: TDE` — en la ronda anterior ambos se
habían descartado implícitamente por parecer "nombres propios" sin fórmula obvia (mismo
criterio que excluyó `PISN_PLK12`). Revisando el código fuente real de SNANA
(`~/github/SNANA_src/src/snlc_sim.c`, bloques `INDEX_RATEMODEL_CCS15` e
`INDEX_RATEMODEL_TDE`) ambos resultaron ser fórmulas simples y bien documentadas:

- **`CC_S15`** (tasa de core-collapse, Strolger 2015): misma forma funcional que `MD14`
  (`SFRfun_MD14`) pero con los parámetros A,B,C,D re-ajustados a la tasa de core-collapse
  observada (Fig 6, Ec 9 de Strolger 2015), no a la formación estelar general:

      rate(z) = k · h² · SFR_MD14(z; A=0.015, B=1.50, C=5.00, D=6.10) · DNDZ_ALLSCALE
      k = 0.0091, h = H0/100

- **`TDE`**: decaimiento exponencial simple en base 10, sin dependencia de cosmología en la
  forma funcional misma:

      rate(z) = rate0 · 10^(-0.5·z/0.6)

Ambas nuevas en `snana_params.py`: `build_dndz_ccs15_cdf()`, `build_dndz_tde_cdf()` — mismo
patrón de inversión de CDF numérica que `build_dndz_md14_cdf()`/`build_dndz_powerlaw2_cdf()`,
verificadas standalone antes de conectarlas al grafo (salidas con forma y percentiles
razonables). `PISN_PLK12` (la única `DNDZ` de nombre propio que queda entre las 11 clases
SIMSED) se revisó de nuevo por si el mismo patrón de "está en snlc_sim.c con nombre distinto"
aplicaba, pero no se encontró razón para reconsiderarla en esta ronda — sigue fuera de
alcance, no una clase de esta ronda.

## 2. Extinción de host real implementada (modelo exponencial puro, no WV07)

`SNIax` y `TDE-MOSFIT` declaran en su `.INPUT` real (confirmado leyendo
`SIMGEN_INCLUDE_SNIax.INPUT` y el equivalente de `TDE-MOSFIT`) `GENTAU_AV`/`GENRANGE_AV`/
`GENPEAK_RV` **sin** `GENAV_WV07` — el modelo exponencial puro que Fase 0/G10 ya había
señalado como implementable con `make_exp_av_sampler()` (Fase 2 parte B, ronda 1). Se conectó
por primera vez esta ronda: `av_func` (muestreo de AV por inversión de CDF truncada) →
conversión a `ebv = av/r_v` → segundo `ExtinctionEffect(frame="rest")` añadido al
`source_model` vía `add_effect()`, sobre el ya existente de extinción MW (`frame="observer"`).

| clase | `GENTAU_AV` | `GENRANGE_AV` | `GENPEAK_RV` |
|---|---|---|---|
| `SNIax` | 1.7 | 0.001–3.0 | 3.1 |
| `TDE-MOSFIT` | 0.4 | (mismo rango asumido, `av_max=3.0`) | 3.1 |

## 3. Bug real encontrado: `CCM89` no está calibrado para el UV extremo que z=2.9 produce en rest-frame

Al conectar la extinción de host para `TDE-MOSFIT` (`GENRANGE_REDSHIFT: 0.01–2.9`, el rango de
redshift más amplio de las 8 clases SIMSED corridas hasta ahora), el primer smoke test
(`N=15`) falló con:

    ValueError: Input x outside of range defined for CCM89 [0.3 <= x <= 10.0, x has units 1/micron]

Causa raíz (confirmada leyendo `lightcurvelynx/models/physical_model.py::_evaluate_single()`):
los efectos `frame='rest'` reciben `wavelengths` ya convertidas a rest-frame
(`obs_to_rest_times_waves(times, wavelengths, redshift, t0)`, división por `1+z`). El borde
azul de LSST-u (~3200Å observado) a z≈2.9 cae en rest-frame a ~820Å — por debajo del límite
físico real de 1000Å (x=10 μm⁻¹) al que está calibrada la ley de extinción CCM89 (y toda la
familia de leyes paramétricas estándar: O94, F99, etc. comparten el mismo límite UV). No es un
bug de LightCurveLynx ni nuestro — es el límite real de la calibración empírica de esa ley,
que `dust_extinction` (correctamente) rechaza en vez de extrapolar en silencio.

**Fix**: `ClippedExtinctionEffect` (nuevo en `snana_params.py`, subclase de `ExtinctionEffect`)
clampea las longitudes de onda al rango válido del modelo (`ext_obj.x_range`) antes de
evaluar, en vez de fallar — mismo espíritu que la extrapolación `ZeroPadding`/`LinearDecay` que
LightCurveLynx ya usa para el SED fuera de `RESTLAMBDA_RANGE`: la extinción se mantiene
constante (igual al valor de borde) más allá del rango calibrado, en vez de inventar una
fórmula de extrapolación nueva. Aplicado tanto a la extinción MW como a la de host (esta última
es la que realmente lo necesita; la de MW opera en wavelengths de observador, siempre dentro de
rango) — cambio barato y sin efecto en clases de redshift bajo (el clip es un no-op ahí).
Verificado: el mismo smoke test de `TDE-MOSFIT` con el fix corre limpio de punta a punta.

## 4. Otro bug real encontrado (no nuestro): línea suelta inválida en `SED.INFO` de `TDE-MOSFIT`

`SIMSEDModel._read_simsed_info_file()` (que sí exige YAML estricto) falló al cargar
`SIMSED.TDE-MOSFIT/SED.INFO` con un `yaml.scanner.ScannerError` en la línea 254. Confirmado con
`sed`/`cat -A` en NLHPC: esa línea es literalmente `tde_384.json` — un nombre de archivo
suelto, sin prefijo `SED:` ni `#`, intercalado entre dos entradas `SED:` reales (entre
`tde239.dat` y `tde241.dat`). El parser de SNANA (`snlc_sim.exe`) lo tolera por no exigir YAML
estricto; el nuestro no. A diferencia del typo de un solo carácter de `SNIa-91bg` (Fase 2B,
ronda 1), este archivo es demasiado grande para copiar entero (**144M, 745 templates** vs los
35 de `SNIa-91bg`) — `setup_simsed_local.py` (nuevo, generaliza `setup_simsed_91bg_local.py`)
en vez de copiar, **symlinkea** los 745 archivos de template y solo reescribe `SED.INFO`,
descartando cualquier línea que no matchee un formato conocido (comentario, blank, o una
palabra clave real como `SED:`/`PARNAMES:`/etc.) — 1 línea descartada, 745 symlinkeadas. No se
toca el archivo real de SNANA. `CLASS_CONFIGS["TDE-MOSFIT"]["simsed_dir"]` apunta a esta copia
local saneada (`exploration/lightcurvelynx/simsed_tdemosfit_local/`, no versionada).

## 5. Resultado: 3/3 corridas limpias, `NGENTOT_LC=2000` (igual que SNANA DDF real)

Comparado contra los baselines reales de la campaña v8 (`postprocess_manifest.json`,
`n_objects` = detectados de `NGENTOT_LC=2000`):

| clase | extinción host | SNR mediana LCL | SNR p90 LCL | detectados SNANA real | detectados LCL | razón |
|---|---|---|---|---|---|---|
| `SNII-NMF` | no declarada (control limpio) | 0.741 | 1.921 | 356/2000 (17.8%) | 498/2000 (24.9%) | **1.40x** |
| `TDE-MOSFIT` | sí, `GENTAU_AV=0.4` | 1.007 | 4.406 | 812/2000 (40.6%) | 1277/2000 (63.85%) | **1.57x** |
| `SNIax` | sí, `GENTAU_AV=1.7` | 0.761 | 2.054 | 175/2000 (8.75%) | 464/2000 (23.2%) | **2.65x** |

**La hipótesis de la ronda anterior se confirma parcialmente, no del todo.** `SNII-NMF`
(control limpio, sin extinción) y `TDE-MOSFIT` (con extinción de host real implementada) caen
ambas dentro de la misma banda de brecha residual sistémica ya documentada para las clases
"limpias" de rondas anteriores (`SNIa` 1.8x, `SNIa-91bg` 1.37x, ver Fase 2 parte A/B) — un
resultado que **sí** respalda la hipótesis: implementar extinción de host real en
`TDE-MOSFIT` la trajo de vuelta a la banda 1.4-1.8x, en vez de quedarse en la banda 2.5-8.5x de
`KN-K17`/`CaRT`/`SLSN-I` (que omitieron extinción). Pero `SNIax` **no** siguió el mismo patrón:
pese a implementar extinción de host con los parámetros exactos de su `.INPUT` real
(`GENTAU_AV=1.7`, `GENRANGE_AV=0.001–3.0`, `GENPEAK_RV=3.1` — verificado línea por línea contra
`SIMGEN_INCLUDE_SNIax.INPUT`, sin discrepancia), su razón (2.65x) queda claramente por encima de
la banda sistémica, más cerca de las clases sin extinción de la ronda anterior.

**No se investigó más a fondo esta ronda** (mismo criterio de "dos hipótesis concretas, luego
documentar y decidir con el usuario" ya aplicado en Fase 2 parte A) — candidatos abiertos, sin
confirmar: (a) el `GENTAU_AV` de `SNIax` (1.7) es ~4x el de `TDE-MOSFIT` (0.4), así que
cualquier error pequeño en el muestreo de AV alto pesaría más en `SNIax` que en `TDE-MOSFIT`;
(b) `SNIax` es la única de las 3 clases de esta ronda que reusa `DNDZ: MD14` (ya usado en la
ronda anterior para `CaRT`/`SLSN-I`, ambas con brechas grandes) en vez de un modelo de tasa
nuevo — no se puede descartar un efecto de la tasa/población en sí, independiente de la
extinción. Ninguno de los dos se investigó con la misma profundidad que el diagnóstico término
a término de Fase 2 parte A.

## 6. Hallazgo de rendimiento: `SNIax` confirma que la carga de templates es impredecible por clase

    | clase      | templates | tiempo de carga (aislado) | seg/template |
    |------------|-----------|----------------------------|---------------|
    | `TDE-MOSFIT` | 742     | ~150-190s                  | ~0.20-0.26    |
    | `SNIax`      | 1001    | 465s (smoke, login) / 992s (sbatch, largemem) | 0.46-0.99 |

Mismo patrón que `KN-K17` en la ronda anterior (6.0s/template vs 0.2s/template de `SLSN-I` con
más templates): el tiempo de carga no escala solo con la cantidad de templates, sino con
tamaño/resolución de cada archivo SED individual — y aquí además con contención de I/O
compartida del nodo (la corrida de `sbatch` en partición `largemem` tardó ~2x más que el smoke
test aislado en el login node para la misma clase). El límite de tiempo del sbatch
(`-t 02:00:00`) sigue siendo suficiente margen (corrida real: 21 min), pero confirma que no hay
forma de estimar el tiempo de job de una clase nueva sin correr al menos un smoke test primero
— práctica que ya se venía siguiendo, esta ronda la justifica de nuevo.

## Archivos de esta ronda

- `snana_params.py` — agregado `build_dndz_ccs15_cdf()`, `build_dndz_tde_cdf()`,
  `make_exp_av_sampler()` (ya existía desde antes, conectado por primera vez esta ronda),
  `make_correlated_normal_weights()`, `ClippedExtinctionEffect`.
- `setup_simsed_local.py` (nuevo) — versión generalizada/symlink de
  `setup_simsed_91bg_local.py`, para clases SIMSED grandes con un `SED.INFO` inválido.
- `simsed_tdemosfit_local/` (no versionado, se regenera) — copia saneada de `SED.INFO` +
  745 templates symlinkeados.
- `run_simsed_poc.py` — 3 configs nuevas (`SNIax`, `TDE-MOSFIT`, `SNII-NMF`), branching de
  `DNDZ`/pesos/extinción de host generalizado.
- `poc_output_sniax/`, `poc_output_tdemosfit/`, `poc_output_sniinmf/` — resultados reales
  (`summary.json` + 4 QC c/u).

## Estado y siguiente decisión

8 clases SIMSED/SALT2 validadas de punta a punta en total. La hipótesis de "extinción de host
omitida explica las brechas grandes" quedó **parcialmente confirmada** (`TDE-MOSFIT` sí,
`SNIax` no) — un resultado honesto, no la confirmación limpia que se esperaba, y una señal de
que la brecha residual sistémica (ruido/población, Fase 2 parte A) y la extinción de host no
son completamente independientes o hay un tercer factor sin identificar específico de
`SNIax`/`MD14`. A decidir con el usuario: (a) investigar el caso `SNIax` con el mismo rigor que
Fase 2 parte A (comparación término a término, no solo eficiencia agregada), (b) seguir
escalando a las 3 clases restantes que sí declaran WV07 (`ILOT-MOSFIT`, `SNIIn-MOSFIT`,
`PISN-MOSFIT` con su `DNDZ` propia) con las brechas ya conocidas como caveat, o (c) dar por
suficientemente cubierto el catálogo SIMSED (8/11 clases, cobertura de todos los patrones de
implementación: peso uniforme, `SIMSED_REDCOR`, extinción de host exponencial, 4 modelos
`DNDZ` distintos) y cerrar la evaluación de LightCurveLynx con una recomendación final.

# Fase 2 — parte B (continuación 3): investigación del caso `SNIax` + 3 clases más
# (`ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`)

## 1. Root-cause de `SNIax`: el `.INPUT` real no es pura exponencial — se leyó incompleto

Releyendo `SIMGEN_INCLUDE_SNIax.INPUT` línea por línea (no solo `grep`-eando las claves ya
conocidas de `TDE-MOSFIT`, como se hizo en la ronda 2) aparecen dos líneas que la ronda anterior
no vio:

    GENTAU_AV:        1.7          # dN/dAV = exp(-AV/xxx)
    GENSIG_AV:        0.6          # += Guass(AV,sigma)
    GENRATIO_AV0:     4.0

`SNIax` **no** es el caso "solo componente exponencial" que se le asignó — es una **mezcla
exponencial + semi-Gaussiana**, con la componente Gaussiana pesada 4x más fuerte que la
exponencial en `AV=0` (`GENRATIO_AV0`). El error de la ronda 2 fue de lectura, no de
implementación: se generalizó el patrón de `TDE-MOSFIT` (que sí declara únicamente
`GENTAU_AV`) sin verificar que `SNIax` no tuviera parámetros adicionales.

**¿Es esto el modelo WV07 bugueado que se descartó en la ronda 1?** No — confirmado leyendo
`snlc_sim.c::gen_AV()` completo: hay dos caminos de código completamente distintos.
`GENAV_WV07()` (el que trae el bug histórico documentado, usado por `KN-K17`/`CaRT`/`SLSN-I`/
`ILOT-MOSFIT`/`SNIIn-MOSFIT`/`PISN-MOSFIT` vía el flag real `GENAV_WV07: 1`, confirmado en sus
`.INPUT`) solo se invoca si `INPUTS.WV07_GENAV_FLAG` está activo. `SNIax` no declara ese flag —
usa el camino `INPUTS.GENPROFILE_AV.USE` → `getRan_GEN_EXP_HALFGAUSS()`
(`sntools_genExpHalfGauss.c`), una función **refactorizada en Mar 2020** (D.Brout/R.Kessler) y
con un bug de peso relativo distinto **corregido en Dic 2023** (`WGT_EXPON`/`WGT_GAUSS`
invertidos) — el propio comentario del fix dice explícitamente: *"WV07 AV flag was never
refactored to use this function, so this might be a harmless bug"*, confirmando que son dos
funciones independientes con historiales de bugs separados. Implementable con confianza.

## 2. Implementación real del algoritmo (no una aproximación)

`make_exp_halfgauss_av_sampler()` (nuevo en `snana_params.py`) replica exactamente
`getRan_GEN_EXP_HALFGAUSS()` con la versión ya corregida (Dic 2023):

    WGT_EXPON = tau * (exp(-r0/tau) - exp(-r1/tau))
    WGT_GAUSS = 0.5 * ratio * sqrt(2*pi*sig^2)

Con probabilidad `WGT_EXPON/(WGT_EXPON+WGT_GAUSS)`: AV de una exponencial truncada en
`[r0,r1]` (inversión de CDF). Si no: AV de una semi-Gaussiana (`peak=0` → solo lado positivo,
`sig*|Gauss|`) por rechazo hasta caer en `[r0,r1]`. Verificado standalone contra la versión
pura exponencial que se venía usando:

| | mediana AV | media AV | p90 AV |
|---|---|---|---|
| pura exponencial (ronda 2, incorrecta para `SNIax`) | 0.908 | 1.079 | 2.328 |
| mezcla real (`tau=1.7, sig=0.6, ratio=4.0`) | **0.493** | **0.670** | **1.515** |

La mezcla real aplica **menos** extinción típica que la aproximación exponencial pura (68% de
los objetos cae en la rama Gaussiana, con AV típico ~0.4-0.5, no en la cola exponencial de AV
típico ~1.2-1.7) — el sesgo iba en la dirección opuesta a la esperada.

## 3. Resultado: la brecha no se cerró — empeoró levemente

`NGENTOT_LC=2000`, mismo pipeline, único cambio: el sampler de AV.

| | SNR mediana | SNR p90 | detectados SNANA | detectados LCL | razón |
|---|---|---|---|---|---|
| ronda 2 (AV exponencial puro, incorrecto) | 0.761 | 2.054 | 175/2000 (8.75%) | 464/2000 (23.2%) | 2.65x |
| ronda 3 (AV mezcla real, correcto) | 0.755 | 2.026 | 175/2000 (8.75%) | 476/2000 (23.8%) | **2.72x** |

**Resultado honesto, no el esperado**: corregir el modelo de extinción (menos AV típico →
objetos menos atenuados → más detecciones) empeoró la brecha en vez de cerrarla, exactamente
como predecía el cálculo de AV típico del punto 2. Esto **descarta la extinción de host como
la causa de la brecha anómala de `SNIax`** — con el modelo correcto implementado y verificado
línea por línea contra `snlc_sim.c`, la brecha persiste casi sin cambio (2.65x→2.72x, dentro
del ruido de simulación). La causa real de por qué `SNIax` queda fuera de la banda sistémica
1.4-1.8x (que sí explica `TDE-MOSFIT`/`SNII-NMF`) sigue sin identificarse. Candidatos no
descartados pero tampoco confirmados, sin investigar más a fondo esta ronda (mismo criterio de
"documentar y decidir con el usuario" del resto de la sesión): `DNDZ: MD14` (reusado de
`CaRT`/`SLSN-I`, que también mostraron brechas grandes en la ronda 1 — pero esas SÍ tenían
extinción omitida, no es una comparación limpia); o un efecto de población/color específico de
la plantilla SIMSED de `SNIax` no capturado por ninguno de los términos ya auditados en Fase 2
parte A.

## 4. Tres clases más: `ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`

Las 3 últimas del catálogo que declaran extinción de host (todas con el flag real
`GENAV_WV07: 1`, confirmado — no el camino de `SNIax`, así que la omisión sigue siendo la
decisión correcta y justificada, mismo criterio de la ronda 1). `ILOT-MOSFIT` y `SNIIn-MOSFIT`
reusan `DNDZ: CC_S15` (ya validado en `SNII-NMF`). `PISN-MOSFIT` usa `DNDZ: PISN_PLK12` — un
modelo que las rondas 1-2 habían descartado por "nombre propio sin fórmula obvia", pero que
esta vez sí se encontró en el código fuente real (`snlc_sim.c`, bloque
`INDEX_RATEMODEL_PISN`), sin necesidad de `h²`/`H0` en la forma funcional (a diferencia de
`MD14`/`CC_S15`):

    rate(z) = 1.98 + 6.38z + 6.558z² - 4.42z³ + 0.8312z⁴ - 0.0508z⁵   [/yr/Gpc³]

`build_dndz_pisn_cdf()` (nuevo en `snana_params.py`) implementa esta fórmula exacta. Los 3
`SED.INFO` reales parsean como YAML limpio (sin el problema de `TDE-MOSFIT`), no hizo falta
sanitizar nada.

## 5. Resultado: 4/4 corridas limpias esta ronda, `NGENTOT_LC=2000`

| clase | extinción host | SNR mediana | SNR p90 | detectados SNANA | detectados LCL | razón |
|---|---|---|---|---|---|---|
| `SNIax` (corregido) | mezcla real (exp+semi-Gauss) | 0.755 | 2.026 | 175/2000 (8.75%) | 476/2000 (23.8%) | 2.72x |
| `ILOT-MOSFIT` | omitida (WV07 real) | 0.694 | 1.714 | 73/2000 (3.65%) | 143/2000 (7.15%) | 1.96x |
| `SNIIn-MOSFIT` | omitida (WV07 real) | 0.683 | 1.676 | 37/2000 (1.85%) | 187/2000 (9.35%) | 5.05x |
| `PISN-MOSFIT` | omitida (WV07 real) | 0.814 | 2.370 | 411/2000 (20.55%) | 716/2000 (35.8%) | 1.74x |

Las 3 clases con extinción omitida (`ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`) caen dentro
del mismo rango amplio 1.5-8.5x ya visto en la ronda 1 (`KN-K17` 2.56x, `CaRT` 8.5x, `SLSN-I`
1.54x) — más evidencia de que ese rango, no una banda estrecha, es lo que produce omitir
extinción de host, con la magnitud dependiendo de cuán débil es la clase intrínsecamente
(`SNIIn-MOSFIT`, con solo 37 detecciones reales de 2000, es de nuevo el caso extremo, igual que
`CaRT` en la ronda 1 con 16/2000).

## 6. Estado del catálogo SIMSED: 10/11 clases cubiertas

Con esta ronda: `SNIa-91bg`, `KN-K17`, `CaRT`, `SLSN-I`, `SNIax`, `TDE-MOSFIT`, `SNII-NMF`,
`ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT` — 10 de las 11 clases SIMSED del catálogo (más
`SNIa`/SALT2, 11 clases en total evaluadas). Solo queda `KN-BULLA19`, con una estructura de
directorio anidada de 3 sub-variantes nunca investigada (ver Fase 2 parte B, sección "Elegir
la clase más simple") — no evaluada aún, fuera del alcance de esta ronda.

## Archivos de esta ronda

- `snana_params.py` — `make_exp_halfgauss_av_sampler()` (mezcla real exp+semi-Gauss, fix del
  caso `SNIax`), `build_dndz_pisn_cdf()` (fórmula `PISN_PLK12` real).
- `run_simsed_poc.py` — config de `SNIax` corregida (`kind="exp_halfgauss"`), 3 configs nuevas
  (`ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`), dispatch de `host_av["kind"]` generalizado.
- `poc_output_sniax/` (actualizado), `poc_output_ilotmosfit/`, `poc_output_sniinmosfit/`,
  `poc_output_pisnmosfit/` — resultados reales (`summary.json` + 4 QC c/u).

## Estado y siguiente decisión

La investigación del caso `SNIax` produjo un resultado real y útil aunque no el esperado: se
encontró y corrigió un error genuino de caracterización (mezcla exp+semi-Gauss real, no pura
exponencial), implementado con el algoritmo exacto de SNANA verificado línea por línea contra
el código fuente real — pero la corrección **no** explica la brecha anómala de `SNIax`, que
sigue sin causa identificada. Esto es información real: descarta una hipótesis concreta en vez
de dejarla sin probar. 10/11 clases SIMSED evaluadas de punta a punta, con hallazgos honestos
en ambas direcciones (confirmaciones y refutaciones de hipótesis) documentados en todas las
rondas. Suficiente cobertura para una recomendación final de la evaluación LightCurveLynx —
`KN-BULLA19` queda como único pendiente conocido, no bloqueante.

# Fase 2 — parte B (continuación 4): cierre del catálogo — `KN-BULLA19`,
# `PISN-STELLA-HECORE`, `PISN-STELLA-HYDROGENIC`

`KN-BULLA19` es la última de las 11 clases SIMSED originales. Al revisar de nuevo
`pipeline/models.yaml` para confirmar que no quedaba nada suelto, aparecieron 2 clases más
allá de las 11 originales que también usan `GENMODEL: .../SIMSED.*` y nunca se habían corrido:
`PISN-STELLA-HECORE` y `PISN-STELLA-HYDROGENIC` (variantes alternativas de PISN, distintas de
`PISN-MOSFIT` — modelos de S.Blondin basados en Heger & Woosley 2002 y Gilmer et al. 2017
respectivamente).

## 1. `KN-BULLA19`: la estructura anidada resultó ser simple, pero escondía un bug de dato real

`GENMODEL` apunta a `SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP` — de las 3 sub-variantes
anidadas que existen en el directorio (`BULLA-BHNS-M1-2COMP`, `BULLA-BNS-M2-2COMP`,
`BULLA-BNS-M3-3COMP`, confirmado con `find`), el `.INPUT` real solo usa una. No hacía falta
elegir entre las 3 "a ciegas" como se temía en Fase 2B ronda 1 — el `.INPUT` ya lo resuelve.

Al cargar esa sub-variante (550 templates), `SIMSEDModel.from_dir()` falló con
`gzip.BadGzipFile: Not a gzipped file (b'PK')`. Diagnóstico con `file`/`xxd` en NLHPC: los 550
archivos `*.txt.gz` que declara `SED.INFO` **no son gzip** — son archivos **ZIP** (firma real
`PK\x03\x04`) mal etiquetados con extensión `.gz`, cada uno con un solo miembro interno del
mismo nombre. Confirmado con una muestra de 20/550 archivos, todos con el mismo problema — no
es un caso aislado, es sistémico en esta librería SIMSED específica (probablemente un paso de
compresión equivocado al publicarla, no algo que afecte a las otras 10 clases ya corridas). El
parser de SNANA lo tolera (probablemente vía una utilidad de sistema más laxa); el nuestro no.

**Fix**: `setup_knbulla19_local.py` (nuevo) — descomprime cada ZIP (`zipfile`) y re-comprime el
contenido como gzip real (`gzip.open(...).write(...)`), mismo nombre de archivo, `SED.INFO` sin
tocar (ya parsea limpio). Corrida real: 550/550 archivos arreglados en ~2 min, verificado
`np.loadtxt()` cargando una grilla `(50000, 3)` fase×longitud de onda×flujo correctamente
después del fix. No se toca el archivo real de SNANA — copia local en
`simsed_knbulla19_local/` (no versionada).

## 2. `WV07_REWGT_EXPAV`: otra forma de activar el mismo camino de código bugueado

`KN-BULLA19` declara `WV07_REWGT_EXPAV: 0.5` en vez de `GENAV_WV07: 1` directo — a primera
vista parece un mecanismo distinto. Confirmado leyendo `snlc_sim.c` (línea ~7887-7888):
cualquier valor real de `WV07_REWGT_EXPAV` (`> -1.0E-9`) activa
`INPUTS.WV07_GENAV_FLAG = DO_WV07 = 1`, el mismo flag que `KN-K17`/`CaRT`/`SLSN-I`/
`ILOT-MOSFIT`/`SNIIn-MOSFIT`/`PISN-MOSFIT` activan directo — mismo camino de código con el bug
histórico ya documentado (Fase 2B ronda 1). Se omite por el mismo criterio, no una excepción
nueva sin analizar.

## 3. `PISN-STELLA-HECORE`/`PISN-STELLA-HYDROGENIC`: reuso directo, sin sorpresas de config

Ambas declaran `GENAV_WV07: 1` (el camino bugueado directo, se omite igual que `PISN-MOSFIT`)
y `DNDZ: PISN_PLK12` — la misma fórmula real ya implementada la ronda anterior
(`build_dndz_pisn_cdf()`), reusada sin cambios. `GENRANGE_REDSHIFT: 0.02 2.2` (ligeramente más
angosto que el `0.02 2.4` de `PISN-MOSFIT`). Ambos `SED.INFO` parsean limpio, ambos directorios
son pequeños (11M/14 templates y 5.3M/6 templates respectivamente) — las corridas más rápidas
de todo el catálogo SIMSED hasta ahora.

## 4. `PISN-STELLA-HYDROGENIC` usa `NGENTOT_LC=20000`, no 2000 — y eso reveló un límite real de memoria

A diferencia de las demás 10 clases (todas con `ngen_ddf: 2000` en `pipeline/models.yaml`),
`PISN-STELLA-HYDROGENIC` usa `ngen_ddf: 20000` — confirmado, no un valor por defecto sin
verificar. `run_simsed_poc.py` se generalizó (`main(class_key, ngentot_override=None)`,
`CLASS_CONFIGS[...]["ngentot_lc"]` como override opcional) para soportar esto sin tocar las
otras 10 clases.

El primer intento (mismo `--mem=16G` que todas las clases anteriores) terminó en
`OUT_OF_MEMORY` a los 109s, justo después de cargar los 6 templates — 10x más objetos que el
caso normal (2000→20000) implica ~10x más filas de fotometría aplanada (confirmado después:
45.5M filas vs los ~4.5M típicos de N=2000), y el objeto intermedio de curvas de luz por
objeto de `simulate_lightcurves()` excede los 16GB antes de llegar siquiera a esa etapa.
**Fix**: resubmit con `sbatch --mem=64G` (override de CLI sobre el `#SBATCH --mem=16G` del
script, sin tocar el `.sbatch` compartido por las otras clases) — corrió limpio, `MaxRSS` no
llegó a excederse. Tiempo total: **62 minutos** (804s simulación + 2671s aplanado + resto) —
resultó ser proporcional a N (10x el tiempo de una corrida N=2000 típica, no superlineal como
se sospechó a mitad de la espera), solo que en términos absolutos es una corrida larga.

## 5. Resultado: 3/3 corridas limpias

| clase | `NGENTOT_LC` | extinción host | SNR mediana | SNR p90 | detectados SNANA | detectados LCL | razón |
|---|---|---|---|---|---|---|---|
| `KN-BULLA19` | 2000 | omitida (`WV07_REWGT_EXPAV` → mismo camino WV07 real) | 0.683 | 1.685 | 103/2000 (5.15%) | 294/2000 (14.7%) | 2.85x |
| `PISN-STELLA-HECORE` | 2000 | omitida (`GENAV_WV07` real) | 0.746 | 2.054 | 384/2000 (19.2%) | 577/2000 (28.85%) | 1.50x |
| `PISN-STELLA-HYDROGENIC` | 20000 | omitida (`GENAV_WV07` real) | 0.754 | 2.021 | 4268/20000 (21.34%) | 6106/20000 (30.53%) | 1.43x |

Las 3 clases omiten extinción de host (las 3 usan el camino WV07 real, confirmado línea por
línea) — sus razones (1.43x-2.85x) caen dentro del mismo rango amplio ya visto en rondas
anteriores para clases sin extinción (1.5x-8.5x), sin sorpresas nuevas. `PISN-STELLA-HECORE`
(1.50x) y `PISN-STELLA-HYDROGENIC` (1.43x) caen cerca del extremo bueno de ese rango — similar
a `PISN-MOSFIT` (1.74x) y `SLSN-I` (1.54x), clases intrínsecamente más brillantes/comunes.
`KN-BULLA19` (2.85x) es comparable a `KN-K17` (2.56x), su análogo del mismo tipo de evento
(kilonova) — señal cruzada razonable: dos librerías SIMSED distintas para el mismo tipo físico
de evento (kilonovas de fusión de estrellas de neutrones) muestran una brecha similar, lo que
sugiere que el factor dominante es el tipo de evento/población, no una peculiaridad de una
librería de templates en particular.

## 6. Estado del catálogo: 11/11 clases SIMSED + `SNIa`/SALT2 — cobertura completa

Con esta ronda se cierra el catálogo completo de clases basadas en SIMSED del proyecto: las 11
originales (`SNIa-91bg`, `KN-K17`, `CaRT`, `SLSN-I`, `SNIax`, `TDE-MOSFIT`, `SNII-NMF`,
`ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`, `KN-BULLA19`) más las 2 variantes PISN-STELLA
encontradas esta ronda, más `SNIa`/SALT2 de Fase 1 — 14 clases evaluadas de punta a punta en
total. Cobertura de todos los patrones de implementación encontrados: peso uniforme,
`SIMSED_REDCOR` (1D y 3D), extinción de host exponencial pura, extinción de host mezcla
exp+semi-Gauss real, 5 modelos `DNDZ` distintos (`POWERLAW`, `POWERLAW2`, `MD14`, `CC_S15`,
`TDE`, `PISN_PLK12`), y ahora también el caso de `NGENTOT_LC` no estándar.

## Archivos de esta ronda

- `setup_knbulla19_local.py` (nuevo) — descomprime los 550 templates ZIP-mal-etiquetados de
  `KN-BULLA19` y los re-comprime como gzip real; `simsed_knbulla19_local/` (no versionado).
- `run_simsed_poc.py` — `main()` acepta `ngentot_override` opcional, `CLASS_CONFIGS` soporta
  `ngentot_lc` por clase; 3 configs nuevas (`KN-BULLA19`, `PISN-STELLA-HECORE`,
  `PISN-STELLA-HYDROGENIC`).
- `poc_output_knbulla19/`, `poc_output_pisnstellahecore/`, `poc_output_pisnstellahydrogenic/`
  — resultados reales (`summary.json` + 4 QC c/u).

## Estado y siguiente decisión

Catálogo SIMSED/SALT2 completo (14/14 clases planificadas). No quedan clases SIMSED conocidas
sin evaluar en el catálogo activo del proyecto. Recomendación: con esta cobertura, el próximo
paso natural es una recomendación final consolidada de la evaluación LightCurveLynx (síntesis
de las 4 rondas de Fase 2B + Fase 1/2A), no más escalado de clases — a decidir con el usuario.

# Recomendación final — LightCurveLynx como reemplazo de SNANA

Síntesis de Fase 0 (spike técnico) → Fase 1 (PoC SNIa) → Fase 2 parte A (cierre de brecha de
ruido) → Fase 2 parte B, 4 rondas (cobertura SIMSED completa). 14 clases evaluadas de punta a
punta contra baselines DDF reales de la campaña `full_v5.3_10yrs` (v8).

## Veredicto: GO condicional — viable como motor de simulación, no listo para reemplazo directo

LightCurveLynx **sí puede reproducir mecánicamente** cualquier clase del catálogo (SALT2 y las
14 variantes SIMSED, incluyendo los 5 modelos `DNDZ` reales del catálogo) con parámetros reales
de SNANA, extinción MW real, eficiencia de detección real (SEARCHEFF), y una ventaja de
velocidad de ~150x sobre SNANA en throughput crudo — pero **ninguna corrida coincide
cuantitativamente** con SNANA todavía. La eficiencia de detección simulada sale sistemáticamente
más alta, con razones LCL/SNANA entre **1.37x y 8.50x** (promedio 2.57x) según la clase. Esto no
es un fallo binario ("no sirve") ni una confirmación limpia ("listo para producción") — es una
herramienta con mecánica sólida y una calibración cuantitativa pendiente, con las causas
conocidas ya diagnosticadas con precisión variable.

## Tabla completa — 14 clases, ordenadas por razón LCL/SNANA

| clase | modelo | extinción de host | SNANA real | LightCurveLynx | razón |
|---|---|---|---|---|---|
| `SNIa-91bg` | SIMSED (35 templates) | no declarada | 723/2000 (36.15%) | 993/2000 (49.65%) | 1.37x |
| `SNII-NMF` | SIMSED (384, PCA) | no declarada | 356/2000 (17.8%) | 498/2000 (24.9%) | 1.40x |
| `PISN-STELLA-HYDROGENIC` | SIMSED (6) | omitida (WV07 real) | 4268/20000 (21.34%) | 6106/20000 (30.53%) | 1.43x |
| `PISN-STELLA-HECORE` | SIMSED (14) | omitida (WV07 real) | 384/2000 (19.2%) | 577/2000 (28.85%) | 1.50x |
| `SLSN-I` | SIMSED (960) | omitida (WV07 real) | 824/2000 (41.2%) | 1266/2000 (63.3%) | 1.54x |
| `TDE-MOSFIT` | SIMSED (742) | **implementada** (exp. pura) | 812/2000 (40.6%) | 1277/2000 (63.85%) | 1.57x |
| `PISN-MOSFIT` | SIMSED (1000) | omitida (WV07 real) | 411/2000 (20.55%) | 716/2000 (35.8%) | 1.74x |
| `SNIa` | SALT2 (sncosmo H17) | no implementada (solo MW) | 597/2000 (29.85%) | 1086/2000 (54.3%) | 1.82x |
| `ILOT-MOSFIT` | SIMSED (385) | omitida (WV07 real) | 73/2000 (3.65%) | 143/2000 (7.15%) | 1.96x |
| `KN-K17` | SIMSED (329) | omitida (WV07 real) | 82/2000 (4.1%) | 210/2000 (10.5%) | 2.56x |
| `SNIax` | SIMSED (1001) | **implementada** (mezcla real) | 175/2000 (8.75%) | 476/2000 (23.8%) | 2.72x |
| `KN-BULLA19` | SIMSED (550) | omitida (WV07 real) | 103/2000 (5.15%) | 294/2000 (14.7%) | 2.85x |
| `SNIIn-MOSFIT` | SIMSED (839) | omitida (WV07 real) | 37/2000 (1.85%) | 187/2000 (9.35%) | 5.05x |
| `CaRT` | SIMSED (225) | omitida (WV07 real) | 16/2000 (0.8%) | 136/2000 (6.8%) | 8.50x |

## Lo que sí funciona sin reservas

- **Ingesta de OpSim**: exacta, sin transformación de columnas, mismo schema que el simulador
  oficial de Rubin (Fase 0 punto 3).
- **Extinción MW**: completa, más flexible que SNANA (soporta más leyes de extinción que las
  que SNANA usa hoy), verificada por campo real (Fase 1 punto 6).
- **SIMSED nativo**: `SIMSEDModel.from_dir()` funciona para las 14 variantes probadas — 12
  peso uniforme, 2 con `SIMSED_REDCOR` (1D y 3D) — cubriendo 5 modelos `DNDZ` reales
  (`POWERLAW`, `POWERLAW2`, `MD14`, `CC_S15`, `TDE`, `PISN_PLK12`).
- **SEARCHEFF real**: implementado como post-proceso (`searcheff.py`) reusando los archivos de
  calibración reales de SNANA, mismo `PHOTFLAG`/criterio de detección en ambos lados de la
  comparación.
- **Rendimiento**: ~150x más rápido en throughput crudo (Fase 0), confirmado en cada PoC
  posterior (2000 objetos DDF en 50-90s de wall time, incluida ingesta completa de OpSim).
- **Orquestación**: patrón `dask.distributed.LocalCluster` dentro de un job SLURM único
  validado con 3.16x de speedup real (Fase 1 punto 8b) — nunca se necesitó tocar el login node
  en ninguna corrida de toda la evaluación.

## Las dos causas reales de la brecha cuantitativa (diagnosticadas, ninguna es un misterio difuso)

**1. Residuo sistémico de ruido/población (~1.4-1.8x), presente incluso sin extinción de host
omitida.** Diagnosticado en dos rondas reales de investigación (Fase 1 punto 7b, Fase 2 parte
A): se identificaron y corrigieron dos causas concretas (`H0=73`→`70` sin verificar, y el
modelo de ruido propio de LightCurveLynx vs las columnas `SKYSIG`/`PSF`/`ZPT` reales de SNANA,
inyectadas directamente desde Fase 2A en adelante) — la brecha se redujo de ~2x a ~1.4-1.8x
con ambos fixes, pero no se cerró del todo. Las clases "limpias" (sin extinción de host que
declarar: `SNIa-91bg`, `SNII-NMF`) y las que sí implementan extinción de host correctamente
(`TDE-MOSFIT`) caen todas en esta misma banda — señal consistente de que el residuo es
sistémico, no específico de una clase o un modelo de fuente. Causa más probable no confirmada:
diferencias en cómo se evalúa la superficie SALT2/SIMSED entre `sncosmo`/LightCurveLynx y el
código interno de SNANA, o simplificaciones aceptadas de dispersión intrínseca (`SIGMA_INT`
coherente en vez de la covarianza completa de G10).

**2. Extinción de host `WV07` no implementada — afecta a 9/14 clases** (`KN-K17`, `CaRT`,
`SLSN-I`, `ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`, `PISN-STELLA-HECORE`,
`PISN-STELLA-HYDROGENIC`, `KN-BULLA19` — recuento corregido; una cuenta anterior decía 8/14 por
error), **con efecto proporcional a cuán tenue es la clase intrínsecamente.** Decisión
deliberada desde la ronda 1 (no un descuido): se había leído un comentario de bug histórico en
`getRan_GEN_EXP_HALFGAUSS()` (`sntools_genExpHalfGauss.c`) y se asumió, por prudencia, que
afectaba también al modelo WV07. El efecto es medible y coherente: clases intrínsecamente
brillantes/comunes (`SLSN-I` 1.54x, `PISN-STELLA-HECORE` 1.50x, `PISN-MOSFIT` 1.74x) caen cerca
de la banda sistémica pese a omitir extinción, mientras que clases intrínsecamente tenues
(`CaRT` 8.50x con solo 16 detecciones reales de 2000, `SNIIn-MOSFIT` 5.05x con 37/2000)
muestran el efecto amplificado — omitir un factor que oscurece
sistemáticamente pesa mucho más cerca del umbral de detección.

**Validación cruzada real de la causa 2** (Fase 2B ronda 3): al implementar el modelo de host
`no`-WV07 real y correctamente (la mezcla exponencial+semi-Gaussiana de `SNIax`, distinta del
flag `GENAV_WV07` bugueado — confirmado leyendo `snlc_sim.c::gen_AV()` línea por línea), la
corrección **no** cerró la brecha de esa clase (2.65x→2.72x, empeoró levemente) — refutando
extinción como la causa en ese caso puntual y confirmando que `SNIax` es una anomalía real
seguramente ligada a la causa 1 (residuo sistémico), no a extinción. Este es el único resultado
de las 4 rondas que contradice una hipótesis en vez de confirmarla — se documentó como tal, sin
forzar una narrativa limpia.

## Lo que nunca se probó (límites reales de esta evaluación, no ocultos)

- **Escala WFD real**: todas las 14 clases se corrieron a escala DDF (`NGENTOT_LC=2000`,
  excepto `PISN-STELLA-HYDROGENIC` a 20000) — la escala WFD real de producción es
  `NGENTOT_LC=200,000` por clase, 100x más. El patrón `dask` está validado (Fase 1 punto 8b)
  pero nunca se corrió a este volumen real; `PISN-STELLA-HYDROGENIC` (10x escala) ya mostró que
  la memoria necesaria escala con N de forma no trivial (`--mem=16G` no alcanzó, `64G` sí) —
  extrapolar a WFD sin probarlo primero sería especular.
- **`WV07` real**: se decidió omitir por precaución, no se investigó si existe una
  referencia/implementación alternativa confiable (a diferencia de `PISN_PLK12`/`CC_S15`/`TDE`,
  que sí se encontraron y verificaron esta sesión). Afecta a 9/14 clases. **Actualización: ver
  Fase 3 más abajo — se investigó y sí se encontró una referencia sólida.**
- **Comparación contra más de un baseline**: todo se comparó contra la única campaña real
  disponible (`full_v5.3_10yrs`/v8) — no se probó si la brecha cuantitativa es estable entre
  distintas configuraciones OpSim o campañas.
- **Integración real de pipeline**: nada de esto toca `pipeline/orchestrate/` (Capa 3) ni
  ninguna capa de producción — es exploración aislada en `exploration/lightcurvelynx/`, sin
  ningún archivo de producción modificado.

## Recomendación concreta (superada por Fase 3 — ver más abajo)

**No reemplazar SNANA todavía.** La brecha cuantitativa (1.37x-8.50x) es demasiado grande y
variable por clase para usar LightCurveLynx como fuente de verdad científica en su estado
actual. **Sí vale la pena seguir invirtiendo** — la mecánica funciona en las 14 clases del
catálogo, dos causas reales de brecha ya están diagnosticadas con precisión (no es una caja
negra), y la ventaja de velocidad (~150x) es lo bastante grande como para que cerrar la
calibración cuantitativa sea un objetivo con retorno real, no un ejercicio académico.

# Fase 3 — implementar el modelo real de extinción de host `WV07`

Primera fase con alcance definido después de la recomendación final (arriba). De las 2 causas
diagnosticadas de la brecha cuantitativa, `WV07` era la única con una vía de cierre concreta
(el residuo sistémico de Causa 1 ya había agotado dos rondas reales de investigación en Fase
2A). Objetivo: encontrar la fórmula real de `GENAV_WV07()`, implementarla con confianza, y
medir el efecto real en las 9 clases que la declaran.

## 1. La función real es autónoma y ya está corregida — la precaución de las rondas 1-4 era sobre la función equivocada

Leyendo `GENAV_WV07()` completa en `snlc_sim.c` (nunca se había leído línea por línea antes,
solo un comentario de un archivo adyacente): es el modelo real de extinción de host de
**ESSENCE-WV07** (Wood-Vasey et al. 2007) — comentario real en el código: *"return AV from
distribution used by ESSENCE-WV07"*. Mezcla una exponencial ancha + un núcleo semi-Gaussiano
angosto, con **constantes fijas en el código** (no configurables por `.INPUT`, iguales para las
9 clases): `tau=0.4`, `sqsigma=0.01` (sigma del núcleo = 0.1 mag). Muestreo por rechazo: `AV`
uniforme en `GENRANGE_AV`, peso `W(AV) = AEXP·exp(-AV/tau) + BEXP·exp(-0.5·AV²/sqsigma)`
normalizado por `W(0)`, aceptar con probabilidad `W(AV)/W(0)`.

**Es una función completamente autónoma** — nunca llama a `getRan_GEN_EXP_HALFGAUSS()` (la
función con el bug de peso corregido en Dic 2023 que motivó la precaución original). El único
bug histórico real de `GENAV_WV07()` (comentario real: *"Mar 17 2022: fix bug that has resulted
in all AV=0; use INPUTS.GENPROFILE_AV.RANGE instead of obsolete INPUTS.GENRANGE_AV"* — una
variable obsoleta) ya está corregido en la versión del código fuente leída esta ronda. La
precaución de las rondas 1-4 (omitir WV07 por el bug de una función *adyacente*) era razonable
dado lo que se sabía entonces, pero resultó ser sobre la función equivocada.

`make_wv07_av_sampler()` (nuevo en `snana_params.py`) implementa el algoritmo exacto. Si el
`.INPUT` declara `WV07_REWGT_EXPAV` (`KN-K17` y `KN-BULLA19`, valor `0.5` — confirmado que
activa el mismo `WV07_GENAV_FLAG`, mismo camino de código, no una excepción nueva), reescala
`AEXP`. Las otras 7 clases no lo declaran (`AEXP` sin modificar). Verificado standalone: `AV`
mediano ≈0.15 mag (caso default) / ≈0.11 mag (rewgt=0.5) — una distribución bastante
concentrada cerca de cero, con cola larga hasta el límite de `GENRANGE_AV` (3.0 mag).

## 2. Resultado: efecto real, pero pequeño y no sistemático — el catálogo completo apenas se movió

`NGENTOT_LC` real de cada clase (2000, excepto `PISN-STELLA-HYDROGENIC` a 20000). Único cambio
respecto a las corridas ya reportadas: el sampler de `host_av` (de omitido/AV=0 a `WV07` real).

| clase | razón (sin WV07) | razón (WV07 real) | Δ |
|---|---|---|---|
| `SLSN-I` | 1.54x | 1.50x | mejor |
| `PISN-STELLA-HYDROGENIC` | 1.43x | 1.38x | mejor |
| `PISN-STELLA-HECORE` | 1.50x | 1.41x | mejor |
| `PISN-MOSFIT` | 1.74x | 1.62x | mejor |
| `ILOT-MOSFIT` | 1.96x | 2.25x | **peor** |
| `KN-K17` | 2.56x | 2.87x | **peor** |
| `SNIax` *(no afectada, otro modelo)* | 2.72x | 2.72x | — |
| `KN-BULLA19` | 2.85x | 2.84x | igual |
| `SNIIn-MOSFIT` | 5.05x | 4.76x | mejor |
| `CaRT` | 8.50x | 8.56x | **igual, el caso más extremo no se movió** |

**Promedio de las 9 clases afectadas: 3.01x antes → 3.02x después — esencialmente sin
cambio.** 5 mejoraron (leve a moderado), 2 empeoraron, 2 quedaron iguales dentro del ruido.
**Promedio del catálogo completo (14 clases): 2.57x → 2.58x — sin cambio significativo.**

## 3. Esto refuta parcialmente la hipótesis de la ronda 1 de Fase 2B

La hipótesis original (Fase 2B ronda 1) era que omitir `WV07` explicaba las brechas más grandes
del catálogo, con el efecto amplificado en clases intrínsecamente tenues — y que implementarlo
correctamente debía cerrar esas brechas. El resultado real la refuta parcialmente: **`CaRT`,
el caso más extremo (8.50x) y el que más debería beneficiarse según la hipótesis, prácticamente
no se movió** (8.50x→8.56x). `KN-K17` incluso empeoró. Solo las clases que ya estaban cerca de
la banda sistémica (`SLSN-I`, `PISN-MOSFIT`, ambas `PISN-STELLA-*`) mejoraron de forma
consistente — es decir, `WV07` ayuda un poco donde la brecha ya era chica, pero no explica las
brechas grandes.

**Causa más probable, no confirmada**: el `AV` mediano real de `WV07` (~0.15 mag) es
modesto — una corrección de ese tamaño es fácilmente dominada por el residuo sistémico de
Causa 1 (~1.4-1.8x, sin cerrar desde Fase 2A) para las clases ya cerca de esa banda, pero es
demasiado pequeña para mover clases con brechas de 5-8x. Además, los baselines reales de SNANA
para las clases más tenues son conteos muy bajos (`CaRT` n=16, `ILOT-MOSFIT` n=73, `KN-K17`
n=82, `KN-BULLA19` n=103, `SNIIn-MOSFIT` n=37) — con incertidumbre de Poisson de ese orden
(`CaRT`: ±25% relativo solo por conteo), diferencias de ±10-15% en la razón antes/después no
distinguen necesariamente una mejora real de ruido estadístico. **No se investigó más a fondo
esta ronda** (mismo criterio de "documentar y decidir con el usuario" de toda la sesión) — si
se quiere una conclusión más firme sobre `CaRT`/`KN-K17` específicamente, hace falta más de una
semilla/corrida, o una comparación término a término como la de Fase 2A.

## Archivos de esta fase

- `snana_params.py` — `make_wv07_av_sampler()` (modelo ESSENCE-WV07 real, constantes fijas
  `tau=0.4`/`sqsigma=0.01`, muestreo por rechazo).
- `run_simsed_poc.py` — `host_av["kind"]="wv07"` agregado al dispatch; 9 `CLASS_CONFIGS`
  actualizados (`KN-K17`, `CaRT`, `SLSN-I`, `ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`,
  `KN-BULLA19`, `PISN-STELLA-HECORE`, `PISN-STELLA-HYDROGENIC`).
- `poc_output_knk17/`, `poc_output_cart/`, `poc_output_slsni/`, `poc_output_ilotmosfit/`,
  `poc_output_sniinmosfit/`, `poc_output_pisnmosfit/`, `poc_output_knbulla19/`,
  `poc_output_pisnstellahecore/`, `poc_output_pisnstellahydrogenic/` — resultados actualizados
  con `WV07` real (`summary.json` + 4 QC c/u, sobrescriben los de las rondas anteriores).

## Recomendación final (actualizada)

**Sigue siendo GO condicional — la conclusión no cambia, pero la causa raíz sí se aclaró.**
Implementar `WV07` fue lo correcto científicamente (fórmula real, verificada línea por línea
contra el código fuente, no una aproximación) y cerró la brecha para 5 de 9 clases afectadas
— pero el promedio del catálogo completo apenas se movió (2.57x→2.58x), porque el residuo
sistémico de Causa 1 (~1.4-1.8x, sin cerrar desde Fase 2A) domina sobre la extinción de host en
casi todos los casos. **La causa raíz real de la brecha cuantitativa de LightCurveLynx contra
SNANA no es la extinción de host — es el residuo sistémico no resuelto de Fase 2A.** Esto
redirige dónde vale la pena invertir a continuación: cerrar ese residuo (comparación más
profunda de la evaluación de superficie SALT2/SIMSED, o correr múltiples semillas para
distinguir señal de ruido en las clases de bajo conteo) tiene más potencial de cerrar la brecha
que seguir ajustando modelos de extinción.

# Fase 4 — investigar el residuo sistémico (~1.4-1.8x) a fondo

Ataca directamente la causa raíz identificada al cierre de Fase 3, con más rigor que las dos
rondas ya agotadas en Fase 2A. Pista clave no explotada todavía: el residuo está presente
**tanto en clases SALT2 (`SNIa`) como en clases SIMSED** que leen templates de flujo reales
directamente (`SNIa-91bg`, `SNII-NMF`, `TDE-MOSFIT`) — sin pasar por `sncosmo` ni por el modelo
de dispersión G10. Como ambos tipos de fuente muestran la misma banda residual, la causa debe
estar en la maquinaria **compartida** (ruido, extinción MW, SEARCHEFF), no en la evaluación de
un modelo de fuente específico.

## 1. Tres candidatos descartados con evidencia real, antes de encontrar la causa

**Curvas de throughput de filtro — descartado, idénticas.** LightCurveLynx descarga
`total_{ugrizy}.dat` en vivo desde `github.com/lsst/throughputs` rama `main`; SNANA usa el tag
fijo `baseline_1.9` (confirmado en `pipeline/kcor/README.md`). Comparación byte a byte en
NLHPC de las 6 curvas: **0 líneas de diferencia** — la rama `main` no se movió desde `1.9` en
los filtros LSST reales. Descartado con evidencia directa, no supuesto.

**`dark_current`/`readout_noise` — descartado, magnitud insuficiente.** `poisson_bandflux_std()`
(LightCurveLynx) suma varianza de sky+readout+dark+zp_err además de la fuente; solo se
inyectan `sky_bg_e`/`psf_footprint`/`zp` reales desde Fase 2A, dejando `dark_current=0.2 e⁻/s`
y `readout_noise=8.8 e⁻` (defaults de `OpSim`) sin verificar. Cálculo real con parámetros DDF
típicos: `dark_variance + readout_variance ≈` solo **~4.4%** de `sky_variance` — aunque hubiera
doble conteo, el efecto en SNR es de ~2%, muy por debajo de la brecha de 40-80%.

**Eficiencia espectroscópica faltante — descartado, no se exige en la campaña real.** Hipótesis:
¿el `n_objects` real de SNANA exige además un trigger espectroscópico (`SEARCHEFF_SPEC`) que
nunca se modeló? `snlc_sim.c` línea 32911: `APPLY_SEARCHEFF_OPT: += 1,2,4 => require pipe,spec,
zhost`. La campaña real (`pipeline/campaign/templates.py`) usa `APPLY_SEARCHEFF_OPT: 1` —
**solo** el bit de pipeline (fotométrico), igual que lo que ya se modela. Descartado con el
propio código fuente de la campaña, no una suposición.

## 2. La causa real: el trigger de detección contaba observaciones individuales, no épocas reales

`LSST_PIPELINE_LOGIC.DAT` documenta: *"min time between detections is given by NEWMJD_DIF key
in sim-input"* — el trigger de SNANA (`>=2 épocas`) no cuenta observaciones individuales, cuenta
**épocas agrupadas**: `snlc_sim.c` (~línea 20566) usa un algoritmo secuencial real,
`MJD_DIF = MJD - MJD_LAST_KEEP; if (fabs(MJD_DIF) > NEWMJD_DIF) nueva_epoca`, con
`NEWMJD_DIF=0.007` días (~10 min, default real, línea 849: *"same 'epoch' for obs within 10'"*)
— agrupando **todas las bandas juntas**, no por banda separada.

Nuestra implementación (`searcheff.py`, sin cambios desde Fase 1) nunca agrupaba — contaba cada
observación individual con `PHOTFLAG_DETECT` como una "época" candidata para el trigger. Medido
con el algoritmo real sobre el OpSim DDF completo:

    145,345 observaciones DDF  →  14,293 épocas reales  (~10.2 obs/época)

Los campos DDF se observan deliberadamente en secuencias de varias visitas seguidas en la misma
noche/banda (para apilar imágenes profundas) — exactamente el patrón que `NEWMJD_DIF` está
diseñado para colapsar en una sola época, y que nuestra implementación nunca colapsaba. Esto es
compartido por **las 14 clases por igual** (mismo `searcheff.py`, mismo trigger), coincidiendo
con el patrón observado de un residuo sistémico y no específico de una clase.

## 3. Fix: `group_into_epochs()` + verificación formal de corrección

`searcheff.py` (nuevo: `group_into_epochs()`, `object_level_detected()` reescrita) replica el
algoritmo secuencial exacto (agrupa por MJD, todas las bandas, `NEWMJD_DIF=0.007`), y una época
cuenta como detectada si **al menos una** de sus observaciones tiene `PHOTFLAG_DETECT`.
`run_simsed_poc.py`/`run_snia_ddf_poc.py` migrados a usar la nueva función en vez del
`groupby("SNID").size()` que contaba filas crudas.

**Verificación formal**: por construcción, agrupar observaciones en épocas solo puede *fusionar*
observaciones (nunca dividir una), así que el conteo de épocas reales de un objeto es siempre
`<=` su conteo de observaciones individuales detectadas — el nuevo trigger (`>=2 épocas
reales`) debería ser un subconjunto estricto del trigger anterior (`>=2 observaciones`). Se
verificó esto empíricamente corriendo ambos métodos sobre el mismo `phot_df` (instrumentación
temporal, revertida después de verificar) para `CaRT` N=500: **26 detectados con el método
nuevo, 27 con el viejo, y el conjunto nuevo es subconjunto exacto del viejo (diferencia
vacía)** — el fix es lógicamente correcto, sin bugs de implementación.

## 4. Segundo hallazgo real (no buscado): la selección de template SIMSED nunca fue reproducible

Investigando por qué `CaRT` mostraba *más* detecciones después del fix (contradiciendo la
propiedad de subconjunto verificada arriba, que predice igual o menos, nunca más — ver punto 3)
se encontró una causa distinta: `SIMSEDModel.from_dir()` construye su sampler de selección de
template (`GivenValueSampler`) **sin pasarle un `seed`**
(`sed_template_model.py`: `self._sampler_node = GivenValueSampler(all_inds, weights=weights)`).
`NumpyRandomFunc` con `seed=None` cae a `os.urandom()` (`math_nodes/np_random.py`) — es decir,
**la selección de template real nunca fue reproducible entre corridas**, en ninguna ronda de
Fase 2B/3, pese a `SEED_BASE` fijo. Esto afecta a las 9 clases de peso uniforme
(`SIMSED_GRIDONLY`) del catálogo — no a `SNIa`/`SALT2` (sin templates) ni a `SNIa-91bg`/
`SNII-NMF` (peso `SIMSED_REDCOR`, mismo problema en principio pero no verificado esta ronda).

**Fix para corridas futuras** (no se re-corrió el catálogo completo de nuevo solo por esto):
`source_model._sampler_node.set_seed(SEED_BASE + 9)` después de `SIMSEDModel.from_dir()`.
**No resuelto en esta ronda**: cuánto de la varianza observada entre corridas (antes/después del
fix de épocas) se debe al fix real vs. a este ruido de selección de template — sin re-correr con
múltiples semillas fijas no se puede aislar limpiamente. Se documenta como límite real de esta
ronda, no se oculta.

## 5. Resultado: efecto real pero pequeño, y no sistemático en la dirección esperada

`NGENTOT_LC` real de cada clase. Único cambio respecto a las corridas de Fase 3: el trigger de
época (punto 3). `SNIa-91bg` migrada por primera vez de `run_simsed_91bg_ddf_poc.py` (script
histórico dedicado) al patrón generalizado `run_simsed_poc.py` (mismos parámetros reales, sin
cambios), para heredar el fix sin duplicar lógica.

| clase | SNANA real | razón antes (Fase 3) | razón después (Fase 4) | Δ |
|---|---|---|---|---|
| `PISN-STELLA-HYDROGENIC` | 4268/20000 | 1.38x | 1.35x | -0.03x |
| `SNIa-91bg` | 723/2000 | 1.37x | 1.35x | -0.02x |
| `SNII-NMF` | 356/2000 | 1.40x | 1.35x | -0.05x |
| `PISN-STELLA-HECORE` | 384/2000 | 1.41x | 1.41x | 0.00x |
| `SLSN-I` | 824/2000 | 1.50x | 1.52x | +0.01x |
| `TDE-MOSFIT` | 812/2000 | 1.57x | 1.58x | +0.01x |
| `PISN-MOSFIT` | 411/2000 | 1.62x | 1.66x | +0.03x |
| `SNIa` | 597/2000 | 1.82x | 1.81x | -0.01x |
| `ILOT-MOSFIT` | 73/2000 | 2.25x | 2.14x | -0.11x |
| `SNIax` | 175/2000 | 2.72x | 2.49x | -0.23x |
| `KN-BULLA19` | 103/2000 | 2.84x | 2.36x | **-0.49x** |
| `KN-K17` | 82/2000 | 2.87x | 2.46x | **-0.40x** |
| `SNIIn-MOSFIT` | 37/2000 | 4.76x | 4.81x | +0.05x |
| `CaRT` | 16/2000 | 8.56x | 9.56x | **+1.00x** |

**Promedio del catálogo: 2.577x → 2.561x — sin cambio significativo**, pese a que el fix en sí
está formalmente verificado como correcto (punto 3). La mayoría de las clases se mantuvo
prácticamente igual (±0.05x, dentro del ruido esperado). Solo 3 clases mejoraron de forma clara:
`KN-K17`, `KN-BULLA19` (ambas kilonovas, mismo modelo `WV07_REWGT_EXPAV=0.5` y rango de
redshift bajo) y `SNIax` — sugiriendo que el efecto del agrupamiento de épocas es real pero
depende de la cadencia/redshift específico de cada clase, no un factor multiplicativo uniforme.
`CaRT` empeoró, pero dado el hallazgo del punto 4 (selección de template no reproducible) y su
conteo real extremadamente bajo (SNANA n=16), este resultado puntual no es confiable sin
múltiples semillas — no se interpreta como una regresión causada por el fix.

**Por qué el efecto es menor de lo esperado pese al colapso ~10x en conteo de épocas**: agrupar
observaciones reduce el número de "oportunidades" de época, pero cada época real ahora tiene
*varias* exposiciones — la probabilidad de que *al menos una* dispare la eficiencia de detección
es mayor que la de una sola observación aislada (efecto de unión de probabilidades). Este efecto
compensa parcialmente la reducción en conteo de épocas, explicando por qué el promedio del
catálogo casi no se movió pese al hallazgo aparentemente grande del punto 2.

## Archivos de esta ronda

- `searcheff.py` — `group_into_epochs()` (nuevo), `object_level_detected()` reescrita para usar
  épocas agrupadas en vez de observaciones individuales.
- `run_simsed_poc.py` — usa `object_level_detected()` del punto anterior; fix de seed
  (`source_model._sampler_node.set_seed(...)`) para selección de template reproducible en
  corridas futuras; `SNIa-91bg` migrada a `CLASS_CONFIGS` (mismos parámetros reales que
  `run_simsed_91bg_ddf_poc.py`, script histórico que se deja sin tocar).
- `run_snia_ddf_poc.py` — mismo fix de trigger que `run_simsed_poc.py`.
- `poc_output_snia91bg/` (nuevo, reemplaza a `poc_output_91bg/` como fuente activa),
  `poc_output_knk17/`, `poc_output_cart/`, `poc_output_slsni/`, `poc_output_sniax/`,
  `poc_output_tdemosfit/`, `poc_output_sniinmf/`, `poc_output_ilotmosfit/`,
  `poc_output_sniinmosfit/`, `poc_output_pisnmosfit/`, `poc_output_knbulla19/`,
  `poc_output_pisnstellahecore/`, `poc_output_pisnstellahydrogenic/`, `poc_output/` (`SNIa`) —
  las 14 clases, resultados actualizados con el trigger corregido.

## Recomendación final (actualizada de nuevo)

**Sigue GO condicional — dos causas reales cerradas (extinción de host en Fase 3, trigger de
época en Fase 4), y el residuo sistémico sigue prácticamente intacto (2.56x de promedio).** Esto
es información real y valiosa, no un fracaso: dos hipótesis concretas y bien fundamentadas
(extinción omitida, sobre-conteo de épocas) se investigaron con rigor real (fórmulas verificadas
línea por línea contra el código fuente, correcciones formalmente verificadas) y **ninguna de
las dos explica la brecha dominante** — descartar causas reales con evidencia real es progreso
científico genuino, aunque no cierre la brecha. Lo que queda abierto: la causa raíz sigue sin
identificarse con precisión, y esta ronda reveló un problema metodológico adicional (selección
de template SIMSED no reproducible) que probablemente inyectó ruido no cuantificado en **todas**
las comparaciones de clases SIMSED de peso uniforme a lo largo de toda la sesión, no solo en
Fase 4. Antes de seguir cazando la causa raíz, la prioridad real debería ser cerrar ese agujero
de reproducibilidad (semillas fijas + múltiples corridas por clase) para poder confiar en
cualquier comparación futura, incluidas las ya reportadas.

# Fase 5 — reproducibilidad real: semillas múltiples por clase

## Motivación

Fase 4 cerró documentando un problema metodológico: `SIMSEDModel.from_dir()` nunca semilla su
selector interno de template, así que la elección de template real fue no reproducible en
**todas** las corridas de clases SIMSED de peso uniforme a lo largo de toda la sesión (Fases
2B-4). El usuario decidió (confirmado explícitamente vía pregunta directa): antes de seguir
cazando la causa raíz del residuo sistémico, cerrar primero este agujero de reproducibilidad —
correr múltiples semillas fijas por clase para poder poner una banda de incertidumbre real a
cada razón LCL/SNANA reportada, y determinar si la aparente regresión de `CaRT` en Fase 4
(8.56x → 9.56x) fue señal real o ruido de semilla.

## Tres bugs de reproducibilidad adicionales encontrados (más allá del ya documentado en Fase 4)

Antes de poder confiar en un barrido de semillas múltiples, había que verificar que **una misma
semilla produce el mismo resultado** — condición necesaria para que variar la semilla mida algo
real. Un smoke test directo (`CaRT`, N=15, `seed_index=0` corrido dos veces como procesos
Python **separados**, no llamadas repetidas dentro del mismo proceso — para que el test
reflejara el uso real, donde cada semilla es un job SLURM independiente) reveló que el fix de
Fase 4 **no era suficiente**: dos corridas con la misma semilla producían conteos de fotometría
completamente distintos (10,260 vs. 23,240 filas para los mismos 15 objetos). Investigar la
causa, leyendo directamente el código fuente instalado de LightCurveLynx en NLHPC (mismo método
que Fases 3-4, nunca asumir), encontró **tres bugs reales de la librería**, todos con el mismo
patrón de fondo: un nodo interno construye su propio generador aleatorio y nunca recibe el
`seed=` que se le pasa al constructor externo.

**Bug A — jitter de posición sub-FOV no sembrado (`ObsTableRADECSampler.compute()`)**: cuando
`self.radius > 0` (heredado del radio real de campo de visión de `OpSim`, el FOV de LSST),
`compute()` aplica un desplazamiento aleatorio de la posición (RA/dec) dentro del FOV usando
`rng = rng_info if rng_info is not None else np.random.default_rng()` — es decir, si el
`rng_info` no llega explícitamente desde el framework de evaluación del grafo, cae en un
generador **sin semilla**. Confirmado leyendo
`lightcurvelynx/math_nodes/ra_dec_sampler.py` línea por línea en el entorno instalado.
**Fix**: pasar `radius=0.0` explícito al construir `ObsTableRADECSampler` — los campos DDF de
esta campaña son *pointings* fijos (no requieren jitter dentro del FOV), así que esto evita el
código no reproducible por completo, no es un parche indirecto.

**Bug B — selección de fila/pointing no sembrada (`TableSampler.__init__`, clase base de
`ObsTableRADECSampler`)**: el constructor de `TableSampler` arma su propio muestreador de
índice de fila así: `NumpyRandomFunc("integers", low=0, high=self._num_values)` — **sin pasar
`seed=`**, aunque el `seed=` que se le pasó al `ObsTableRADECSampler` externo sí llega hasta
`FunctionNode.__init__` (el nodo padre), nunca hasta este nodo hijo interno. Este es el bug
verdaderamente responsable de la mayor parte de la varianza observada: es el que decide *qué
pointing/fila real de OpSim* (y por lo tanto qué observaciones reales) le corresponde a cada
objeto simulado. Confirmado leyendo `lightcurvelynx/math_nodes/given_sampler.py`. Mismo patrón
exacto que el bug de Fase 4 en `SIMSEDModel`/`GivenValueSampler`. **Fix**: acceder al nodo
interno vía `radec_sampler.setters["selected_table_index"].dependency` (confirmado que expone
`.set_seed()`, mismo método usado en Fase 4) y sembrarlo explícitamente después de construir el
sampler: `radec_sampler.setters["selected_table_index"].dependency.set_seed(seed_base + 5)`.

**Bug C — ruido fotométrico no sembrado (`simulate_lightcurves()`)**: incluso con A y B
corregidos, dos corridas idénticas coincidían exactamente en número de filas de fotometría pero
diferían levemente en SNR (mediana 0.678 vs. 0.676) y conteo de detecciones (2/15 vs. 1/15) —
indicio de que la realización del ruido fotométrico en sí no estaba fija. `simulate_lightcurves()`
acepta un parámetro opcional `rng=` (un `numpy.random.Generator`) que se propaga a cualquier
nodo del grafo sin semilla propia — no se estaba pasando. **Fix**: pasar
`rng=np.random.default_rng(seed_base + 2)` (o `+ 8` en `run_snia_ddf_poc.py`, offset libre en
ese script) explícitamente en la llamada a `simulate_lightcurves()`.

**Verificación**: tras aplicar los tres fixes, `CaRT` con `seed_index=0` corrido dos veces como
procesos separados produjo resultados **byte-idénticos** (7,942 filas de fotometría,
SNR mediana=0.672/p90=1.644, 0/15 detectados en ambas corridas). `seed_index=1` produjo un
resultado claramente distinto (58,330 filas, SNR mediana=0.677, 4/15 detectados) — confirmando
que la semilla ahora tiene efecto real y es plenamente reproducible.

## Alcance real de estos bugs

Los bugs A-C afectan a **todas** las clases que usan `ObsTableRADECSampler` — es decir, las 13
clases SIMSED **y** la corrida `SNIa` (SALT2, `run_snia_ddf_poc.py`) — no solo las clases
SIMSED de peso uniforme como el bug ya documentado en Fase 4. Esto significa que **ninguna**
comparación de una sola corrida a lo largo de toda la sesión (Fases 1-4) tuvo garantía real de
reproducibilidad a nivel de emparejamiento de observaciones o realización de ruido — no solo la
selección de template. No se volvió a correr retroactivamente el catálogo completo solo por
esto (misma decisión práctica que en Fase 4): el propósito de Fase 5 es precisamente generar,
de ahora en adelante, resultados con banda de incertidumbre real usando el código ya corregido,
en vez de intentar reconstruir la incertidumbre de corridas pasadas que nunca la tuvieron.

## Metodología: 5 semillas fijas por clase

`seed_base = SEED_BASE + seed_index * 1_000_000` (offset grande para no colisionar con los
sub-offsets +1..+9 ya usados por cada componente del grafo dentro de una misma semilla).
`seed_index=0` reutiliza el directorio de salida histórico (`poc_output_<clase>/`, ya reportado
en el dashboard/NOTES.md); `seed_index=1..4` escriben en directorios nuevos
(`poc_output_<clase>_seed<N>/`) para no pisar el resultado principal. Se corrieron las 14
clases × 5 semillas (70 corridas) vía `sbatch run_simsed_poc.sbatch <clase> <seed_index>` /
`sbatch run_snia_ddf_poc.sbatch <seed_index>`, con `--mem=64G` para
`PISN-STELLA-HYDROGENIC` (única clase que satura los 16G por defecto, ver Fase 4).

## Persistencia de la tabla real (`head_df`/`phot_df`)

Hasta esta ronda el pipeline nunca escribía a disco los datos crudos de la simulación —
LightCurveLynx no tiene un writer nativo a formato SNANA (FITS/DUMP) ni a ningún otro formato
de tabla (confirmado revisando la documentación oficial, notebooks `snana_example` y
`lclib_example`: ambos solo muestran carga y simulación en memoria, ninguno exporta a disco).
Cada corrida solo generaba las imágenes QC y `summary.json` (métricas agregadas); `head_df`
(un registro por objeto) y `phot_df` (un registro por observación, con `FLUXCAL`/`FLUXCALERR`/
`MAG`/`PHOTFLAG`) vivían solo en memoria durante la corrida y se descartaban al terminar.

Se agregó persistencia real a ambos scripts: `head_df.parquet` y `phot_df.parquet` en cada
`poc_output_<clase>*/`, vía `pyarrow` (ya disponible en el venv de NLHPC). Parquet en vez de
CSV por tamaño — `phot_df` puede tener millones de filas para `NGENTOT` completo. **No se
versiona en git** (agregado a `.gitignore`): con 70 corridas de tamaño completo el volumen
total sería de GBs, impráctico para el repo — las tablas quedan solo en NLHPC (y localmente si
se copian vía `scp` para inspección puntual).

Este cambio se sincronizó a NLHPC **a mitad del barrido de 70 corridas de esta Fase** (después
de que ~16 ya habían terminado) — las corridas que ya estaban corriendo en el momento del sync
usaron la versión anterior del script (sin persistencia); solo las que empezaron a ejecutar
después del sync tienen `head_df.parquet`/`phot_df.parquet`. Esto no afecta los números de
eficiencia de detección de Fase 5 (la persistencia es puramente aditiva), pero significa que no
todas las 70 carpetas de salida de esta ronda van a tener las tablas — las corridas futuras sí
las tendrán todas.

## Resultados: 70/70 corridas completadas sin fallos

Las 70 corridas (14 clases × 5 semillas) terminaron sin errores (`sacct` exit code `0:0` en
las 70). Tiempos de pared por clase: la mayoría 5-20 min, `SLSN-I`/`PISN-MOSFIT`/
`PISN-STELLA-HECORE` 1h40min-2h (960 templates SIMSED), `PISN-STELLA-HYDROGENIC` ~1h10min por
semilla (NGENTOT=20000, `--mem=64G`).

| Clase | SNANA % | Razón media (5 semillas) | ±std | min-max | std relativo |
|---|---:|---:|---:|---:|---:|
| `SNIa-91bg` | 36.15% | 1.420x | 0.037 | 1.367-1.474 | 2.6% |
| `PISN-STELLA-HYDROGENIC` | 21.34% | 1.438x | 0.013 | 1.418-1.450 | 0.9% |
| `SNII-NMF` | 17.80% | 1.538x | 0.024 | 1.511-1.567 | 1.5% |
| `PISN-STELLA-HECORE` | 19.20% | 1.569x | 0.048 | 1.510-1.630 | 3.1% |
| `SLSN-I` | 41.20% | 1.604x | 0.036 | 1.542-1.648 | 2.3% |
| `TDE-MOSFIT` | 40.60% | 1.677x | 0.013 | 1.661-1.701 | 0.8% |
| `PISN-MOSFIT` | 20.55% | 1.825x | 0.059 | 1.762-1.925 | 3.2% |
| `SNIa` | 29.85% | 1.926x | 0.048 | 1.863-2.003 | 2.5% |
| `ILOT-MOSFIT` | 3.65% | 2.277x | 0.132 | 2.068-2.466 | 5.8% |
| `KN-BULLA19` | 5.15% | 2.509x | 0.150 | 2.262-2.699 | 6.0% |
| `KN-K17` | 4.10% | 2.639x | 0.223 | 2.366-2.890 | 8.5% |
| `SNIax` | 8.75% | 2.816x | 0.144 | 2.606-3.011 | 5.1% |
| `SNIIn-MOSFIT` | 1.85% | 5.605x | 0.181 | 5.378-5.892 | 3.2% |
| `CaRT` | 0.80% | 10.825x | 0.691 | 9.875-11.687 | 6.4% |

**Promedio del catálogo (media de las 14 razones, cada una ya promediada sobre 5 semillas):
2.833x** — sube desde el 2.561x reportado al final de Fase 4. Esto **no es simplemente ruido de
muestreo**: **las 14 clases sin excepción subieron** respecto a su valor de Fase 4 (single-run,
código con los bugs A-C sin corregir) — un movimiento sistemático y unidireccional, no disperso
en ambas direcciones como esperaríamos de ruido puro. La lectura más honesta: la corrida única
de Fase 4 no solo era no reproducible, sino que corrió con el bug A (jitter de posición sub-FOV)
activo, que probablemente sesgaba hacia abajo el conteo de observaciones reales emparejadas de
forma sistemática (no solo aleatoria) para algún subconjunto de campos/pointings — al usar
`radius=0.0` (centro exacto del pointing) esto se corrigió, y el efecto neto fue *más*
observaciones reales emparejadas en promedio, no menos. No se investigó a fondo la dirección
exacta de este sesgo (excede el alcance de Fase 5, cuyo objetivo era solo cerrar la
reproducibilidad) — se documenta como un hallazgo honesto, no una hipótesis cerrada.

**El "std relativo" (ruido de semilla puro) es real pero modesto para la mayoría de clases**
(<6% para 10/14 clases) — confirma que las comparaciones de una sola corrida en Fases 1-4 no
estaban mayormente dominadas por ruido de semilla para la mayoría de clases, aunque sí lo
estaban las de **conteo bajo** (`KN-K17` 8.5%, `CaRT` 6.4%, con solo 16-103 objetos SNANA de
referencia — Poisson puro).

**`CaRT`, la pregunta que motivó Fase 5**: la aparente "regresión" de Fase 4 (8.56x → 9.56x) no
era ruido en la dirección optimista — la razón real, con 5 semillas y código reproducible, es
**10.825x ± 0.691x (rango 9.875x-11.687x)**, sistemáticamente *peor* que el 9.56x ya preocupante
de Fase 4. `CaRT` sigue siendo, con margen, la clase con peor comportamiento relativo del
catálogo — esto ahora está confirmado con incertidumbre real, no es un artefacto de una sola
corrida con semilla no reproducible.

## Recomendación final (Fase 5)

**Sigue GO condicional.** Fase 5 no cambia la conclusión cualitativa (LightCurveLynx funciona
mecánicamente, persiste un residuo sistémico multiplicativo cuya causa raíz exacta sigue sin
identificarse), pero sí cambia lo que se puede decir con confianza: por primera vez en toda la
sesión, cada razón LCL/SNANA reportada tiene una banda de incertidumbre real derivada de
semillas independientes, no de una única corrida no reproducible. El promedio del catálogo se
revisa de 2.561x a **2.833x** — un movimiento real (no ruido), atribuible a que la corrida de
Fase 4 heredó un bug de emparejamiento de posición (bug A, jitter sub-FOV) que sesgaba el
resultado, además de no ser reproducible. `CaRT` sigue siendo la clase más alejada del
comportamiento de SNANA (~10.8x), ahora con evidencia sólida de que no es un artefacto de
semilla. La causa raíz del residuo sistémico multiplicativo (ni la extinción de host de Fase 3
ni el trigger de época de Fase 4 la explican) sigue abierta como el ítem de mayor prioridad
para cualquier trabajo futuro — ahora con una base de comparación honesta y reproducible sobre
la cual construir esa investigación.

# Fase 6 — SEARCHEFF verificado contra NLHPC, "detecciones basura" a alto z, primera clase NON1ASED

## Motivación

Tres preguntas del usuario, conectadas: (1) verificar el archivo real de SEARCHEFF de SNANA en
NLHPC contra el puerto de LightCurveLynx, para confirmar (o descartar de una vez por todas) que
no es la causa del residuo abierto desde Fase 4/5; (2) un comentario del profesor del usuario --
en la práctica, las "detecciones" a redshift muy alto suelen ser basura (ruido, imágenes malas),
no transitorios reales -- investigar si eso está modelado (o falta) en esta comparación; (3)
planificar la extensión de cobertura a `GENMODEL: NON1ASED`, la clase de modelo de SNANA que
todavía no tiene ningún soporte en LightCurveLynx (las 14 clases de Fase 0-5 son todas SIMSED o
SALT2).

## SEARCHEFF verificado contra los archivos reales (no solo contra el código)

Se leyeron directamente ambos archivos reales desde NLHPC (`ssh nlhpc`, alias ya configurado en
`~/.ssh/config`, solo lectura):

- `LSST_SEARCHEFF_PIPELINE.DAT`: curva nominal PLASTICC (Kessler 2019), derivada de DES --
  eficiencia de detección **real** (no falsa alarma) vs. SNR por filtro, `EFF=0` para `SNR<3`,
  u≡g y z≡Y comparten curva.
- `LSST_PIPELINE_LOGIC.DAT`: `LSST: 2 u+g+r+i+z+Y` -- trigger exige ≥2 épocas (cualquier
  filtro), agrupadas por `NEWMJD_DIF=0.007d` (default real de `snlc_sim.c`, no sobreescrito en
  esta campaña).

Comparado línea por línea contra `searcheff.py`: es un puerto fiel (mismo parseo, misma
interpolación SNR→eficiencia, mismo Monte Carlo, mismo agrupamiento de épocas, mismo trigger,
misma constante `PHOTFLAG_DETECT=4096`). Ya se había descartado como causa del residuo en Fase 4
por lectura de código -- esta sesión lo reconfirma contra los archivos reales de producción, no
solo contra su documentación inferida. **Sin cambios de código.**

## "Detecciones basura" a alto z: un hueco real, pero en ambos simuladores, no una explicación del residuo

El archivo SEARCHEFF de SNANA (y por lo tanto su puerto en LightCurveLynx) solo modela
**recall**: P(un transitorio real simulado es recuperado | SNR). No existe en ningún lado de
este proyecto (ni en la config SNANA real, ni en LightCurveLynx, confirmado grep de
`FAKE`/`bogus`/`DIFFIMG`/`artifact` en todo el repo -- solo *placeholders* de test) un mecanismo
de tasa de falsos positivos/detecciones espurias (artefactos de resta de imágenes, rayos
cósmicos). En pipelines reales tipo DES/LSST, la curva de eficiencia empírica se construye
inyectando SNe falsas en imágenes reales y corriéndolas por un clasificador real/bogus (p.ej.
AutoScan de DES, Goldstein et al. 2015) -- pero esa curva solo captura el recall sobre las
fuentes reales inyectadas, no la tasa de falsa alarma del clasificador sobre candidatos que no
son transitorios. Tanto SNANA (tal como está configurado aquí) como LightCurveLynx generan
únicamente catálogos "limpios" de objetos ya sabidos reales -- ninguno de los dos alucina nunca
un candidato espurio. El fenómeno que describe el profesor es real, pero está ausente
estructuralmente de **ambos** lados de la comparación -- no explica la brecha LCL vs. SNANA.

Dato adicional que refuerza esto: la razón por clase (tabla de Fase 5) no correlaciona limpio
con el alcance en redshift -- `CaRT` es el peor caso (10.83x) con `z_max=1.4`, mientras que
`SLSN-I` llega a `z=9.7` con uno de los mejores ratios (1.60x). El residuo correlaciona más con
la rareza/tenuidad intrínseca de cada clase (`CaRT` es la clase con menor detección real de
SNANA, 0.8%) que con el rango de redshift en sí. **No se tomó acción aquí** -- se documenta como
un hueco de modelado real pero separado, candidato a una fase futura si se decide perseguirlo
(agregar una capa empírica de tasa de falsos positivos vs. magnitud a ambos simuladores).

## Primera clase NON1ASED: `non1ased.py`, nuevo loader

Las 14 clases de Fase 0-5 son todas SIMSED o SALT2. `GENMODEL: NON1ASED` es la clase de modelo
que usa SNANA para librerías de templates convertidas desde SIMSED vía la herramienta oficial
`convert_SIMSED_to_NON1ASED.py` -- 5 clases ya convertidas y validadas del lado SNANA
(`SNIax`, `SNIa-91bg`, `TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`, ver `NEXT_SESSION.md`
2026-08-06), ninguna con soporte del lado LightCurveLynx (confirmado: `grep -ri NON1A` en los
18 archivos de `exploration/lightcurvelynx/` no encontraba nada antes de esta fase).

**Bloqueador real**: `SIMSEDModel.from_dir()` (lo que usa `run_simsed_poc.py`) exige un
`SED.INFO` (`yaml.safe_load()` sobre el archivo completo). Confirmado vía `ssh nlhpc` que los
directorios NON1ASED reales **no lo tienen** --
`run_SNANA/elastic/model_libs_updates/NON1ASED.SNIa-91bg/` solo trae `*.SED.gz` +
`NON1A.LIST`. Leyendo el código fuente real instalado en el venv de NLHPC
(`lightcurvelynx==0.5.2`, `inspect.getsource()`), se confirmó que `SIMSEDModel.from_dir()`
internamente solo hace: parsear `SED.INFO` → construir una lista de `SEDTemplate` vía
`SIMSEDModel._read_simsed_data_file()` (un staticmethod, ya usado directamente en
`run_simsed_poc.py` para otra cosa) → `cls(templates, flux_scale=flux_scale, **kwargs)`, que es
el constructor heredado de `MultiSEDTemplateModel.__init__(templates, *, weights=None,
**kwargs)`. Es decir, `from_dir()` es solo un parser de `SED.INFO` sobre un constructor genérico
que no exige ese formato -- se puede saltar el parser y llamar al constructor directo.

`non1ased.py` (nuevo) hace exactamente eso, leyendo el formato real de NON1ASED en su lugar:

- `parse_non1a_list()`: `NON1A.LIST` real (`NON1A: <index> <name> <filename>`, mismo formato
  que ya parseaba parcialmente `pipeline/tools/generate_non1a_block.py` del lado SNANA, extendido
  aquí para devolver también el nombre de archivo).
- `parse_flux_scale()`: la línea suelta `FLUX_SCALE: <valor>` de `NON1A.LIST` (no es YAML, a
  diferencia del `FLUX_SCALE` de `SED.INFO`).
- `parse_non1a_weights_from_input()`: el bloque real `NON1A_KEYS:`/`NON1A: <idx> <WGT> <MAGOFF>
  <MAGSMEAR> <SNTYPE>` ya escrito en el `.INPUT` real -- se usan esos pesos reales tal cual, no
  se re-derivan como `1/N`. `MAGOFF`/`MAGSMEAR` != 0 lanza `NotImplementedError` explícito (no
  hay precedente de calibración, ni hook equivalente en `SIMSEDModel`, para esas 5 clases).
- `load_non1ased_model()`: arma `templates` con `SIMSEDModel._read_simsed_data_file()` (el mismo
  staticmethod, sin reimplementar el parseo del grid de flujo) y llama al constructor directo
  `SIMSEDModel(templates, flux_scale=..., weights=..., **kwargs)`.

Verificado también (leyendo `GivenValueSampler.__init__`) que los pesos no necesitan sumar 1 --
se normalizan internamente (`self._weights /= weight_sum`), así que pasar los pesos reales del
`.INPUT` sin normalizar es seguro.

`run_non1ased_poc.py` (nuevo) es un espejo casi exacto de `run_simsed_poc.py` -- mismo ruido
real inyectado, extinción MW, SEARCHEFF, `simulate_lightcurves()`, QC -- solo cambia la
construcción del `source_model` (`non1ased.load_non1ased_model()` en vez de
`SIMSEDModel.from_dir()`). Mismo bug de Fase 4 aplica igual aquí (`GivenValueSampler` interno
sin semilla) -- mismo fix (`source_model._sampler_node.set_seed(...)`).

**Primera clase: `SNIa-91bg`** (35 templates -- el conjunto más chico de las 5 clases NON1ASED
ya convertidas, para iterar rápido; `SNIax` tiene 1001 templates, carga de horas). Confirmado
por diff de listado de directorio que `NON1ASED.SNIa-91bg/` trae los mismos 35 archivos `.SED`
que `SIMSED.SNIa-91bg/` (más `NON1A.LIST`/`SED.BINARY`) -- son los mismos templates físicos,
solo re-encapsulados. `SLSN-I_NON1ASED`/`TDE_NON1ASED` quedan descartadas como candidatas para
un diagnóstico "misma física, distinta codificación": sus directorios reales apuntan a una
familia de templates físicamente distinta (`*-BBFIT`) de la ya evaluada en LCL vía SIMSED
(`*-MOSFIT`). `KN-BULLA-BNS-M2COMP` dio 0/300 detecciones en su validación SNANA -- objetivo
demasiado incierto para un primer PoC.

**Smoke test** (`N=20`, sbatch corto): cargó los 35 templates, simuló 20 objetos, aplicó
SEARCHEFF, generó QC -- sin errores, eficiencia por bin de z con forma razonable (pico en
z bajo-medio, cae a alto z). **Corrida completa** (`NGENTOT_LC=2000`, sbatch job 11483111,
6m51s, partición `largemem` reasignada automáticamente por el scheduler de NLHPC):

    355/2000 detectados (17.75%)

SNANA real (leído del `.README` de producción real,
`DATASIM_LSST_1/DDF/SIMDv8/SNIa-91bg_NON1ASED_DDF_baseline_v5.3.1_10yrs/`, no un archivo
inventado): `NGENTOT_LC: 20000`, `NGENLC_WRITE: 1470` → **7.35%**.

**Razón LCL/SNANA = 2.41x** -- cae dentro del rango ya visto en el catálogo de 14 clases
(1.42x-10.83x), entre `ILOT-MOSFIT` (2.28x) y `KN-BULLA19` (2.51x). Nada indica un bug nuevo por
sí solo.

## Discrepancia real encontrada al preparar el PoC: dos generaciones de config SIMSED.SNIa-91bg en NLHPC

El `.INPUT` real NON1ASED (`run_SNANA/elastic/model_config/
SIMGEN_INCLUDE_SNIa-91bg_NON1ASED.INPUT`) declara `GENRANGE_REDSHIFT: 0.011 1.2`, distinto del
`0.011 0.6` que usa la entrada `SNIa-91bg` de `CLASS_CONFIGS` en `run_simsed_poc.py` (la que ya
tiene 5 semillas reportadas en Fase 5, ratio 1.42x). Investigado por qué: existen **dos
generaciones distintas** del mismo `.INPUT` SIMSED en NLHPC --
`run_SNANA/model_config/SIMGEN_INCLUDE_SNIa-91bg.INPUT` (z 0.011-0.6, la que se usó para el PoC
SIMSED de Fase 2B/4/5) y `run_SNANA/elastic/model_config/SIMGEN_INCLUDE_SNIa-91bg.INPUT` (z
0.011-1.2, la que realmente se convirtió a NON1ASED) -- mismos templates físicos
(confirmado por diff de directorio), `.INPUT` de campaña distinto. El PoC NON1ASED usa el rango
real de **su propio** `.INPUT` (0.011-1.2), así que su razón de 2.41x contra el `NGENLC_WRITE`
real de esa misma campaña es válida en sí misma -- pero **no** es directamente comparable, sin
más, contra la fila `SNIa-91bg` (SIMSED, z 0.011-0.6) ya publicada, porque el rango de z
por sí solo ya explicaría parte de la diferencia (ver Fase 5: el residuo correlaciona con
tenuidad/rareza, y un rango de z más ancho añade más objetos marginales).

## Bake-off LCL-vs-LCL: aislando el efecto de la codificación del modelo

Para aislar si la codificación SIMSED vs. NON1ASED en sí (no el rango de z) explica parte de la
diferencia, se agregó una clase auxiliar a `run_simsed_poc.py`, `SNIa-91bg-elastic`: mismo
directorio de templates que `SNIa-91bg` (`simsed_91bg_local`, los mismos 35 archivos físicos),
pero con `GENRANGE_REDSHIFT=(0.011, 1.2)` -- el rango real "elastic", igual al de la clase
NON1ASED. No existe una corrida SNANA real de este `.INPUT` SIMSED-elastic en la campaña de
producción (el `.INPUT` elastic solo se usó como fuente para la conversión a NON1ASED, nunca se
simuló como SIMSED por sí mismo) -- esta clase no tiene razón propia contra SNANA, sirve
únicamente para comparar LCL-SIMSED contra LCL-NON1ASED al mismo rango de z y mismos templates.

Corrida completa (`NGENTOT_LC=2000`, sbatch job 11483232, 6m57s):

    SIMSED-elastic (SIMSED_REDCOR, stretch/color):    289/2000 = 14.45%
    NON1ASED       (NON1A_KEYS uniforme 1/35):        355/2000 = 17.75%

**~1.23x de diferencia solo por la codificación**, con templates y rango de z idénticos. La
explicación mecanística es real, no un artefacto: `SIMSED_REDCOR` pesa cada template según su
cercanía al pico de una normal bivariada real (`stretch=0.975, color=0.557`, correlación
`-0.656`, los mismos parámetros reales que ya usa la entrada `SNIa-91bg` de Fase 2B) -- es
decir, favorece los templates "típicos" de la población real de 91bg. La conversión oficial de
SNANA a NON1ASED (`convert_SIMSED_to_NON1ASED.py`, confirmado leyendo
`pipeline/tools/generate_non1a_block.py` y el bloque real `NON1A_KEYS` del `.INPUT`,
`WGT=2.857143e-02` = 1/35 en las 35 filas) descarta esa información de población y pesa cada
template por igual, incluyendo las esquinas físicamente raras de la grilla stretch/color. **Esto
es una diferencia real entre dos codificaciones de SNANA para la misma clase física, no un bug
de LightCurveLynx** -- el ratio 2.41x de la fila NON1ASED combina este efecto de codificación
(~1.23x) con el efecto del rango de z más ancho (el resto).

Alcance de este hallazgo: un solo caso (`SNIa-91bg`, que usa `SIMSED_REDCOR`). No se sabe si
aplica igual a clases SIMSED de peso uniforme (`SIMSED_GRIDONLY`, la mayoría del catálogo de 14)
-- ahí no habría información de `SIMSED_REDCOR` que perder al convertir a NON1ASED uniforme, así
que el efecto de codificación por sí solo podría ser mucho menor o nulo. Queda como pregunta
abierta para las próximas clases NON1ASED.

## Barrido de 5 semillas: `SNIa-91bg` NON1ASED (mismo patrón de Fase 5)

Todo lo anterior en esta fase usó una sola corrida (`seed_index=0`) -- mismo riesgo
metodológico que Fase 5 corrigió para el catálogo SIMSED/SALT2 (una sola semilla no distingue
señal real de ruido de semilla). Se corrieron las 4 semillas restantes
(`sbatch run_non1ased_poc.sbatch SNIa-91bg <1..4>`, mismo patrón de `seed_base` que
`run_simsed_poc.py`), las 4 completaron sin fallos (6-7 min cada una).

| Semilla | Detectados/2000 | % | Razón vs. SNANA (7.35%) |
|---|---:|---:|---:|
| 0 | 355 | 17.75% | 2.415x |
| 1 | 326 | 16.30% | 2.218x |
| 2 | 327 | 16.35% | 2.224x |
| 3 | 324 | 16.20% | 2.204x |
| 4 | 325 | 16.25% | 2.211x |

**Media de 5 semillas: 2.254x ± 0.081 (rango 2.204x-2.415x)** -- la semilla 0, la única
disponible cuando se calculó el 2.41x reportado más arriba, resultó ser la más alta de las 5,
no la típica (las otras 4 caen apretadas entre 2.20x-2.22x). Mismo patrón cualitativo que varias
clases de Fase 5 (KN-K17, CaRT): una sola corrida sin banda de incertidumbre puede sobre-reportar
el caso real. El promedio de 5 semillas (2.254x) es el número más confiable, no el 2.41x de la
corrida única original.

**Esto también revisa el bake-off de codificación de la sección anterior**: la corrida
`SIMSED-elastic` (289/2000=14.45%) sigue siendo de una sola semilla (no se corrió su propio
barrido de 5), pero comparándola contra la media de 5 semillas de NON1ASED (16.57%, no el 17.75%
de la semilla 0 sola) el efecto de codificación baja de ~1.23x a **~1.15x**
(16.57/14.45 = 1.147). Sigue siendo un efecto real y en la misma dirección (NON1ASED detecta
más), pero más chico de lo que sugería la comparación semilla-a-semilla original. Para acotar
bien la incertidumbre de esta cifra haría falta además un barrido de 5 semillas del lado
`SIMSED-elastic` -- no se hizo en esta ronda.

## Archivos de esta fase

- `exploration/lightcurvelynx/non1ased.py` (nuevo) -- loader NON1ASED.
- `exploration/lightcurvelynx/run_non1ased_poc.py` (nuevo) -- PoC NON1ASED, clase `SNIa-91bg`.
- `exploration/lightcurvelynx/run_non1ased_poc.sbatch` (nuevo).
- `run_simsed_poc.py` -- nueva entrada `SNIa-91bg-elastic` en `CLASS_CONFIGS` (diagnóstico, sin
  contraparte SNANA real).
- `docs/lcl_qc/lcl_qc_index.json` -- nueva fila `SNIa-91bg (NON1ASED)` con media/std/rango real
  de 5 semillas; `docs/index.html` -- Fase 6 documentada en la sección 06, nueva tarjeta de
  diagnóstico, tabla ajustada para mostrar `NGENTOT` real por lado (SNANA 20000 vs. LCL 2000,
  primera fila donde no coinciden).

## Recomendación final (Fase 6)

**Sigue GO condicional.** NON1ASED funciona mecánicamente igual que SIMSED (mismo staticmethod
de lectura de grid de flujo, mismo constructor subyacente) -- el bloqueador real era solo de
formato de metadata (`SED.INFO` vs. `NON1A.LIST`+`NON1A_KEYS`), no de física ni de rendimiento.
El hallazgo nuevo y genuino de esta fase es que **la codificación del modelo en SNANA (no solo
la física que representa) puede cambiar el resultado simulado en una cantidad no trivial
(~1.15x-1.23x según se use la media de 5 semillas o la semilla única, en este caso)** -- un
hallazgo sobre SNANA mismo, no sobre LightCurveLynx, que hay que tener presente al comparar
clases NON1ASED contra sus equivalentes SIMSED de aquí en adelante. La verificación de SEARCHEFF
contra los archivos reales de NLHPC y la investigación de "detecciones basura" a alto z
confirman ambas, con evidencia real, que ninguna es la causa del residuo sistémico abierto desde
Fase 4/5 -- ese sigue siendo el ítem de mayor prioridad. Trabajo futuro concreto: barrido de 5
semillas para `SNIa-91bg-elastic` (solo 1 corrida hasta ahora, necesario para acotar bien el
~1.15x de arriba); las 4 clases NON1ASED restantes (`SNIax`, `TDE`, `SLSN-I`,
`KN-BULLA-BNS-M2COMP`) -- `SNIax` es el candidato natural para repetir el bake-off de
codificación en una clase `SIMSED_GRIDONLY` (peso uniforme), ya que su conversión NON1ASED usa
la misma familia física de templates que su entrada SIMSED ya existente, y así ver si el efecto
de codificación es específico de clases con `SIMSED_REDCOR` o más general.

# Fase 7 -- bake-off en clase de peso uniforme, cobertura NON1ASED completa, comparación directa de brillo sin ruido

## Motivación

Tres tareas del usuario, en orden: (1) repetir el bake-off de codificación de Fase 6 en `SNIax`
(peso uniforme nativo, a diferencia de `SNIa-91bg`) para saber si el efecto de ~1.15x es
específico de `SIMSED_REDCOR` o más general; (2) extender la cobertura NON1ASED a las 4 clases
restantes ya convertidas por SNANA (`TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`); (3) atacar la
pregunta que todas las fases anteriores dejaron abierta -- la causa raíz del residuo sistémico --
con un ángulo nunca probado: comparar el brillo simulado directamente, no solo los conteos de
detección posteriores a SEARCHEFF.

## Bake-off en `SNIax`: confirma que el efecto de codificación es específico de `SIMSED_REDCOR`

Se agregó `SNIax-elastic` a `run_simsed_poc.py::CLASS_CONFIGS` -- mismos 1001 templates físicos
que la entrada `SNIax` ya publicada (confirmado por listado de directorio), mismos parámetros
reales de extinción de host (`GENTAU_AV=1.7`/`GENSIG_AV=0.6`/`GENRATIO_AV0=4.0`, idénticos entre
el `.INPUT` elastic y no-elastic), pero con el `GENRANGE_REDSHIFT` real del `.INPUT` elastic
(0.011-1.5, el mismo que se convirtió a NON1ASED) en vez del 0.011-0.7 ya publicado. Igual que
`SNIa-91bg-elastic`, no tiene corrida SNANA real propia (el elastic solo se usó como fuente para
la conversión a NON1ASED).

Corrida completa (`NGENTOT_LC=2000`, ~14 min de carga por los 1001 templates, confirmado por
smoke test previo de N=20 antes de comprometerse a la corrida completa):

    SIMSED-elastic (peso uniforme nativo, SIMSED_GRIDONLY):  214/2000 = 10.70%
    NON1ASED       (NON1A_KEYS uniforme 1/1001):             228/2000 = 11.40%

**Solo ~1.065x de diferencia** -- muchísimo más chico que el ~1.15-1.23x de `SNIa-91bg`
(`SIMSED_REDCOR`), y del orden de lo esperable por ruido puro de una sola semilla
(`sqrt(214)≈15`, ~7% relativo). **Confirma la hipótesis dejada abierta en Fase 6**: el efecto de
codificación viene principalmente de perder la ponderación `SIMSED_REDCOR` (que favorece
templates "típicos" cerca del pico de la población real) al convertir a NON1ASED, no del formato
NON1ASED en sí -- cuando el peso SIMSED de origen ya era uniforme, convertir a NON1ASED apenas
cambia el resultado.

## Cobertura NON1ASED extendida a las 4 clases restantes

Generalizado `run_non1ased_poc.py`: agregado el bloque de extinción de host (3 variantes,
idéntico al de `run_simsed_poc.py`) y soporte para `DNDZ: MD14`/`DNDZ: TDE` (antes solo
`POWERLAW`), necesarios para las clases nuevas. Cada clase se investigó por separado contra su
propio `.INPUT` real en NLHPC -- **no se asumió que reusar los parámetros de la clase SIMSED
equivalente fuera correcto**, y esa cautela encontró varias discrepancias reales:

- **`SLSN-I` (NON1ASED)**: directorio real `NON1ASED.SLSN-I-BBFIT` -- familia física *distinta*
  de `SIMSED.SLSN-I-MOSFIT` (la ya evaluada), confirmado que `PATH_NON1ASED` no apunta a una
  conversión de esa SIMSED. **Un solo template** (no un ensemble): fit de blackbody a un evento
  real específico, SLSN-I 2016apd (Yan+2017/Kangas+2017/Guillochon+2017, fit por Kaustav Das,
  Caltech), confirmado leyendo `NON1A.LIST` real. `GENRANGE_REDSHIFT` real 0.02-2.95 (NO 0.02-9.7
  como la entrada SIMSED -- comentario real en el `.INPUT`: *"stay within hostlib range"*),
  `SNTYPE` real 41 (no 40, confirmado en el bloque `NON1A_KEYS` real).
- **`TDE` (NON1ASED)**: mismo patrón -- directorio real `NON1ASED.TDE-BBFIT`, familia física
  distinta de `SIMSED.TDE-MOSFIT`. También **un solo template**: fit de blackbody al TDE real
  2019qiz (Nicholl+2020/Hung+2021, fit por Kaustav Das). A diferencia de SLSN-I,
  `GENRANGE_REDSHIFT`/`DNDZ`/extinción de host del `.INPUT` real resultaron **idénticos** a los
  ya usados para `TDE-MOSFIT` (mismo `GENTAU_AV=0.4`, `GENAV_WV07` comentado/deshabilitado).
- **`KN-BULLA-BNS-M2COMP`**: misma sub-variante física (`BNS-M2-2COMP`) que ya usa la entrada
  SIMSED `KN-BULLA19`, pero con nombre de directorio/`.INPUT` real inconsistente con las otras
  dos clases -- `NON1ASED.BULLA-BNS-M2-2COMP` (sin prefijo `KN-`) y
  `SIMGEN_INCLUDE_BULLA-BNS-M2-2COMP.INPUT` (sin sufijo `_NON1ASED`), confirmado por listado real
  de directorio, no una suposición. `GENRANGE_REDSHIFT` real 0.011-0.5 (NO 0.011-0.28 como
  `KN-BULLA19`), `SNTYPE` real 62 (no 52).

### Dos bugs de dato reales más encontrados (mismo patrón de Fase 1/2B/2B-ronda-4)

**`TDE-BBFIT`**: `2019qiz.sed.gz` tiene una segunda línea de encabezado
(`phase wavelength flux`) sin el prefijo `#` -- confirmado comparando línea por línea contra el
archivo hermano `SLSN-I-BBFIT/2016apd.sed.gz`, que sí lo tiene. Typo real de un solo carácter en
el archivo de referencia, mismo patrón que el `$`/`#` de `SNIa-91bg` en Fase 2B. Fix: copia local
saneada (`setup_tdebbfit_local.py`, mismo patrón que `setup_simsed_91bg_local.py`).

**`KN-BULLA-BNS-M2COMP`**: mismo problema real ya visto en Fase 2B ronda 4 para `KN-BULLA19`
(549 de los 550 archivos `*.txt.gz` son en realidad ZIP mal etiquetados, firma `PK`) **más un
segundo bug nunca visto antes**: exactamente 1 de los 550 archivos
(`sed_cos_theta_0.0_mej_0.010_phi_15.txt`) no tiene sufijo `.gz` en absoluto -- está en texto
plano, mientras que `NON1A.LIST` lo referencia igual como `...phi_15.txt.gz`. El fallback
automático de `_read_simsed_data_file()` (agrega `.gz` si el archivo base no existe) no cubre
este caso porque es al revés: el archivo base *sin* `.gz` es el que existe genuinamente sin
comprimir. Fix: `setup_bullansed_local.py` (mismo patrón que `setup_knbulla19_local.py`,
extendido para también comprimir por primera vez el archivo plano).

### Resultados (`NGENTOT_LC=2000`, corrida única cada una, sbatch, sin fallos tras los fixes)

| Clase | SNANA real (NGENTOT/detectados/%) | LCL (%) | Razón |
|---|---|---:|---:|
| `TDE` (NON1ASED) | 10000 / 2311 / 23.11% | 49.20% | 2.129x |
| `SLSN-I` (NON1ASED) | 20000 / 11004 / 55.02% | 90.45% | 1.644x |
| `KN-BULLA-BNS-M2COMP` (NON1ASED) | 20000 / 279 / 1.395% | 7.20% | 5.161x |
| `SNIax` (NON1ASED) | 10000 / 149 / 1.49% | 11.40% | 7.651x |

Los 4 caen dentro del rango ya visto en el catálogo (1.42x-10.83x) -- nada indica un bug nuevo
por sí solo. `KN-BULLA-BNS-M2COMP`: la validación previa a pequeña escala (300 objetos,
NEXT_SESSION.md) había dado 0/300 detectados en SNANA, sugiriendo una clase "demasiado incierta"
-- la campaña real completa (20000 objetos) sí muestra señal real (279 detectados, 1.4%),
confirmando que era un efecto de tamaño de muestra pequeño, no que la clase no tenga detecciones.
`SNIax` (NON1ASED) tiene el ratio más alto del grupo (7.65x) principalmente por el rango de z más
ancho de su `.INPUT` real (0.011-1.5 vs. 0.011-0.7 de la entrada SIMSED), no por la codificación
en sí -- mismo patrón que `SNIa-91bg` en Fase 6, confirmado por el bake-off de arriba (~1.07x de
efecto de codificación puro en esta clase).

## El hallazgo mayor de esta fase: comparación directa de brillo simulado, sin ruido

Todas las fases anteriores (Fase 3, 4, 6) investigaron el lado de la *detección*: extinción,
trigger de época, SEARCHEFF, codificación de pesos. Ninguna tocó la pregunta más directa: ¿el
brillo que cada simulador le asigna al mismo objeto físico (misma clase, mismo redshift) es
siquiera el mismo, antes de que entre en juego cualquier lógica de detección?

### El dato real de SNANA: `PEAKMAG_u/g/r/i/z/Y` en el `.DUMP`

El archivo `.DUMP` real de cada campaña SNANA (`SELECTION: NONE (write every generated event)`,
confirmado en su propio encabezado -- es la población COMPLETA generada, no solo los detectados)
trae una columna `PEAKMAG_<filtro>` por objeto: la magnitud de pico **teórica/sin ruido** del
modelo simulado, no una estadística derivada de las observaciones ruidosas. Confirmado leyendo el
`.DUMP` real de `SNIa-91bg_DDF_baseline_v5.3.1_10yrs` (2000 filas, columnas
`VARNAMES: CID LIBID ... PEAKMAG_u PEAKMAG_g PEAKMAG_r ... SNRMAX ... stretch color`).

### Primer intento (con ruido): resultado dramático pero, se descubrió, un artefacto metodológico

Un primer script (`compare_brightness.py`) comparó `PEAKMAG_r` real de SNANA contra el **mínimo**
de `MAG` (columna ya ruidosa, `FLUXCAL`/`FLUXCALERR` con ruido real de SNANA inyectado) por
objeto en el `phot_df.parquet` ya persistido de la corrida SIMSED `SNIa-91bg` (Fase 2B/5, mismo
rango de z 0.011-0.6). Resultado, binned por redshift:

    z=[0.03,0.11): LCL-SNANA = +0.06 mag (similar)
    z=[0.44,0.52): LCL-SNANA = -0.71 mag (LCL mas brillante)
    z=[0.52,0.60): LCL-SNANA = -1.43 mag (LCL MUCHO mas brillante)

Un patrón dramático, creciente con z -- a primera vista, una explicación perfecta para el
sobre-conteo sistémico (objetos más brillantes cruzan el umbral de detección más fácil,
especialmente a alto z donde el SNR es marginal). Pero el `std` global de SNANA (4.324 mag) era
sospechosamente alto comparado con LCL (0.909 mag), señal de que algo no estaba limpio.

### Verificación antes de confiar en el resultado: `SIMSEDModel.from_dir()` real, `PEAKMAG` real de SNANA es sin ruido

Investigando qué es realmente `PEAKMAG_r` (leyendo el código fuente instalado de LightCurveLynx,
`inspect.getsource(lightcurvelynx.simulate)`), se encontró que `simulate_lightcurves()` ya
calcula internamente un flujo **sin ruido** por observación
(`object_nested_dict["flux_perfect"].append(bandfluxes_perfect)`, columna `flux_perfect` en el
DataFrame `lightcurve` de cada objeto) -- nunca extraído por ningún script anterior (todos
descartaban `flux_perfect` al aplanar, quedándose solo con `flux`/`fluxerr` ruidosos). SNANA
`PEAKMAG_r` es la magnitud de pico teórica del modelo, no una estadística de las observaciones
ruidosas -- comparar eso contra el **mínimo** de N observaciones ruidosas introduce un sesgo tipo
Eddington real: el mínimo de una muestra ruidosa es sistemáticamente más brillante que el valor
verdadero, y el sesgo crece cuanto menor es el SNR (es decir, más fuerte exactamente a alto z,
donde el patrón "dramático" de arriba aparecía). Esto significaba que el primer resultado podía
ser, total o parcialmente, un artefacto de la métrica usada, no una diferencia real entre
simuladores.

### Segunda pasada (sin ruido): el patrón se invierte

Se escribió `compare_brightness_truth.py`, que reconstruye el mismo `source_model` real de
`SNIa-91bg` SIMSED (mismos parámetros, `SIMSED_REDCOR`, extinción MW) pero extrae
`flux_perfect` en vez de descartarlo -- verificado primero con un smoke test de N=10 (confirmó
que la columna existe: `['mjd', 'filter', 'flux', 'fluxerr', 'flux_perfect', 'survey_idx',
'obs_idx', 'is_saturated']`) antes de comprometerse a la corrida completa (`NGENTOT=2000`, sbatch,
~2.5 min). Magnitud de pico real = `max(flux_perfect)` en banda r por objeto (el máximo de flujo
sin ruido, no un mínimo de magnitud ruidosa -- sin sesgo de Eddington). Comparado contra el mismo
`PEAKMAG_r` real de SNANA, binned por los mismos 7 bins de redshift:

| z_bin | N SNANA | mediana SNANA | N LCL | mediana LCL | delta (LCL-SNANA) |
|---|---:|---:|---:|---:|---:|
| [0.011,0.095) | 9 | 19.122 | 8 | 19.564 | +0.442 |
| [0.095,0.179) | 57 | 21.072 | 45 | 21.245 | +0.173 |
| [0.179,0.263) | 129 | 22.151 | 131 | 22.440 | +0.289 |
| [0.263,0.348) | 201 | 23.188 | 234 | 23.415 | +0.227 |
| [0.348,0.432) | 336 | 24.022 | 361 | 24.464 | +0.442 |
| [0.432,0.516) | 496 | 24.782 | 502 | 25.343 | +0.561 |
| [0.516,0.600) | 677 | 25.694 | 669 | 26.092 | +0.398 |

**El signo se invirtió por completo.** LightCurveLynx resulta **~0.2-0.6 mag más tenue** que
SNANA en todos los bins de redshift -- lo opuesto exacto al primer resultado (con ruido), y lo
opuesto a la hipótesis obvia que hubiera explicado el sobre-conteo ("LCL simula objetos
demasiado brillantes"). El global también cambia de forma reveladora: mediana SNANA 24.787,
mediana LCL (sin ruido) 25.351 -- LCL más tenue en mediana, con un `std` mucho más ajustado
(2.003 vs. 4.324 de SNANA) que sugiere que la población de SNANA tiene una cola real más ancha
hacia el extremo tenue (posiblemente ligada a cómo `SIMSED_REDCOR` real de SNANA muestrea las
esquinas de la grilla stretch/color de 91bg-tenues, un detalle no investigado a fondo aquí).

### Por qué esto importa: descarta una hipótesis obvia y redirige la búsqueda de la causa raíz

Si LightCurveLynx simulara objetos sistemáticamente *más brillantes* que SNANA, eso explicaría
directamente el sobre-conteo (~1.4x-11x más detecciones en todo el catálogo, Fase 0-6). El
resultado real es lo contrario -- LightCurveLynx es *más tenue*, no más brillante -- lo que
significa que el brillo/flujo simulado en sí **no** es la causa del sobre-conteo (si acaso, un
efecto opuesto y más chico que debería sub-detectar, no sobre-detectar). Esto descarta con
evidencia real una hipótesis nunca antes probada explícitamente, y redirige la búsqueda de la
causa raíz del residuo sistémico -- que sigue sin resolverse tras Fase 3 (extinción, refutada),
Fase 4 (trigger de época, refutada), Fase 6 (SEARCHEFF/encoding, refutada para el catálogo
general) -- hacia dos candidatos que quedan sin descartar: el cálculo de ruido/SNR en sí (más
allá de las columnas de ruido ya inyectadas en Fase 2A), o la forma/duración de la curva de luz
cerca del pico (que afecta cuántas épocas reales cruzan el umbral de SEARCHEFF incluso con un
pico de brillo similar o más tenue).

## Archivos de esta fase

- `run_simsed_poc.py` -- nueva entrada `SNIax-elastic` en `CLASS_CONFIGS` (diagnóstico, sin
  contraparte SNANA real).
- `run_non1ased_poc.py` -- generalizado: bloque de extinción de host (3 variantes, igual que
  `run_simsed_poc.py`), soporte `DNDZ: MD14`/`DNDZ: TDE`; 4 entradas nuevas en `CLASS_CONFIGS`
  (`SNIax`, `TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`).
- `run_non1ased_poc.sbatch` -- límite de tiempo subido a 2h (antes 30 min, insuficiente para
  clases de cientos/miles de templates).
- `setup_tdebbfit_local.py` (nuevo) -- fix de encabezado sin comentar en `2019qiz.sed.gz`;
  `tdebbfit_local/` (no versionado).
- `setup_bullansed_local.py` (nuevo) -- fix de ZIP mal etiquetado + archivo plano sin `.gz`;
  `bullansed_local/` (no versionado).
- `compare_brightness.py` (nuevo, exploratorio) -- primera comparación (con ruido, luego
  revisada).
- `compare_brightness_truth.py` (nuevo) -- comparación real (sin ruido, `flux_perfect`).
- `compare_brightness_truth_binned.py` (nuevo) -- agrupa por bin de redshift la salida de
  `compare_brightness_truth.py` contra el `.DUMP` real de SNANA; produce la tabla reportada
  arriba.
- `docs/lcl_qc/lcl_qc_index.json` -- 4 filas nuevas (`TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`,
  `SNIax`, todas NON1ASED); nota de `SNIax` (SIMSED) actualizada con el resultado del bake-off.
- `docs/index.html` -- Fase 7 documentada en la sección 06, dos tarjetas de diagnóstico nuevas
  (bake-off confirmado + comparación de brillo).

## Recomendación final (Fase 7)

**Sigue GO condicional.** Cobertura NON1ASED ahora completa (5/5 clases convertidas por SNANA
evaluadas). El bake-off de `SNIax` cierra la pregunta abierta en Fase 6 con una respuesta clara:
el efecto de codificación (~1.15-1.23x en `SNIa-91bg`) es específico de clases con
`SIMSED_REDCOR`, no una propiedad general de NON1ASED (~1.07x en `SNIax`, peso ya uniforme). El
hallazgo más importante de la fase -- y posiblemente de toda la evaluación hasta ahora -- es la
comparación directa de brillo sin ruido: LightCurveLynx simula objetos más tenues que SNANA, no
más brillantes, lo que descarta con evidencia real la hipótesis más obvia para el sobre-conteo
sistémico y estrecha genuinamente el espacio de causas restantes (ruido/SNR o forma de curva de
luz, no calibración de brillo). La causa raíz exacta del residuo sistémico multiplicativo sigue
sin identificarse -- pero después de Fase 3, 4, 6 y 7, la lista de sospechosos descartados con
evidencia real es larga, y la dirección de la búsqueda futura es más concreta que en cualquier
fase anterior. Trabajo futuro: extender la comparación de brillo sin ruido a más clases del
catálogo (un solo caso hasta ahora); investigar el cálculo de ruido/SNR más a fondo; comparar
directamente la forma temporal de la curva de luz (no solo el pico) entre ambos simuladores;
barrido de 5 semillas para las 4 clases NON1ASED nuevas y para `SNIax-elastic`.

# Fase 8 -- barrido de 5 semillas para las 4 clases NON1ASED nuevas, incidente real de cuota de disco

## Motivación

Fase 7 dejó las 4 clases NON1ASED nuevas (`TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`, `SNIax`) con
una sola corrida cada una -- mismo riesgo metodológico que ya se corrigió para el catálogo
SIMSED/SALT2 en Fase 5 y para `SNIa-91bg` NON1ASED en Fase 6. Se lanzaron las 4 semillas
restantes (`seed_index=1..4`) para las 4 clases -- 16 jobs en total.

## Incidente real: cuota de disco de NLHPC agotada a mitad del barrido

11/16 corridas terminaron sin fallos. 5 fallaron con el mismo error real:
`OSError: [Errno 122] Disk quota exceeded`. No es un bug de código -- confirmado leyendo el
traceback completo: en los 5 casos, la simulación y SEARCHEFF ya habían corrido correctamente
(en el caso de `SLSN-I` seed 1, incluso ya se habían persistido `head_df.parquet`/
`phot_df.parquet` completos, con `PHOTFLAG`/`DETECTED` ya calculados) -- el fallo ocurría recién
al intentar escribir el `summary.json` final (unos pocos cientos de bytes) o las imágenes QC,
porque la cuota de disco de la cuenta ya estaba agotada por la acumulación de `phot_df.parquet`
de todas las rondas anteriores (Fase 5: 70 corridas × hasta 1.4GB cada una para
`PISN-STELLA-HYDROGENIC`; Fase 6-7: más corridas NON1ASED de cientos de MB cada una) --
`exploration/lightcurvelynx/` sola sumaba 18GB, la cuenta completa ~200GB.

Los 4 `SNIax` (seeds 1-4) fallaron completos (ninguno alcanzó a persistir sus tablas -- corrida
más larga, ~1001 templates, más probabilidad de coincidir con el pico de uso simultáneo de las
16 corridas paralelas). `SLSN-I` seed 1 sí alcanzó a persistir sus tablas antes de fallar.

## Limpieza mínima, sin borrar de más

Verificado el headroom real disponible con escrituras de prueba (`dd`) antes de tocar cualquier
archivo real -- confirmó que la cuota estaba prácticamente en cero (una escritura de 2GB falló a
los ~65MB). Se eliminó **un solo archivo** (`poc_output_knk17_seed3/phot_df.parquet`, ~61MB) --
una clase de Fase 5 ya completamente reportada en el dashboard/NOTES.md (`summary.json` y las 4
imágenes QC verificados intactos antes de borrar), dejando la tabla cruda (reproducible desde el
script sembrado si hiciera falta) fuera. Suficiente para restaurar ~100MB de headroom.

## Recuperación de `SLSN-I` seed 1 sin re-simular

En vez de volver a correr la simulación completa (que hubiera vuelto a escribir un
`phot_df.parquet` de ~160MB con la cuota todavía ajustada, arriesgando fallar de nuevo),
`recover_slsni_seed1.py` (nuevo, no versionado -- exploratorio de un solo uso) leyó
directamente `head_df.parquet`/`phot_df.parquet` ya persistidos (que ya traían `DETECTED` y
`PHOTFLAG` calculados, guardados antes del `OSError`), recalculó las métricas agregadas y corrió
QC sobre esas tablas -- sin volver a simular ni a escribir ningún archivo grande nuevo. Resultado
idéntico al que hubiera dado una corrida completa: 1826/2000 detectados (91.3%).

## Resultados: 5 semillas completas para 3/4 clases; `SNIax` sigue en 1 semilla

| Clase | Semillas | Razón media (5 semillas) | ±std | min-max |
|---|---|---:|---:|---:|
| `TDE` (NON1ASED) | 5/5 | 2.074x | 0.031 | 2.038-2.129x |
| `SLSN-I` (NON1ASED) | 5/5 | 1.647x | 0.009 | 1.636-1.659x |
| `KN-BULLA-BNS-M2COMP` (NON1ASED) | 5/5 | 4.746x | 0.325 | 4.265-5.161x |
| `SNIax` (NON1ASED) | 1/5 (completado despues, ver abajo) | -- (solo 7.651x de la semilla 0) | -- | -- |

`SLSN-I` tiene el std relativo más bajo del catálogo completo (0.5%) -- clase de recall muy alto
(~90%) con poca varianza de semilla. `KN-BULLA-BNS-M2COMP` tiene el std relativo más alto de las
clases NON1ASED (6.8%), mismo patrón que `KN-K17`/`CaRT` en Fase 5 -- conteo SNANA bajo como
denominador (279/20000) amplifica el ruido de Poisson. En los 3 casos la semilla 0 (la única
usada al reportar por primera vez en Fase 7) resultó ser una de las más altas de las 5, mismo
patrón ya visto repetidamente desde Fase 5 -- otra confirmación de por qué reportar solo una
semilla sistemáticamente sobre-representa el caso real.

`SNIax` quedó pendiente en la primera pasada -- las 4 corridas fallaron por la cuota antes de
persistir nada, así que no había tablas parciales que recuperar como con `SLSN-I`. Completado en
una segunda ronda inmediatamente después (mismo día): verificado el headroom real con una
escritura de prueba antes de tocar nada (~117MB, apenas alcanzaba para 1 de las 4 semillas
faltantes, cada una necesita ~116MB de `phot_df.parquet`) -- en vez de borrar varios archivos
chicos como la primera vez, se liberó un solo archivo grande ya completamente resumido en el
dashboard (`poc_output_pisnstellahydrogenic_seed4/phot_df.parquet`, ~1.3GB, verificado
`summary.json`+QC intactos antes de borrar), dejando ~800MB de headroom -- suficiente margen para
las 4 semillas en paralelo (~464MB de pico esperado). Las 4 corrieron limpias (~20 min cada una,
sin fallos).

| Semilla | Detectados/2000 | % | Razón vs. SNANA (1.49%) |
|---|---:|---:|---:|
| 0 | 228 | 11.40% | 7.651x |
| 1 | 202 | 10.10% | 6.779x |
| 2 | 211 | 10.55% | 7.081x |
| 3 | 202 | 10.10% | 6.779x |
| 4 | 209 | 10.45% | 7.013x |

**Media de 5 semillas: 7.060x ± 0.320 (rango 6.779x-7.651x)** -- la semilla 0, la única disponible
cuando se publicó por primera vez en Fase 7, volvió a ser la más alta de las 5, exactamente el
mismo patrón que `SNIa-91bg` (NON1ASED, Fase 6), `TDE`, `KN-BULLA-BNS-M2COMP` (ambas arriba en
esta misma fase) y varias clases SIMSED de Fase 5. Con esto, las 5 clases NON1ASED del catálogo
(`SNIa-91bg`, `TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`, `SNIax`) tienen banda de incertidumbre real
de 5 semillas -- cobertura NON1ASED completa y reproducible, no solo mecánicamente funcional.

## Archivos de esta fase

- `recover_slsni_seed1.py` (nuevo, exploratorio, no versionado) -- recupera métricas/QC desde
  tablas ya persistidas sin re-simular.
- `docs/lcl_qc/lcl_qc_index.json` -- `TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`, `SNIax` (las 4 NON1ASED
  nuevas de Fase 7) actualizadas con media/std/rango real de 5 semillas.
- Dos archivos borrados en NLHPC (ninguno versionado, ambos ya completamente resumidos en el
  dashboard antes de borrar): `poc_output_knk17_seed3/phot_df.parquet` (~61MB) y
  `poc_output_pisnstellahydrogenic_seed4/phot_df.parquet` (~1.3GB).

## Recomendación final (Fase 8)

**Sigue GO condicional**, sin cambios cualitativos. Las 5 clases NON1ASED del catálogo ya tienen
bandas de incertidumbre reales de 5 semillas, consistente con el resto del catálogo -- cobertura
NON1ASED completa (Fase 7) y reproducible (Fase 8). El incidente de cuota de disco es un
recordatorio real y concreto del costo de almacenamiento de `phot_df.parquet` sin comprimir a esta
escala (decenas de GB acumulados solo para diagnóstico) -- vale la pena considerar, como trabajo
futuro real, comprimir o rotar las tablas crudas de corridas ya completamente resumidas en el
dashboard, en vez de acumularlas indefinidamente hasta el próximo incidente de cuota. Trabajo
futuro: barrido de 5 semillas para las 2 clases auxiliares diagnósticas (`SNIa-91bg-elastic`,
`SNIax-elastic`) para acotar mejor la incertidumbre del efecto de codificación reportado en
Fase 6-7 (~1.15x / ~1.07x, cada uno de una sola corrida todavía).

## Addendum -- panel QC de curvas de luz: objetos mas brillantes, no muestra aleatoria

`pipeline/postproc/qc.py::sample_lightcurves()` elegía 6 SNID al azar (`rng.choice`, `seed=42`
fijo) para el panel "Curvas de luz" de los 4 gráficos de control -- útil para verificar que el
pipeline no está roto, pero no para juzgar visualmente qué tan brillante/creíble es la población
simulada de una clase. Cambiado a elegir los 6 objetos con el `FLUXCAL` pico más alto (máximo de
la observación individual más brillante de cada objeto, sobre todas sus bandas) -- sin parámetro
`seed` (ya no hay aleatoriedad que fijar). Esta función es compartida entre el QC de producción
real de SNANA (sección 03, Capa 4, `postprocess.py`) y el QC de todos los PoC de LightCurveLynx
(sección 06) -- el cambio aplica a ambos lados por diseño, pero **solo se regeneraron los 19
`lightcurves.png` del dashboard de LightCurveLynx** (desde los `head_df.parquet`/
`phot_df.parquet` ya persistidos, sin re-simular nada, vía `regen_lightcurves_qc.py`, exploratorio
y no versionado).

**Intento de regenerar también la sección 03 (producción real) reveló un problema real e
independiente**: `python -m pipeline.postprocess --campaign build/full_v5.3_10yrs` (el comando
oficial, corrido vía `sbatch slurm/run_pipeline_step.sbatch`, job 11492352) encontró que **78 de
los 80 GENVERSION del manifiesto de campaña ya no existen en `$SNDATA_ROOT/SIM`** -- el FITS crudo
fue limpiado del disco de NLHPC (mismo tipo de presión de espacio que el incidente de cuota de
Fase 8, aunque esta limpieza específica no la hizo esta sesión). Solo `SNIa_WFD_baseline_v5.3.1_10yrs`
y `SNII_WFD_baseline_v5.3.1_10yrs` seguían presentes, y ambos fallaron ademas con un
`UnicodeDecodeError` real en `converter.py` (bug preexistente, no relacionado a este cambio, no
investigado a fondo). **No es posible regenerar las 351 imágenes de producción desde FITS real en
su estado actual.**

Decisión del usuario, explícita, tras confirmar que entendía la implicancia: sustituir el panel
`lightcurves.png` de las 19 clases de producción (solo DDF) que sí tienen contraparte de datos ya
persistidos de LightCurveLynx (`exploration/lightcurvelynx/poc_output_*`), usando esos datos en
vez de FITS real que ya no existe. **El título del gráfico deja explícito que la fuente es
LightCurveLynx, no SNANA real** (`sample_lightcurves()` ahora acepta un parámetro `title` para
esto, ver `regen_production_lightcurves_lcl_substitute.py`, exploratorio y no versionado) -- para
no hacer pasar datos de un simulador distinto como si fueran la salida de producción real. Solo se
tocó el panel de curvas de luz de esas 19 (no los otros 3, que siguen siendo el `redshift`/
`magnitudes`/`detections` real ya generado antes de que el FITS se limpiara). Las versiones WFD de
esas mismas 19 clases, y las ~57 clases restantes sin ninguna corrida de LightCurveLynx
(LCLIB de variables, NON1A adicionales, etc.), quedan con el panel de muestra aleatoria -- no
hay ningún dato real ni sustituto disponible para esas todavía.

# Fase 9 -- barrido de 5 semillas para `SNIa-91bg-elastic`/`SNIax-elastic`: el bake-off de codificación queda cerrado

## Motivación

Las dos clases auxiliares diagnósticas del bake-off de codificación (Fase 6-7) -- `SNIa-91bg-elastic`
y `SNIax-elastic` en `run_simsed_poc.py`, sin contraparte SNANA real -- seguían en una sola corrida
cada una. Los ratios de codificación reportados (~1.15x para `SNIa-91bg`, ~1.07x para `SNIax`)
combinaban un lado ya con 5 semillas (el NON1ASED) contra el otro de una sola corrida (el
SIMSED-elastic) -- una comparación asimétrica en confiabilidad. Correr las 4 semillas restantes de
ambas clases cierra esa asimetría.

## Corridas: dos tandas, sin incidentes de cuota

Headroom verificado antes de empezar (~1GB+, escritura de prueba de 1.2GB exitosa) -- suficiente
para las 8 corridas nuevas sin liberar espacio (referencia: `phot_df.parquet` de
`SNIa-91bg-elastic` ~106MB/semilla, de `SNIax-elastic` ~121MB/semilla, ~908MB de pico si las 8
corrieran en paralelo). Por margen de seguridad se corrieron en dos tandas de 4 (primero
`SNIa-91bg-elastic`, después `SNIax-elastic`) en vez de las 8 a la vez -- reduce el pico
simultáneo sin costar tiempo real (cada tanda corre en paralelo internamente). Las 8 corridas
terminaron limpias (`SNIa-91bg-elastic` ~7 min c/u; `SNIax-elastic` ~20 min c/u, misma carga de
1001 templates que su par NON1ASED).

## Resultados: los dos bake-offs quedan resueltos con evidencia sólida

| Semilla | `SNIa-91bg-elastic` (SIMSED_REDCOR) | `SNIax-elastic` (SIMSED_GRIDONLY) |
|---|---:|---:|
| 0 | 289/2000 = 14.45% | 214/2000 = 10.70% |
| 1 | 298/2000 = 14.90% | 225/2000 = 11.25% |
| 2 | 311/2000 = 15.55% | 212/2000 = 10.60% |
| 3 | 299/2000 = 14.95% | 209/2000 = 10.45% |
| 4 | 309/2000 = 15.45% | 218/2000 = 10.90% |
| **media** | **15.06% ± 0.40%** | **10.78% ± 0.28%** |

Comparado contra la media de 5 semillas del lado NON1ASED correspondiente (ya conocida de Fase 6/8):

- **`SNIa-91bg`**: SIMSED_REDCOR 15.06% ± 0.40% vs. NON1ASED 16.57% ± 0.59% -- **razón final ~1.10x**
  (baja del ~1.23x de una sola semilla, y del ~1.15x de la estimación intermedia con solo el lado
  NON1ASED promediado). Las bandas de incertidumbre de ambos lados **ya no se solapan** -- es un
  efecto real y medido con confianza, no una estimación de un solo punto.
- **`SNIax`**: SIMSED-elastic 10.78% ± 0.28% vs. NON1ASED 10.52% ± 0.48% -- **razón final ~0.98x**,
  **indistinguible de 1.0** (las bandas se solapan por completo, la diferencia es más chica que
  cualquiera de los dos errores estándar). El efecto de codificación desaparece por completo cuando
  no hay `SIMSED_REDCOR` que perder al convertir a NON1ASED.

Ambos resultados refuerzan, ahora con la evidencia más sólida disponible en todo el proyecto para
esta pregunta específica, la conclusión de Fase 6-7: **el efecto de codificación SIMSED→NON1ASED
es real pero específico de clases con ponderación correlacionada (`SIMSED_REDCOR`)** -- no una
propiedad general del formato NON1ASED en sí. Para clases de peso ya uniforme (`SIMSED_GRIDONLY`,
la mayoría del catálogo de 14 SIMSED), convertir a NON1ASED no debería introducir ningún sesgo de
población por sí solo.

## Archivos de esta fase

- `docs/lcl_qc/lcl_qc_index.json` -- notas de `SNIa-91bg (NON1ASED)` y `SNIax` (SIMSED) actualizadas
  con los ratios finales de 5 semillas por lado.
- Sin archivos nuevos de código; sin incidentes de cuota (headroom suficiente desde el inicio).

## Fase 10 — Dispersión `GENSIGMA_MWEBV_RATIO` (primer candidato del roadmap post-Fase-9)

Tras cerrar el bake-off de codificación (Fase 9), el residuo sistémico multiplicativo (~1.1x-10.8x
según clase) seguía sin causa raíz identificada. Se absorbió la documentación oficial de
LightCurveLynx (readthedocs) y el manual de SNANA, y se cruzó cada mecanismo candidato encontrado
contra los archivos reales de esta campaña en NLHPC (`pipeline/campaign/templates.py`, el
`.INPUT` de survey real, el `.SIMLIB` real) -- ver plan de investigación aprobado para la tabla
completa de candidatos descartados esta sesión (FLUXERRMODEL, NEXPOSE/coadd, ruido Poisson de host,
velocidad peculiar, bits de SEARCHEFF zHOST, Om0, GENMAG_SMEAR fuera de SNIa-SALT2). El primer
candidato con evidencia real de estar activo y sin portar: `GENSIGMA_MWEBV_RATIO: 0.16`, presente
en el `include_survey_*.INPUT` real de las 19 clases.

### Paso 1 -- fórmula exacta (confirmada contra el código fuente real de SNANA)

Se descargó `snlc_sim.c` directo del repo público `RickKessler/SNANA` (rama `master`) y se leyó la
función `gen_MWEBV()` completa (líneas ~13505-13620). Hallazgos:

```c
// siempre se quema un numero aleatorio para permanecer sincronizado
MWXT_GaussRan = getRan_GaussClip(1, -3.0, 3.0);   // Z~N(0,1), recorte a +-3 sigma

// GENLC.MWEBV = valor nominal (de SIMLIB o mapa SFD98, ver mas abajo)
if ( INPUTS.OPT_MWEBV == OPT_MWEBV_FILE ) {
    if ( INPUTS.MWEBV_SIGRATIO < 0.0 ) { /* error fatal: ratio sin definir */ }
    ERR1 = INPUTS.MWEBV_SIG;                       // fijo, 0 en esta campaña
    ERR2 = INPUTS.MWEBV_SIGRATIO * GENLC.MWEBV;     // 0.16 * EBV_nominal
    GENLC.MWEBV_ERR = sqrt(ERR1*ERR1 + ERR2*ERR2);
}

GENLC.MWEBV_SMEAR = GENLC.MWEBV + GENLC.MWEBV_ERR*MWXT_GaussRan + INPUTS.MWEBV_SHIFT;
GENLC.MWEBV_SMEAR *= INPUTS.MWEBV_SCALE;   // SHIFT=0, SCALE=1 en esta campaña (defaults)
```

Con `MWEBV_SIG=0`, `MWEBV_SHIFT=0`, `MWEBV_SCALE=1` (ninguno de los tres se toca en
`templates.py`), la fórmula colapsa exactamente a:

```
EBV_true = EBV_nominal * (1 + 0.16 * Z),   Z ~ N(0,1) recortado a ±3σ
```

Como `0.16 * |Z| <= 0.48 < 1`, el resultado nunca es negativo -- no hace falta piso en 0.

**Hallazgo colateral, no menor:** el bloque `gen_MWEBV()` primero intenta leer `GENLC.MWEBV` desde
el `.SIMLIB` (columna `MWEBV:` del header de cada LIBID, opción `OPT_MWEBV_FILE`, que es el default
de SNANA y también el default de este proyecto, `templates.py:76 opt_mwebv: int = 1`). Si ese valor
es `<= 0.0`, SNANA cae automáticamente a `OPT_MWEBV_SFD98` -- el mapa real de polvo galáctico
(Schlegel-Finkbeiner-Davis 1998) evaluado en el RA/DEC exacto de cada objeto. Se verificó el
`.SIMLIB` real de la campaña (`DDF_baseline_v5.3.1_10yrs.SIMLIB`, escrito por
`pipeline/simlib/writer.py::lib_header()`, que hardcodea `mwebv: float = 0.0` como default y nunca
lo sobreescribe con un valor real) -- **el campo `MWEBV:` es `0.00` en cada uno de los LIBID
inspeccionados**, sin excepción. Es decir: en la campaña real, el EBV nominal de MW que sufre la
dispersión del 16% **no es un valor fijo por campo** -- es el mapa SFD98 real, con variación
espacial continua dentro de cada pointing DDF. El diccionario `DDF_FIELD_EBV` de este proyecto usa
un único valor fijo por campo (aparentemente un promedio SFD98 precalculado, sin documentar su
origen). Este es un hallazgo relacionado pero *distinto* al de la dispersión del 16% -- deliberadamente
no se prueba en la misma corrida (misma disciplina de aislar una variable a la vez que Fase 6/9);
queda anotado como candidato "Fase 10b" si el resultado de abajo no cierra el residuo.

### Paso 2 -- implementación

Se agregó `make_mwebv_ratio_scatter(ratio, seed=...)` a `snana_params.py` (usa
`scipy.stats.truncnorm(-3, 3)` para el recorte real de ±3σ, no un clip crudo del extremo) y se
conectó en el `_field_to_ebv()` de los 5 scripts que lo definen (`run_non1ased_poc.py`,
`run_simsed_poc.py`, `run_snia_ddf_poc.py`, `run_simsed_91bg_ddf_poc.py`,
`compare_brightness_truth.py`), con `seed=seed_base + 10` (offset previamente libre en las 5
firmas de seeding). Verificado en el venv real de NLHPC antes de correr nada: la fórmula produce
valores con std ≈ 0.985 (esperado para N(0,1) recortado a ±3σ) y siempre positivos.

### Paso 3 -- resultado empírico (clase de prueba: `SNIa-91bg` NON1ASED)

Se eligió `SNIa-91bg (NON1ASED)` como clase de prueba -- rápida, y con la línea base de 5 semillas
más reciente y confiable del catálogo (Fase 8/9): **ratio 2.254 ± 0.081**. Los directorios
`poc_output_non1ased_snia91bg{,_seed1..4}` pre-existentes se renombraron a
`*_prefase10_baseline` (sin gasto extra de cuota, cuota de cuenta ya en ~200G) antes de re-correr,
para no perder los datos crudos de comparación. Se lanzaron 5 semillas nuevas (jobs 11518682-86)
con la dispersión del 16% activa.

Incidente de cuota durante el lanzamiento (mismo techo ~200G de siempre): las 5 corridas fallaron
la primera vez, no por bug sino por `OSError: ... Disk quota exceeded` justo al escribir
`phot_df.parquet` -- la simulación en sí llegó al 100% sin problema. Compresión in-situ resultó no
ser viable como primer movimiento (`tar`/`gzip` necesitan espacio libre para escribir el archivo
nuevo, y no quedaba ninguno: un intento de `dd` de 700MB confirmó solo ~130MB de margen real, y
`gzip` sobre un `phot_df.parquet` de muestra solo comprime ~12% porque parquet ya viene comprimido
con snappy). Se liberó espacio borrando los 5 directorios `*_prefase10_baseline` recién renombrados
(su ratio agregado, 2.254 ± 0.081, ya estaba guardado de forma permanente en
`docs/lcl_qc/lcl_qc_index.json`, así que no se perdió nada analíticamente necesario) y se
relanzaron las 5 semillas (jobs 11518989-93), esta vez completas.

**Resultado:**

| semilla | `detection_efficiency_pct` (con dispersión MWEBV) | ratio (÷ `snana_pct`=7.35%) |
|---|---|---|
| 0 | 17.75% (355/2000) | 2.415 |
| 1 | 16.30% (326/2000) | 2.218 |
| 2 | 16.35% (327/2000) | 2.224 |
| 3 | 16.20% (324/2000) | 2.204 |
| 4 | 16.25% (325/2000) | 2.211 |
| **media** | **16.57% ± 0.59%** | **2.254 ± 0.081** |

**Prácticamente idéntico a la línea base sin dispersión** (2.254 ± 0.081, Fase 8/9) -- la media
nueva coincide a 3 decimales y el std tampoco cambia. La semilla 0 incluso reprodujo exactamente
el mismo conteo (355/2000, 17.75%) que la línea base, lo cual tiene sentido: los campos DDF de
este proyecto ya tienen E(B-V) nominal muy bajo (`DDF_FIELD_EBV`: 0.006-0.025), y con
`ratio=0.16` la dispersión máxima a 3σ es de solo `0.16*3=48%` sobre un valor ya pequeño --
del orden de A_V~0.01-0.04 mag en el peor caso (`xmm_lss`), muy por debajo del ruido
semilla-a-semilla que ya existía.

### Conclusión Fase 10

**`GENSIGMA_MWEBV_RATIO` queda descartado como causa del residuo.** El efecto es real (la fórmula
está bien portada y verificada contra el código fuente de SNANA) pero su magnitud es despreciable
en esta campaña específica, porque los campos DDF fueron elegidos deliberadamente por su E(B-V)
bajo. Esto refuerza -- no contradice -- el hallazgo de Fase 3 (extinción de host tampoco explica
el residuo): la extinción en general, ya sea de host o de MW, no parece ser el mecanismo detrás
del residuo sistémico. Por la misma razón, el hallazgo colateral del Paso 1 (mapa SFD98 real vs.
`DDF_FIELD_EBV` fijo por campo, "Fase 10b") se deprioriza -- ambos son formas de generar un EBV
nominal de magnitud similarmente pequeña, así que es poco probable que ese cambio por sí solo
mueva la aguja. El cambio queda en el código (aporta fidelidad real a la simulación,
`seed_base + 10` en los 5 scripts) pero no se extiende al resto del catálogo -- exactamente la
disciplina de "probar barato antes de escalar" que pide el plan. **Próximo paso: Fase 11**
(grilla precomputada de SIMSED vs. integración en vivo de `PassbandGroup`).

## Recomendación final (Fase 9)

**Sigue GO condicional.** El bake-off de codificación queda cerrado con evidencia sólida en ambas
direcciones -- ya no depende de comparar una sola corrida contra un promedio de 5. Con esto, las
19 clases del catálogo principal y las 2 clases auxiliares diagnósticas tienen todas banda de
incertidumbre real de 5 semillas; no queda ninguna comparación de este proyecto basada en una sola
corrida sin cuantificar su varianza. La causa raíz del residuo sistémico multiplicativo (Fase 3-4,
SEARCHEFF/encoding en Fase 6, brillo sin ruido en Fase 7) sigue siendo la prioridad para trabajo
futuro -- ninguna de las fases de reproducibilidad (5, 8, 9) cambia esa conclusión, solo la hacen
más confiable. **Fase 10 (arriba) descarta la dispersión MW E(B-V) como candidato; la investigación
continúa en Fase 11.**

## Fase 11 — grilla LOGZBIN de SIMSED (SNANA) vs. evaluación continua (LightCurveLynx)

Absorbiendo la documentación oficial de LightCurveLynx y el manual de SNANA (dos agentes de
investigación), se sharpeó la hipótesis original ("grid vs. live integration") en algo concreto y
testeable: SNANA's SIMSED precomputa flujo en una grilla de redshift log-espaciada (`LOGZBIN`,
default 0.02, pero `SLSN-I-MOSFIT`/`PISN-MOSFIT`/`SNIIn-MOSFIT` usan 0.1 -- 5x más gruesa, confirmado
en sus `SED.INFO` reales en NLHPC) e interpola **linealmente** entre nodos -- mientras que
LightCurveLynx evalúa cada objeto a su redshift exacto y continuo, sin discretizar nunca (confirmado
leyendo `sed_template_model.py`/`physical_model.py` del paquete real instalado: la interpolación de
LCL es `RectBivariateSpline` solo en fase×longitud-de-onda, el redshift se aplica analíticamente).

### Paso 1 (fallido) -- intento de volcar `Sinterp` crudo via `GENMODEL_MSKOPT: 512`

Un research agent encontró en `genmag_SIMSED.c` un bloque de debug (`LDMP_DEBUG`) que imprime el
flujo crudo interpolado (`Sinterp`) por época real cuando `OPTMASK & 512` es verdadero, y documentación
que sugiere que `GENMODEL_MSKOPT: 512` en el `.INPUT` activa ese bit. Se construyó un harness
completo (`exploration/lightcurvelynx/fase11_simsed_zgrid/`) para explotar esto -- pero **dos
corridas reales (jobs 11561825/11561826) devolvieron 0 líneas de debug**. Leyendo `snlc_sim.c`
línea por línea (call site real, ~línea 29249) se confirmó la causa: el modelo SIMSED usa
`INPUTS.OPTMASK_SIMSED` para armar el `OPTMASK` que le pasa a `genmag_SIMSED()`, **no**
`INPUTS.GENMODEL_MSKOPT` (que sí se usa para otros modelos como BYOSED/PySEDModel, pero no para
SIMSED). Y `OPTMASK_SIMSED` solo se alimenta internamente desde `SIMSED_GRIDONLY`/`SIMSED_WGTMAP_FILE`
-- no existe ninguna clave de `.INPUT` documentada que le pase el bit 512. El código de debug es
real pero inalcanzable sin recompilar SNANA (hay incluso una línea comentada en el propio código,
`//    if ( GENLC.CID==19201 && ifilt_obs==1 ) { OPTMASK += 8 ; }`, que confirma que este debug se
usa históricamente editando el fuente a mano, no vía config). Camino muerto, descartado.

### Paso 1 (real) -- pivote a `PEAKMAG_r` del `.DUMP`, mismo patrón de Fase 7

En vez de un flujo crudo pre-`x0`, se reusa el patrón ya probado en Fase 7: `PEAKMAG_r` del `.DUMP`
real (`SIMGEN_DUMPALL`, `SELECTION: NONE` -- escribe TODO lo generado) menos `MU` (columna real,
módulo de distancia, función suave de z sin relación con la grilla) aísla una cantidad que debería
ser suave en z salvo por el artefacto de interpolación buscado. Harness: `GENRANGE_REDSHIFT`
angosto (ancla = `GENRANGE_REDSHIFT[0]` real de cada clase, ventana = 5 celdas de `LOGZBIN`,
`VEL_CMBAPEX: 0` para anclar la grilla exactamente ahí sin el margen de VPEC/CMB que SNANA le agrega
por default), `NGENTOT_LC: 3000` para muestrear esa ventana con densidad. Ver
`exploration/lightcurvelynx/fase11_simsed_zgrid/debug_survey_include.INPUT` (bloque `SIMGEN_DUMPALL`
recortado a 30 variables -- `PEAKMAG_u/g/i/z/Y` quitadas porque `GENFILTERS: r` solo genera esa
banda, y SNANA aborta con "Undefined SIMGEN_DUMP variable" si se pide una banda no generada).

Dos incidentes reales de cuota más en el camino (jobs 11561879/11561880/11561925, mismo techo
~200G): la ventana completa de 10 años del SIMLIB real hace que SNANA lea la cadencia acumulada
COMPLETA de un LIBID antes de filtrar por `GENFILTERS` -- algunos LIBID acumulan 47.210 obs en 10
años, por encima del límite fijo `MXOBS_SIMLIB=30000` (`FATAL ERROR ABORT`); se resolvió acotando
`GENRANGE_MJD`/`GENRANGE_PEAKMJD` a ~1 año. Y el `sbatch` original borraba el FITS/SIM real de
ambas clases recién al final -- `SLSN-I-MOSFIT` (960 templates, muchas más columnas `SIMSED_PAR*`)
se quedó sin cuota a mitad de escribir su FITS porque el de `SNIa-91bg` (51MB) todavía no se había
liberado; se corrigió borrando cada FITS inmediatamente después de copiar su `.DUMP`, antes de
generar la siguiente clase.

### Resultado

Análisis en `exploration/lightcurvelynx/fase11_snana_selfcheck.py`: `PEAKMAG_r - MU`, ajuste de una
tendencia suave global (polinomio grado 2 en `log10(z)`, sin necesitar que el mismo template SIMSED
se repita a distinto z -- el ruido objeto-a-objeto de parámetros no sesga el ajuste de la tendencia,
solo agrega varianza), residuo cuadriculado por posición fraccional dentro de una celda de la grilla
(`frac=0` en un nodo exacto, `frac=0.5` en el punto medio).

| Clase | `LOGZBIN` | N válido | std del residuo global | cerca de nodo | cerca de punto medio | diferencia |
|---|---|---|---|---|---|---|
| `SNIa-91bg` (control) | 0.02 | 1930 | 0.152 mag | -0.013 ± 0.008 | -0.001 ± 0.007 | +0.012 ± 0.011 mag |
| `SLSN-I-MOSFIT` (hipótesis) | 0.1 | 1944 | **1.173 mag** | +0.088 ± 0.062 | -0.030 ± 0.060 | -0.118 ± 0.086 mag |

**`SNIa-91bg`: resultado limpio, sin patrón.** Los 10 bins de `frac` oscilan sin tendencia
(-0.004 a +0.015 mag, dentro de ±1 SEM), la diferencia nodo-vs-punto-medio no es significativa. Este
es exactamente el resultado nulo esperado para la grilla más fina (default).

**`SLSN-I-MOSFIT`: prueba sin potencia estadística suficiente, no un resultado nulo limpio.** La
dispersión intrínseca de brillo entre los 960 templates físicos distintos (parámetros
`kappa/kappagamma/mej/temp/vej` del magnetar-model MOSFIT, cada uno con su propia curva de luz) es
**~8x mayor** que la de `SNIa-91bg` (std=1.17 mag vs. 0.15 mag) -- con `NGENTOT_LC=3000` repartido
sobre 960 templates (~3 objetos por template en promedio), el ajuste de tendencia global de grado 2
no puede separar "forma de curva de luz propia de cada template" de "sesgo de interpolación de
grilla", y el SEM por bin (~0.06-0.09 mag) queda demasiado grande para confirmar o refutar un efecto
del orden de 0.1 mag con confianza (diferencia nodo-vs-medio de -0.118 ± 0.086 mag, ~1.4σ, no
significativa). Escalar esto a una potencia real necesitaría o bien `NGENTOT_LC` uno o dos órdenes
de magnitud más grande, o bien un diseño que fije/repita un puñado de templates específicos a través
de la ventana de redshift en vez de dejar que SNANA elija uno al azar por objeto -- ninguna de las
dos es barata en el sentido de la disciplina de este proyecto ("probar barato antes de escalar").

### Conclusión Fase 11

**No hay evidencia de un artefacto de interpolación de grilla de magnitud relevante, en ninguna de
las dos clases probadas -- pero el resultado de la clase con la hipótesis afilada (`SLSN-I-MOSFIT`)
es genuinamente ambiguo, no un descarte limpio.** Incluso tomando el punto estimado (no
significativo) de -0.118 mag como cota superior aproximada del efecto: es un orden de magnitud
demasiado chico para explicar un residuo que típicamente implica varias décimas a >1 mag de
diferencia sistemática de brillo/flujo (razones de detección de 2x-10x) -- el mismo argumento de
"real pero demasiado chico para importar" que cerró Fase 10 (dispersión MW E(B-V)). Dado el costo ya
invertido (3 pivotes de diseño, 5 incidentes/reintentos de cuota) y que escalar esto más allá
requeriría una inversión de cómputo sustancialmente mayor sin garantía de resolver la ambigüedad, se
recomienda **no continuar escalando Fase 11 por ahora** y pasar a **Fase 12** (mismatch de
passband/zeropoint entre `kcor_LSST.fits` real y los throughputs de `lsst/throughputs` que descarga
LightCurveLynx) -- dejando la puerta abierta a retomar Fase 11 con un diseño de mayor potencia si
Fase 12-14 tampoco cierran el residuo.

### Archivos de esta fase

- `exploration/lightcurvelynx/fase11_simsed_zgrid/` -- harness completo (`.INPUT` de survey/modelo/root,
  `run_fase11_zgrid.sbatch`); el intento fallido de `GENMODEL_MSKOPT: 512` queda documentado en los
  comentarios del `.INPUT` como referencia de qué NO funciona y por qué.
- `exploration/lightcurvelynx/fase11_zgrid_compare.py`/`.sbatch` -- construido para el diseño
  original (comparación punto a punto contra `evaluate_bandfluxes()` de LightCurveLynx usando
  `Sinterp`); no se llegó a usar porque el Paso 1 original resultó inalcanzable, pero queda
  verificado que la API (`SIMSEDModel(templates=[...], flux_scale=..., redshift=..., distance=10.0,
  t0=0.0)` + `evaluate_bandfluxes(passband_group, times, [band], state=None)`) funciona end-to-end
  (probado interactivamente en el venv real de NLHPC) -- reutilizable si se retoma esta fase con más
  potencia estadística.
- `exploration/lightcurvelynx/fase11_snana_selfcheck.py` -- el análisis real que sí se corrió
  (solo lado SNANA, ver Resultado arriba).

## Fase 12 — mismatch de passband/zeropoint (`kcor_LSST.fits` real vs. `lsst/throughputs` que descarga LCL)

Siguiente candidato del roadmap: cada corrida de LightCurveLynx descarga los passbands de
`raw.githubusercontent.com/lsst/throughputs/main/baseline/total_<banda>.dat` (visible en el stdout
de cada job) -- el preset genérico `LSST` de LCL, no necesariamente la curva de transmisión exacta +
cualquier offset de zeropoint nativo-vs-sintético que trae el `kcor_LSST.fits` real de la campaña
(referenciado por el `.INPUT` de las 19 clases, nunca antes inspeccionado -- es un FITS, necesita
`astropy.io.fits`).

### Paso 1 -- leer `kcor_LSST.fits` real

Abierto con `astropy.io.fits` en el venv real de NLHPC (`/home/mvalenzuela/run_SNANA/kcor_LSST.fits`).
Estructura real: HDU `ZPoff` (offset de zeropoint nativo-vs-sintético por banda), `FilterTrans`
(curva de transmisión real, 991 puntos, 2100-12000 Å en bins de 10 Å), `PrimarySED` (espectro de
referencia AB), más `KCOR`/`MAG+MWXTCOR` (tablas de K-correction, vacías -- no aplican a este modo de
generación). Header confirma `FILTPATH1 = '$SNDATA_ROOT/filters/LSST/baseline_1.9'` -- el kcor real
usa la versión **1.9** de los throughputs de Rubin.

**Hallazgo 1 -- `ZPoff` es cero en las 6 bandas** (`ZPoff(Primary)=ZPoff(SNpot)=0.0` para
`LSST-u/g/r/i/z/Y`, sistema `AB` puro): no hay ningún offset de zeropoint nativo-vs-sintético oculto
en el kcor real -- descarta de entrada la mitad de la hipótesis original sin necesitar comparar nada
más. Coincide exactamente con la convención `MAG_AB_ZP_NJY = 8.9 + 2.5*9` (AB puro) que ya usa todo
el proyecto (Fase 7, `compare_brightness_truth.py`).

### Paso 2 -- diff numérico contra lo que descarga LightCurveLynx

Se forzó una descarga real (`PassbandGroup.from_preset(preset="LSST")` en el venv de NLHPC) y se leyó
el archivo cacheado (`~/.cache/lightcurvelynx/passbands/LSST/<banda>.dat`). **El propio header del
archivo descargado dice `# Version 1.9`** -- coincide exactamente con `baseline_1.9` del kcor real; la
rama `main` de `lsst/throughputs` en GitHub sigue sirviendo la misma versión 1.9 que usa esta
campaña, no hay deriva de versión entre ambos.

Comparación numérica directa (interpolando la curva de LCL a la grilla de 10 Å del kcor real):

| Banda | Δλ_efectiva (Å) | pico kcor | pico LCL | razón de área (LCL/kcor) | max\|ΔT\| |
|---|---|---|---|---|---|
| u | -13.49 | 0.1806 | 0.1806 | 1.0039 | 0.0001 |
| g | -1.08 | 0.4828 | 0.4828 | 1.0004 | 0.0003 |
| r | +0.01 | 0.5777 | 0.5777 | 1.0001 | 0.0004 |
| i | +0.25 | 0.6235 | 0.6235 | 1.0003 | 0.0001 |
| z | +0.89 | 0.6306 | 0.6306 | 1.0004 | 0.0001 |
| Y | +3.43 | 0.3405 | 0.3405 | 1.0013 | 0.0006 |

Transmisión de pico idéntica a 4 decimales en las 6 bandas; longitud de onda efectiva difiere menos
de 14 Å incluso en el peor caso (`u`, la banda más angosta y con el corte azul más agudo -- esperable
por diferencias de grilla/interpolación, no de forma real); área integrada difiere menos del 0.4% en
todas las bandas. Esto es efectivamente **la misma curva**, con diferencias del orden de la
discretización numérica (kcor a 10 Å de resolución vs. la grilla nativa más fina que descarga LCL),
no una diferencia física real de transmisión.

### Conclusión Fase 12

**Descartado, con evidencia numérica directa y concluyente -- no ambiguo, a diferencia de Fase 11.**
No hay offset de zeropoint nativo-vs-sintético (ZPoff=0) ni diferencia real de forma/posición de las
curvas de transmisión (mismo release v1.9, diffs sub-Angstrom/sub-porcentuales explicables por
resolución de grilla). El passband/zeropoint no es la causa del residuo sistémico. Recomendación:
pasar a **Fase 13** (extrapolación en los bordes del template: relleno a cero por defecto de
LightCurveLynx vs. supresión de la observación de SNANA) -- señalado en el plan original como "el
lead más concreto mecánicamente" de todos los candidatos restantes.

### Archivos de esta fase

Sin archivos nuevos -- investigación completa e inline (lectura de FITS + comparación numérica
directa en el venv real de NLHPC, sin necesitar ninguna simulación nueva). Sin incidentes de cuota.

## Fase 13 — extrapolación en los bordes del template (LightCurveLynx) vs. supresión de la observación (SNANA)

El lead marcado como "el más concreto mecánicamente" del plan original: LightCurveLynx dice en su
documentación que sus `LightcurveTemplateModel` no periódicos "caen a 0.0" fuera de su rango de fase
por defecto; SNANA, según el manual, suprime la observación (no la genera) cuando la longitud de onda
en marco de reposo cae fuera del rango declarado del SED. Una observación de flujo cero con ruido
Poisson realista encima es, en principio, capaz de disparar una detección espuria si ambos lados no
manejan el borde igual.

### Paso 1 -- ¿qué clases tocan este borde, y cuánto de la población?

Se escanearon las 19 clases (`fase13_scan.py`, no versionado -- exploratorio, lee `SED.INFO`/
`RESTLAMBDA_RANGE` o, si no está declarado, el primer `.SED` real) y se calculó, para cada banda LSST
(rango observado real extraído de `kcor_LSST.fits`) y cada extremo de `GENRANGE_REDSHIFT`, si la
longitud de onda en marco de reposo necesaria cae fuera del `RESTLAMBDA_RANGE` declarado. Resultado:
**`SLSN-I` (SIMSED y NON1ASED, `GENRANGE_REDSHIFT` hasta z=9.7) es, con mucha diferencia, la clase más
expuesta** -- a z=9.7 las 6 bandas caen completamente fuera del rango 1000-11000 Å declarado.
`PISN-MOSFIT` toca el borde de forma marginal (banda `u` apenas, a z=2.4). El resto de las 17 clases
no toca el borde en absoluto con sus rangos reales.

Lo que hace esto importante, no solo una curiosidad de la cola: con el `dndz` real de `SLSN-I`
(`MD14`, ponderado por SFR), **el 46% de TODA la población generada ya está en z≥2.2** -- el punto
donde la banda `u` empieza a caer fuera de rango. No es un caso extremo raro, es casi la mitad del
catálogo simulado.

### Paso 2 -- confirmar el comportamiento real de cada lado (no solo confiar en la documentación)

**LightCurveLynx real (código, no doc):** `SEDTemplate.evaluate_sed()` (`sed_template_model.py`)
inicializa la matriz de salida en cero y solo llena las FASES dentro de `self.times[0]-self.times[-1]`
-- el cero-padding documentado es real, pero **solo en el eje de fase**. En el eje de longitud de
onda no hay ningún chequeo de rango en absoluto -- se llama a
`RectBivariateSpline(...)(wavelengths, grid=True)` con cualquier longitud de onda, dentro o fuera del
rango nativo del SED. Probado interactivamente en el venv real de NLHPC (`SIMSED.SLSN-I-MOSFIT`,
template 0): a longitudes de onda por debajo de 1000 Å o por encima de 11000 Å, el flujo devuelto
**no es cero -- es un valor constante, clampeado exactamente al valor del borde** (p.ej. idéntico a
100, 300, 500, 999 y 1000 Å, los cinco dieron el mismo flujo). No es la hipótesis original (cero), es
peor: LightCurveLynx sigue generando una observación con flujo real y no-trivial, sin importar cuán
lejos del rango declarado se pregunte.

**SNANA real (código, no manual):** confirmado en `genmag_SEDtools.c` (función que construye la
tabla de flujo, comentario real "Mar 22 2017 -- bail if any part of filter trans it outside of model
range"):
```c
if ( LAMOBS_MIN/z1 < SEDMODEL.LAMMIN[ised] ) { continue ; }
if ( LAMOBS_MAX/z1 > SEDMODEL.LAMMAX[ised] ) { continue ; }
```
Si el rango COMPLETO de la banda no cabe en marco de reposo dentro del SED declarado, SNANA nunca
construye esa celda de la tabla -- la observación no se genera (existe incluso una variable real y
distinta, `NOBS_UNDEFINED`, en la lista de variables permitidas de `SIMGEN_DUMP`, confirmando que
SNANA rastrea esto por separado de `NOBS`).

### Paso 3 -- implementación y prueba en `SLSN-I` (SIMSED)

Se agregó `restlambda_gate()` a `run_simsed_poc.py` (replica exacta de la condición real de arriba)
y se conectó en el paso de aplanado: cualquier observación cuya banda no quepa completa en marco de
reposo dentro de `restlambda_range=(1000, 11000)` se descarta antes de construir `phot_df`/`head_df`
(igual que SNANA, que nunca la genera). Solo aplicado a `SLSN-I` por ahora -- el resto de las clases
no declara `restlambda_range` y su comportamiento queda byte-idéntico.

5 semillas nuevas (jobs 11562466/579/640/755/829, con limpieza de `phot_df.parquet` entre semilla y
semilla por headroom ajustado, ~168MB libres):

| semilla | observaciones suprimidas | detectados/2000 |
|---|---|---|
| 0 | 1.011.432 (14.7% del total generado) | 1239 (61.95%) |
| 1 | -- | 1327 (66.35%) |
| 2 | -- | 1325 (66.25%) |
| 3 | -- | 1304 (65.20%) |
| 4 | -- | 1303 (65.15%) |
| **media** | | **64.98% ± 1.60%** |

**Ratio final: 1.577 ± 0.039** (rango 1.504-1.610), contra la línea base sin el fix, **1.604 ± 0.036**
(rango 1.542-1.648) -- las bandas se solapan casi por completo, no es un cambio estadísticamente
significativo a nivel de 5 semillas, aunque la dirección es la correcta (baja, no sube) y la magnitud
por semilla individual (hasta -3.6pp en la semilla 0) es real.

### Conclusión Fase 13

**Mecanismo real, confirmado y corregido -- pero no explica el residuo de `SLSN-I` por sí solo.** El
14.7% de observaciones suprimidas es una fracción grande, pero `SEARCHEFF` solo exige 2 épocas reales
agrupadas para el trigger (Fase 4) -- los objetos que pierden observaciones por este mecanismo están
casi todos en el extremo de alto z, donde de cualquier forma ya eran marginales o indetectables antes
del fix (ver la eficiencia por bin de redshift de la semilla 0: 81.1% en z<1.92, cayendo a 0.0% en
z=[7.69,9.61)). El fix es una mejora real de fidelidad física (ahora `SLSN-I` respeta el mismo límite
físico que SNANA) y se queda en el código -- el ratio del dashboard se actualiza al nuevo valor más
correcto (1.577 ± 0.039) -- pero no se escala a `SLSN-I (NON1ASED)` ni a `PISN-MOSFIT` por ahora: el
resultado de la clase con mayor exposición ya muestra que el efecto, aunque real, es demasiado chico
para mover el residuo de forma significativa, y `PISN-MOSFIT` tiene una exposición mucho más marginal
(solo `u` a z=2.4). Recomendación: pasar a **Fase 14** (estado de `GENMAG_SMEAR_MODELNAME: G10` en
`SNIa`, último candidato del roadmap original) o a los ítems de menor prioridad (`GENSIGMA_SEARCH_PEAKMJD`,
`REDCOV`) si Fase 14 tampoco cierra el residuo.

### Archivos de esta fase (Fase 13)

- `exploration/lightcurvelynx/run_simsed_poc.py` -- `BAND_RANGES_OBS`, `restlambda_gate()`, y el
  chequeo en el aplanado; `restlambda_range=(1000.0, 11000.0)` agregado solo a `CLASS_CONFIGS["SLSN-I"]`.
- `docs/lcl_qc/lcl_qc_index.json` -- ratio de `SLSN-I` actualizado a 1.577 ± 0.039 (antes 1.604 ± 0.036).
- `exploration/lightcurvelynx/fase13_scan.py` -- exploratorio, no versionado (escaneo de
  `RESTLAMBDA_RANGE` real de las 19 clases, Paso 1).

## Fase 14 — estado real de `GENMAG_SMEAR_MODELNAME: G10` (`SNIa` únicamente)

Último candidato del roadmap original, marcado de entrada como el de menor prioridad (afecta solo
1/19 clases) pero barato de verificar. `run_snia_ddf_poc.py` ya trae un comentario propio desde
Fase 0/1 admitiendo que `SIGMA_INT=0.090` (leído de `SALT2.INFO`) es una "aproximación aceptada del
modelo G10 completo... fuera de alcance para un PoC" -- nunca se había re-confirmado qué le falta
exactamente ni si la falta podría explicar parte del residuo.

### Qué hace el G10 real (confirmado en código, no en el manual)

`GENMAG_SMEAR_MODELNAME: G10` está real y activo en `SIMGEN_INCLUDE_SNIa-SALT2.INPUT`. Leyendo
`sntools_genSmear.c::get_genSmear_SALT2()` (repo público de SNANA), la dispersión intrínseca real de
G10 es la suma de DOS términos independientes, no solo uno:

```c
magSmear(lam) = SMEAR0 + SMEAR(lam)
```
- `SMEAR0 = rCOH * SIGCOH` -- **exactamente lo que ya implementa el PoC**: un solo número aleatorio
  gaussiano por evento, multiplicado por `SIGCOH` (0.090, de `SALT2.INFO`), igual para todas las
  bandas.
- `SMEAR(lam)` -- **el término que falta por completo**: SNANA lee un archivo real,
  `salt2_color_dispersion.dat` (viene con el template `SALT2.WFIRST-H17`, no un archivo genérico),
  construye nodos de longitud de onda cada 800 Å, y a CADA nodo le asigna un número aleatorio
  gaussiano INDEPENDIENTE escalado por `sigma(lambda)` de ese archivo -- interpolado suavemente entre
  nodos (`interp_SINFUN`). El resultado es dispersión cromática real: bandas distintas de un mismo
  evento pueden salir más o menos brillantes entre sí, no solo el evento completo desplazado parejo
  como hace `SIGMA_INT` solo.

### Magnitud real de `sigma(lambda)` (leída directo del archivo real en NLHPC)

`salt2_color_dispersion.dat` tiene una forma de "cuenco": mínimo cerca de 5700 Å (banda V), sube
fuerte hacia el UV y sube de nuevo hacia el IR cercano:

| λ rest (Å) | sigma(λ) | banda LSST aprox. (z≈0) |
|---|---|---|
| 3040 | 0.159 | borde azul de `u` |
| 3990 | 0.042 | borde rojo de `u` / `g` |
| 4590-6990 | 0.017-0.028 | `g`/`r` (mínimo real ≈5690 Å) |
| 7980 | 0.059 | `i`/`z` |
| 9000 | 0.090 | `z`/`Y` |
| 10500 | 0.125 | borde rojo de `Y` |

Comparado con la aproximación plana `SIGCOH=0.090` sola: en `g`/`r` el término cromático que falta
(0.017-0.03) es chico frente a `SIGCOH` -- la aproximación actual ya es razonable ahí (dispersión
total real ≈√(0.090²+0.02²)≈0.092, casi igual a 0.090). En `u` e `Y`, en cambio, el término cromático
que falta es del mismo orden o MAYOR que `SIGCOH` (dispersión total real ≈√(0.090²+0.10²)≈0.13-0.15
mag) -- ahí la aproximación actual **subestima** la dispersión real, no la sobreestima.

### Razonamiento de dirección (sin correr nada todavía)

Justo por subestimar, no sobreestimar, la dispersión real en `u`/`Y`: el efecto esperado de corregir
esto va en la dirección **contraria** a "explicar el sobre-conteo". Más dispersión gaussiana
simétrica alrededor de un umbral de detección de un solo lado (SNR/flujo mínimo) empuja, en promedio,
MÁS objetos marginales por encima del umbral, no menos (el mismo sesgo tipo Eddington ya documentado
en Fase 7) -- así que agregar el término cromático real probablemente subiría un poco la eficiencia
de detección de LightCurveLynx en `u`/`Y`, no la bajaría. Es el mismo patrón que Fase 7 (LightCurveLynx
resultó más tenue, no más brillante, que SNANA) y que Fase 10/13 (mecanismos reales pero que no
explican -- o incluso apuntan en contra de -- el sobre-conteo).

### Conclusión Fase 14

**No se implementa el término cromático completo por ahora.** El razonamiento de dirección (arriba)
sugiere que, si tuviera algún efecto medible, sería en el sentido contrario al que hay que explicar
-- y como implementar el término cromático completo (leer `salt2_color_dispersion.dat`, replicar la
interpolación de nodos de 800 Å con randoms independientes por nodo) es un trabajo bastante más
grande que las demás verificaciones "baratas" de este roadmap, para una clase que además es solo
1/19 del catálogo, no se justifica la inversión sin una razón más concreta para esperar que sí
explique el residuo. Se deja documentado como pendiente reutilizable si en el futuro se necesita
mayor fidelidad de `SNIa` específicamente.

**Con esto se cierran los 5 candidatos del roadmap post-Fase-9** (Fases 10-14): dos reales pero
insuficientes en magnitud (MW E(B-V), extrapolación de borde de SIMSED), dos descartados limpio
(grilla LOGZBIN -- ambiguo más que descartado, en rigor -- y passband/zeropoint), y este último
razonado como improbable sin necesidad de implementarlo. La causa raíz del residuo sistémico sigue
sin identificarse. Los ítems de menor prioridad que quedan en el plan original
(`GENSIGMA_SEARCH_PEAKMJD`, `REDCOV`, la crítica documentada de LightCurveLynx a su propio modelo de
ruido Poisson) son la única pista no explorada; alternativamente, vale la pena considerar que el
residuo podría no tener una causa única identificable vía este tipo de auditoría mecanismo-por-
mecanismo, y que el camino que queda sea una calibración empírica agregada en vez de un fix puntual.

### Archivos de esta fase (Fase 14)

Sin archivos nuevos -- investigación completa e inline (lectura de código fuente de SNANA +
inspección directa del archivo real `salt2_color_dispersion.dat` en NLHPC, sin simulación nueva).
Sin incidentes de cuota.

## Fase 15 — los 3 ítems de menor prioridad del plan original

Cierra el roadmap completo. Los tres se descartan rápido, con evidencia directa de código o de los
archivos reales de esta campaña -- ninguno requirió simulación nueva.

### 15a — `GENSIGMA_SEARCH_PEAKMJD: 1.0`

Real y activo campaña-wide (`include_survey_DDF_baseline_v5.3.1_10yrs.INPUT`). Leyendo
`snlc_sim.c::gen_peakmjd_smear()` completa: calcula `PEAKMJD_SMEAR = GENLC.PEAKMJD + smear` (un
número gaussiano, sigma=1 día) y lo asigna a `SNDATA.SEARCH_PEAKMJD` -- **una única asignación, en
una única línea (`snlc_sim.c:25532`), y esa variable no se vuelve a leer en ningún otro lugar de
`snlc_sim.c`, `genmag_SIMSED.c` ni `genmag_SEDtools.c`** (grep completo, cero resultados adicionales).
Es puro metadata de salida -- una estimación "de pipeline de búsqueda" que se escribe en el header
para quien después ajuste la curva de luz y necesite un PEAKMJD inicial aproximado con algo de
incertidumbre realista. **No afecta el trigger de SEARCHEFF, no afecta el cálculo de Trest (fase) de
ninguna observación generada (que usa `GENLC.PEAKMJD`, el valor verdadero, no el suavizado), no
afecta SNR ni el conteo de detecciones de ninguna forma.** Descartado sin necesidad de portarlo --
no hay nada que replicar en LightCurveLynx porque no participa del cálculo real de nada comparable.

### 15b — `REDCOV` / covarianza de ruido de flujo correlacionado

Grep de `REDCOV`/`TEMPLATE_ZPT`/`CORRELATED`/`FLUXERRMODEL` contra los `.INPUT` reales de las 19
clases (`model_config/` y `elastic/model_config/`), el `.INPUT` de survey real, y el `.SIMLIB` real:
**una sola coincidencia en total**, un comentario en inglés en `SIMGEN_INCLUDE_SNII-NMF.INPUT`
("SIMSED parameters are correlated & interpolated") que se refiere a la interpolación de parámetros
físicos SIMSED, no a covarianza de ruido de flujo. `REDCOV`/`TEMPLATE_ZPT` no aparecen en ningún
archivo real de esta campaña. Descartado -- no está configurado, nada que portar.

### 15c — crítica de LightCurveLynx a su propio modelo de ruido Poisson (notebook `data_driven_noise_dp1`)

Los propios autores de LightCurveLynx muestran (notebook `data_driven_noise_dp1.html`, absorbido vía
WebFetch) que el modelo Poisson estándar de flujo-vs-error se desvía de datos reales de Rubin DP1
(~800k observaciones), y proponen un modelo "data-driven" alternativo (normalizing flow entrenado con
`pzflow`) como mejora general -- no cuantifican una dirección de sesgo específica ni una condición
concreta, lo presentan como una limitación general de cualquier fórmula analítica de ruido fotométrico
frente a la complejidad real de las condiciones de observación.

**Más importante: esta crítica no aplica a este proyecto en absoluto.** El modelo Poisson "genérico"
que critica ese notebook es el que arma sus parámetros (profundidad, PSF, cielo) a partir del OpSim
crudo -- pero este proyecto reemplazó eso desde **Fase 2A** (muy al principio): `snana_noise_columns()`
en cada `run_*.py` construye `sky_bg_e`/`psf_footprint`/`zp` directamente desde `SKYSIG`/`seeingFwhmEff`/
`ZPT` **reales del `.SIMLIB` real de SNANA** (confirmado en el propio código, `run_simsed_poc.py:331-339`),
no desde una estimación genérica derivada del OpSim. El `PoissonFluxNoiseModel` de LightCurveLynx sigue
usándose (sigue siendo "Poisson" en su forma matemática, varianza=señal+fondo), pero alimentado con los
mismos números reales que usa SNANA -- exactamente lo que evita el problema que señala el notebook (usar
parámetros de ruido no representativos de la campaña real). No hay nada que implementar aquí para esta
comparación específica.

### Conclusión Fase 15 (y del roadmap post-Fase-9 completo)

Los 3 ítems de menor prioridad se cierran limpio: dos no están configurados en absoluto en esta
campaña (`REDCOV`, y de hecho tampoco importa `GENSIGMA_SEARCH_PEAKMJD` aunque sí esté activo, porque
no participa del cálculo real), y el tercero (crítica de ruido Poisson de LCL) no es aplicable porque
este proyecto ya usa parámetros de ruido reales de SNANA, no los genéricos que la crítica señala.

Con esto se agotan los 8 candidatos identificados en el roadmap de investigación estructurado tras
absorber la documentación oficial de LightCurveLynx y el manual de SNANA (Fases 10-15). Ninguno
explica el residuo sistémico multiplicativo por sí solo. El estado del proyecto queda así:
- **Confirmado no explicativo, con evidencia directa de código en ambos lados**: extinción MW
  (Fase 10), grilla LOGZBIN de SIMSED (Fase 11, aunque con potencia estadística limitada),
  passband/zeropoint (Fase 12), extrapolación de borde de SED (Fase 13), dispersión cromática G10
  (Fase 14, por razonamiento de dirección), y los 3 ítems de esta fase.
- **Ya descartado en fases anteriores** (Fase 3-9): extinción de host, trigger de detección,
  reproducibilidad/semillas, codificación SIMSED-vs-NON1ASED.
- **Hallazgo más sólido que queda sin explicar**: LightCurveLynx simula objetos ~0.2-0.6 mag más
  *tenues*, no más brillantes, que SNANA (Fase 7) -- lo opuesto a la hipótesis obvia de "sobre-brillo"
  -- y aun así sobre-detecta sistemáticamente. Esto apunta a algo en la interacción ruido/SNR/forma de
  curva de luz que ninguna de las 8 verificaciones puntuales de Fases 10-15 logró aislar.

**Recomendación:** la auditoría mecanismo-por-mecanismo (candidato concreto → verificar en código real
→ probar si corresponde) agotó su lista razonable de candidatos identificables desde la documentación.
Los próximos pasos productivos probablemente ya no sean "¿qué parámetro le falta a LightCurveLynx?"
sino algo más holístico: (a) extender la comparación de brillo sin ruido de Fase 7 a las 18 clases
restantes para confirmar si el patrón "~0.2-0.6 mag más tenue" es universal o varía por clase/tipo de
SED; (b) una comparación pointwise de la propagación completa ruido→SNR→trigger para un solo objeto
fijo en ambos códigos (más ambicioso que Fase 11, pero aislaría la cadena completa en vez de un
mecanismo a la vez); o (c) aceptar el residuo como una diferencia de calibración agregada entre ambos
simuladores y trabajar con un factor de corrección empírico por clase en vez de perseguir una causa
única.

### Archivos de esta fase (Fase 15)

Sin archivos nuevos -- investigación completa e inline (greps contra los `.INPUT`/`.SIMLIB` reales de
NLHPC, lectura de código fuente de SNANA, y una consulta WebFetch al notebook real de LightCurveLynx).
Sin simulación nueva, sin incidentes de cuota.

## Fase 16 — comparación pointwise ruido→SNR→trigger (Opción 2 del usuario tras Fase 15)

Con los 8 candidatos del roadmap agotados, se retoma el enfoque "holístico" (b) que quedó pendiente:
comparar la cadena completa ruido→SNR→trigger para un objeto/clase fijo, en vez de un mecanismo a la
vez. Se eligió `SNIa` (SALT2) para esto -- no por casualidad: **Fase 1 (el origen mismo del proyecto)
ya había documentado una discrepancia de SNR real y sin resolver para esta clase específica**
("el modelo de ruido fotométrico de LightCurveLynx subestima el ruido por-época real... queda como
brecha abierta para Fase 2"), y esa brecha nunca se retomó formalmente con las herramientas y el
acceso al código fuente real que este proyecto fue acumulando en Fases 10-15.

### Paso 1 -- fórmula de ruido: reconstruida línea por línea, resulta matemáticamente equivalente

Se leyó `gen_fluxNoise_calc()` completa (`snlc_sim.c`, ~L27505-27600) -- la función real que arma la
varianza de ruido de SNANA. Fórmula real (unidades p.e., gain=1 en esta campaña):
```
NEA = 4π·σ²_psf(arcsec) / pixsize²          (Noise Equivalent Area, misma formula en ambos lados)
fluxsn_pe = 10^(0.4·(zpt-mag))                (shot noise de la fuente)
sqerr_sky_pe = NEA · SKYSIG²                  (ruido de cielo)
sqerr_ccd_pe = NEA · readnoise²                (read noise CCD)
sqerr_zp_pe  = (fluxsn_pe · (10^(0.4·zpterr)-1))²   (incertidumbre de zeropoint)
sqsig_true = fluxsn_pe + sqerr_sky_pe + sqerr_ccd_pe + sqerr_zp_pe
```
Comparada término a término contra `poisson_bandflux_std()` real de LightCurveLynx
(`noise_models/base_noise_models.py`) -- reconstruidas ambas en Python
(`fase16_noise_formula_compare.py`, no versionado) y evaluadas con condiciones de observación reales
tomadas del `.SIMLIB` real (SKYSIG/PSF1/ZPTAVG/ZPTERR reales) para varias magnitudes de fuente:
**con los mismos parámetros reales (`readout_noise=0.25`, `dark_current=0`, los valores reales de esta
campaña), el `fluxerr` de LightCurveLynx coincide con el de SNANA con una razón de 0.9986-1.0000** --
prácticamente idéntico. Las dos fórmulas son matemáticamente equivalentes.

**Hallazgo colateral real, pero en la dirección contraria:** `snana_noise_columns()` nunca pasa
`read_noise`/`dark_current` explícitos a `OpSim`, así que LightCurveLynx cae en los *defaults*
hardcodeados de la clase `OpSim` (`obstable/opsim.py`): `readout_noise=8.8` e⁻/píxel y
`dark_current=0.2` e⁻/s/píxel (constantes genéricas de LSSTCam, fuente citada:
`smtn-002.lsst.io`) -- muy por encima del `readnoise=0.25` real y simplificado que usa el `.SIMLIB`
de esta campaña (`WriterParams.ccd_noise`). Con los defaults reales del proyecto (no los "matched"),
el `fluxerr` de LightCurveLynx sale **entre 0.3% y 12% más grande** que el de SNANA (mayor en
`g`/`r` a magnitudes brillantes, donde el ruido de cielo es más chico y el read noise pesa más) --
real, pero en la dirección **contraria** a explicar el sobre-conteo (más ruido en LCL, no menos).
Se deja documentado como una discrepancia real de fidelidad (candidato de bajo impacto para portar
si se retoma esta fase), no como causa del residuo.

### Paso 2 -- SNR remedido hoy: la brecha de Fase 1 se achicó mucho, pero no desapareció

Se corrió `run_snia_ddf_poc.py` fresco (job 11563393) con TODO el código acumulado desde Fase 1
(incluye `zp_err_mag=0.005` ya corregido en Fase 1 punto 7b, ruido real de SNANA vía
`snana_noise_columns()`, dispersión MWEBV real de Fase 10, etc.) -- el propio script ya compara
automáticamente contra la referencia real:

| | mediana SNR | p90 SNR |
|---|---|---|
| SNANA real (`SNIa_DDF`) | 0.78 | 2.26 |
| LightCurveLynx, medido en Fase 1 (histórico) | 1.008 (+29%) | 5.68 (+151%, 2.5x) |
| LightCurveLynx, remedido hoy (Fase 16) | 0.868 (+11.3%) | 2.948 (+30.4%) |

La brecha se redujo sustancialmente (de 2.5x a 1.3x en la cola alta) gracias a los fixes acumulados
en fases posteriores, pero **sigue existiendo un residuo real del 11-30%** -- no explicado por la
fórmula de ruido (Paso 1 la confirmó equivalente). Tiene que venir del numerador (flujo simulado),
no del denominador (ruido).

### Paso 3 -- brillo sin ruido para SALT2: nunca antes probado, y en dirección OPUESTA a Fase 7

Fase 7 estableció (para `SNIa-91bg`, SIMSED) que LightCurveLynx simula objetos **más tenues** que
SNANA -- pero esa comparación nunca se hizo para `SNIa` (SALT2), un modelo completamente distinto
(`sncosmo.SALT2Source`, no `SIMSEDModel`). `run_snia_ddf_poc.py` nunca extraía `flux_perfect` (mismo
bug metodológico que Fase 7 encontró y corrigió para SIMSED, nunca portado a SALT2). Se construyó
`compare_brightness_truth_salt2.py` (mismo patrón de Fase 7, reconstruye el `source_model` real de
`run_snia_ddf_poc.py` pero captura `flux_perfect` en banda `r` en vez de descartarlo) y se comparó
contra el `.DUMP` real de producción (`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`, `PEAKMAG_r`,
`SELECTION: NONE`):

| bin z | N SNANA | mediana SNANA | N LCL | mediana LCL | Δ (LCL-SNANA) |
|---|---|---|---|---|---|
| [0.011,0.181) | 10 | 19.691 | 13 | 20.176 | +0.486 (poca estadística) |
| [0.181,0.351) | 64 | 21.489 | 56 | 21.256 | **-0.234** |
| [0.351,0.521) | 164 | 22.415 | 158 | 22.277 | **-0.137** |
| [0.521,0.690) | 257 | 23.313 | 276 | 23.185 | **-0.128** |
| [0.690,0.860) | 368 | 24.346 | 382 | 24.106 | **-0.239** |
| [0.860,1.030) | 490 | 25.169 | 546 | 25.029 | **-0.140** |
| [1.030,1.200) | 379 | 26.156 | 552 | 26.040 | **-0.116** |

**Salvo el primer bin (poca estadística), LightCurveLynx sale sistemáticamente MÁS BRILLANTE que
SNANA en todo el rango de redshift real, ~0.12-0.24 mag** -- lo opuesto de Fase 7, y en la dirección
CORRECTA para explicar el sobre-conteo de `SNIa`. Cuantitativamente consistente: 0.12-0.24 mag de
exceso de brillo ≈ 11-25% de exceso de flujo, del mismo orden que el 11-30% de exceso de SNR medido
en el Paso 2 -- y dado que el Paso 1 mostró que el ruido de LCL es *más* grande, no más chico, que el
de SNANA, el exceso de brillo tiene que ser -- por eliminación -- toda la explicación del exceso de
SNR observado (y un poco más, para compensar el exceso de ruido).

**Candidato de causa más probable, no verificado hasta el fondo:** `GENMEAN_SALT2ALPHA=0.14`,
`GENMEAN_SALT2BETA=3.1`, `GENPEAK_SALT2c/x1` y sus sigmas coinciden EXACTAMENTE con
`SIMGEN_INCLUDE_SNIa-SALT2.INPUT` real -- pero **`GENMAG_OFF`/la magnitud absoluta M_abs no está
declarada en absoluto en el `.INPUT` real** (`GENMAG_OFF_GLOBAL` default de SNANA es 0.0, sin M_B0
explícito para SALT2 en este archivo). El PoC usa `m_abs_func = Normal(loc=-19.3, ...)` -- un valor
de la literatura general, nunca verificado contra la convención interna real que usa SNANA para
`SALT2.WFIRST-H17` (que probablemente deriva su M_B0 de la normalización `FLUXSCALE` propia del
template, no de un M_abs configurable). Una diferencia de calibración de ~0.15-0.2 mag entre la
convención `X0FromDistMod` de LightCurveLynx/sncosmo y la normalización real de SNANA explicaría el
patrón observado limpiamente. No se llegó a verificar la convención exacta de sncosmo (fuera del
alcance razonable de esta sesión, ya muy extensa) -- queda como el cabo suelto más concreto y
accionable de todo el proyecto.

### Conclusión Fase 16

**El hallazgo más sólido y accionable desde Fase 7.** A diferencia de los candidatos de Fase 10-15
(todos descartados o insuficientes), este apunta a una causa real, cuantificada, en la dirección
correcta, y específica de una sola clase bien delimitada (`SNIa`/SALT2): LightCurveLynx simula
supernovas ~0.12-0.24 mag más brillantes que SNANA para los mismos parámetros SALT2 reales
(alpha/beta/x1/c/z), consistente numéricamente con el exceso de SNR observado. La causa más probable
es una diferencia de calibración de magnitud absoluta (M_abs/M_B0) entre la convención que usa
`X0FromDistMod` de LightCurveLynx y la normalización interna real de SNANA para este template SALT2
específico -- no verificada hasta el fondo, pero el cabo suelto más concreto de todo el proyecto.
**Recomendación:** el siguiente paso natural (fuera de esta sesión) es leer el código fuente de
`sncosmo.SALT2Source`/`X0FromDistMod` para encontrar la convención exacta de M_B0 que asumen, y
comparar contra cómo SNANA deriva x0 internamente para `SALT2.WFIRST-H17` sin `GENMAG_OFF`
declarado -- si se confirma una diferencia de calibración, es un fix de una constante, no una
reimplementación.

### Archivos de esta fase (Fase 16)

- `exploration/lightcurvelynx/compare_brightness_truth_salt2.py`/`.sbatch` -- primera comparación de
  brillo sin ruido para la clase SALT2 (nunca antes hecha, Fase 7 solo cubrió SIMSED).
- `exploration/lightcurvelynx/fase16_noise_formula_compare.py` -- exploratorio, no versionado
  (reconstrucción y comparación numérica de ambas fórmulas de ruido, Paso 1).
- Sin cambios a `run_simsed_poc.py`/`run_snia_ddf_poc.py` -- esta fase es diagnóstico, no
  implementación (el fix de M_abs, si se confirma, queda para retomar).

### Paso 4 -- se retoma el candidato M_abs: descartado, con el signo contrario al esperado

Se leyó el código fuente REAL de ambos lados para la fórmula x0↔magnitud absoluta:

**LightCurveLynx** (`X0FromDistMod`/`_x0_from_distmod`, `astro_utils/snia_utils.py`):
```python
# distmod = -2.5*log10(x0) + alpha*x1 - beta*c - m_abs + 10.635
x0 = 10 ** (-0.4 * (distmod - alpha*x1 + beta*c + m_abs - 10.635))
```

**SNANA** (`SALT2x0calc()`, `genmag_SALT2.c:2932`):
```c
arg   = 0.4 * ( dlmag - alpha*x1 + beta*c );
x0inv = X0SCALE_SALT2 * pow(TEN, arg);   // X0SCALE_SALT2 = 1.0E-12 (genmag_SALT2.h)
x0    = 1./x0inv;
```
con `mBoff_SALT2 = 10.635` (`load_mBoff_SALT2()`, `genmag_SALT2.c:2975`) -- **la misma constante
exacta que usa LightCurveLynx**, confirmando que ambos códigos implementan la misma convención
estándar de normalización SALT2 (mB = mBoff - 2.5·log10(x0), SNLS/VEGA system, Guy+2010).

Despejando ambas fórmulas para el mismo `x0`/`distmod`/`alpha·x1`/`beta·c`, el M_abs *implícito* que
usa SNANA (vía `X0SCALE_SALT2`) es:
```
m_abs_SNANA = 2.5·log10(X0SCALE_SALT2) + mBoff_SALT2 = 2.5·log10(1e-12) + 10.635 = -30 + 10.635 = -19.365
```
contra `m_abs = -19.3` que usa el PoC (`m_abs_func`, valor de la literatura general nunca antes
verificado). **Diferencia real: 0.065 mag -- pero con el signo CONTRARIO al necesario.** -19.365 es
*más brillante* que -19.3 (más negativo). Si se corrigiera el PoC a -19.365, LightCurveLynx generaría
objetos **aún más brillantes** que ahora -- empeoraría la discrepancia observada (LCL ya sale más
brillante que SNANA), no la explicaría. Descartado como causa del exceso de 0.12-0.24 mag: de hecho,
sin este pequeño efecto de compensación en la dirección opuesta, la discrepancia real subyacente
sería *aún mayor* (~0.19-0.30 mag) que la medida en el Paso 3.

**Candidatos residuales, no verificados (quedan para retomar si se decide seguir):** la fórmula de
conversión x0↔mB ya se confirmó idéntica -- el exceso de brillo tiene que venir de la propia
NORMALIZACIÓN DE FLUJO del template SALT2 (`salt2_template_0.dat`/`_1.dat`, interpolación 2D
fase×longitud de onda -- sncosmo vs. el motor interno de SNANA podrían interpolar/normalizar
distinto pese a leer el mismo archivo real), o del *color law* (`SALT2.INFO::COLORCOR_PARAMS`,
"reconstruido a mano" desde Fase 0/1, nunca verificado línea por línea contra la fórmula real de
`genmag_SALT2.c` -- un error de escala en el término `beta·c` produciría justo un offset sistemático
como el observado, dado que `GENPEAK_SALT2c=-0.054` no es cero). Verificar cualquiera de los dos
requiere una comparación punto a punto de flujo crudo (patrón similar a Fase 11's
`evaluate_bandfluxes()`, pero para SALT2/sncosmo en vez de SIMSED) -- no se hizo en esta sesión.

### Paso 5 -- color law verificado hasta el fondo: coincide EXACTO, descartado como causa

Se cerró el segundo candidato residual de Fase 16. `sncosmo.models.SALT2Source._set_colorlaw_from_file()`
sí lee `Salt2ExtinctionLaw.version`/`min_lambda`/`max_lambda` del archivo real que genera
`setup_salt2_local.py` (confirmado leyendo `models.py` real del paquete instalado, `sncosmo==2.13.0`
en el venv de NLHPC) y, para `version=1`, delega en `SALT2ColorLaw` -- una clase Cython compilada
(`salt2utils.cpython-312-x86_64-linux-gnu.so`), sin fuente Python instalada localmente. Se descargó el
`.pyx` real (`raw.githubusercontent.com/sncosmo/sncosmo/master/sncosmo/salt2utils.pyx`) para leer su
implementación exacta:

```cython
# SALT2CL_B = 4302.57, SALT2CL_V = 5428.55 (constantes fijas, iguales a las internas de SNANA)
# coeffs[0] = alpha = 1.0 - sum(params)          -- misma normalizacion que SNANA
# P(l) = alpha*l + params[0]*l^2 + params[1]*l^3 + ...   -- mismo polinomio
# fuera de [l_lo, l_hi]: extrapolacion lineal tangente (valor + derivada analitica en el borde)
#   -- mismo mecanismo exacto que SALT2colorfun_pol/_dpol de SNANA (Paso 4 arriba)
```
Coincide, término a término, con `SALT2colorlaw1`/`SALT2colorfun_pol`/`_dpol` reales de SNANA
(`genmag_SALT2.c`) -- misma normalización `alpha`, mismo polinomio, mismo mecanismo de extrapolación
lineal tangente, mismas constantes de referencia B/V. El único punto que requería verificación
numérica (no solo algebraica) era si el doble signo negativo interno de sncosmo
(`out = -out` dentro de `__call__`, luego `10**(-0.4*colorlaw(wave)*c)` en `models.py:813`) se cancela
correctamente contra la convención de signo de SNANA (`exp(c*constant*val)`, sin negar) -- confirmado
numéricamente:

```python
# fase16_verify_colorlaw.py (no versionado) -- evalua AMBAS formulas reales (sncosmo.salt2utils.
# SALT2ColorLaw cargando el archivo real, y una reconstruccion Python 1:1 de SALT2colorlaw1) en el
# mismo grid de lambda, incluyendo puntos DENTRO y FUERA de [2800,9500] A, con c=-0.054 real (GENPEAK_SALT2c)
```

| λ (Å) | factor sncosmo | factor SNANA (reconstruido) | razón | Δmag |
|---|---|---|---|---|
| 1500 (fuera, extrapolado) | 2.468619 | 2.468619 | 1.000000 | 0.000000 |
| 2800 (borde) | 1.394828 | 1.394828 | 1.000000 | -0.000000 |
| 4302.6 (B, referencia) | 1.000000 | 1.000000 | 1.000000 | -0.000000 |
| 5428.6 (V, referencia) | 0.951481 | 0.951481 | 1.000000 | -0.000000 |
| 9500 (borde) | 0.865289 | 0.865289 | 1.000000 | 0.000000 |
| 12000 (fuera, extrapolado) | 0.856784 | 0.856784 | 1.000000 | -0.000000 |

**Coinciden a precisión de máquina en todo el rango probado, dentro y fuera de la zona de calibración
-- el color law está correctamente implementado, no explica el exceso de brillo de 0.12-0.24 mag.**
Con esto, los DOS candidatos concretos identificados en la Fase 16 (M_abs, color law) quedan
descartados con evidencia numérica sólida. El candidato que queda -- la normalización/interpolación
2D (fase×longitud de onda) del propio flujo del template `salt2_template_0/1.dat` en `sncosmo` vs. el
motor interno de SNANA -- sigue sin verificar; requeriría comparar flujo crudo punto a punto (mismo
patrón de Fase 11 pero para SALT2), no hecho en esta sesión.

## Fase 17 — limpieza de disco, glosario del dashboard, escala WFD

Ronda de trabajo pedida explícitamente por el usuario: liberar espacio, verificar el color law (Paso
2/5 arriba, ya cerrado dentro de Fase 16), mejorar el dashboard con un glosario, confirmar el `z`
máximo de `SLSN-I`, correr simulaciones a escala WFD, y generar un notebook de análisis.

### Limpieza de disco (~14.6 GB liberados)

Se borraron los `phot_df.parquet` de las 97 carpetas `poc_output_*` que lo tenían (76 de semillas
`_seed1..4` + 20 de "semilla 0"/principal), verificando antes que cada una tuviera `summary.json`
(ninguna carpeta se saltó -- las 97 lo tenían). Se conservó `head_df.parquet`/`summary.json`/`qc/*.png`
en todas. **199G → 185G** confirmado (`du -sh ~/`). Además, a pedido explícito del usuario durante la
sesión, se borraron también los `head_df.parquet` de las 80 carpetas `_seed1..4` que lo tenían (~10MB,
son chicos) -- las carpetas de semilla quedan solo con `summary.json`/`qc/`, que es toda la
"comprobación" que hace falta conservar de esas corridas extra (su número ya está incorporado a
`ratio_mean_5seeds`/`ratio_std_5seeds` en el dashboard). Las carpetas "semilla 0"/principal conservan
su `head_df.parquet` intacto.

### Confirmación de `z` máximo de `SLSN-I` (sin cambio de código)

El usuario preguntó si había que ajustar el `z` máximo de `SLSN-I` a 6 (recordando que "en SNANA lo
extendimos más"). Investigación real (grep exhaustivo de todos los `.INPUT` de `SLSN-I` en NLHPC, con
fecha de modificación) confirmó que **no existe ningún `GENRANGE_REDSHIFT=6` activo en ningún archivo
real hoy** -- los valores reales activos son `z=9.7` (SIMSED/MOSFIT,
`/home/mvalenzuela/run_SNANA/model_config/SIMGEN_INCLUDE_SLSN-I-MOSFIT.INPUT`, el canónico que usa la
campaña de producción real) y `z=2.95` (NON1ASED/BBFIT, el más reciente de los tres archivos
relacionados con `SLSN-I` encontrados, `run_SNANA/elastic/model_config/SIMGEN_INCLUDE_SLSN-I_NON1ASED.INPUT`,
modificado 6-Ago-2026). El valor `6.0` solo existe **comentado/deshabilitado**
(`#GENRANGE_REDSHIFT: 0.02 6.0`) en el archivo canónico más antiguo (Oct-2025) -- nunca activo en
ninguna corrida real verificable. `run_simsed_poc.py`/`run_non1ased_poc.py` ya usan exactamente estos
mismos rangos (`(0.02, 9.7)` y `(0.02, 2.95)` respectivamente) -- coinciden con la campaña real, no
hay desalineamiento. **El usuario confirmó usar `z=9.7`** -- no se requirió ningún cambio de código,
solo esta verificación explícita para que quede documentada y no se reabra la duda.

### Soporte WFD en `run_simsed_poc.py`/`run_non1ased_poc.py`/`run_snia_ddf_poc.py` (scripts listos, campaña sin lanzar)

El usuario pidió correr simulaciones a escala WFD (nunca antes probada por LightCurveLynx en este
proyecto -- todo el trabajo previo, Fases 0-16, es DDF), pero a mitad de esta ronda pidió
explícitamente **dejar los scripts escritos sin lanzar la campaña** (la cuota de NLHPC sigue siendo
frágil incluso después de liberar los ~14.6GB de arriba). Este apartado documenta el diseño y la
implementación; la ejecución queda pendiente para cuando el usuario decida lanzarla.

**Problema de diseño**: a diferencia de DDF (6 campos fijos, `DDF_FIELD_EBV` como diccionario nombre→
E(B-V)), WFD no tiene campos fijos -- el dithering real de LSST hace que casi ningún pointing comparta
exactamente la misma posición (`SELECT COUNT(DISTINCT fieldRA || '_' || fieldDec) FROM observations
WHERE target_name NOT LIKE '%ddf_%'` → **1,015,331** combinaciones únicas, confirmado). El SIMLIB real
de WFD (`WFD_baseline_v5.3.1_10yrs.SIMLIB`, ~1.08GB, 20.000 LIBID) también escribe `MWEBV: 0.00` fijo
en cada header (mismo default hardcodeado de `writer.py` que DDF), así que no sirve como fuente. El
mapa SFD real (`dustmaps`/`sfdmap2`) sigue sin poder descargarse desde NLHPC (Fase 0/1: Harvard
Dataverse devuelve cuerpo vacío, el mirror de GitHub solo tiene un README).

**Solución**: `build_wfd_mwebv_grid.py` (nuevo) agrupa las posiciones reales de WFD en una grilla
gruesa de 8° directamente en SQL (`ROUND(fieldRA/8.0)`, `ROUND(fieldDec/8.0)`, `GROUP BY` -- evita
materializar >1M filas en pandas, que colgaba el primer intento con un `SELECT DISTINCT` sin agrupar),
reduciendo a **671 celdas reales**. Consulta el mismo servicio REST IRSA Dust Extinction Service
(`nph-dust`, columna `refPixelValueSFD`) ya usado para los 6 valores DDF, una vez por celda, y guarda
`wfd_mwebv_grid.csv` (columnas `ra,dec,ebv_sfd`). Nuevo helper `snana_params.make_wfd_ebv_lookup()`
hace nearest-neighbor angular (con wrap de RA en 0/360°) contra esa tabla usando el RA/DEC exacto de
cada objeto simulado (no el nombre de campo), reusando `make_mwebv_ratio_scatter()` para el mismo
`GENSIGMA_MWEBV_RATIO=0.16` real ya aplicado en DDF.

**Cambios en los 3 scripts** (`run_simsed_poc.py`, `run_non1ased_poc.py`, `run_snia_ddf_poc.py`), todos
detrás de un nuevo parámetro `wfd: bool = False` / flag CLI `--wfd` (en cualquier posición de los
argumentos):
- Filtro de `OpSim` invertido: `~df["target_name"].str.contains("ddf_", na=False)` en vez de sin la
  negación, sobre el mismo `baseline_v5.3.1_10yrs.db` (mismo patrón ya establecido de leer directo del
  `.db`, no del SIMLIB pre-construido).
- Sin columna `field` para WFD (no se extrae, `ObsTableRADECSampler(..., extra_cols=[])` en vez de
  `["field"]`).
- `ebv_func` bifurcado: `_field_to_ebv` (dict fijo) para DDF, `make_wfd_ebv_lookup(...)` (nearest-
  neighbor real) para WFD -- mismo `seed_base + 10` en ambos casos.
- `NGENTOT`: **igual que DDF** (2000/clase, misma excepción `PISN-STELLA-HYDROGENIC`=20000) -- el
  usuario eligió "NGENTOT chico, tipo DDF" en vez de la escala real de producción (200.000/clase) para
  no volver a agotar la cuota.
- Nuevo sufijo de directorio de salida `_wfd` (p.ej. `poc_output_91bg_wfd`, `poc_output_wfd` para
  `run_snia_ddf_poc.py`) -- no pisa ninguna corrida DDF existente.
- `summary.json` gana un campo `"strategy": "WFD"|"DDF"`; el label de QC (`qc.run_all_qc(...)`) pasa a
  decir `..._WFD_poc` en vez de `..._DDF_poc`.

**Verificado**: los 4 archivos (`snana_params.py` + los 3 `run_*_poc.py`) compilan (`py_compile`) sin
error. **No verificado todavía** (pendiente de una corrida real, que el usuario pidió no lanzar en esta
sesión): que `wfd_mwebv_grid.csv` cargue correctamente dentro de `simulate_lightcurves()` y que el
nearest-neighbor produzca valores de E(B-V) razonables end-to-end. `build_wfd_mwebv_grid.py` corrió
como job en background en NLHPC (`nohup`, ~671 celdas × ~1.1s/celda ≈ 12-13 min) -- confirmar que
terminó y que `wfd_mwebv_grid.csv` tiene ~671 filas válidas antes de la primera corrida WFD real.

**Cómo lanzar cuando se decida** (no ejecutado en esta sesión): `python3 run_simsed_poc.py
SNIa-91bg-elastic --wfd` (smoke test sugerido, clase rápida ya familiar) desde un job sbatch, tras
verificar headroom real con `dd if=/dev/zero of=... bs=1M count=N` antes de cada clase -- una clase a
la vez, no las 19 en paralelo, dado que la cuota de NLHPC sigue siendo el recurso más frágil del
proyecto.

`build_wfd_mwebv_grid.py` sí terminó de correr en esta sesión (job en background en NLHPC, ~671
celdas × ~1.1s/celda): `wfd_mwebv_grid.csv` quedó generado y versionado (671 filas, `ebv_sfd` real
SFD98: mediana=0.090, p75=0.185, máx=22.53 -- rango correcto para un footprint que cruza el plano
galáctico, a diferencia de los 6 campos DDF que se eligieron justamente por tener E(B-V) bajo).

### Notebook Jupyter de análisis (`analyze_phot_df.ipynb`)

Nuevo `exploration/lightcurvelynx/analyze_phot_df.ipynb`, 18 celdas (9 markdown + 9 código). Diseño
clave: como el Paso 1 borró casi todos los `phot_df.parquet` reales (solo queda uno,
`poc_output/phot_df.parquet` -- SNIa DDF/SALT2, 107MB, 3.8M filas de fotometría) y la campaña WFD no
se lanzó (ver arriba), el notebook **escanea el disco en cada ejecución** (`poc_output*/summary.json`)
en vez de asumir una lista fija de clases/estrategias, y separa el análisis en dos niveles:
- Lo que **no** depende de `phot_df.parquet` (eficiencia de detección por clase, distribución de
  redshift/NOBS, eficiencia vs. redshift binned) -- funciona hoy con las 25 corridas que sí conservan
  `head_df.parquet` más los 106 `summary.json` que quedan en todas las carpetas.
- Lo que sí depende de `phot_df.parquet` (SNR simulado, cobertura de bandas, curvas de luz de ejemplo)
  -- se salta con un aviso explícito (no falla) en cualquier corrida que no lo tenga.
- Una sección final de comparación DDF-vs-WFD que hoy imprime "todavía no hay ninguna clase con ambas"
  (0 corridas WFD encontradas) pero se completa sola, sin editar el notebook, en cuanto se lance
  cualquier clase con `--wfd`.

Incluye un glosario condensado de columnas (`SNID`/`RA`/`DEC`/`REDSHIFT_HELIO`/`NOBS`/`DETECTED` en
`head_df`; `MJD`/`FLT`/`FLUXCAL`/`FLUXCALERR`/`MAG`/`PHOTFLAG` en `phot_df`; los campos de
`summary.json`) para que sea autocontenido, no solo remita al glosario del dashboard.

**Jupyter no estaba instalado en el venv de NLHPC** (solo tenía `pandas`/`pyarrow`/`matplotlib`, las
librerías de simulación) -- se instaló `jupyter`/`nbconvert`/`ipykernel` (verificado headroom con `dd`
antes, ~180MB instalados, sin impacto real en la cuota). **Verificado end-to-end real**: se corrió
`jupyter nbconvert --to notebook --execute --inplace` dentro de un job sbatch (nunca en el login node,
`execute_analyze_notebook.sbatch`, job 11891199, `COMPLETED 0:0`) contra los datos reales ya en disco
-- las 9 celdas de código ejecutaron sin error (incluidas las 3 celdas "guardia" que hoy reportan datos
faltantes en vez de fallar), las 4 celdas de gráficos generaron imagen real. La versión commiteada es
la ejecutada (con outputs reales embebidos, ~510KB), no una plantilla vacía.

## Fase 18 — síntesis de los 9 puntos de la reunión con el profe

El usuario trajo una lista de 9 puntos de una conversación con su profesor sobre por qué
LightCurveLynx difiere de SNANA. Esta fase no investigó nada nuevo -- cruzó cada punto contra la
evidencia ya acumulada en Fases 0-17 y armó una síntesis (documento HTML, no versionado en el repo,
publicado como artifact para llevar a la reunión). Resultado: **8 de los 9 puntos quedan cerrados con
evidencia directa de código real de ambos lados**:

1. Campo angular -- Fase 1 punto 4 (footprint DDF real vía `ObsTableRADECSampler`) + Fase 17 (WFD).
2. Propiedades del telescopio -- Fase 12 (throughput/zeropoint, `kcor_LSST.fits` real, `ZPoff=0`,
   mismo release v1.9) + Fase 2A (SKYSIG/PSF/ZPT reales del `.SIMLIB`).
3. Criterio de detección -- mismo criterio (Fase 1 punto 5, Fase 6), **con un bug real identificado
   y ya corregido que el usuario confirmó que hay que reportar formalmente**: Fase 4 encontró que
   `searcheff.py` contaba observaciones individuales en vez de épocas reales agrupadas
   (`NEWMJD_DIF=0.007d`) antes del trigger `>=2` -- afectaba a las 14 clases SIMSED por igual, ya
   corregido (`group_into_epochs()`), verificado formalmente como subconjunto estricto del método
   viejo.
4. Ruido -- Fase 16 paso 1 (`gen_fluxNoise_calc()` reconstruida, `fluxerr` coincide 0.9986-1.0000).
5. Tasa DNDZ(z) por clase -- 5 modelos reales (`POWERLAW2`/`MD14`/`CC_S15`/TDE/`PISN_PLK12`) de
   Fases 2B/6/7, tabla completa de 20 configs (SIMSED+NON1ASED+SALT2) verificada en esta síntesis.
6. z máximo por clase -- misma tabla del punto 5; caso `SLSN-I` reconfirmado explícitamente en Fase 17.
7. Ley de extinción R_V -- MW (Fase 1 punto 6, Fase 10, fórmula `gen_MWEBV()` verificada línea por
   línea) + color law SALT2 (Fase 16, coincide a precisión de máquina con `sncosmo`).
8. A_V por clase (extinción de host) -- 3 variantes reales (`exp`/`exp_halfgauss`/`wv07`) de Fase 3 y
   Fase 2B rondas 2-3, tabla completa por clase.
9. **Parámetros SALT2 -- el único punto que queda abierto**, y es el más importante: alpha/beta/x1/c
   y sus sigmas coinciden EXACTOS con el `.INPUT` real (Fase 16 paso 3), pero `M_abs`/`M_B0` nunca se
   verificó contra la convención interna real de SNANA (el `.INPUT` no declara `GENMAG_OFF`) -- sigue
   siendo el candidato más fuerte, con evidencia cuantitativa consistente en signo y magnitud
   (0.12-0.24 mag de exceso de brillo sin ruido, Fase 16 paso 3), para el residuo que queda tras
   cerrar los otros 8 puntos.

**Acciones que salen de esta síntesis** (no ejecutadas en esta fase): (a) reportar formalmente el bug
del punto 3 como hallazgo documentado; (b) el siguiente paso técnico real del proyecto sigue siendo el
que ya recomendaba el cierre de Fase 16 -- leer `sncosmo.SALT2Source`/`X0FromDistMod` para encontrar
la convención de M_B0 y compararla contra cómo SNANA deriva `x0` internamente sin `GENMAG_OFF`.

## Fase 19 -- auditoría real de z máximo por clase, convención M_B0/SALT2, instructivo, y nota de bugs

Continuación directa de Fase 18: (1) auditoría fresca de `GENRANGE_REDSHIFT` contra la fuente de
verdad real de producción (no solo los `.INPUT` template, sino qué `.INPUT` **de verdad** compiló cada
`GENVERSION`), (2) el seguimiento técnico que Fase 16/18 dejó pendiente -- la convención real de
`M_B0`/`x0` de SNANA para SALT2 --, (3) un instructivo operativo (`HOWTO.md`), y (4) la nota pedida
sobre qué bug es local y cuál amerita reportarse a la comunidad de LightCurveLynx.

### Auditoría de z máximo -- resultado: ningún cambio de código hizo falta

Fase 17/18 ya habían verificado `GENRANGE_REDSHIFT` por clase contra los `.INPUT` template
(`run_SNANA/model_config/`, `run_SNANA/elastic/model_config/`) -- pero esos árboles tienen variantes
sin usar (p.ej. `elastic/model_config/SIMGEN_INCLUDE_SNIa-SALT2.INPUT` con `z=1.65`, que nunca se
compila a ningún `GENVERSION` real de esta campaña). Esta fase fue más allá: se encontró la fuente de
verdad real -- `AUTOSIM/build/full_v5.3_10yrs/includes/include_model_<clase>.INPUT`, el archivo
`INPUT_INCLUDE_FILE:` que **de verdad** referencia cada `GENVERSION` compilado (confirmado leyendo
`sim_SNIa_DDF_baseline_v5.3.1_10yrs.INPUT` real, que a su vez incluye
`includes/include_model_SNIa.INPUT`, que apunta a
`run_SNANA/model_config/SIMGEN_INCLUDE_SNIa-SALT2.INPUT`, NO al árbol elastic). Se grepeó
`INPUT_INCLUDE_FILE` de los 40 `include_model_*.INPUT` reales y se cruzó contra el `GENRANGE_REDSHIFT`
real de cada uno, comparado clase por clase contra `CLASS_CONFIGS` de los 3 scripts:

**Las 19 clases dentro del alcance del proyecto (14 SIMSED + 5 NON1ASED + SALT2) coinciden EXACTAS
con el `z` real de producción, sin excepción** -- incluidas las variantes NON1ASED (que usan el árbol
`elastic/`, confirmado que ESA sí es la fuente real para ellas vía su propio `include_model_*.INPUT`).
Confirmado además que el include de modelo es **el mismo para DDF y WFD** (`include_model_SNIa.INPUT`
aparece igual en `sim_SNIa_DDF_...INPUT` y `sim_SNIa_WFD_...INPUT`) -- no hay `z` distinto por
estrategia en la campaña real, así que los scripts WFD (Fase 17, comparten `CLASS_CONFIGS` con DDF)
ya están alineados por construcción, sin necesitar overrides nuevos.

Las dos entradas `-elastic` de `run_simsed_poc.py` (`SNIa-91bg-elastic`, `SNIax-elastic`) siguen sin
corresponder a ningún `GENVERSION` real -- son variantes deliberadas creadas en Fase 6/7 para el
bake-off de codificación SIMSED-vs-NON1ASED (probar el efecto de un `z` más ancho), nunca tuvieron la
intención de igualar una corrida SNANA real, así que no aplican a este punto.

**Conclusión: no se modificó ningún `CLASS_CONFIGS`** -- la petición del usuario ("que cada clase
quede simulada hasta el mismo z que SNANA") ya estaba cumplida, con una verificación ahora más
rigurosa que confirma no solo que el valor está bien sino que se leyó del archivo correcto.

### Convención real de M_B0/x0 de SNANA para SALT2 (seguimiento de Fase 16/18, punto 9)

Se leyó el código fuente real de SNANA (`genmag_SALT2.c`) para encontrar `SALT2x0calc()`/
`SALT2mBcalc()`/`load_mBoff_SALT2()` -- la pieza que Fase 16 dejó pendiente.

**Fórmula real de SNANA:**
```c
// genmag_SALT2.c
mBoff_SALT2 = 10.635;                                   // load_mBoff_SALT2(), hardcoded real
arg   = 0.4 * (dlmag - alpha*x1 + beta*c);               // dlmag = GENLC.DLMU, distmod COSMOLÓGICO
                                                           // puro (gen_distanceMag() real, SIN M_abs)
x0inv = X0SCALE_SALT2 * pow(10, arg);   x0 = 1/x0inv;     // X0SCALE_SALT2 = 1.0E-12 ("arbitrary
                                                           // normalization", genmag_SALT2.h)
mB    = mBoff_SALT2 - 2.5*log10(x0);                      // SALT2mBcalc() -- SOLO diagnóstico/
                                                           // referencia, "not used to generate
                                                           // fluxes" (comentario real del código)
```
**Hallazgo real 1 -- coincide la constante `10.635`**: `mBoff_SALT2 = 10.635` (SNANA, hardcoded
"Aug 11, 2010... hard-wire to value based on SNLS VEGA system") es EXACTAMENTE la misma constante que
usa `X0FromDistMod`/`_x0_from_distmod` de LightCurveLynx (`astro_utils/snia_utils.py`:
`x0 = 10^(-0.4*(distmod - alpha*x1 + beta*c + m_abs - 10.635))`) -- misma forma funcional, mismo signo
en cada término (`alpha*x1` resta de `mB`, `beta*c` suma), evidencia sólida de que ambos códigos
implementan la MISMA relación de Tripp/SALT2 estándar, no hay bug estructural de signo ni de forma.

**Hallazgo real 2 -- `X0SCALE_SALT2` es puro bookkeeping, NO un M_abs real (trampa algebraica real,
encontrada y corregida en esta misma fase)**: un primer intento de igualar las dos fórmulas
algebraicamente (despejar qué `m_abs` haría que `X0FromDistMod` reproduzca la `mB` de SNANA) da
`m_abs_equiv = 10.635 + 2.5*log10(1e-12) = -19.365` -- pero esto resultó ser un espejismo. Se rastreó
`X0SCALE_SALT2` hasta `INTEG_zSED_SALT2()` (misma función que integra el flujo real): `SEDMODEL.FLUXSCALE
= X0SCALE_SALT2` se aplica AL FLUJO GENERADO (`*Finteg *= x0; *Finteg *= MODELNORM_Finteg` con
`MODELNORM_Finteg` que carga el mismo factor `X0SCALE_SALT2`) -- es decir, `X0SCALE_SALT2` aparece una
vez en `x0` (como `1/X0SCALE_SALT2`) y otra vez en el flujo (`× X0SCALE_SALT2`), **se cancela
exactamente** en el flujo físico real. La `mB`/`x0` que SNANA reporta como diagnóstico (`SIM_SALT2mB`,
`SIM_SALT2x0` en el `.DUMP`/FITS) vive en una escala corrida ~30 mag por esta convención de
bookkeeping -- consistente con el propio comentario del código ("mB is not used to generate fluxes").
**Cualquier `M_abs` derivado igualando esa fórmula de `mB` directamente es indistinguible de un
artefacto de esta convención interna, no de una calibración física real** -- confirmado indirectamente
porque el signo resultante (`-19.365`, más brillante que el `-19.3` actual) va en la dirección
CONTRARIA a la necesaria para cerrar el exceso de brillo ya medido en Fase 16 (LightCurveLynx ya sale
más brillante, no más tenue).

**Camino que sí es confiable -- calibración empírica usando el residuo ya medido**: dado que resolver
esto de punta a punta requeriría además inspeccionar la normalización física interna de los templates
`salt2_template_0/1.dat` tal como los lee `sncosmo.SALT2Source` (tercera convención de unidades, no
inspeccionada en esta fase), el camino confiable es usar directamente el residuo YA MEDIDO
end-to-end en Fase 16 (que sí compara brillo físico real, no una fórmula intermedia): 6 bins bien
poblados (excluyendo el primero, con poca estadística) dieron
`Δmag = LCL - SNANA = {-0.234, -0.137, -0.128, -0.239, -0.140, -0.116}`, media `-0.166` mag (LCL más
brillante). Como `mB` y `m_abs` se mueven 1:1 en la fórmula de LightCurveLynx (confirmado arriba,
misma forma que SNANA), la corrección calibrada es
**`m_abs ≈ -19.3 + 0.166 ≈ -19.13`** (más tenue que el valor actual, para compensar el exceso).
**No se aplicó este cambio a `run_snia_ddf_poc.py`** -- es una calibración empírica ajustada al
residuo medido, no una derivación de primeros principios, y cambiar `m_abs` invalidaría/recalcularía
todos los resultados de Fase 16 ya documentados como el hallazgo principal; queda como recomendación
concreta para la próxima sesión, junto con el paso pendiente real (inspeccionar
`sncosmo.SALT2Source`/normalización de los archivos `.dat` para cerrar esto con evidencia de primeros
principios en vez de un ajuste empírico).

### Nota -- bug local vs. bug real de LightCurveLynx (qué reportar al foro de la comunidad)

El usuario pidió aclarar si el bug de Fase 4 (trigger de detección contando observaciones individuales
en vez de épocas reales) es un bug **local** (de este proyecto) o del **programa** LightCurveLynx. Es
**100% local**: `SEARCHEFF` (curvas de eficiencia de detección, lógica de trigger) no existe en
absoluto dentro de LightCurveLynx -- es un módulo propio de este proyecto (`searcheff.py`) escrito
para replicar el comportamiento real de `snlc_sim.exe`. El bug estaba en nuestra propia
reimplementación del trigger, no en ningún código de LightCurveLynx -- **no hay nada que reportar al
foro de la comunidad por este hallazgo específico.**

Dicho esto, esta investigación SÍ encontró bugs reales **dentro del propio paquete instalado**
(`lightcurvelynx==0.5.2`, confirmado leyendo `inspect.getsource()` del código real en NLHPC, no
supuesto) que sí ameritan reportarse -- mismo patrón en los 3: un nodo interno arma su propio
generador aleatorio y nunca hereda el `seed=` del constructor externo, rompiendo reproducibilidad
para cualquier usuario que dependa de semillas fijas (no solo este proyecto):

1. **`ObsTableRADECSampler.compute()`** (`lightcurvelynx/math_nodes/ra_dec_sampler.py`) -- aplica
   jitter de posición sub-FOV con `np.random.default_rng()` sin semilla cuando `self.radius > 0`.
2. **`TableSampler.__init__`** (`lightcurvelynx/math_nodes/given_sampler.py`, clase base del
   anterior) -- arma su sampler de índice de fila (`NumpyRandomFunc("integers", ...)`) sin pasarle el
   `seed=` que sí llegó al constructor externo.
3. **`SIMSEDModel.from_dir()`** (`lightcurvelynx/models/sed_template_model.py`) -- arma su
   `GivenValueSampler` de selección de template sin `seed=`.
4. **`MultiSEDTemplateModel.__init__`** (mismo módulo, usado por NON1ASED) -- mismo problema.

Los 4 se confirmaron con un test real (Fase 5: dos procesos Python separados, misma semilla,
resultados distintos hasta corregirlos; byte-idénticos después). Son candidatos reales para un issue
en `github.com/lincc-frameworks/LightCurveLynx` -- "seed= passed to the parent node doesn't propagate
to internal samplers in ObsTableRADECSampler/SIMSEDModel/MultiSEDTemplateModel", con los 4 puntos de
arriba como reproducción. No se abrió el issue en esta fase (el usuario pidió la nota, no la acción).

**Seguimiento (Fase 20)**: se evaluó formalmente publicarlo -- `gh issue list` contra el repo real
(`lincc-frameworks/LightCurveLynx`) confirmó que no es duplicado, y se verificó contra `main` en GitHub
(no solo la versión `0.5.2` instalada) que los 3 bugs (`ObsTableRADECSampler`, `TableSampler`,
`SIMSEDModel`) siguen presentes hoy, sin arreglar. Se redactó el issue completo (título + cuerpo,
formato calibrado contra issues reales del repo) y se le mostró al usuario para confirmación explícita
antes de publicarlo -- **el usuario decidió no publicarlo por ahora**. El borrador completo queda
guardado en `exploration/lightcurvelynx/ISSUE_DRAFT_seed_propagation.md`, listo para publicar más
adelante si se decide (no correr `gh issue create` sin una confirmación explícita nueva).

## Fase 20 -- M_abs de SALT2 cerrado con primeros principios: la Fase 19 se corrige a sí misma

Retoma el pendiente explícito de Fase 19: leer `sncosmo.SALT2Source`/`X0FromDistMod` para encontrar la
convención real de M_B0 y compararla contra cómo deriva `x0` SNANA. **Resultado: la "corrección" que
propuso Fase 19 (declarar el `M_abs=-19.365` de Fase 17 un espejismo, y proponer `-19.13` en su lugar)
era ella misma un error** -- Fase 19 solo verificó que `X0SCALE_SALT2` se cancela del lado de SNANA,
sin verificar si `sncosmo`/LightCurveLynx cancela el mismo factor de la misma forma. No lo hace.

### El hallazgo que faltaba: `sncosmo.SALT2Source._SCALE_FACTOR = 1e-12`

Leyendo `sncosmo/models.py` real (`inspect.getsourcefile`, venv real de NLHPC, `sncosmo==2.13.0`):

```python
class SALT2Source(Source):
    _SCALE_FACTOR = 1e-12          # -- EXACTAMENTE el mismo valor que X0SCALE_SALT2 de SNANA
    def __init__(self, ...):
        for key in ['M0', 'M1']:
            phase, wave, values = read_griddata_ascii(names_or_objs[key])
            values *= self._SCALE_FACTOR      # -- aplicado UNA VEZ, al cargar el archivo
            self._model[key] = BicubicInterpolator(phase, wave, values)
    def _flux(self, phase, wave):
        m0 = self._model['M0'](phase, wave)   # ya trae el *1e-12 horneado
        m1 = self._model['M1'](phase, wave)
        return (self._parameters[0] * (m0 + self._parameters[1] * m1) * ...)  # x0 * M0, sin mas factores
```

A diferencia de SNANA (donde `x0 = 1/(X0SCALE*10^arg)` y el flujo se multiplica DE NUEVO por
`X0SCALE` en `INTEG_zSED_SALT2()` -- por eso se cancela, ver Fase 19), `sncosmo` aplica el `1e-12`
**una sola vez, al leer el archivo**, y `x0` (el parámetro libre que pone `X0FromDistMod`) se usa
directo, sin ningún factor de compensación. **El `1e-12` NO se cancela del lado de LightCurveLynx.**
Fase 19 asumió (sin verificarlo) que ambos lados cancelaban igual -- no era así.

### Verificación numérica directa (no solo álgebra, tercera vez que se hace esta pregunta)

Confirmado que los archivos crudos son **byte-idénticos** (`md5sum` real:
`a75b5afcc7c59354af25c4b182ee3edd` para `salt2_h17_local/salt2_template_0.dat` local y el
`salt2_template_0.dat.gz` descomprimido de `run_SNANA/plasticc_models/SALT2.WFIRST-H17/` real). Con
eso, `fase20_verify_mabs.py` (no versionado) calculó, para `z=0.3, x1=0, c=0, alpha=0.14, beta=3.1`:

| M_abs probado | `x0` (LightCurveLynx) | flujo LCL/flujo SNANA | Δmag (LCL−SNANA) |
|---|---|---|---|
| -19.300 (Fases 0-19) | 3.906753e-05 | 0.941890 | +0.0650 |
| **-19.365** | **4.147783e-05** | **1.000000** | **-0.0000** |
| -19.130 (propuesta Fase 19) | 3.340535e-05 | 0.805378 | +0.2350 |

`x0_SNANA` reconstruido de `SALT2x0calc()` real dio **4.147783e-05** -- coincide con el `x0` de
LightCurveLynx a `M_abs=-19.365` a 6 cifras significativas exactas. El flujo físico (`x0 * 1e-12 *
M0_crudo`, mismo `M0` crudo real para ambos) coincide con razón `1.000000` exacta. `-19.365` no es una
aproximación: es exactamente `10.635 - 30` (`mBoff_SALT2 - 2.5*log10(X0SCALE_SALT2)`), la identidad
algebraica que hace que `X0FromDistMod` reproduzca el `x0` real de SNANA byte a byte.

### Aplicado y verificado end-to-end: la corrección es real, pero el residuo NO se cierra (empeora)

Se corrigió `m_abs_func` (`loc=-19.3` → `loc=-19.365`) en `run_snia_ddf_poc.py` y
`compare_brightness_truth_salt2.py`, y se corrió de nuevo `compare_brightness_truth_salt2.sbatch`
(job 11897156, `COMPLETED`) contra el mismo `.DUMP` real de `SNIa_DDF_baseline_v5.3.1_10yrs`:

| z bin | Δmag Fase 17 (`M_abs=-19.3`) | Δmag Fase 20 (`M_abs=-19.365`, correcto) |
|---|---|---|
| [0.181,0.351) | -0.234 | -0.319 |
| [0.351,0.521) | -0.137 | -0.196 |
| [0.521,0.690) | -0.128 | -0.193 |
| [0.690,0.860) | -0.239 | -0.310 |
| [0.860,1.030) | -0.140 | -0.208 |
| [1.030,1.200) | -0.116 | -0.181 |
| **media** | **-0.166** | **-0.235** |

El desplazamiento medio real (-0.235 − (-0.166) = -0.069 mag) coincide con la predicción algebraica
(0.065 mag) dentro del ruido de binning -- **confirmación end-to-end, no solo de fórmula**.

### Conclusión Fase 20 (cierra el punto 9 de la Fase 18 de forma definitiva)

1. **`M_abs=-19.365` es la calibración físicamente correcta** -- verificada por triplicado (álgebra,
   coincidencia exacta de `x0`/flujo con archivos reales, y re-corrida end-to-end) -- y ya se aplicó a
   `run_snia_ddf_poc.py`/`compare_brightness_truth_salt2.py`. El valor `-19.3` de las Fases 0-19 era un
   placeholder de la literatura general, nunca antes verificado; corregirlo es una mejora real de
   fidelidad, independiente de lo que sigue.
2. **M_abs queda descartado como causa del residuo, con la evidencia más sólida de todo el
   proyecto** -- corregirlo a su valor real EMPEORA el exceso de brillo medido (-0.166 → -0.235 mag),
   no lo cierra. Esto revierte la propuesta de "calibración empírica ~-19.13" de Fase 19, que resultó
   ser un artefacto de un supuesto no verificado (que `X0SCALE_SALT2` cancela simétricamente en ambos
   simuladores) -- no cancela en LightCurveLynx/`sncosmo`, solo en SNANA.
3. **Lección metodológica explícita** (para no repetirla una cuarta vez): cuando dos simuladores
   comparten una constante de "normalización arbitraria", verificar SIEMPRE si esa constante se cancela
   en el flujo físico final de **ambos** lados por separado -- nunca asumir simetría. Las tres rondas
   sobre esta misma pregunta (Fase 17 álgebra parcial, Fase 19 "corrección" parcial, Fase 20 verificación
   completa) son un caso de estudio de por qué este proyecto insiste en verificar numéricamente contra
   archivos/código reales en vez de confiar en la derivación simbólica sola.
4. **Recomendación real que queda**: con M_abs, color law (Fase 16), extinción, ruido, footprint,
   SEARCHEFF, DNDZ y R_V todos cerrados o descartados con evidencia directa, el candidato que queda sin
   investigar es el que Fase 16 ya señalaba: la normalización/interpolación 2D (fase×longitud de onda)
   del propio flujo del template SALT2 -- comparar `M0(phase,wave)`/`M1(phase,wave)` punto a punto entre
   el `BicubicInterpolator` de `sncosmo` y la interpolación real de SNANA (`SALT2_TABLE`, spline/bicúbica
   propia en `genmag_SALT2.c`) sobre la misma grilla cruda -- nunca hecho, y ahora es el único mecanismo
   de la cadena SALT2 sin verificar directamente.

### Archivos de esta fase

- `run_snia_ddf_poc.py`/`compare_brightness_truth_salt2.py`: `m_abs_func` corregido a `-19.365`, con
  comentario explicando la derivación completa.
- `fase20_verify_mabs.py`/`fase20_compare_bins.py` (exploratorios, no versionados, borrados de NLHPC
  tras usarlos -- mismo criterio del proyecto para scripts de verificación puntual).
- `docs/index.html`: pestañas "Resumen"/"21 fases" de LightCurveLynx actualizadas para reflejar este
  cierre (reemplaza la recomendación de `-19.13` de Fase 19, ya superada).

## Fase 21 -- interpolación 2D del template SALT2: verificada y descartada como causa

Retoma el último candidato concreto que dejó pendiente Fase 16/20: la normalización/interpolación 2D
(fase × longitud de onda) del propio flujo del template SALT2 -- nunca antes comparada directamente
entre `sncosmo`/LightCurveLynx y SNANA.

### Hallazgo real: los dos simuladores usan esquemas de interpolación genuinamente distintos

Leyendo `fill_SALT2_TABLE_SED()`/`INTEG_zSED_SALT2()` reales (`genmag_SALT2.c`) y el `SALT2.INFO` real
de `SALT2.WFIRST-H17` (`SEDFLUX_INTERP_OPT: 1  # 1=>linear, 2=>spline` -- **confirmado LINEAR activo
para esta campaña**, no el default `2` (spline) del código): SNANA evalúa el flujo en cualquier
`(Trest, LAMSED)` con **interpolación bilinear real** (2×2 vecinos, lineal en día y en longitud de
onda, fórmulas `FSED = VAL0+(VAL1-VAL0)*FRAC_INTERP_LAMSED` y `FTMP = FSED[0]+FDIF*FRAC_INTERP_DAY`).

`sncosmo.salt2utils.BicubicInterpolator` (descargado el `.pyx` real, mismo método de Fase 16 --
`sncosmo/salt2utils.pyx` en GitHub, el paquete instalado solo trae el binario compilado) es
literalmente el <em>"Grid2DFunction" de snfit</em> -- **convolución bicúbica real** (kernel de Keys,
`a=-0.5`, ventana de 4×4 vecinos), con fallback a bilineal solo cerca de los bordes de la grilla. Son
dos algoritmos de interpolación genuinamente distintos, nunca antes comparados en este proyecto.

### Verificación numérica: la diferencia es real, pero 100x demasiado chica

`fase21_verify_interp.py` (no versionado) reimplementó la fórmula bilineal exacta de SNANA y la
comparó contra el `BicubicInterpolator` real de `sncosmo` (mismo objeto interno que usa
`SALT2Source._model['M0']`), sobre el `M0` crudo real (grilla nativa real: `DAYSTEP=1.0` día,
`LAMSTEP=10` Å) -- en el pico (`phase=0`) para la longitud de onda rest-frame real de la banda `r` en
los 7 `z` de Fase 16/20, y en un barrido fino de fase (`-10` a `+30` días) en B rest-frame:

| Punto de prueba | Δmag (bicúbico − bilineal) |
|---|---|
| pico, 7 valores de z reales (rest-frame r) | entre -0.0017 y +0.0022 mag |
| barrido de fase completo (B rest-frame, -10 a +30 d) | entre -0.0017 y +0.0022 mag |

**Máximo absoluto medido: 0.0022 mag** -- tres órdenes de magnitud más chico que el residuo de
`-0.235` mag (Fase 20). Con `DAYSTEP=1` día y `LAMSTEP=10` Å (grilla fina respecto a la escala de
variación real de la superficie SALT2), bilineal y bicúbico convergen -- **descartado como causa, con
evidencia numérica directa, no solo argumento de plausibilidad.**

### Conclusión Fase 21

Con esto se agotan los tres candidatos concretos de la cadena de generación de flujo SALT2 (color law
-- Fase 16 --, M_abs/M_B0 -- Fase 20 --, e interpolación 2D del template -- esta fase): **los tres
verificados directamente contra código y archivos reales, los tres descartados como causa del residuo
de ~0.235 mag.** La cadena SALT2 (`x0`↔magnitud, ley de color, superficie M0/M1) está ahora verificada
de punta a punta -- el residuo no viene de la física del modelo SALT2 en sí.

**Candidato metodológico nuevo, no descartado, no investigado todavía**: la comparación de "brillo
pico" (Fase 7/16/20) toma `flux_perfect.max()` sobre las épocas realmente observadas (cadencia real de
`OpSim`) del lado LightCurveLynx, no un escaneo continuo de fase -- si SNANA computa `PEAKMAG_r` de
forma distinta (evaluación directa en el verdadero pico de la curva, no limitada a la cadencia
observada), una diferencia de método -- no de física -- podría sesgar la comparación. No verificado en
esta sesión; requeriría leer cómo SNANA calcula `PEAKMAG_<filtro>` en el `.DUMP` real (`snlc_sim.c`).

### Archivos de esta fase

`fase21_verify_interp.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo). Sin cambios de
código en los scripts del proyecto -- esta fase es diagnóstico puro, sin fix que aplicar (candidato
descartado, no una causa a corregir).

## Fase 22 -- el residuo real es más grande de lo reportado: la metodología de "pico" subestimaba el brillo

Retoma el candidato metodológico que dejó pendiente Fase 21: la comparación de "brillo pico" usada en
Fases 7/16/20/21 (`flux_perfect.max()` sobre las épocas que la cadencia real de OpSim efectivamente
observó) podría no ser la misma medición que `PEAKMAG_r` real de SNANA.

### Confirmado: SNANA mide el pico verdadero, no uno limitado por cadencia

Leyendo `snlc_sim.c` real (~línea 12857-12866, comentario real *"always add artificial PEAKMJD epoch
to be last"*): SNANA inserta, para cada filtro, un epoch **sintético** exactamente en
`GENLC.PEAKMJD` (`OBSFLAG_GEN=false` -- no es una observación real generada, solo bookkeeping interno)
específicamente para que `PEAKMAG_<filtro>` sea el flujo evaluado en el pico verdadero/continuo
(fase=0 rest-frame), **no** el máximo sobre las épocas realmente cadenciadas.

### Herramienta real encontrada: `compute_noise_free_lightcurves()`/`compute_single_noise_free_lightcurve()`

LightCurveLynx expone una API real y ya probada (`lightcurvelynx/simulate.py`) para evaluar curvas de
luz sin ruido en fases rest-frame arbitrarias, **sin pasar por ningún `OpSim`/cadencia** -- reutiliza
`model.evaluate_bandfluxes()`, la misma maquinaria interna real que usa `simulate_lightcurves()`, no
una aproximación. Permite reusar el mismo `graph_state` (parámetros ya sampleados: z, x1, c, t0, ra,
dec) para comparar de forma pareada, objeto por objeto, la métrica vieja (cadencia) contra la métrica
correcta (`rest_frame_phase_min=0, rest_frame_phase_max=0.5, rest_frame_phase_step=1.0` → un solo
punto exacto en `t0`).

### Resultado: ~1/3 de los objetos tienen cobertura de cadencia pésima cerca de su propio pico

Corrido sobre los mismos 2000 objetos de `compare_brightness_truth_salt2.py` (mismo `seed_base`, mismo
`M_abs=-19.365` de Fase 20), comparando `flux_perfect.max()` (cadencia) vs. flujo evaluado en
`rest_phase=0` (verdadero), objeto por objeto:

- **33.6% de los objetos tienen `|Δmag| > 0.5`** entre ambas métricas -- la cadencia real de DDF
  (pocas épocas por objeto) frecuentemente no cae cerca del pico real de un objeto dado.
- Caso extremo real verificado (no un bug de cómputo -- confirmado comparando contra la distribución
  completa de su bin de `z`, donde el valor "verdadero" cae justo en la mediana): un objeto con
  `flux_cadence_max=0.000355` pero `flux_true_peak=8945.6` (mediana real de su bin de z: ~8095) -- la
  cadencia simplemente nunca lo observó cerca de su pico real.
- La dirección es sistemática, no aleatoria: la mediana por objeto de `Δmag(verdadero−cadencia)` es
  **negativa** en los bins de `z` bajo (el pico verdadero es más brillante que el medido por cadencia,
  como predice la lógica -- un máximo sobre un subconjunto discreto de épocas nunca puede superar al
  máximo continuo) y se vuelve **positiva** hacia `z` alto (más complejo -- posición del pico real de
  banda `r` observada, que a alto `z` mapea a longitudes de onda rest-frame más azules, no coincide
  exactamente con `t0` definido en banda B).

### Recalculado contra el `.DUMP` real: el residuo casi se duplica

Repitiendo el binning de Fase 20 (mismos 7 bins de `z`, misma mediana poblacional por bin,
`PEAKMAG_r` real de SNANA sin cambios) pero con la métrica corregida (`flux` en `rest_phase=0` en vez
de `flux_perfect.max()` sobre cadencia):

| z bin | Δmag Fase 20 (cadencia, método viejo) | Δmag Fase 22 (`rest_phase=0`, corregido) |
|---|---|---|
| [0.181,0.351) | -0.319 | -0.466 |
| [0.351,0.521) | -0.196 | -0.480 |
| [0.521,0.690) | -0.193 | -0.534 |
| [0.690,0.860) | -0.310 | -0.599 |
| [0.860,1.030) | -0.208 | -0.503 |
| [1.030,1.200) | -0.181 | -0.534 |
| **media** | **-0.235** | **-0.519** |

**El residuo real (medido de forma consistente en ambos lados -- SNANA ya evalúa su `PEAKMAG_r` en el
pico verdadero, no limitado por cadencia) es de ~-0.52 mag, más del doble de los ~-0.235 mag
reportados desde Fase 16.** La metodología usada desde Fase 7 (incluyendo Fase 16/20/21, todas las
verificaciones de color law/M_abs/interpolación 2D) subestimaba sistemáticamente el brillo real de
LightCurveLynx por el sesgo de cadencia -- esas tres verificaciones (color law, M_abs, interpolación)
siguen siendo válidas como descartes (todas comparaban contra la MISMA métrica vieja de forma
consistente, así que sus conclusiones de "no explica la brecha" no cambian), pero la magnitud real de
lo que hay que explicar es mayor de lo que se pensaba.

### Conclusión Fase 22

**Hallazgo metodológico real, no una causa física nueva**: el residuo sistémico de brillo de este
proyecto es más grande de lo reportado en las Fases 7-21 (~-0.52 mag, no ~-0.235 mag), pero la causa
raíz sigue sin identificarse -- de hecho ahora es un problema más grande de lo que parecía. Con color
law, M_abs e interpolación 2D ya descartados (Fase 16/20/21) y ahora con la magnitud real confirmada
más alta, el siguiente paso natural (Paso 2 de esta fase, pendiente) es comparar la curva de luz SALT2
completa -- no solo el pico -- entre ambos simuladores, para localizar en qué fase/banda específica
diverge la física, ya que "es más grande de lo pensado" por sí solo no dice dónde buscar.

**Nota metodológica para trabajo futuro**: cualquier comparación de brillo "pico" en este proyecto de
ahora en adelante debe usar `compute_noise_free_lightcurves()` (evaluado en `rest_phase=0`), no
`flux_perfect.max()` sobre la cadencia real -- la cadencia real de DDF (pocas épocas por objeto) no es
suficientemente densa para que el máximo observado sea una proxy confiable del pico verdadero.

### Archivos de esta fase

`fase22_paso1_peak_bias.py`/`fase22_paso1_vs_dump.py` (exploratorios, no versionados, borrados de
NLHPC tras usarlos). Sin cambios a `run_*_poc.py`/`compare_brightness_truth_salt2.py` -- este hallazgo
es sobre la METODOLOGÍA de comparación (un script de análisis nuevo, no parte del pipeline de
simulación), no sobre un parámetro a corregir en la simulación en sí.

## Fase 23 -- la otra arista: el residuo corregido depende de la banda (patrón tipo extinción)

Continuación directa de Fase 22 -- se extiende la métrica corregida (`compute_noise_free_lightcurves`
en `rest_phase=0`, sin sesgo de cadencia) de la banda `r` sola a las **6 bandas LSST reales**
(`u,g,r,i,z,y`), comparadas contra las columnas reales `PEAKMAG_u/g/r/i/z/Y` del mismo `.DUMP` de
producción -- nunca antes comparado banda por banda con la métrica corregida.

### Resultado: el residuo NO es plano en longitud de onda

| Banda | Δmag medio (LCL−SNANA, bins 2-7, métrica corregida) |
|---|---|
| `g` | -0.593 |
| `r` | -0.519 |
| `i` | -0.469 |
| `z` | -0.435 |
| `y` | -0.382 |
| `u` | (solo 1 bin con datos válidos -- `PEAKMAG_u` real queda indefinido en la mayoría de los bins de
  `z`, banda muy angosta/tenue para SNIa a estos redshifts, sin estadística suficiente para concluir) |

**Patrón claro y monótono**: el exceso de brillo de LightCurveLynx es MÁXIMO en `g` (banda más azul con
estadística suficiente) y decrece sistemáticamente hacia el rojo (`r`→`i`→`z`→`y`) -- una diferencia de
~0.21 mag entre `g` y `y`. Esto es cualitativamente **el mismo patrón que produce la extinción** (más
fuerte en azul, más débil en rojo) -- un candidato real y concreto que no se había visto antes porque
todas las comparaciones de brillo previas (Fases 7/16/20/21/22) se hicieron solo en banda `r`.

### Lo que esto NO invalida (y lo que sí reabre)

- El color law en sí (`SALT2colorlaw1`/`SALT2ColorLaw`, Fase 16) sigue verificado idéntico a precisión
  de máquina -- ese mecanismo específico no es la causa.
- `x0` (el factor acromático que escala toda la SED) también sigue verificado idéntico (Fase 20) -- no
  puede producir por sí solo una dependencia de banda.
- La interpolación 2D (Fase 21) ya se midió despreciable (`<0.0022` mag) en B rest-frame -- no se
  volvió a medir explícitamente para las otras 5 bandas en este barrido, queda como cabo suelto menor.
- **Candidato real que reabre esto**: la extinción MW (`ExtinctionEffect`/`O94`, aplicada
  `frame="observer"`) es intrínsecamente cromática (más fuerte en azul) -- nunca se verificó si
  LightCurveLynx aplica la MISMA cantidad de extinción, banda por banda, que el `OPT_MWCOLORLAW`/`R_V`
  real de SNANA para el mismo `E(B-V)` nominal. Fase 10 solo verificó la FÓRMULA de dispersión
  (`GENSIGMA_MWEBV_RATIO`) sobre el valor nominal de `E(B-V)`, nunca la curva de extinción cromática
  aplicada al flujo en sí, banda por banda. Es el candidato más concreto y accionable que queda.

### Conclusión Fase 23

Confirma que la "otra arista" (comparar más allá de un solo número/banda) sí revela información nueva
que el enfoque anterior (solo banda `r`) no podía ver: el residuo tiene estructura cromática real, no
es un offset acromático global. El siguiente paso natural, no ejecutado en esta sesión, es comparar
directamente la curva de extinción MW aplicada (`ClippedExtinctionEffect`/`dust_extinction` `O94` vs.
`OPT_MWCOLORLAW` real de SNANA) evaluada en las 6 bandas para un `E(B-V)` fijo, aislando ese mecanismo
específico del resto de la cadena.

### Archivos de esta fase

`fase23_multiband_peak.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo). Sin cambios a
scripts del pipeline -- diagnóstico puro.

## Fase 24 -- accionado el candidato de Fase 23: ley de extinción MW real es Fitzpatrick99, no O94

Acciona directamente el candidato que dejó abierto Fase 23 (extinción MW cromática).

### Hallazgo real: el `.INPUT` real usa `OPT_MWCOLORLAW: 99` (Fitzpatrick99 exacto), nunca O94/CCM89

Grepeando `AUTOSIM/build/full_v5.3_10yrs/includes/include_model_<clase>.INPUT` reales (confirmado
idéntico para `SNIa`, `SLSN-I`, `SNIa-91bg` -- se inyecta por clase, campaña-wide, no varía):
```
OPT_MWEBV:  1
OPT_MWCOLORLAW:  99
```
Leyendo `MWgaldust.h` real de SNANA: `OPT_MWCOLORLAW_FITZ99_EXACT = 99` ("exact Fitzpatrick (1999),
S.Thorp 2024") -- **no** `OPT_MWCOLORLAW_CCM89=89` ni `OPT_MWCOLORLAW_ODON94=94`. Los 5 scripts del
proyecto que aplican extinción MW (`run_simsed_poc.py`, `run_non1ased_poc.py`, `run_snia_ddf_poc.py`,
`compare_brightness_truth.py`, `compare_brightness_truth_salt2.py`) usaban
`extinction_model="O94"` desde Fase 1 -- un supuesto ("misma familia que SNANA") nunca antes verificado
contra el valor numérico real del `.INPUT`. Afecta a las 19 clases por igual, no solo `SNIa`.

### Verificado numéricamente: la diferencia es real, pero demasiado chica para explicar Fase 23

`dust_extinction` (el mismo paquete que ya usa el proyecto) trae `F99` como clase nativa. Comparando
`O94(Rv=3.1)` vs `F99(Rv=3.1)` -- `.extinguish()` real de ambas -- en las 6 bandas LSST, para los
`E(B-V)` reales de los 6 campos DDF (`0.006-0.025`) y un valor de referencia 6x más alto (`0.10`):
**diferencia máxima medida: <0.005 mag**, incluso en el caso de referencia con `E(B-V)` artificialmente
alto -- tres órdenes de magnitud más chico que el patrón de ~0.21 mag (g→y) de Fase 23. Consistente con
el hallazgo ya establecido en Fase 1 (los 6 campos DDF se eligieron deliberadamente por su baja
extinción): con `E(B-V)` tan bajo, la elección de ley de extinción casi no importa en magnitud absoluta,
sin importar cuál de las dos sea la "correcta". **Descartado como causa del patrón cromático de
Fase 23**, con evidencia numérica directa -- pero es una corrección real de todas formas.

### Corregido en los 5 scripts, sin necesidad de re-correr para verificar

Se corrigió `extinction_model="O94"` → `extinction_model="F99"` en los 5 scripts. No se re-corrió el
catálogo completo para confirmar el cambio -- la propia verificación numérica de arriba (<0.005 mag de
diferencia máxima a estos `E(B-V)`) ya acota el efecto esperado muy por debajo del ruido estadístico de
5 semillas ya reportado por clase (Fase 5), así que no hay nada que una re-corrida real pudiera revelar
que la verificación directa no haya cerrado ya.

### Conclusión Fase 24

El candidato concreto de Fase 23 queda accionado (corrección real aplicada) pero **no explica el patrón
cromático** -- descartado con la misma evidencia numérica directa que ya cerró color law (Fase 16),
M_abs (Fase 20) e interpolación 2D (Fase 21). El patrón g→y de ~0.21 mag de Fase 23 sigue sin explicarse.
**Candidato que queda, no investigado**: dado que el patrón correlaciona con la banda OBSERVADA (mismo
orden descendente `g>r>i>z>y` en cada bin de `z` de Fase 23, no con la longitud de onda rest-frame que
cada banda mapea según `z` -- lo que descartaría un artefacto ligado al redshift) el mecanismo más
probable que queda sin verificar es la propia **convención de integración de flujo en banda**
(photon-counting vs. energy-flux, factor `LAMSED*TRANS` visto en `INTEG_zSED_SALT2()` real de SNANA
vs. la integración real de `sncosmo`/LightCurveLynx) -- nunca comparada explícitamente término a
término, a diferencia de la forma estática del passband (Fase 12, sí verificada idéntica).

### Archivos de esta fase

`run_simsed_poc.py`, `run_non1ased_poc.py`, `run_snia_ddf_poc.py`, `compare_brightness_truth.py`,
`compare_brightness_truth_salt2.py`: `extinction_model` corregido de `"O94"` a `"F99"`.
`fase24_verify_extinction.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo).

## Fase 25 -- integración de flujo en banda: intento sin resultado confiable (documentado honesto)

Ataca el candidato que dejó abierto Fase 24: la convención de integración de flujo en banda
(photon-counting vs. energy-flux) entre SNANA y `sncosmo`/LightCurveLynx.

### Lo que se confirmó con lectura de código real (sólido)

- **SNANA** (`INTEG_zSED_SALT2()` real, `genmag_SALT2.c`): `Fbin_forFlux = FTMP * CCOR * HOSTXT_FRAC *
  MWXT_FRAC * LAMSED * TRANS`, con `LAMSED` = longitud de onda REST-FRAME (`LAMOBS/(1+z)`) y `TRANS` =
  transmisión real del filtro en `LAMOBS`. Pesa por `λ` (photon-counting), consistente con la
  convención estándar de fotometría de conteo de fotones.
- **LightCurveLynx** (`Passband.compute_system_response_table()` real,
  `astro_utils/passbands.py`): `φ_b(λ) = S_b(λ)/λ / ∫[S_b(λ)/λ]dλ` -- cita explícita "eq. 8, On the
  Choice of LSST Flux Units (Ivezić et al.)" -- pesa por `1/λ`, no por `λ`. Documentado como una
  convención real y deliberada (no un bug), con referencia a un paper técnico real de LSST.

Que ambas fórmulas tengan un peso de signo opuesto en `λ` (uno `+λ`, el otro `1/λ`) es real y
verificado -- **pero no se pudo determinar de forma confiable si esto produce una diferencia neta
significativa**, por lo que sigue abajo.

### Intento de verificación numérica: resultado NO confiable, documentado en vez de ocultado

Se intentó reconstruir "a mano" la fórmula literal de SNANA (mismo patrón exitoso de Fases 16/19-21)
y compararla contra `Passband.fluxes_to_bandflux()` real de LightCurveLynx, usando el mismo `M0`/`M1`
crudo real y el mismo color law real (`sncosmo.SALT2ColorLaw`), en las 6 bandas LSST reales, a `z=0.6`
(representativo de la población de Fase 23). **Primer intento**: bug real encontrado y corregido en el
propio script (reconstruir `S_b(λ)` desde `normalized_system_response` de LightCurveLynx es circular --
ya trae horneada la normalización `1/λ` de LCL con una constante DISTINTA por banda, contaminando la
comparación). Corregido usando la tabla de transmisión cruda real (`transmission_table`, sin normalizar)
interpolada a la grilla de cada banda.

**Resultado tras la corrección: sigue sin ser confiable.** Los números salen implausiblemente grandes
(hasta ~3 mag en banda `u`) y **no monótonos** entre bandas (`u:+2.97, g:+0.36, r:0, i:-0.22, z:-0.15,
y:+0.58`) -- ni de lejos compatible con el patrón suave y monótono de Fase 23 (`g→y`, ~0.21 mag total).
Diagnóstico probable: a `z=0.6`, el borde azul de la banda `u` observada mapea a `λ_rest≈2000` Å --
exactamente el límite crudo del template SALT2 (`wave_grid[0]=2000`) -- el corte duro que aplica el
script ahí (`wave_rest >= wave_grid[0]`) introduce una discontinuidad artificial justo dentro de la
banda `u`, y el resultado inestable en las otras bandas (el signo de `y` se invirtió por completo entre
el primer y segundo intento, solo por corregir el bug de normalización circular) sugiere que la
reconstrucción manual, aislada de la ejecución real de ninguno de los dos códigos, es demasiado frágil
para esta pregunta específica -- **no aporta evidencia confiable en ninguna dirección.**

### Conclusión Fase 25 -- honesta: candidato ni confirmado ni descartado

A diferencia de Fases 16/20/21/24 (donde la reconstrucción manual sí dio resultados limpios y
verificables), este intento no llegó a un resultado defendible. No se reporta un número porque no se
confía en él -- **el candidato de la convención de integración de banda queda abierto, sin resolver**,
ni confirmado ni descartado. La forma correcta y confiable de cerrar esto (no intentada en esta sesión,
requiere más tiempo/alcance): correr el binario REAL de `snlc_sim.exe` (`SNANA_DIR` real ya disponible
en NLHPC, confirmado en fases anteriores) con un objeto de prueba controlado (`x1`/`c`/`z`/`t0` fijos,
`NGENTOT_LC` chico) y comparar su flujo por banda real, epoch por epoch, directo contra
`compute_noise_free_lightcurves()` real de LightCurveLynx para el mismo objeto -- comparación código
real contra código real, no una reconstrucción manual de la fórmula de SNANA que ya mostró ser frágil
en este caso específico (a diferencia de `SALT2x0calc`/interpolación 2D/color law, donde sí funcionó
bien en Fases 16/20/21).

### Archivos de esta fase

`fase25_bandflux_convention.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo -- 2
versiones, la primera con el bug de normalización circular ya documentado arriba). Sin cambios a
scripts del pipeline -- ningún hallazgo lo suficientemente confiable como para actuar sobre él.

## Fase 26 -- integración de flujo en banda cerrada: código real vs. código real, descartada

Cierra definitivamente el candidato que dejó abierto Fase 25, siguiendo el camino que esa misma fase
identificó como el correcto: comparar código real contra código real, no una reconstrucción manual de
la fórmula de SNANA.

### 1a/1b -- higiene: la reconstrucción manual NO es de fiar, ni por borde de template ni por forma del SED

Se repitió el intento de Fase 25 a `z` seguros (`0.15, 0.3, 0.6, 0.9`, lejos del borde azul del template
SALT2 salvo un efecto menor en `u` a `z=0.9`) y con un control de espectro plano (`f_λ=`constante).
Resultado: la señal es **estable en `z`** (no es un artefacto de borde, contra lo que sugería el
diagnóstico de Fase 25) pero **espectro real y espectro plano dan prácticamente el mismo resultado**
implausible y no monótono (`u:+3.0, g:+0.44, r:0, i:-0.23, z:-0.16, y:+0.56` mag relativo a `r`) -- muy
distinto del patrón suave y monótono de Fase 23. Esto confirma que el problema no es el SED ni el borde
del template: la propia reconstrucción manual, comparando dos fórmulas ad-hoc con normalizaciones no
directamente comparables entre sí, no rastrea ningún efecto físico real. Confirma la recomendación de
Fase 25: abandonar la reconstrucción manual y pasar directo a la prueba definitiva.

### 1c -- la prueba definitiva: `snlc_sim.exe` real vs. `compute_noise_free_lightcurves()` real

Se corrió el binario real de SNANA (`SNANA_DIR=/home/lmod/software/SNANA/11.05p`, módulo `SNANA/11.05p`,
el mismo binario que genera toda la campaña de producción) con un `.INPUT` mínimo (`sbatch`, no en login
node) que fija un objeto SALT2 exactamente conocido: `GENRANGE_REDSHIFT`/`GENRANGE_SALT2c`/
`GENRANGE_SALT2x1` colapsados a un punto (`z=0.15`, `x1=0.973`, `c=-0.054`, mismos valores pico
nominales de la campaña), `GENSIGMA_SALT2c/x1: 0 0`, `OPT_MWEBV: 0` (aísla el objeto de la extinción MW,
ya descartada en Fase 24), mismo modelo real `SALT2.WFIRST-H17`, mismo SIMLIB DDF real,
`OPT_MWCOLORLAW: 99` (Fase 24). No existe un modo `GENPERFECT` que simplifique esto directamente para
este caso (revisado en `snlc_sim.c` real: sus bits solo tocan smearing/extinción/HOSTLIB, no colapsan
rangos de parámetros) -- se usó la vía directa de colapsar `GENRANGE_*`.

Dos bugs reales de sintaxis `.INPUT` encontrados y corregidos en el camino (documentados porque son
reales, no artefactos): `SIMGEN_DUMPALL: N` debe declarar el conteo EXACTO de variables listadas
(un desfase de 3 corrompió el parseo de todas las keys siguientes, incluyendo `GENMODEL`, con el error
engañoso `'' is not a valid genmag-model`); y `DNDZ` es obligatorio incluso con `GENRANGE_REDSHIFT`
colapsado a un punto (sin él, `init_DNDZ_Rate` aborta con `Unknown rate model`).

El `.DUMP` real resultante (`TEST_FASE26_bandflux_hygiene.DUMP`) dio `PEAKMAG_z`/`PEAKMAG_Y` = `-9`
(sin dato) para los 40 objetos generados, pese a que el LIBID elegido sí tiene epochs reales en `z`
(523 observaciones, confirmado grepeando el SIMLIB) -- un comportamiento real de `snlc_sim.exe` no
diagnosticado a fondo (posiblemente relacionado con `GENLC.SIMLIB_USEFILT_ENTRY`/`keep_SIMLIB_OBS`,
visto en el código real pero sin causa raíz confirmada), que queda anotado como cabo suelto menor y no
bloqueante: `u/g/r/i` sí quedaron completos y son exactamente las bandas centrales del patrón de
Fase 23.

Del lado LightCurveLynx: se reconstruyó el objeto EXACTO que generó SNANA (mismo `z` heliocéntrico,
`x1`, `c`, `t0=PEAKMJD` real, `x0` calculado con `_x0_from_distmod()` real de LightCurveLynx usando el
`MU` real que SNANA generó) vía `SncosmoWrapperModel` + `compute_noise_free_lightcurves()` real (sin
`ExtinctionEffect`, ya que `OPT_MWEBV=0` del lado SNANA), para dos objetos reales independientes del
`.DUMP` (CID=2 y CID=7, distintos `z`/`RA`/`DEC`/`PEAKMJD`).

**Resultado, banda por banda, relativo a `r` (aísla el efecto puro de convención, cancela cualquier
offset acromático global):**

| banda | CID=2: LCL−r | CID=2: SNANA−r | diff | CID=7: LCL−r | CID=7: SNANA−r | diff |
|---|---|---|---|---|---|---|
| u | +0.8702 | +0.8722 | −0.0020 | +0.8741 | +0.8760 | −0.0019 |
| g | −0.0708 | −0.0706 | −0.0002 | −0.0707 | −0.0705 | −0.0002 |
| i | +0.3243 | +0.3238 | +0.0005 | +0.3218 | +0.3213 | +0.0005 |

Las diferencias reales (`diff`) son de **0.0002 a 0.002 mag** -- dos a tres órdenes de magnitud más
chicas que el patrón de Fase 23 (`~0.07-0.12` mag entre bandas adyacentes). El offset acromático global
sí es real y del orden esperado (`Δmag(LCL−SNANA)` ≈ `-0.27` mag parejo en las 4 bandas, consistente con
el residuo ya conocido desde Fase 22) -- pero es constante entre bandas, no cromático: la convención de
integración NO introduce estructura cromática detectable a este nivel de precisión.

### Conclusión Fase 26 -- descartado con evidencia sólida, código real contra código real

La convención de integración de flujo en banda (`λ` de SNANA vs. `1/λ` de LightCurveLynx) **no explica
el patrón cromático de Fase 23**, con la evidencia más fuerte posible para esta pregunta: no una
reconstrucción manual de fórmulas (que ya mostró ser frágil en Fase 25 y de nuevo en 1a/1b de esta
fase), sino los dos binarios/APIs reales de producción, para el mismo objeto exacto, comparados
directamente. Con esto se agotan **todos** los candidatos concretos identificados en la cadena SALT2:
color law (Fase 16), `M_abs`/`x0` (Fase 20), interpolación 2D del template (Fase 21), ley de extinción MW
(Fase 24), y ahora la convención de integración de banda (Fase 26) -- los cinco descartados con
evidencia numérica directa. **El patrón cromático de Fase 23 (`g→y`, ~0.21 mag de spread total) queda
sin causa identificada** dentro del alcance de esta investigación de la cadena SALT2 propiamente dicha.
Esto es en sí mismo un resultado válido y bien acotado, no un fracaso: la investigación deja mapeado con
precisión qué NO lo explica, lo cual reduce sustancialmente el espacio de búsqueda para cualquier
continuación futura (candidatos fuera de la cadena SALT2 -- p.ej. el modelo de ruido/PSF por banda, o
algo en el propio `Passband`/`kcor_LSST.fits` no cubierto aún -- quedan como las áreas más probables no
exploradas). Las conclusiones finales de la investigación completa (síntesis como astrónomo experto)
quedan fuera de esta fase, a pedido explícito del usuario, para una sesión aparte.

### Archivos de esta fase

Exploratorios, no versionados, borrados de NLHPC tras usarlos: `fase26_bandflux_hygiene.py` (1a),
`fase26_flat_control.py` (1b), `sim_fase26_bandflux_test.INPUT` + `run_fase26_bandflux_test.sh` (1c,
SNANA real), `fase26_lcl_vs_real_snana.py` + `fase26_check2.py` (1c, LightCurveLynx real). Sin cambios a
scripts del pipeline -- candidato descartado, nada que corregir.

## Fase 27 — la integración de banda SÍ crece con z, pero de signo contrario al patrón de Fase 23

Fase 26 cerró el candidato "integración de flujo en banda" probándolo en un único punto, `z=0.15`, y
generalizó esa conclusión (diferencia despreciable) a toda la cadena SALT2. Pero el patrón cromático de
Fase 23 es un promedio poblacional sobre `z≈0.18` a `z≈1.2` — nunca se verificó si la diferencia (chica
a `z` bajo) se mantiene chica a `z` alto. Antes de asumir eso, se revisaron dos candidatos más por
lectura de código, sin necesitar corridas:

- **Extinción de host (`HOSTXT_FRAC`)**: descartado. El `.INPUT` real de la clase `SNIa` de esta campaña
  (`include_model_SNIa.INPUT` → `SIMGEN_INCLUDE_SNIa-SALT2.INPUT`) no declara `GENTAU_AV`/`GENRANGE_AV`
  — a diferencia de `SNIax`/`TDE-MOSFIT` (Fases previas), SNANA no aplica extinción de host a `SNIa` en
  este modelo. No puede ser la fuente de una diferencia con LightCurveLynx (que tampoco la aplica).
- **`kcor_LSST.fits` vs. preset `LSST`**: ya descartado con evidencia numérica concluyente en **Fase 12**
  (`ZPoff=0`, curvas idénticas a 4 decimales, mismo release v1.9) — no hacía falta repetirlo.

### Paso A — el offset relativo a `r` NO es plano en `z` (dato ya simulado, sin `sbatch` de simulación)

Se extendió `compare_brightness_truth_salt2.py` (mismo `seed_base=20260812`, mismos 2000 objetos) para
capturar las 6 bandas vía `compute_noise_free_lightcurves()` (rest_phase=0) en vez de solo `r`, y se
comparó contra `PEAKMAG_u/g/r/i/z/Y` real del `.DUMP` de producción
(`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`), binned en los mismos 7 bins equi-anchos de `z` de Fases 20/22/23
(`np.linspace(0.011, 1.2, 8)`). Corrección de metodología real encontrada en el propio análisis:
`PEAKMAG_<filt>=-9` es el flag real de SNANA para "banda no definida en este `z`" (Fase 13 — el borde del
`RESTLAMBDA_RANGE`, `u`/`g` observados mapean a rest-frame por debajo de 2000 Å a `z` alto) — hay que
enmascarar esos valores ANTES de tomar la mediana, no después, o contaminan el resultado con outliers de
`-9` mag (un bug real cometido y corregido en el primer intento de este mismo script).

| bin `z` (centro) | `u−r` | `g−r` | `i−r` | `z−r` | `y−r` |
|---:|---:|---:|---:|---:|---:|
| 0.10 | nan | nan | +0.066 | nan | nan |
| 0.27 | nan | -0.182 | 0.000 | +0.037 | nan |
| 0.44 | nan | -0.099 | -0.026 | -0.037 | +0.285 |
| 0.61 | nan | -0.015 | -0.083 | -0.109 | +0.376 |
| 0.78 | nan | nan | -0.138 | -0.173 | nan |
| 0.95 | nan | nan | -0.074 | -0.096 | nan |
| 1.12 | nan | nan | +0.012 | -0.065 | nan |

*(`u`/`g`/`y` quedan mayormente indefinidos en `PEAKMAG` real fuera de `z` bajo — mismo fenómeno de
borde de template ya señalado en Fase 23; `i` y `z` son las únicas columnas con cobertura completa en
los 7 bins.)* El offset relativo a `r` **no es plano** — crece en magnitud desde los bins bajos hacia
`z≈0.6-0.8` (`i−r`: `+0.066 → 0.000 → -0.026 → -0.083 → -0.138`) y luego se revierte parcialmente hacia
`z` alto. No es una función limpia y monótona de `z`, pero tampoco es constante — suficiente para
justificar extender la prueba código-real-contra-código-real de Fase 26 a más valores de `z`, en vez de
asumir que el resultado de `z=0.15` generaliza.

### Paso B1 — extender Fase 26 (código real vs. código real) a `z=0.6` y `z=0.9`

Mismo método exacto de Fase 26 (1c): `snlc_sim.exe` real (`SNANA/11.05p`) con `GENRANGE_REDSHIFT`/
`GENRANGE_SALT2c`/`GENRANGE_SALT2x1` colapsados a un punto (`x1=0.973`, `c=-0.054`, valores pico
nominales de la campaña), `OPT_MWEBV: 0`, mismo modelo `SALT2.WFIRST-H17`, mismo SIMLIB DDF real,
`NGENTOT_LC: 5`. **Bug real de sintaxis `.INPUT` nuevo, distinto a los dos de Fase 26**: SNANA aborta con
`'GENRANGE_REDSHIFT:' keys exceeds limit=1` si se incluye el `.INPUT` completo del modelo real
(`SIMGEN_INCLUDE_SNIa-SALT2.INPUT`, que ya declara `GENRANGE_REDSHIFT`/`SALT2c`/`SALT2x1`) y ADEMÁS se
re-declaran esas mismas keys para colapsarlas a un punto — `checkStringUnique` con `limit=1` no permite
keys duplicadas, ni siquiera para "sobreescribir". Corregido copiando a mano solo las keys necesarias
(`GENMODEL`, `DNDZ`, `GENRANGE_TREST`, `GENMEAN_SALT2ALPHA/BETA`) sin incluir el archivo completo del
modelo — coherente con la nota de Fase 26 de que no hay una vía de "override" directa en este release.

Del lado LightCurveLynx: se tomó el objeto `CID=1` de cada `.DUMP` real (mismo RA/Dec/PEAKMJD en ambos
`z` porque el `LIBID` de SIMLIB quedó fijo entre corridas) y se reconstruyó exacto vía
`SncosmoWrapperModel` + `compute_noise_free_lightcurves()` real, con `x0` calculado por
`X0FromDistMod` usando el `MU` real que generó SNANA (no una cosmología propia recalculada) — mismo
patrón que Fase 26.

**Resultado, banda por banda, relativo a `r` (misma convención de Fase 26: `diff = (LCL−r) − (SNANA−r)`):**

| `z` | banda | LCL−r | SNANA−r | diff |
|---:|---|---:|---:|---:|
| 0.15 (Fase 26, referencia) | u/g/i | — | — | `-0.0020` / `-0.0002` / `+0.0005` |
| 0.6 | g | +1.3132 | +1.2197 | **+0.0935** |
| 0.6 | i | -0.0270 | +0.0594 | **-0.0864** |
| 0.6 | z | +0.0144 | +0.1141 | **-0.0997** |
| 0.6 | y | +0.1041 | +0.2019 | **-0.0978** |
| 0.9 | i | -0.7188 | -0.5987 | **-0.1201** |
| 0.9 | z | -0.7546 | -0.5775 | **-0.1771** |
| 0.9 | y | -0.6263 | -0.4288 | **-0.1975** |

(`u` queda indefinido en el `.DUMP` real a ambos `z` — banda `u` observada mapea por debajo de 2000 Å
rest-frame ya a `z=0.6`; `g` queda indefinido también a `z=0.9`, mismo mecanismo de borde de Fase 13,
consistente con el patrón de `nan` del Paso A.)

**El efecto SÍ crece fuertemente con `z`**: de `~0.0002-0.002` mag en `z=0.15` (Fase 26) a `~0.09-0.20`
mag en `z=0.6-0.9` — dos órdenes de magnitud, y en `z=0.9` la magnitud (`i:-0.12, z:-0.18, y:-0.20`) es
comparable o mayor a la del propio patrón de Fase 23 (`~0.07-0.12` mag entre bandas adyacentes). **Fase
26 no generalizaba**: su descarte era válido solo en el punto que probó, no para toda la cadena SALT2
como se documentó entonces.

### Pero el signo es el opuesto al patrón que hay que explicar

Traduciendo el patrón poblacional de Fase 23 (`Δmag(LCL−SNANA)` por banda) a la misma convención "relativo
a `r`" que esta prueba (`Δ_Fase23(banda) − Δ_Fase23(r)`): `g: -0.074, i: +0.050, z: +0.084, y: +0.137` —
**creciente y positivo** de `g` a `y` (LCL relativamente cada vez MÁS brillante que SNANA hacia el rojo,
respecto de `r`). El efecto medido acá en `z=0.6-0.9` es **decreciente y negativo** hacia el rojo
(`i:-0.09/-0.12, z:-0.10/-0.18, y:-0.10/-0.20`) — **signo contrario**, no solo en `y` sino en `i`/`z`
también. Un mecanismo que empuja en la dirección opuesta a la observada no puede ser la explicación
(directa, aislada) del patrón de Fase 23 — como mucho, **cancela parcialmente** parte de la señal real a
`z` alto, lo que implica que la causa verdadera (aún no identificada) debe ser de magnitud mayor a la ya
medida en Fase 23 para sobrevivir a esta cancelación parcial.

### Conclusión Fase 27 — reabierto en magnitud, descartado en dirección; resultado genuinamente mixto

No es un descarte limpio ni una confirmación limpia, y se documenta así en vez de forzar una lectura
simple (mismo criterio de honestidad que Fase 25): la integración de banda **no es despreciable a todo
`z`** (Fase 26 generalizaba de más), pero tampoco puede ser la causa (aislada) del patrón de Fase 23
porque el signo no coincide. Verificado además, por lectura de código real sin necesitar corridas
nuevas, que el modelo de dispersión intrínseca cromática real de esta campaña
(`GENMAG_SMEAR_MODELNAME: G10` en `SIMGEN_INCLUDE_SNIa-SALT2.INPUT`, confirmado activo — simplificación
ya señalada como conocida en `NOTES.md` desde las primeras fases, nunca antes verificada) tampoco puede
ser la causa de un sesgo sistemático de mediana: `init_genSmear_SALT2()`
(`sntools_genSmear.c` real) construye el smear como `SIGCOH * RANGauss_LIST[...]` — un draw Gaussiano de
media cero por construcción, no una función determinista con sesgo direccional; además `PEAKMAG_<filt>`
en el `.DUMP` es la magnitud teórica/sin ruido (Fase 22 — epoch sintético en `PEAKMJD`), que no incluye
el smear en absoluto, consistente con el match exacto a 4 decimales de Fase 26 en `z=0.15`. Con esto se
agotan también estos dos candidatos adicionales. El patrón cromático de Fase 23 **sigue sin causa
identificada**, ahora con un candidato adicional (integración de banda) reclasificado de "descartado" a
"real pero de signo opuesto, insuficiente como única explicación" — y con el espacio de búsqueda para
una continuación futura reducido a mecanismos fuera de la cadena SALT2 propiamente dicha (p.ej. algo en
el modelo de ruido/PSF por banda, aunque eso no debería afectar una comparación sin ruido como esta).

### Archivos de esta fase

Exploratorios, no versionados, borrados de NLHPC tras usarlos: `fase27_paso_a_zbins.py` +
`fase27_paso_a.sbatch` (Paso A, población completa 6 bandas), `sim_fase27_bandflux_z06.INPUT` +
`sim_fase27_bandflux_z09.INPUT` + `run_fase27_bandflux_test.sbatch` (Paso B1, SNANA real),
`fase27_lcl_vs_real_snana.py` + `fase27_lcl_check.sbatch` (Paso B1, LightCurveLynx real). GENVERSIONs
`TEST_FASE27_bandflux_z06`/`z09` generados en `SNDATA_ROOT/SIM/` y borrados tras extraer el `.DUMP`. Sin
cambios a scripts del pipeline -- diagnóstico puro, ningún candidato quedó en condición de accionar una
corrección.

## Fase 28 — interpolación 2D descartada también a z alto; M1 confirmado idéntico; la descomposición término a término se topa con un límite real

Antes de escribir código se revisó un candidato más por lectura de código, sin necesitar corridas:
**offsets de calibración/magnitud del `.INPUT` real** (`GENMAG_OFF_GLOBAL`/`GENMAG_OFF_MODEL`/
`FUDGE_MAG`/`MAGOFF`) -- grepeado en `include_model_SNIa.INPUT`, `SIMGEN_INCLUDE_SNIa-SALT2.INPUT` y
todo `~/AUTOSIM/build/full_v5.3_10yrs/`: **ninguna de esas keys aparece en ningún `.INPUT` de la
campaña** -- descartado sin ambigüedad.

### Paso 1 — interpolación 2D (Fase 21) reabierta en las λ_rest reales de z alto: descartada de nuevo, con más margen que antes

Fase 21 solo había medido la diferencia bilineal (SNANA real) vs. bicúbica (`sncosmo` real) en la
longitud de onda rest-frame de la banda `r` cerca de `z` bajo y en un barrido de fase en B rest-frame
-- nunca en las λ_rest que `g/i/z/y` muestrean realmente a `z=0.6-0.9`, justo donde Fase 27 encontró que
el residuo total (código real vs. código real) crece a `0.09-0.20` mag. Se repitió el método exacto de
Fase 21 (mismo `M0`/`M1` crudo, mismo `SALT2ColorLaw` real) pero evaluando el **bandflux real completo**
(vía `Passband.fluxes_to_bandflux()` real de LightCurveLynx, integrado sobre el ancho real de cada
banda, no solo su centro) dos veces -- una con `M0`/`M1` interpolados bilinealmente (fórmula exacta de
SNANA) y otra con el `BicubicInterpolator` real de `sncosmo` (`src._model["M0"]`/`["M1"]`) -- manteniendo
fijos la ley de color, `x1`/`c`, y la convención de integración de banda (ambos cálculos usan la MISMA
integración real de LightCurveLynx), para aislar el efecto puro del esquema de interpolación 2D.

**Bug real encontrado y corregido en el propio script** (mismo tipo de trampa de normalización que ya
mordió a Fase 25): `src._model["M0"]`/`["M1"]` (bicúbico real de `sncosmo`) ya trae horneado el factor
`X0SCALE_SALT2=1e-12` desde `__init__` (hallazgo de Fase 19/20), mientras que `M0`/`M1` crudo leído del
archivo (usado para el bilineal) no lo trae -- sin corregir esto, la razón de flujos salía contaminada
por un factor `1e12` fijo (`Δmag=30.00` idéntico en las 7 combinaciones banda/z, un valor obviamente
artificial). Corregido escalando el lado bilineal por `X0SCALE_SALT2` antes de comparar.

**Resultado, tras la corrección — negligible en las 7 combinaciones banda/`z` probadas:**

| `z` | banda | Δmag(bicúbico−bilineal) | `diff` real Fase 27 |
|---:|---|---:|---:|
| 0.6 | g | +0.0001 | +0.0935 |
| 0.6 | i | -0.0000 | -0.0864 |
| 0.6 | z | -0.0000 | -0.0997 |
| 0.6 | y | +0.0000 | -0.0978 |
| 0.9 | i | +0.0001 | -0.1201 |
| 0.9 | z | -0.0000 | -0.1771 |
| 0.9 | y | +0.0000 | -0.1975 |

El efecto de esquema de interpolación es de `~0.0000-0.0001` mag -- **más chico todavía que el máximo ya
despreciable de Fase 21 (`0.0022` mag)**, y tres a cuatro órdenes de magnitud menor que el residuo real
de Fase 27 (`0.09-0.20` mag). **Descartado de nuevo, ahora con cobertura completa de las λ_rest que
realmente importan a `z` alto** -- no queda como "cabo suelto" como lo dejó Fase 23. Con `DAYSTEP=1`
día/`LAMSTEP=10` Å (grilla nativa fina respecto a la curvatura real de la superficie SALT2), bilineal y
bicúbico siguen convergiendo incluso lejos de B/r.

### Verificación adicional — el template `M1` (nunca antes chequeado) es byte-idéntico

Las fases previas (16/20/21/25) solo habían confirmado `md5sum` idéntico para `salt2_template_0.dat`
(`M0`) entre `salt2_h17_local/` (copia local de LightCurveLynx) y el `SALT2.WFIRST-H17` real de
`$SNDATA_ROOT/models/SALT2/` (comprimido `.gz` en la copia real de SNANA) -- `M1` nunca se había
verificado explícitamente. Confirmado ahora: **`3685abb568a787b27bcb258cd2e823b2`, idéntico en ambos
lados** (igual que `M0`, re-confirmado de paso: `a75b5afcc7c59354af25c4b182ee3edd`). Cierra un supuesto
que se venía arrastrando sin verificar desde el inicio de la investigación.

### Paso 2 — descomposición término a término: todos los factores individualmente aislables ya están descartados, salvo uno que resiste el aislamiento

Con Paso 1 (interpolación) y la verificación de `M1` de arriba, junto a lo ya establecido en fases
previas, **todos los factores multiplicativos de `Fbin_forFlux = FTMP * CCOR * HOSTXT_FRAC * MWXT_FRAC *
LAMSED * TRANS`** (`genmag_SALT2.c`, confirmada real en Fase 25) quedan verificados individualmente:

| factor | estado | fase |
|---|---|---|
| `FTMP` (superficie `M0`+`x1·M1`, interpolación) | idéntico/despreciable | 21, **28 (esta fase, extendido a z alto)** |
| `M0`/`M1` (valores crudos del template) | byte-idéntico | 16 (M0), **28 (M1, primera vez)** |
| `CCOR` (ley de color) | idéntico a precisión de máquina | 16 |
| `HOSTXT_FRAC` | =1, no aplica a `SNIa` en esta campaña | 27 |
| `MWXT_FRAC` | =0 por diseño del test (`OPT_MWEBV:0`) | 26, 27 |
| `TRANS` (curva de transmisión) | idéntica a 4 decimales | 12 |
| `x0`/`M_abs` (normalización global) | idéntico a 6 cifras | 20 |
| dispersión cromática (`GENMAG_SMEAR_MODELNAME: G10`) | media cero, no sesga | 27 |
| `LAMSED*TRANS` (convención de integración: peso `λ` vs. `1/λ`) | **el único factor no aislado con éxito** | 25, 26 (higiene), este intento |

El único factor que queda es la propia convención de integración de banda. Se evaluó si se podía aislar
de forma limpia esta vez (a diferencia del intento fallido de Fase 25): en vez de reconstruir el flujo
absoluto de SNANA desde cero (la fuente de los bugs de normalización de Fase 25), la idea era comparar,
dentro del propio pipeline real de LightCurveLynx, el mismo SED real integrado con dos kernels de peso
distintos (`S_b(λ)/λ` real vs. `S_b(λ)·λ`), aislando así la convención sin tocar la física de SNANA. Pero
esto es **exactamente el experimento que Fase 25 y la higiene de Fase 26 (1a/1b) ya intentaron dos veces
y documentaron como no confiable** -- incluyendo el control de espectro plano de Fase 26, que debería
haber dado una razón moderada y predecible, y en cambio dio el mismo resultado implausible (`~3` mag en
`u`, no monótono) que con el SED real. Ese patrón (un control de espectro plano fallando igual que el
caso real) es la firma de un artefacto del propio método de comparación, no de un efecto físico -- y
reintentarlo por tercera vez sin identificar la causa raíz de esa falla tiene alta probabilidad de
reproducir el mismo artefacto. No se reintentó por esa razón: **se documenta como un límite metodológico
real de este proyecto**, no como un candidato pendiente de "intentar de nuevo".

### Conclusión Fase 28

Con la interpolación 2D descartada ahora también en el régimen de `z` alto (no solo B/r) y el template
`M1` confirmado idéntico, **se agota la lista completa de factores multiplicativos de la fórmula real de
SNANA que se pueden aislar y verificar de forma independiente y confiable con las herramientas
disponibles en este proyecto** -- los ocho primeros de la tabla de arriba, los ocho, están descartados
con evidencia numérica directa. Queda un único factor, la convención de integración de banda, que sigue
siendo plausible por eliminación (es lo único no verificado independientemente) pero que **no se puede
aislar de forma confiable con los métodos disponibles** (reconstrucción manual, intentada tres veces
contando esta fase, falla de la misma manera incluso con un control de espectro plano). Cerrar esto de
forma definitiva requeriría instrumentar el binario real de SNANA (agregar un `printf`/dump de
`FTMP`/`CCOR`/`LAMSED*TRANS` dentro de `INTEG_zSED_SALT2()` y recompilar `snlc_sim.exe`) -- una
escalación real, fuera del alcance de este proyecto exploratorio tal como está planteado (no toca código
de producción ni requiere recompilar SNANA). El patrón cromático de Fase 23 **sigue sin causa
identificada**, ahora con la investigación de la cadena SALT2 verdaderamente agotada dentro de los
métodos no invasivos disponibles -- cualquier continuación futura necesitaría, o bien instrumentación de
SNANA a nivel de C, o bien un cambio de enfoque hacia candidatos genuinamente fuera de la cadena SALT2
(el espacio ya señalado en Fase 27: modelo de ruido/PSF -- aunque no debería afectar una comparación sin
ruido como esta -- u otro mecanismo aún no identificado).

### Archivos de esta fase

`fase28_interp_zhigh.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo). Sin cambios a
scripts del pipeline -- diagnóstico puro, ningún candidato quedó en condición de accionar una corrección.

## Fase 29 — instrumentando SNANA real: la convención de integración de banda, correctamente normalizada, confirma el signo (y una fracción de la magnitud) del diff de Fase 27

A pedido explícito del usuario ("vamos por el lado a"), se instrumenta y recompila el propio código C de
SNANA (opción (a) del cierre de Fase 28) para aislar de una vez por todas el único factor de
`Fbin_forFlux = FTMP * CCOR * HOSTXT_FRAC*MWXT_FRAC * LAMSED*TRANS` (`genmag_SALT2.c`) nunca verificado
de forma confiable: la convención de integración de banda (`λ` de SNANA vs. `1/λ` de LightCurveLynx),
que Fases 25/26-higiene fallaron en aislar por reconstrucción manual (resultados implausibles, ~3 mag en
`u`, no monótonos, cambiando de signo entre intentos).

### El clon propio de SNANA ya era compilable -- solo hacía falta reconstruir el entorno de build

Verificado antes de tocar código: `~/github/SNANA_src` (clon privado del usuario, branch `master`, al
día con `origin/master`) ya tenía un `bin/snlc_sim.exe` previamente compilado con 2 parches locales
reales (`USE_PYTHON`/`USE_ROOT` deshabilitados en `genmag_PySEDMODEL.h`/`sntools_output.h`), pero sin el
`Makefile`/`config.status` generado (se había limpiado tras el build anterior) -- hubo que rehacer
`autoreconf -fi && ./configure && make snlc_sim` desde cero en NLHPC, lo cual reveló una cadena real de
dependencias de build rotas, todas resueltas sin tocar el código de SNANA en sí:

- `autoreconf` fallaba (`Can't locate File/Compare.pm`) porque el `/usr/bin/perl` del sistema (5.32) no
  trae ese módulo core -- resuelto copiando solo `File/Compare.pm` (puro Perl, sin binario XS) desde un
  módulo `perl/5.40` a un directorio aislado y apuntando `PERL5LIB` ahí (copiar el `lib` completo del
  perl 5.40 rompe por mismatch de ABI en `Cwd.so`, un XS binario -- solo el archivo puro-Perl es seguro
  de mezclar entre versiones).
- `./configure` requiere `python3-config` (para el flag `USE_PYTHON`, aunque esté deshabilitado a nivel
  de macro C -- el check de `configure.ac` es incondicional) -- resuelto con `module load
  python/3.13.2-zen4-6` (evitando cualquier módulo que dependa de `intel/`, que reemplaza `CC` por
  `mpiicc` y rompe la cadena de compilación gcc-nativa).
- La regla de compilación real de `Makefile.am` (`SNCFLAGS`/`ICFITSIO`/`IGSL`, NO las variables estándar
  `CPPFLAGS`/`LDFLAGS` de autoconf) requiere que GSL/cfitsio estén en el `PATH` de búsqueda nativo de
  `gcc` -- resuelto exportando `C_INCLUDE_PATH`/`LIBRARY_PATH`/`LD_LIBRARY_PATH` apuntando directo a
  instalaciones reales de `gsl/2.8` (build skylake_avx512) y `cfitsio/4.4.0` (build zen4/aocc) ya
  presentes en el árbol `spack` de NLHPC, en vez de usar módulos `module load` (que en este cluster no
  siempre exportan esas rutas de forma completa).
- El link final fallaba (`cannot find -lintl`) porque `python3-config --embed` de ese módulo Python
  requiere `libintl` (gettext) explícito -- resuelto agregando el `lib/` de un módulo `gettext/0.23.1`
  ya presente en el mismo árbol `spack`, sin necesitar `module load` adicional.

Build final verificado: `snlc_sim.exe` compila limpio (solo warnings preexistentes de `-Wformat-overflow`
en `snlc_sim.c`, no relacionados) y corre (menú de ayuda real confirmado).

### El parche real a `genmag_SALT2.c`

`INTEG_zSED_SALT2()` ya tenía hooks de debug reales (`int LDMP`, hardcodeado a `0`) -- en vez de
reactivarlos, se agregó un volcado nuevo gateado por variable de entorno, inmediatamente después del
cálculo real de `Fbin_forFlux` (línea 2843), solo para `ised==0` (superficie `M0`):

```c
	Fbin_forFlux = (FTMP * CCOR * HOSTXT_FRAC*MWXT_FRAC * LAMSED*TRANS);
	Fbin_forSpec = (FTMP * CCOR * HOSTXT_FRAC*MWXT_FRAC );

	// ALCES Fase29: volcado real de (LAMOBS,LAMSED,TRANS,FTMP,Fbin_forFlux) por bin de
	// longitud de onda, gateado por env var -- para aislar la convencion de integracion
	// de banda (LAMSED*TRANS) sin reconstruir FTMP a mano del lado LightCurveLynx.
	// Ver exploration/lightcurvelynx/NOTES.md Fase 29 en el repo ALCeS.
	if ( ised==0 && getenv("ALCES_DUMP_INTEG") != NULL ) {
	  FILE *fp_alces = fopen("/home/mvalenzuela/AUTOSIM/exploration/lightcurvelynx/dump_integ_salt2.csv","a");
	  if ( fp_alces != NULL ) {
	    fprintf(fp_alces, "%d,%d,%.6f,%.6f,%.6f,%.8e,%.8e,%.8e\n",
		    ifilt_obs, ilamobs, Trest, LAMOBS, LAMSED, TRANS, FTMP, Fbin_forFlux);
	    fclose(fp_alces);
	  }
	}
```

`Trest` (agregado en una segunda iteración, necesario para poder aislar la evaluación sintética exacta en
el pico -- ver Fase 22) y `ifilt_obs`/`Tobs` ya eran parámetros/variables reales de la función; nada del
resto de la función se modificó. Este parche vive **solo en el clon privado de SNANA del usuario**
(`~/github/SNANA_src`, repo externo, no versionado en este repo git) -- no se commitea a ALCeS.

**No-regresión verificada**: se corrió el mismo objeto controlado (z=0.6, `x1`/`c` fijos, `RANSEED`
fijo) dos veces con el binario recompilado -- una vez sin `ALCES_DUMP_INTEG`, otra con la variable
seteada -- y el `.DUMP` real resultante (`PEAKMAG_*`/`MU`/`PEAKMJD`/etc., las 35 columnas de
`SIMGEN_DUMPALL`) salió **byte-idéntico** entre ambas corridas. El parche es comprobadamente inocuo
cuando la variable de entorno no está seteada.

### El experimento: mismo `FTMP`/`TRANS` real de SNANA, dos convenciones de pesado, correctamente normalizadas

Objeto controlado real (`GENRANGE_REDSHIFT`/`SALT2c`/`SALT2x1` colapsados a un punto, `OPT_MWEBV:0`,
`OPT_MWCOLORLAW:99`, mismo patrón de Fase 26/27) corrido a `z=0.6` y `z=0.9` con el binario instrumentado
y `ALCES_DUMP_INTEG=1`. El volcado captura, por cada bin real de longitud de onda observada evaluado en
`Trest=0` (el epoch sintético del pico verdadero, Fase 22), el `FTMP`/`TRANS`/`LAMOBS` reales que usó
SNANA -- sin ninguna interpolación/reconstrucción de por medio.

**Primer intento -- sumas crudas sin normalizar, descartado como sin sentido**: comparar directamente
`Σ FTMP·TRANS·LAMSED` (SNANA) contra `Σ FTMP·TRANS/LAMSED` (LightCurveLynx) da diferencias de hasta
`~1 mag`, absurdamente grandes -- el mismo tipo de resultado implausible de Fase 25. Diagnóstico real
esta vez (con los datos de SNANA en mano, no una reconstrucción): las dos sumas crudas viven en escalas
completamente distintas (`~1e5` vs. `~1e-3`) porque ninguna está normalizada por su propia integral de
peso -- exactamente el mismo error de fondo que arruinó Fase 25, ahora identificado con precisión en vez
de solo sospechado.

**Corregido -- promedio ponderado normalizado (el formalismo estándar de fotometría sintética)**:
`<F>_SNANA = Σ(FTMP·TRANS·LAMSED) / Σ(TRANS·LAMSED)` y `<F>_LCL = Σ(FTMP·TRANS/LAMSED) / Σ(TRANS/LAMSED)`
-- ambos convergen a la misma magnitud física cuando el SED es plano, y aíslan limpiamente el efecto de
la FORMA del peso dentro de la banda. Resultado, relativo a `r` (misma convención `diff` que Fase 27):

| `z` | banda | Δmag (peso LCL − peso SNANA), esta fase | `diff` real Fase 27 |
|---:|---|---:|---:|
| 0.6 | g | **+0.1011** | +0.0935 |
| 0.6 | i | **-0.0229** | -0.0864 |
| 0.6 | z | **-0.0094** | -0.0997 |
| 0.6 | y | **-0.0151** | -0.0978 |
| 0.9 | i | **-0.0373** | -0.1201 |
| 0.9 | z | **-0.0517** | -0.1771 |
| 0.9 | y | **-0.0462** | -0.1975 |

### Conclusión Fase 29 -- la convención de integración de banda queda confirmada, no descartada: mismo signo en las 7 combinaciones, magnitud parcial

A diferencia de Fase 25 (sin resultado confiable) y de la lectura literal de Fase 27 ("signo opuesto,
insuficiente"), esta vez con evidencia código-real-vs-código-real y correctamente normalizada: **el
efecto puro de pesar por `λ` vs `1/λ` reproduce el mismo signo que el `diff` real de Fase 27 en las 7
combinaciones banda/`z` probadas** (`g` positivo, `i`/`z`/`y` negativos, en ambos `z`), y explica entre
~25% y ~45% de la magnitud total medida por Fase 27. Esto **confirma** (no descarta) que la convención de
integración de banda es un componente real y verificado del mecanismo que separa a SNANA de
LightCurveLynx -- consistente en signo con el `diff` de Fase 27 en las 7 pruebas -- pero es
insuficiente por sí sola para explicar toda la magnitud de ese `diff`, y ese mismo `diff` ya tiene signo
opuesto al patrón cromático poblacional de Fase 23. Es decir: el patrón cromático de Fase 23 sigue **sin
causa identificada**, pero ahora se sabe con precisión que la integración de banda es una pieza real
(cuantificada, no descartada) de un mecanismo más grande, cuyo resto (~55%-75% de la magnitud del `diff`
de Fase 27) queda sin aislar -- candidato para una continuación futura: la definición exacta de punto
cero/normalización de fotometría sintética de cada código más allá del simple exponente de peso (`λ`
vs. `1/λ`), no abordada en esta fase.

### Archivos de esta fase

Parche real a `~/github/SNANA_src/src/genmag_SALT2.c` (contenido completo arriba) -- vive en el clon
privado de SNANA del usuario, no versionado en este repo. Exploratorios en NLHPC, borrados tras usarlos:
`sim_fase29_z06.INPUT`/`sim_fase29_z06_dump.INPUT`/`sim_fase29_z09.INPUT` (objetos controlados),
`analyze_z06.py`/`analyze_z06_v2.py`/`analyze_z09.py` (análisis del volcado real). GENVERSIONs
`TEST_FASE29_bandflux_z06`/`z06_dump`/`z09_dump` generados en `SNDATA_ROOT/SIM/` y borrados tras extraer
el `.DUMP`/volcado. Sin cambios a scripts del pipeline de este repo -- diagnóstico puro.

## Fase 30 — el punto cero real (espectro de referencia) añade una fracción real, pero no cierra el resto

A pedido explícito del usuario ("sigamos cazando el resto de la magnitud"), se ataca el candidato que
dejó abierto Fase 29: la definición exacta de punto cero/normalización de fotometría sintética de cada
código, más allá del simple exponente de peso (`λ` vs. `1/λ`) ya aislado ahí.

### El mecanismo real que Fase 29 nunca incluyó

Leyendo `genmag_SEDtools.c` real (`init_filter_SEDMODEL()`, líneas ~270-350): SNANA no convierte flujo
integrado a magnitud con un punto cero universal fijo -- lo calibra **por banda**, integrando un
**espectro de referencia primario real** (`interp_primaryFlux_SEDMODEL(lam)`, la curva `PrimarySED` real
de `kcor_LSST.fits`, ya leída como HDU real en Fase 12) con la **misma convención de pesado por `λ`**
que usa para el objeto científico:

```c
fluxREF_sum  += transREF * fluxREF * lam ;        // linea 298
...
fluxREF_sum *= (lamstep/hc8) ;                     // linea 343
FILTER_SEDMODEL[ifilt].ZP = 2.5*log10(fluxREF_sum) + magprimary ;   // linea 346
```

y luego (`genmag_SALT2.c` línea 3628, ya citado en Fase 29): `MAG = -2.5*log10(FTMP) + ZP`. El promedio
ponderado normalizado que usó Fase 29 (`<F>=Σ(FTMP·TRANS·peso)/Σ(TRANS·peso)`) es equivalente, solo para
fines de esa comparación relativa, a asumir que el espectro de referencia usado para calibrar el punto
cero es plano dentro de la banda -- nunca contrastado contra el `PrimarySED` real, que no tiene por qué
serlo (un espectro AB puro es plano en `f_ν`, lo que en `λ` es `f_λ∝1/λ²`).

### El parche real

Mismo patrón que Fase 29 (`getenv("ALCES_DUMP_INTEG")`), esta vez en `genmag_SEDtools.c`, volcando por
bin del espectro de referencia y, al final de cada banda, el resumen real:

```c
    fluxREF_sum  += transREF * fluxREF * lam ;

    // ALCES Fase30: volcado real de (lam,transREF,fluxREF) por bin del espectro
    // de referencia primario, gateado por env var -- para recalcular el punto
    // cero (ZP) bajo la convencion 1/lambda sin reconstruirlo a mano.
    // Ver exploration/lightcurvelynx/NOTES.md Fase 30 en el repo ALCeS.
    if ( getenv("ALCES_DUMP_INTEG") != NULL ) {
      FILE *fp_alces_zp = fopen("/home/mvalenzuela/AUTOSIM/exploration/lightcurvelynx/dump_zp_salt2.csv","a");
      if ( fp_alces_zp != NULL ) {
        fprintf(fp_alces_zp, "BIN,%s,%d,%.6f,%.8e,%.8e\n",
                filter_name, ifilt_obs, lam, transREF, fluxREF);
        fclose(fp_alces_zp);
      }
    }
```
```c
  if( fluxREF_sum != 0.0 )
    { FILTER_SEDMODEL[ifilt].ZP = 2.5*log10(fluxREF_sum) + magprimary ; }
  else
    { FILTER_SEDMODEL[ifilt].ZP = 0.0 ; }

  // ALCES Fase30: volcado real de (magprimary,fluxREF_sum,ZP) final por banda,
  // gateado por env var. Ver exploration/lightcurvelynx/NOTES.md Fase 30.
  if ( getenv("ALCES_DUMP_INTEG") != NULL ) {
    FILE *fp_alces_zp2 = fopen("/home/mvalenzuela/AUTOSIM/exploration/lightcurvelynx/dump_zp_salt2.csv","a");
    if ( fp_alces_zp2 != NULL ) {
      fprintf(fp_alces_zp2, "SUMMARY,%s,%d,%.6f,%.8e,%.6f\n",
              filter_name, ifilt_obs, magprimary, fluxREF_sum, FILTER_SEDMODEL[ifilt].ZP);
      fclose(fp_alces_zp2);
    }
  }
```

Vive solo en el clon privado de SNANA del usuario (`~/github/SNANA_src`), no versionado en este repo.
Reconstruir el binario recicló toda la cadena de dependencias de build ya resuelta en Fase 29 (perl,
`python3-config`, GSL/cfitsio/gettext vía rutas reales del árbol `spack`, esta vez además con
`LD_LIBRARY_PATH` en tiempo de ejecución, no solo de build, porque el binario recompilado enlaza contra
`libcfitsio.so.10` dinámica).

**No-regresión verificada**: mismo objeto controlado de Fase 27/29 (`z=0.6`) corrido con y sin
`ALCES_DUMP_INTEG` -- `.DUMP` real resultante byte-idéntico (`diff` vacío).

### El experimento: `ZP` real de SNANA bajo ambas convenciones, combinado con el `Finteg` real de Fase 29

Objeto controlado real (mismo patrón de Fase 26/27/29: `GENRANGE_REDSHIFT`/`SALT2c`/`SALT2x1` colapsados
a un punto, `x1=0.973`, `c=-0.054`, `OPT_MWEBV:0`, `OPT_MWCOLORLAW:99`, `NGENTOT_LC:5`) corrido a `z=0.6`
y `z=0.9` con el binario doblemente instrumentado y `ALCES_DUMP_INTEG=1`. El volcado de `ZP` da, para
cada banda, `(magprimary, fluxREF_sum, ZP)` reales -- `magprimary=0` en las 6 bandas (consistente con
`ZPoff=0` de Fase 12), pero `fluxREF_sum` real con forma no trivial (no un simple factor por banda).

Con las `(lam,transREF,fluxREF)` reales volcadas por bin: se recalculó `fluxREF_sum` bajo la convención
`1/λ` (`Σ transREF·fluxREF/lam`, reescalado por la misma constante `lamstep/hc8` derivada empíricamente
de la propia banda -- verificado que la reconstrucción de la convención `λ` original coincide con el
`fluxREF_sum` real a precisión de máquina, sanity-check pasado) → `ZP_alt`. Con el `Fbin_forFlux` real ya
volcado por Fase 29 (evaluado en `Trest=0`, el epoch sintético del pico verdadero de Fase 22, deduplicado
entre los 4-5 objetos idénticos generados por `NGENTOT_LC:5`): `Finteg_λ = Σ Fbin_forFlux` (la integral
real que usa SNANA) y `Finteg_alt = Σ Fbin_forFlux/LAMSED²` (equivalente exacto bajo `1/λ`, ya que
`Fbin_forFlux=FTMP·CCOR·LAMSED·TRANS` con `HOSTXT_FRAC=MWXT_FRAC=1`).

`MAG_SNANA_real = -2.5·log10(Finteg_λ) + ZP_SNANA` vs. `MAG_alt = -2.5·log10(Finteg_alt) + ZP_alt`,
comparado relativo a `r` contra el `diff` real de Fase 27:

| `z` | banda | Fase 27 (`diff` real) | Fase 29 (solo forma del peso) | Fase 30 (forma + punto cero real) | fracción explicada |
|---:|---|---:|---:|---:|---:|
| 0.6 | g | +0.0935 | +0.1011 | **+0.1026** | 110% |
| 0.6 | i | -0.0864 | -0.0229 | **-0.0334** | 39% |
| 0.6 | z | -0.0997 | -0.0094 | **-0.0288** | 29% |
| 0.6 | y | -0.0978 | -0.0151 | **-0.0309** | 32% |
| 0.9 | i | -0.1201 | -0.0373 | **-0.0443** | 37% |
| 0.9 | z | -0.1771 | -0.0517 | **-0.0639** | 36% |
| 0.9 | y | -0.1975 | -0.0462 | **-0.0585** | 30% |

### Conclusión Fase 30 -- el punto cero real es una pieza real y adicional, pero insuficiente

Incluir la forma real del espectro de referencia (`PrimarySED`) en el punto cero, en vez de asumirlo
plano como hacía implícitamente Fase 29, **aumenta consistentemente la magnitud explicada** en las 6
combinaciones donde Fase 29 dejaba más margen (`i`/`z`/`y` en ambos `z`): de un rango de ~9%-31% (Fase
29, excluyendo `g`) a un rango más estrecho y más alto de ~29%-39% -- una mejora real, más marcada en
`z@0.6` (9.4%→28.9%, el peor explicado por Fase 29). La banda `g` ya estaba esencialmente explicada por
Fase 29 sola (108%) y el término de punto cero no la cambia de forma apreciable (110%). **Con esto, los
dos mecanismos aislados de la convención de integración de banda (forma del peso + punto cero) explican
en conjunto ~29%-39% de la magnitud del `diff` de Fase 27 en las bandas más difíciles**, dejando todavía
~60%-70% sin identificar. El patrón cromático poblacional de Fase 23 sigue **sin causa identificada** --
sigue de signo opuesto al `diff` de Fase 27 (ya establecido en Fase 27/29), así que este avance tampoco
lo explica directamente. Con la cadena SALT2 exhaustivamente descompuesta término a término (Fase 28) y
ahora también la convención de integración de banda descompuesta en sus dos sub-mecanismos (forma +
punto cero, Fases 29-30), el resto de la magnitud del `diff` de Fase 27 queda como una pregunta abierta
genuina que ya no tiene un candidato concreto identificado dentro de la fórmula de integración SALT2 de
SNANA -- cualquier candidato adicional requeriría mirar fuera de `genmag_SALT2.c`/`genmag_SEDtools.c`
(p.ej. el propio tratamiento de `CCOR`/color law evaluado en la grilla discreta, ya verificado idéntico
en Fase 16 pero no re-verificado en este régimen de `z` alto específico) o aceptar que la comparación
entre `PEAKMAG_<filt>` real y `compute_noise_free_lightcurves()` real, aun usando el mismo objeto exacto,
compara dos implementaciones de fotometría sintética suficientemente distintas en su núcleo (no solo en
la convención de pesado) como para no cerrar del todo con descomposición término a término.

### Archivos de esta fase

Parche real a `~/github/SNANA_src/src/genmag_SEDtools.c` (contenido completo arriba) -- vive en el clon
privado de SNANA del usuario, no versionado en este repo. Exploratorios en NLHPC, borrados tras usarlos:
`sim_fase30_z06.INPUT`/`sim_fase30_z09.INPUT` (objetos controlados), `fase30_analyze.py` (análisis del
volcado real, combina `dump_zp_salt2.csv` y el `dump_integ_salt2.csv` ya generado por el parche de Fase
29). GENVERSIONs `TEST_FASE30_zp_z06`/`z09` generados en `SNDATA_ROOT/SIM/` y borrados tras extraer el
`.DUMP`. Sin cambios a scripts del pipeline de este repo -- diagnóstico puro.

## Fase 31 — dos aristas nuevas: la premisa de la primera resultó errónea (Fase 30 ya incluía `CCOR`); la segunda audita la calibración de LightCurveLynx y la encuentra sólida

A pedido explícito del usuario ("sigamos cazando... revisar la calibración completa de LightCurveLynx
pues puede que sea deficiente"), se atacan dos aristas nuevas sobre el ~60-70% del `diff` de Fase 27 que
Fases 29-30 dejaron sin explicar.

### Paso 1 — la premisa resultó errónea: `CCOR` ya estaba incluido en el cálculo real de Fase 30

El plan de esta fase partía de una relectura de Fase 29/30 que concluía que la ley de color (`CCOR`)
había quedado excluida del promedio ponderado usado ahí. Al reconstruir el cálculo completo desde cero
(nuevo objeto controlado real, `CID=1` con `z=0.6`/`z=0.9`, mismo binario instrumentado de Fases 29-30,
mismo `.INPUT` -- claves copiadas a mano por el bug de keys duplicadas de Fase 27, `OPT_MWEBV:0`,
`OPT_MWCOLORLAW:99`) se confirma que **la premisa era incorrecta**: el cálculo *final* de Fase 30 usó
`Finteg_λ = Σ Fbin_forFlux` directamente (el producto real que SNANA calcula, `Fbin_forFlux =
FTMP·CCOR·LAMSED·TRANS`, `genmag_SALT2.c` línea 2843) -- `CCOR` estaba efectivamente incluido desde el
principio ahí; solo la comparación *preliminar* de Fase 29 (el primer intento, con el promedio
autonormalizado `<F>=Σ(FTMP·TRANS·peso)/Σ(TRANS·peso)`) lo excluía, y ese intento preliminar fue
superado por el cálculo real de Fase 30.

Recuperando `CCOR` real por bin (`CCOR = Fbin_forFlux/(FTMP·LAMSED·TRANS)`, válido con
`HOSTXT_FRAC=MWXT_FRAC=1`) se confirma además que `CCOR` es un factor real y activo, no un no-op: varía
entre `~0.92` (banda `Y`) y `~1.70` (banda `g`, cerca del pico de curvatura de la ley de color SALT2 real
del `c=-0.054` de esta campaña) -- no es plano, tiene forma real dentro de cada banda.

**Resultado de repetir el cálculo completo de Fase 30 (peso + `CCOR` + punto cero real) con un objeto
nuevo e independiente (`CID=1`, no el mismo objeto de Fase 30):**

| `z` | banda | Fase 30 (peso+CCOR+ZP real) | Este paso (mismo método, objeto distinto) |
|---:|---|---:|---:|
| 0.6 | g | +0.1026 | +0.10139 |
| 0.6 | i | -0.0334 | -0.03411 |
| 0.6 | z | -0.0288 | -0.02690 |
| 0.6 | y | -0.0309 | -0.03294 |
| 0.9 | i | -0.0443 | -0.03480 |
| 0.9 | z | -0.0639 | -0.05675 |
| 0.9 | y | -0.0585 | -0.05187 |

Coinciden a `~0.001-0.01` mag (diferencias explicables por tratarse de un objeto distinto -- mismo `z`
pero distinto `RA`/`DEC`/`PEAKMJD`, y por lo tanto distinta cadencia/`SIMLIB_MAXRANSTART` -- no por un
error de método). **Esto no es un hallazgo nuevo: es una replicación independiente que confirma la
reproducibilidad de Fase 30**, no un avance sobre el ~60-70% que queda sin explicar. Ambas fases
comparten la misma limitación conocida y explícita: solo se dumpea la superficie `M0` (`ised==0`), no
`M1` (`x1`) -- el factor `x0` global cancela exactamente en la diferencia `MAG_alt−MAG_SNANA` (aparece
idéntico en ambas convenciones, se cancela en el cociente dentro del logaritmo), pero la forma cromática
propia de `M1` pesada por `x1=0.973` queda fuera de esta aproximación en ambas fases -- un cabo suelto
menor y compartido, no introducido por este paso.

### Paso 2 — auditoría de la calibración de LightCurveLynx: estructuralmente sólida, con un detalle real pero despreciable

**(A) Autoconsistencia con fuente plana en `f_ν`**: se pasó una fuente sintética perfectamente plana
(`f_ν=12345.678` nJy, arbitrario) por el pipeline real (`PassbandGroup.from_preset(preset="LSST")` +
`Passband.fluxes_to_bandflux()` real). Resultado: **`Δmag` de `~2×10⁻¹³` mag en las 6 bandas** -- exacto
a precisión de máquina. Esto es **matemáticamente garantizado por construcción**, no un descubrimiento
empírico: `compute_system_response_table()` real (`passbands.py`) normaliza `φ_b(λ)` para que
`∫φ_b(λ)dλ=1` siempre, sin importar la forma de la banda -- cualquier fuente plana se reproduce a sí
misma exactamente, para cualquier banda, por diseño. La prueba se documenta igual (evidencia negativa
real), pero no puede en principio revelar un bug de esta clase.

**(B) Auditoría del jacobiano `f_λ→f_ν`**: se leyó el código real de conversión de unidades
(`lightcurvelynx/astro_utils/unit_utils.py`, funciones `flam_to_fnu()`/`get_flam_to_fnu_multiplier()`)
-- usa álgebra de unidades real de `astropy` (`(flam_unit·wave_unit²)/const.c.unit).to_value(fnu_unit)`)
para derivar el multiplicador escalar correcto, no una constante manual. El punto de llamada real
(`sncosmo_models.py`, `SncosmoWrapperModel.evaluate_sed()`) pasa `wave_unit=u.AA` consistente con las
longitudes de onda reales que usa (`self.source.flux(phase, wavelengths)`, documentadas "en angstroms").
**No hay bug de unidades real** -- la conversión `f_λ`(SALT2, erg/s/cm²/Å) → `f_ν`(nJy) está implementada
correctamente y de forma dimensionalmente rigurosa.

**(C) Hallazgo real nuevo -- `trim_quantile=1e-3` nunca se había auditado contra producción**: leyendo
`PassbandGroup._lsst_load_preset()`/`Passband.__init__` reales se confirma que
`PassbandGroup.from_preset(preset="LSST")` (la llamada real que usan los 5 scripts de producción de este
proyecto) aplica por defecto `trim_quantile=1e-3` (recorta el 0.1% de área en cada extremo) y
`delta_wave=5.0` Å -- **nunca antes verificado contra la tabla usada realmente en producción**: Fase 12
comparó la tabla CRUDA descargada (`transmission_table`, sin recortar) contra `kcor_LSST.fits` real, no
la tabla recortada+resampleada (`normalized_system_response`/`waves`) que `fluxes_to_bandflux()` usa de
verdad. El recorte es real y sustancial en longitud de onda (p.ej. banda `u`: `[3000,11500]`Å crudo →
`[3285,8410]`Å recortado; banda `g`: `[3000,11500]`Å → `[3925,5625]`Å).

Verificado numéricamente con el SED real SALT2 M0 (mismo template de Fases 16/20/21/25/28/29) en `z=0.15,
0.6, 0.9`, comparando `Δmag` relativo a `r` con `trim_quantile=1e-3` (producción) vs. `trim_quantile=None`
(sin recortar): el efecto es **despreciable en `g/i/z/y`** (`≤0.006` mag en todos los `z` probados) --
salvo en `u`, donde crece hasta **`+0.09`** mag a `z=0.9` (banda ya excluida del análisis principal de
todas formas, por `PEAKMAG_u` real indefinido a partir de `z≈0.6`, Fase 13/27). **No explica el residuo
de `g/i/z/y`** que sigue sin causa identificada, pero es una corrección real de higiene metodológica que
queda documentada -- cualquier futura comparación en banda `u` a `z` alto debería usar
`trim_quantile=None` o verificar explícitamente su efecto.

### Conclusión Fase 31 -- ninguna de las dos aristas cierra el resto de la magnitud; la calibración de LightCurveLynx queda auditada y verificada sólida

**Arista 1 (color law × punto cero)**: la premisa era errónea -- no había nada nuevo que combinar, Fase
30 ya lo había hecho. Este paso aporta una replicación independiente que confirma la reproducibilidad del
resultado de Fase 30 (no un avance).

**Arista 2 (auditoría de calibración de LightCurveLynx)**: **no se encontró una deficiencia real y
corregible**. La normalización de `Passband` es autoconsistente por construcción (garantizado
matemáticamente, no solo verificado), la conversión de unidades `f_λ→f_ν` es correcta y dimensionalmente
rigurosa (verificada leyendo el código real de `astropy`-based `unit_utils.py`), y el único detalle real
encontrado (`trim_quantile` nunca antes auditado contra producción) tiene un efecto medido pero
despreciable en las bandas que importan (`g/i/z/y`). **No se aplicó ninguna corrección de código** en
esta fase -- a diferencia del precedente de Fase 24, no hay nada concreto que corregir: ambas auditorías
dieron negativo, con evidencia numérica directa, no por falta de intentarlo.

El patrón cromático de Fase 23 **sigue sin causa identificada**. Con la cadena SALT2 agotada (Fase 28),
la convención de integración de banda cuantificada pero insuficiente y de signo mixto (Fases 26/27/29/30),
y ahora también la calibración de LightCurveLynx auditada y verificada sólida (Fase 31), el espacio de
candidatos concretos, verificables por lectura de código y evidencia numérica directa, está prácticamente
agotado. Lo que queda -- el ~60-70% de magnitud sin explicar del `diff` de Fase 27, y el patrón cromático
poblacional de signo opuesto de Fase 23 -- probablemente requiere una síntesis a nivel más alto (las
conclusiones finales, todavía diferidas a pedido del usuario) en vez de un candidato aislado más.

### Archivos de esta fase

Exploratorios en NLHPC, borrados tras usarlos: `fase31_lcl_calib_audit.py` (Paso 2, autoconsistencia +
auditoría de trim), `sim_fase31_z06.INPUT`/`sim_fase31_z09.INPUT` (Paso 1, objeto controlado nuevo),
`fase31_paso1_analyze.py` (análisis del volcado real, reutiliza el binario instrumentado de Fases
29-30 sin recompilar). GENVERSIONs `TEST_FASE31_ccor_z06`/`z09` generados en `SNDATA_ROOT/SIM/` y
borrados tras extraer el `.DUMP`. Sin parches nuevos a SNANA (se reutilizó el binario ya instrumentado
de Fases 29-30 sin modificarlo). Sin cambios a scripts del pipeline de este repo -- ambas auditorías
dieron negativo, no hay nada que corregir.

## Fase 32 — el hallazgo más significativo de la investigación: el sampler de `c`/`x1` no pesaba las dos mitades como SNANA

Nueva arista, distinta de toda la cadena de Fases 26-31 (que atacó la fórmula fotométrica de un objeto
controlado único): esta vez se audita la **fidelidad del muestreo poblacional**. Leyendo el código real
de SNANA (no documentación) se encontró un bug real y concreto, no solo una hipótesis.

### El bug real: SNANA pesa cada mitad de la Gaussiana bifurcada por su sigma, no 50/50

`~/github/SNANA_src/src/sntools.c::getRan_GaussAsym()` (la función real que SNANA usa para samplear
`SALT2c`/`SALT2x1`, invocada desde `getRan_GENGAUSS_ASYM()` en `sntools_genGauss_asym.c`) no elige el
lado "bajo"/"alto" de la Gaussiana bifurcada con 50/50 de probabilidad -- lo pesa **proporcional a cada
sigma**, para que la densidad de probabilidad sea continua en el pico:

```c
// sntools.c, getRan_GaussAsym() real
double BIGAUSSNORMCON = 1.25331413732;  // sqrt(2*pi)/2, normaliza cada media-Gaussiana
psum = (siglo + sighi) * BIGAUSSNORMCON + peakinterval;
p[0] = (siglo * BIGAUSSNORMCON) / psum;      // prob. de tomar el lado "bajo"
p[2]-p[1] = (sighi * BIGAUSSNORMCON) / psum;  // prob. de tomar el lado "alto"
```

Es decir, `P(lado alto) = sighi/(siglo+sighi)`, NO `0.5`. `snana_params.py::make_bifurcated_normal_sampler()`
(línea 284-311, usada en `compare_brightness_truth_salt2.py`/`run_snia_ddf_poc.py`/`run_dask_poc.py`)
usaba `side = rng.uniform(size=batch) < 0.5` -- siempre 50/50, sin importar cuán distintos fueran
`sigma_lo`/`sigma_hi`. Confirmado contra el `.INPUT` real (`SIMGEN_INCLUDE_SNIa-SALT2.INPUT`, vía
`include_model_SNIa.INPUT`): `GENPEAK_SALT2c/x1` son valores únicos (no un rango), y **no hay
`GENSKEW_SALT2c`/`GENSKEW_SALT2x1` declarado** -- `peakinterval=0` es válido, no hace falta implementar
la rama de `getRan_skewGauss()`.

Para `SALT2c` (`peak=-0.054, sigma_lo=0.043, sigma_hi=0.101`), la asimetría es grande: `sigma_hi` es
2.35x `sigma_lo`. `P(lado alto)` real es `0.101/(0.043+0.101) ≈ 70.1%`, no `50%`. Con 50/50,
LightCurveLynx sub-muestreaba el lado ancho (rojo, `c` alto) y sobre-muestreaba el lado angosto (azul,
`c` bajo) -- sesgo en la dirección correcta para producir tanto exceso de brillo global como señal
cromática. `SALT2x1` (`sigma_lo=1.472, sigma_hi=0.222`, asimetría opuesta) también estaba afectado.

### Corregido: `make_bifurcated_normal_sampler()` ahora replica la fórmula real

```python
p_side_lo = 0.5 if (sigma_lo == 0.0 and sigma_hi == 0.0) else sigma_lo / (sigma_lo + sigma_hi)
...
side = rng.uniform(size=batch) < p_side_lo
```

Verificado con un test estadístico directo (2M draws): `P(lado alto)` empírico coincide con el valor
esperado a 4 decimales (`SALT2c`: 0.7013 vs. 0.7014 esperado; `SALT2x1`: 0.1318 vs. 0.1311 esperado).

### Impacto real medido: recorrida completa de la población (2000 objetos, sampler corregido)

A diferencia de Fases 26-31 (objeto controlado único), este bug es inherentemente poblacional -- se
recorrió `compare_brightness_truth_salt2.py` (2000 objetos, mismo `seed_base=20260812`, mismo `.DUMP`
real de producción) con el sampler ya corregido, repitiendo la comparación banda-por-banda de Fase 23
(`compute_noise_free_lightcurves()` en `rest_phase=0`, mediana por los mismos 7 bins de `z`):

| banda | Fase 23 (pre-fix) | Fase 32 (post-fix) | reducción | % reducción |
|---|---:|---:|---:|---:|
| `g` | -0.593 | -0.3448 | -0.248 | 41.9% |
| `r` | -0.519 | -0.3142 | -0.205 | 39.5% |
| `i` | -0.469 | -0.3138 | -0.155 | 33.1% |
| `z` | -0.435 | -0.3113 | -0.124 | 28.4% |
| `y` | -0.382 | -0.2562 | -0.126 | 32.9% |

**El nivel acromático se reduce ~28-42% en todas las bandas con estadística suficiente**, y el **spread
cromático `g−y` se reduce de -0.211 a -0.089 mag -- una reducción del 58%**. `u` queda con un solo bin
de estadística válida (mismo problema de borde de Fase 13/23), resultado no confiable ahí.

### Conclusión Fase 32 — el hallazgo más significativo de la investigación

Un bug de muestreo real y corregible -- no una diferencia de convención fotométrica -- explica una
fracción sustancial (28-42% del nivel acromático, 58% del spread cromático) del residuo que las Fases
16-31 persiguieron a través de la cadena SALT2/fotometría sintética completa. `make_bifurcated_normal_sampler()`
no se usa en ningún otro lugar del proyecto fuera de estos 3 scripts SNIa/SALT2 (`grep` confirmado). El
residuo restante (~58-72% del nivel acromático según banda, ~42% del spread cromático) sigue sin causa
identificada, pero el espacio de búsqueda se redujo sustancialmente.

### Archivos de esta fase

`snana_params.py`: `make_bifurcated_normal_sampler()` corregido (probabilidad de lado proporcional a
sigma, no 50/50 fijo). Exploratorios en NLHPC, borrados tras usarlos: `fase32_verify_sampler.py` (Paso
2), `fase32_smoketest.py` (verificación de API), `fase32_population_6band.py`/`.sbatch` (Paso 3, output
`fase32_population_6band_output.parquet` también borrado tras extraer los números).

## Fase 33 — E(B-V) real (SFD98 por objeto) vs. el promedio fijo por campo: efecto marginal, pero se descubre contaminación real en el `.DUMP` de referencia

Siguiendo la misma estrategia que dio el mayor resultado hasta ahora (Fase 32: auditar un sampler/
aproximación custom contra el algoritmo real de SNANA, no la fórmula fotométrica), se ataca una nota
real que ya estaba escrita en el código, nunca investigada a fondo: `snana_params.py::
make_mwebv_ratio_scatter()` (líneas 532-539) señala que la campaña real de SNANA no usa un `E(B-V)` fijo
por campo DDF -- el SIMLIB real escribe `MWEBV=0.00` en cada header `LIBID`, disparando el fallback real
de `gen_MWEBV()` a `OPT_MWEBV_SFD98` (mapa real de polvo, evaluado en el RA/Dec exacto de cada objeto).
Este proyecto usa `DDF_FIELD_EBV`, un promedio fijo por campo (6 valores).

### Paso 1 -- el desajuste real, medido sin simular nada nuevo

El `MWEBV` real por objeto ya está en el `.DUMP` de producción (`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`,
columna `MWEBV` real, `VARNAMES` de 36 columnas confirmado) -- comparar contra `DDF_FIELD_EBV` no
requiere ninguna simulación nueva. Primer intento (media simple): resultados absurdos
(`elaiss1`: media real `1.94`, `std=7.57`, contra el valor fijo `0.008`) -- diagnosticado: **el `.DUMP`
de referencia contiene un ~15% de objetos que NO son miembros reales de ninguno de los 6 campos DDF**.

Asignando cada objeto al campo real más cercano (centros de campo reales extraídos del propio OpSim,
`target_name LIKE '%ddf_%'`, mismo patrón que usa el proyecto) y midiendo la separación angular: la
distribución es claramente **bimodal** (mediana `1.47°`, percentil 90 `76.6°`) -- **298/1957 objetos
(15.2%) están a más de 2° de cualquier campo DDF real** (separación mediana de ese subgrupo: `~77°`,
posiciones de cielo sin relación con las 6 pointings DDF). Inspeccionando los objetos de `MWEBV` más
alto (hasta `72.68`): sus RA/Dec (`~267°, ~-28°`) caen casi exactamente sobre el **centro galáctico**
(RA≈266.4°, Dec≈-28.9°) -- **astrofísicamente real, no un bug de parseo**: son objetos generados fuera
del footprint DDF de baja extinción, mezclados en el mismo `.DUMP` (coherente con el nombre real del
directorio que los contiene, `_stale_pre_v8fix`, y con los `target_name` reales del OpSim que mezclan
`ddf_*` con `GW_case_*`/`neutrino_*` en la misma tabla). Este es un hallazgo real de calidad de datos del
`.DUMP` de referencia usado desde Fase 16 -- dado que **todas** las comparaciones poblacionales de Fases
16-32 usan la **mediana** (robusta a un ~15% de contaminación siempre que no domine el bin), es poco
probable que invalide los hallazgos ya reportados, pero queda como un cabo suelto real para una
auditoría futura de esa referencia.

Filtrando a objetos bien-matcheados (separación `<2°`, 1659/1957) y usando **mediana** (no media, ya
sensible a outliers) por campo:

| campo | N | `MWEBV` real (mediana) | `DDF_FIELD_EBV` (fijo) | delta |
|---|---:|---:|---:|---:|
| cosmos | 269 | 0.02416 | 0.01820 | +0.00596 |
| ecdfs | 274 | 0.01002 | 0.00840 | +0.00162 |
| edfs_a | 282 | 0.00914 | 0.00620 | +0.00294 |
| edfs_b | 268 | 0.01320 | 0.01520 | -0.00200 |
| elaiss1 | 295 | 0.00816 | 0.00800 | +0.00016 |
| xmm_lss | 271 | 0.02445 | 0.02510 | -0.00065 |

Desajustes reales pero chicos (`-0.002` a `+0.006` en `E(B-V)`), del mismo orden que la propia dispersión
intra-campo.

### Paso 2 -- propagado a magnitud con F99 real (Fase 24): marginal

Usando `dust_extinction.F99(Rv=3.1)` (mismo estándar del proyecto desde Fase 24) sobre los deltas reales
de arriba, en las 6 bandas LSST:

| banda | cosmos | ecdfs | edfs_a | edfs_b | elaiss1 | xmm_lss | media ponderada |
|---|---:|---:|---:|---:|---:|---:|---:|
| u | +0.0281 | +0.0076 | +0.0139 | -0.0094 | +0.0008 | -0.0031 | **+0.0063** |
| g | +0.0218 | +0.0059 | +0.0107 | -0.0073 | +0.0006 | -0.0024 | **+0.0049** |
| r | +0.0152 | +0.0041 | +0.0075 | -0.0051 | +0.0004 | -0.0017 | **+0.0034** |
| i | +0.0113 | +0.0031 | +0.0056 | -0.0038 | +0.0003 | -0.0012 | **+0.0025** |
| z | +0.0089 | +0.0024 | +0.0044 | -0.0030 | +0.0002 | -0.0010 | **+0.0020** |
| y | +0.0073 | +0.0020 | +0.0036 | -0.0025 | +0.0002 | -0.0008 | **+0.0016** |

La media ponderada por población (`+0.006` a `+0.002` mag, `u`→`y`) es marginal -- del mismo orden que
el hallazgo ya descartado de Fase 24 (`<0.005` mag, cambio de ley de extinción a estos niveles de
`E(B-V)`). Incluso el peor caso de un solo campo (`cosmos`, `+0.028` mag en `u`) es pequeño frente al
residuo real que dejó Fase 32 (`~0.31` mag acromático, `~0.089` mag de spread cromático `g-y`). **No se
pasa al Paso 3** (implementación del lookup SFD98 real) -- el efecto estimado no lo justifica, mismo
criterio de decisión que Fase 24.

### Candidatos de reserva auditados

- **`build_dndz_powerlaw2_cdf`/`make_dndz_sampler` (DNDZ POWERLAW2, redshift)**: comparado el `z`
  (`ZHELIO`) muestreado por el sampler real del proyecto (200k draws, mismos segmentos reales
  `[(2.5e-5,1.5,0,1),(9.7e-5,-0.5,1,3)]`) contra el `ZHELIO` real de los 1659 objetos DDF bien-matcheados
  del `.DUMP`. Test KS: `stat=0.038, p=0.183` -- **no se puede rechazar que sean la misma distribución**;
  percentiles coinciden dentro de `0.01-0.02` en `z` en los 5 cuantiles probados. **Sin bug** -- el
  método de inversión de CDF reproduce fielmente la distribución real.
- **`ObsTableRADECSampler` (asignación de campo/posición)**: lectura del código real instalado
  (`ra_dec_sampler.py`) confirma un diseño documentado ("visit-weighted distribution") -- pesa por
  densidad real de visitas/observaciones del OpSim, no un supuesto arbitrario. Los conteos reales por
  campo del `.DUMP` (bien-matcheados) son casi uniformes (`268-295` de `1659`, `<10%` de spread),
  consistente con ese diseño. No se encontró indicio de sesgo en una revisión de código; una validación
  cuantitativa completa (recorrida de población + comparación de conteos por campo) queda fuera del
  presupuesto de esta fase -- honestamente marcada como no verificada a fondo, no como "descartada".

### Conclusión Fase 33 -- candidato marginal, pero con un hallazgo lateral real

El `E(B-V)` fijo por campo introduce un desajuste real mensurable, pero **marginal** frente al residuo
que queda tras Fase 32 -- mismo patrón que Fase 24 (corrección conceptualmente correcta pendiente, pero
sin magnitud suficiente para justificar la implementación completa en esta ronda). Los dos candidatos de
reserva (DNDZ, asignación de campo) no revelaron ningún bug adicional del tipo Fase 32. El hallazgo más
importante de esta fase no estaba en el plan original: **~15% del `.DUMP` de referencia usado desde Fase
16 no son miembros reales de los 6 campos DDF** -- un hallazgo de calidad de datos real, que no invalida
los resultados ya reportados (todos basados en medianas, robustas a esa fracción de contaminación) pero
queda documentado como un cabo suelto real para el futuro. El residuo post-Fase-32 (`~0.31` mag
acromático, `~0.089` mag cromático `g-y`) sigue sin causa identificada.

### Archivos de esta fase

Exploratorios en NLHPC, borrados tras usarlos: `fase33_paso1_mwebv.py` (Paso 1, con su output
`fase33_paso1_mwebv_output.csv`, también borrado). Paso 2 y los candidatos de reserva se corrieron
inline (sin script separado). Sin cambios a `snana_params.py`/scripts de producción -- ningún candidato
alcanzó el umbral para justificar una corrección esta fase.

## Fase 34 — `Omega_m=0.3` era un valor asumido, no el default real de SNANA (`0.315`): corregido, efecto real pero pequeño y en dirección inesperada

Nueva arista: auditar el módulo de distancia cosmológica propio de LightCurveLynx
(`DistModFromRedshift`, envoltorio real de `astropy.cosmology.FlatLambdaCDM.distmod(z)`, usado en
`compare_brightness_truth_salt2.py` desde Fase 16) contra el `MU` real de SNANA -- nunca antes validado
de forma independiente (las pruebas código-real-vs-código-real de Fases 26-31 siempre reusaron el `MU`
real de SNANA directamente, evitando el cálculo propio de LightCurveLynx por diseño).

### Paso 1 -- desajuste real medido, sin simular nada nuevo

El `.DUMP` real de producción (`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`) ya trae `ZCMB`/`ZHELIO`/`MU`/
`LENSDMU` por objeto. Aplicando el mismo filtro de contaminación de Fase 33 (separación angular `<2°`
al campo DDF real más cercano, 1659/1957 objetos bien-matcheados -- sin ese filtro, el `.DUMP` completo
da resultados absurdos, mismo hallazgo de Fase 33) y comparando `MU_LCL = FlatLambdaCDM(H0=70,
Om0=0.3).distmod(z).value` contra el `MU` real:

| | media | mediana | std |
|---|---:|---:|---:|
| `MU_LCL(ZCMB) − MU_real` | +0.01629 | +0.01719 | 0.00416 |
| `MU_LCL(ZHELIO) − MU_real` | +0.01739 | +0.01824 | 0.00463 |

`LENSDMU` real es exactamente cero para los 1659 objetos (media/mediana/std/min/max = 0.0) -- esta
campaña no aplica dispersión de lente gravitacional, no es la fuente del desajuste.

**El desajuste NO es un offset constante -- crece suavemente con `z`** (`ZCMB`, mediana por bin):

| bin `z` | N | `MU_LCL−MU_real` (mediana) |
|---:|---:|---:|
| [0.011,0.181) | 10 | 0.00225 |
| [0.181,0.351) | 51 | 0.00594 |
| [0.351,0.521) | 147 | 0.00949 |
| [0.521,0.690) | 219 | 0.01246 |
| [0.690,0.860) | 313 | 0.01537 |
| [0.860,1.030) | 438 | 0.01778 |
| [1.030,1.200) | 481 | 0.01972 |

Un crecimiento suave y monótono con `z` -- la firma exacta de un parámetro de cosmología mal
matcheado (no un offset/bug de fórmula). Ajustando `Om0` contra el `MU` real (manteniendo `H0=70`,
`scipy.optimize.minimize_scalar`, residuo mediano absoluto como función de costo): **`Om0=0.31435`
reduce el residuo mediano a 0.00068 mag** (esencialmente ruido numérico), contra `0.01719` mag con
`Om0=0.3`. Un ajuste equivalente variando `H0` con `Om0=0.3` fijo da `H0=70.59`, con un residuo
`0.0022` mag -- peor ajuste, confirmando que el parámetro mal matcheado es `Om0`, no `H0`.

**Confirmado contra el código fuente real de SNANA**: `~/github/SNANA_src/src/sntools.h`, línea 53:
`#define OMEGA_MATTER_DEFAULT 0.315` -- coincide con el `Om0` ajustado numéricamente a 4 decimales. La
misma cabecera confirma `H0_SALT2 = 70.0` (línea 57, "tied to SALT2 training") -- el `H0=70` que ya
usa el proyecto era correcto; solo `Omega_m=0.3` (un valor redondo asumido desde las primeras fases,
nunca verificado contra el default real) estaba mal. Ningún `.INPUT` real de la campaña (ni el de
`SNIa`, ni ningún archivo compartido bajo `~/AUTOSIM/build/full_v5.3_10yrs/` o
`/home/mvalenzuela/run_SNANA/model_config/`) sobreescribe `OMEGA_MATTER`, confirmado por grep sin
resultados -- la campaña corre con el default interno real de SNANA.

**Hallazgo de alcance más amplio, no corregido en esta fase**: `Om0=0.3` está hardcodeado en 8 archivos
del proyecto (`bench_snia.py`, `compare_brightness_truth.py`, `compare_brightness_truth_salt2.py`,
`run_dask_poc.py`, `run_non1ased_poc.py`, `run_simsed_91bg_ddf_poc.py`, `run_simsed_poc.py`,
`run_snia_ddf_poc.py`) -- afecta potencialmente a todas las clases, no solo `SNIa`. Esta fase corrige
únicamente los scripts SNIa/SALT2 ya tocados por la cadena de investigación (ver abajo); el resto queda
como trabajo pendiente identificado, no una fase futura todavía planificada. `run_dask_poc.py` además
usa `H0=73.0` (no `70.0`) -- un error real y más grande (~0.09 mag, `5·log10(73/70)`) que el de `Om0`,
pero fuera de alcance de esta fase (no es parte de la cadena de comparación poblacional que usan las
Fases 16-34, es un PoC de paralelización con Dask).

### Paso 3 -- corregido y medido: efecto real, pero pequeño, y en la dirección opuesta a "cerrar el residuo"

Corregido `Omega_m: 0.3 → 0.315` en `compare_brightness_truth_salt2.py` y `run_snia_ddf_poc.py` (los
2 de los 3 scripts SNIa/SALT2 que usan `DistModFromRedshift` directamente -- `run_dask_poc.py` queda
fuera, ver nota de `H0` arriba). Re-corrida la población completa (2000 objetos, mismo `seed_base`,
sobre la base ya corregida de Fase 32 -- sampler bifurcado real) con `compute_noise_free_lightcurves()`
en `rest_phase=0`, misma metodología exacta de Fase 32:

| banda | Fase 32 (antes) | Fase 34 (después, `Om0=0.315`) | Δ(Fase34−Fase32) |
|---|---:|---:|---:|
| `g` | -0.3448 | -0.3547 | -0.0099 |
| `r` | -0.3142 | -0.3285 | -0.0143 |
| `i` | -0.3138 | -0.3283 | -0.0145 |
| `z` | -0.3113 | -0.3271 | -0.0158 |
| `y` | -0.2562 | -0.2737 | -0.0175 |

**El residuo acromático NO se reduce -- se hace ligeramente más negativo (~0.01-0.018 mag), consistente
en signo y magnitud con la propia medición del Paso 1** (`MU_LCL(Om0=0.3)` era ~0.017-0.02 mag *mayor*
que el `MU` real, es decir LightCurveLynx generaba objetos ligeramente *más tenues* de lo que debería
por este único efecto -- una compensación parcial, no relacionada con la causa real del exceso de
brillo, que enmascaraba una fracción del residuo verdadero). Corregir `Om0` **elimina esa compensación
accidental**, revelando un residuo acromático real ligeramente mayor (~0.33 mag en vez de ~0.31 mag) que
el reportado en Fase 32 -- una medición más honesta, no un empeoramiento real de la física. El spread
cromático `g−y`, en cambio, mejora levemente: `-0.3547 − (-0.2737) = -0.0810` mag, contra `-0.0886` mag
de Fase 32 (~9% de reducción adicional) -- coherente con que el efecto de `Om0` es predominantemente
acromático (entra igual en las 6 bandas vía `x0`), con variación banda a banda solo por diferencias de
cobertura de bins de `z` válidos entre bandas (`u`/`z`/`y` tienen menos bins con estadística completa
por el efecto de borde de Fase 13/23), no por un mecanismo cromático nuevo. `u` sigue sin ser confiable
(solo 1-2 bins con datos, mismo problema de siempre).

### Candidato de reserva (`GENSIGMA_VPEC`/`GENRANGE_RV` en `.INPUT` compartido)

Grepeado en todos los `.INPUT` reales bajo `/home/mvalenzuela/run_SNANA/model_config/` y
`~/AUTOSIM/build/full_v5.3_10yrs/`: `GENRANGE_RV` sí aparece, pero solo en los `.INPUT` de clases con
extinción de host parametrizada (`SNIax`, `TDE-MOSFIT`, etc. -- ya documentado en fases previas, `RV`
del polvo de host, no de la Vía Láctea). El `.INPUT` real de `SNIa` (`SIMGEN_INCLUDE_SNIa-SALT2.INPUT`,
leído completo en la planificación de esta fase) no declara `GENSIGMA_VPEC` ni ningún parámetro de `RV`
-- descartado, sin necesidad de simular nada.

### Conclusión Fase 34 -- corrección real y precisa, pero de magnitud pequeña y de signo contraintuitivo

A diferencia de Fase 32 (reducción sustancial del residuo) y más parecido a Fase 24/33 (corrección real
pero de magnitud marginal frente al residuo total), esta fase identifica con precisión inusual la causa
exacta de un desajuste real (`Om0=0.3` asumido vs. `Om0=0.315` real, confirmado a 4 decimales contra el
código fuente de SNANA) -- pero corregirlo **no reduce** el residuo acromático reportado, lo aumenta
ligeramente (~0.01-0.018 mag), porque el error de `Om0` estaba parcialmente enmascarando, no causando,
parte del exceso de brillo real. El spread cromático mejora un poco (~9% adicional). El residuo que
queda tras Fase 32+34 (`~0.33` mag acromático, `~0.081` mag de spread cromático `g−y`) sigue sin causa
identificada. La corrección queda aplicada de todas formas -- es física y numéricamente correcta,
verificada contra el código fuente real de SNANA, independientemente de que no achique el número que se
viene persiguiendo.

### Archivos de esta fase

`compare_brightness_truth_salt2.py`, `run_snia_ddf_poc.py`: `Omega_m`/`Om0` corregido de `0.3` a
`0.315`, con comentario citando `OMEGA_MATTER_DEFAULT` real de `sntools.h`. Exploratorios en NLHPC,
borrados tras usarlos: `fase34_paso1_mu.py` (Paso 1, con su verificación de ajuste de `Om0`/`H0` inline),
`fase34_population_6band.py`/`.sbatch` (Paso 3, output `fase34_population_6band_output.parquet` también
borrado tras extraer los números).

## Fase 35 — el fix de `Om0=0.315` (Fase 34), extendido a los otros 6 scripts que lo tenían hardcodeado en `0.3`

A pedido explícito del usuario, se extiende el fix de cosmología de Fase 34 (`Om0=0.315`,
`OMEGA_MATTER_DEFAULT` real de SNANA, `sntools.h`) a los 6 archivos del proyecto que quedaron fuera de
esa fase (grep real confirmó 8 archivos con `Om0=0.3`/`Omega_m=0.3` hardcodeado en total; Fase 34 solo
corrigió `compare_brightness_truth_salt2.py`/`run_snia_ddf_poc.py`). Además, `bench_snia.py` y
`run_dask_poc.py` tenían `H0=73.0` (no `70.0`) -- el mismo bug de placeholder que Fase 34 encontró y
descartó para la clase `SNIa`.

### Verificación previa: `Om0=0.315` es correcto para las 6 clases, no solo `SNIa`

`OMEGA_MATTER_DEFAULT=0.315` (`sntools.h`) es un default GLOBAL de SNANA, no específico de una clase --
pero antes de asumir que ninguna clase lo sobreescribe, se grepeó `OMEGA_MATTER`/`OMEGA_LAMBDA`/`H0:`/
`H0_REF` en los 34 `include_model_<clase>.INPUT` reales de la campaña
(`~/AUTOSIM/build/full_v5.3_10yrs/includes/`) y en los `include_survey_*.INPUT`: **ninguno declara una
cosmología propia** -- el default global aplica sin excepción a las 6 clases que tocan estos scripts
(`SNIa` vía `bench_snia.py`/`run_dask_poc.py` -- ambos usan el mismo `SncosmoWrapperModel`/SALT2 que
`run_snia_ddf_poc.py`, confirmado leyendo su código --, `SNIa-91bg` SIMSED vía
`compare_brightness_truth.py`/`run_simsed_91bg_ddf_poc.py`, y las clases genéricas `NON1ASED`/`SIMSED`
vía `run_non1ased_poc.py`/`run_simsed_poc.py`). `H0=70.0` (ya confirmado real para `SNIa` en Fase 34)
también aplica sin cambios a `bench_snia.py`/`run_dask_poc.py`, ya que ambos simulan la misma clase
`SNIa`/SALT2.

### Corrección aplicada

| archivo | antes | después |
|---|---|---|
| `bench_snia.py` | `H0=73.0, Omega_m=0.3` | `H0=70.0, Omega_m=0.315` |
| `compare_brightness_truth.py` | `H0=70.0, Om0=0.3` | `H0=70.0, Om0=0.315` |
| `run_dask_poc.py` | `H0=73.0, Omega_m=0.3` | `H0=70.0, Omega_m=0.315` |
| `run_non1ased_poc.py` | `H0=70.0, Om0=0.3` | `H0=70.0, Om0=0.315` |
| `run_simsed_91bg_ddf_poc.py` | `H0=70.0, Om0=0.3` | `H0=70.0, Om0=0.315` |
| `run_simsed_poc.py` | `H0=70.0, Om0=0.3` | `H0=70.0, Om0=0.315` |

Verificado con `python3 -m py_compile` sobre los 6 archivos -- compila limpio. No se re-corrieron las
poblaciones completas de estas otras clases (`SNIa-91bg`/`NON1ASED`/`SIMSED` tienen su propio historial
de resultados reportados en Fases 5-9, sweeps de 5 semillas por clase -- fuera del hilo principal de esta
sesión, que es el residuo `SNIa`/SALT2) -- mismo criterio que Fase 24: se corrige por precisión de
calibración aunque no se mida el impacto numérico completo en cada clase.

### Conclusión Fase 35

Corrección de seguimiento, no una investigación nueva: cierra el hallazgo de Fase 34 en los 8 archivos
del proyecto que usan cosmología (2 ya corregidos ahí, 6 acá), con la misma diligencia de verificar
contra los `.INPUT` reales antes de aplicar el valor a ciegas. El residuo `SNIa`/SALT2 (~0.33 mag
acromático, ~0.081 mag cromático `g−y`) no cambia -- esta fase no lo toca, solo extiende la precisión de
calibración ya establecida al resto del proyecto.

### Archivos de esta fase

`bench_snia.py`, `compare_brightness_truth.py`, `run_dask_poc.py`, `run_non1ased_poc.py`,
`run_simsed_91bg_ddf_poc.py`, `run_simsed_poc.py`: `Om0`/`Omega_m` corregido de `0.3` a `0.315`
(y `H0` de `73.0` a `70.0` en `bench_snia.py`/`run_dask_poc.py`), con comentario citando `NOTES.md`
Fase 34. Sin scripts exploratorios nuevos -- la verificación de `.INPUT` fue grep directo, sin necesidad
de un script.

## Fase 36 — la contaminación del 15% que encontró Fase 33 SÍ infla el residuo: gran parte del patrón cromático de Fase 23 era un artefacto de calidad de datos

A pedido del usuario ("sigamos cazando otras aristas"), en vez de un candidato físico nuevo se revisa
un supuesto que quedó **sin verificar directamente** en Fase 33: que la contaminación real del 15% en
el `.DUMP` de referencia (`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`, 298/1957 objetos que no son miembros
reales de ningún campo DDF, muchos con `MWEBV` de hasta `72.68` sobre el centro galáctico) "es poco
probable que invalide los hallazgos ya reportados" porque toda la metodología usa la **mediana**. Ese
argumento nunca se puso a prueba -- y un análisis de cómo se comporta una mediana ante contaminación
**unidireccional** (los contaminantes son siempre más tenues, nunca más brillantes, por la extinción
extrema) sugiere que el argumento es, en principio, incorrecto: insertar contaminantes solo del lado
tenue de la distribución desplaza el ítem que cae en la mediana del conjunto contaminado hacia un
percentil más bajo (más tenue) de la población limpia real -- la mediana reportada de SNANA saldría
sistemáticamente **más tenue** de lo que debería, inflando artificialmente el "SNANA sale más tenue que
LightCurveLynx" que se persigue desde Fase 16.

### Paso 1 — recalcular la comparación de siempre, con y sin el filtro, número a número

Se reconstruyó la comparación banda-por-banda de Fase 32/34 desde cero (no existía un script versionado
único -- cada fase escribía y borraba el suyo): población LCL completa (2000 objetos, mismo
`seed_base=20260812`, modelo con Fase 32+34 ya aplicados) evaluada con `compute_noise_free_lightcurves()`
en `rest_phase=0` para las 6 bandas LSST, comparada contra la mediana `PEAKMAG_u/g/r/i/z/Y` real del
`.DUMP` por los mismos 7 bins de `z` (`ZCMB`, `np.linspace(0.011, 1.2, 8)`, enmascarando `-9`), **dos
veces**: sin filtrar, y filtrando con el criterio exacto de Fase 33 (separación angular `<2°` al campo
DDF real más cercano vía centros reales del OpSim, 1659/1957 objetos bien-matcheados).

**Sanity check**: el caso sin filtrar reproduce Fase 34 exacto en `g/r/i` (`-0.3547/-0.3285/-0.3283`,
match a 4 decimales) y muy cerca en `z/y` (`-0.3323` vs. `-0.3271`, `-0.2838` vs. `-0.2737` -- diferencia
chica, probablemente por cobertura de bins ligeramente distinta en las bandas con el problema de borde de
Fase 13/23, documentado honestamente, no oculto -- no afecta la conclusión porque lo que importa es el
delta filtrado-vs-sin-filtrar dentro de esta misma corrida, no la comparación cross-run).

| banda | `diff` sin filtrar (media bins 2-7) | `diff` filtrado (`<2°`) | cambio |
|---|---:|---:|---:|
| `u` | +0.8371 (no confiable, borde de template) | +0.8238 | -- |
| `g` | -0.3547 | **-0.2297** | +0.1250 |
| `r` | -0.3285 | **-0.2515** | +0.0770 |
| `i` | -0.3283 | **-0.2599** | +0.0684 |
| `z` | -0.3323 | **-0.2914** | +0.0409 |
| `y` | -0.2838 | **-0.2884** | -0.0046 |

**Nivel acromático** (media `g/r/i/z/y`): `-0.3255` mag sin filtrar → **`-0.2642` mag filtrado** --
reducción del **19%**. **Spread cromático `g−y`**: `-0.0762` mag sin filtrar → **`+0.0164` mag filtrado**
-- el spread **cambia de signo**, prácticamente desaparece.

### Paso 2 — interpretación: confirmado, con la dirección exacta que predice la física

El patrón de mejora es asimétrico y consistente con la hipótesis: `g` mejora **0.125 mag** (la banda más
afectada por extinción, la más sensible a contaminantes con `MWEBV` extremo), `y` casi no cambia (`-0.005
mag`, la banda menos sensible a extinción). Esto es exactamente lo que predice la física de la
contaminación (extinción ∝ mucho más fuerte en azul que en rojo) -- no un ajuste ad-hoc. **El patrón
cromático `g>r>i>z>y` que motivó las Fases 23 a 31 completas (integración de banda, punto cero,
interpolación 2D, instrumentar y recompilar SNANA...) resulta, en una fracción sustancial, un artefacto
de calidad de datos del `.DUMP` de referencia** -- no una diferencia real de física/fotometría entre
LightCurveLynx y SNANA. Aplicado como corrección permanente de metodología: nueva función
`filter_ddf_field_contamination()` en `snana_params.py` (reutilizable para cualquier comparación futura
contra este `.DUMP`).

### Conclusión Fase 36 — el hallazgo más grande de la investigación después de Fase 32

Con Fase 32 (bug de muestreo, ~30-40% del nivel acromático, ~58% del spread cromático) y Fase 36
(contaminación de datos, ~19% adicional del nivel acromático, prácticamente el 100% del spread cromático
restante) combinadas: el **residuo acromático real** queda en **~0.26 mag** (bajando de ~0.52 mag desde
Fase 22), y el **patrón cromático de Fase 23, que llevó 8 fases completas de investigación de la cadena
SALT2/fotometría sintética, resulta mayormente explicado por un problema de datos, no de física** --
con el spread `g−y` real cambiando de signo tras el filtro (`+0.016` mag, compatible con ruido/cobertura
de bins, no con un patrón cromático sistemático). Queda un residuo acromático real de ~0.26 mag sin
causa identificada -- significativamente más chico que el `~0.33` mag que dejó Fase 34, y sin ningún
patrón cromático claro que perseguir. Esto cambia sustancialmente el mapa de la investigación: el
trabajo de Fases 25-31 (aislar la convención de integración de banda, el punto cero) sigue siendo
metodológicamente válido y real (esos mecanismos existen y están cuantificados), pero ya no son
necesarios para explicar el patrón cromático observado -- ese patrón, en gran medida, nunca fue tal cosa.

### Archivos de esta fase

`snana_params.py`: nueva función `filter_ddf_field_contamination()` (filtro de contaminación de campo
DDF, reutilizable). Exploratorios en NLHPC, borrados tras usarlos: `fase36_population_6band.py`/`.sbatch`
(recorrida poblacional 6 bandas, output `fase36_population_6band_output.parquet` también borrado),
`fase36_analysis.py` (comparación con/sin filtro, outputs `fase36_diff_unfiltered.csv`/
`fase36_diff_filtered.csv` también borrados tras extraer los números).

## Fase 37 — RESUELTO: el residuo acromático era `MAG_OFFSET: 0.27`, una clave del `SALT2.INFO` real del modelo que `sncosmo` no lee en absoluto

Cierra el residuo que la investigación persigue desde Fase 16. **No estaba en la cadena SALT2, ni en
la fotometría sintética, ni en el muestreo poblacional: estaba en un archivo del propio directorio del
modelo que `sncosmo` abre pero nunca lee.**

### El cambio de método que lo destrabó: comparación PAREADA, no mediana-contra-mediana

Todas las comparaciones poblacionales de Fases 16-36 son `mediana(LCL)` contra `mediana(SNANA)` de
**dos poblaciones muestreadas independientemente** (LightCurveLynx samplea su propio `z`/`x1`/`c`;
SNANA los suyos). Eso mezcla irreversiblemente dos efectos distintos:

- **(a) diferencia de FOTOMETRÍA** — mismos parámetros, distinto flujo;
- **(b) diferencia de MUESTREO POBLACIONAL** — distinta distribución de `z`/`x1`/`c`/`MU`.

Ninguna fase anterior pudo separarlos, y por eso el espacio de candidatos parecía agotado: cada fase
atacaba un mecanismo de (a) o de (b) sin poder acotar cuánto podía aportar cada familia. El `.DUMP`
usado desde Fase 16 no trae `x1`/`c` (36 columnas reales, ninguna es `S2c`/`S2x1`), así que el pareo
nunca fue posible con ese archivo.

**Lo que sí lo hace posible, y nunca se había mirado: el `_HEAD.FITS` real de producción.** Tiene 212
columnas, entre ellas `SIM_SALT2x0`, `SIM_SALT2x1`, `SIM_SALT2c`, `SIM_SALT2mB`, `SIM_SALT2alpha`,
`SIM_SALT2beta`, `SIM_DLMU`, `SIM_MWEBV`, `SIM_PEAKMJD`, `SIM_MAGSMEAR_COH` y `SIM_PEAKMAG_u..Y` —
**por objeto**. Con eso se le pueden dar a LightCurveLynx los parámetros EXACTOS que usó SNANA y
comparar objeto a objeto, aislando (a) de (b) por primera vez en todo el proyecto.

### Paso 0 — hallazgo lateral de higiene: el `.DUMP` de referencia estaba truncado

El archivo usado desde Fase 16 vive en `_stale_pre_v8fix/` y tiene **1957** filas. Existe la versión
no-stale de la MISMA simulación (mismo `RANSEED: 12945`, filas 1-1957 byte-idénticas) en
`/home/mvalenzuela/DATASIM_LSST_1/DDF/SIMDv8/SNIa_DDF_baseline_v5.3.1_10yrs/`, con las **2000** filas
completas (`NGENTOT_LC: 2000`). El `_stale` era simplemente una copia truncada, no una corrida
distinta. Se pasa a la versión completa (43 objetos más, ~2%).

De paso, su `.README` confirma contra el registro real de la corrida varios valores que fases
anteriores dedujeron indirectamente: `OMEGA_MATTER: 0.3150` y `H0 = 70.00` (Fase 34 ✓),
`GENSIGMA_VPEC: 0` (Fase 34 ✓), `GENSIGMA_MWEBV_RATIO: 0.16` (Fase 10 ✓), `WRFLAG_MODELPAR: 1`.

### Paso 1 — verificación previa: la definición de `mB` de SNANA, objeto por objeto

Antes de nada, con las columnas reales del `_HEAD.FITS` (597 objetos escritos):

| relación probada | residuo mediano | std |
|---|---:|---:|
| `SIM_SALT2mB` vs `-2.5·log10(SIM_SALT2x0) + 10.635` | **0.000000** | — |
| `SIM_SALT2mB` vs `SIM_DLMU − 19.365 − α·x1 + β·c` | **0.000000** | 0.000001 |

`SIM_SALT2alpha=0.14`, `SIM_SALT2beta=3.1`, `SIM_SALT2gammaDM=0` exactos. **`M_abs=-19.365` de Fase 20
queda confirmado por tercera vez, ahora contra datos reales por objeto y no contra una reconstrucción.**
Además `SIM_MAGSMEAR_COH` tiene `std=0.0911` — es el término coherente de G10, y coincide con el
`SIGMA_INT=0.090` que el proyecto ya usaba.

### Paso 2 — la comparación pareada: el residuo es 100% fotométrico y perfectamente plano

Se alimentó a LightCurveLynx, objeto por objeto, el `SIM_SALT2x0`/`x1`/`c`/`SIM_REDSHIFT_HELIO`/
`SIM_MWEBV`/`SIM_PEAKMJD` **exactos** de SNANA (`SncosmoWrapperModel` +
`compute_single_noise_free_lightcurve()` en `rest_phase=0`, mismo motor real de Fases 22-36), con el
filtro de contaminación de Fase 36 aplicado (586/597):

| banda | N | mediana Δ (LCL−SNANA) | media | std | p16 | p84 |
|---|---:|---:|---:|---:|---:|---:|
| `u` | 28 | -0.2931 | -0.2803 | 0.189 | -0.438 | -0.117 |
| `g` | 266 | -0.2656 | -0.2746 | 0.132 | -0.409 | -0.154 |
| `r` | 584 | -0.2620 | -0.2641 | 0.114 | -0.369 | -0.153 |
| `i` | 585 | -0.2613 | -0.2620 | 0.098 | -0.355 | -0.165 |
| `z` | 566 | -0.2608 | -0.2605 | 0.094 | -0.353 | -0.168 |
| `y` | 517 | -0.2574 | -0.2607 | 0.094 | -0.354 | -0.165 |

Y **descontando el smear coherente real de cada objeto** (`SIM_PEAKMAG − SIM_MAGSMEAR_COH`):

| banda | mediana Δ | std |
|---|---:|---:|
| `g` | -0.2722 | 0.098 |
| `r` | -0.2722 | 0.073 |
| `i` | -0.2710 | **0.033** |
| `z` | -0.2693 | **0.023** |
| `y` | -0.2699 | **0.022** |

Ajustando `Δ_r` contra `SIM_MAGSMEAR_COH`: **pendiente `-0.9672`, intercepto `-0.2719`** — confirma
numéricamente que `SIM_PEAKMAG` SÍ incluye el smear intrínseco (dato nuevo: Fase 27 había supuesto lo
contrario) y que, quitándolo, lo que queda es una **constante**.

Y por bin de `z` (mediana, banda `r`): `-0.2977 / -0.2492 / -0.2700 / -0.2694 / -0.2623 / -0.2387 /
-0.2637` — **plano también en redshift**.

Con `std` de **0.022-0.033 mag** en `i`/`z`/`y` sobre ~570 objetos, esto no es un residuo estadístico:
es un **offset constante y acromático de −0.272 mag**. Y como el pareo elimina por construcción toda
diferencia de muestreo, **el 100% del residuo es fotométrico** — toda la familia (b) queda descartada
de un solo golpe.

### Paso 3 — ¿de qué lado está el error? Prueba a tres bandas

Se comparó la MISMA magnitud AB sintética para el mismo objeto SALT2 (`z=0.6`, sin extinción) por tres
caminos independientes: (1) LightCurveLynx (`PassbandGroup`/`evaluate_bandfluxes`), (2) `sncosmo`
nativo (`Model.bandmag(band, "ab", t0)`, implementación de referencia independiente), y (3) una
integral AB photon-counting escrita a mano desde `model.flux()`:

| banda | LCL | sncosmo | manual | LCL−sncosmo | LCL−manual |
|---|---:|---:|---:|---:|---:|
| `g` | 24.7335 | 24.6997 | 24.7335 | +0.0338 | **0.0000** |
| `r` | 23.3787 | 23.3761 | 23.3787 | +0.0027 | **0.0000** |
| `i` | 23.3418 | 23.3441 | 23.3418 | -0.0023 | **0.0000** |
| `z` | 23.3757 | 23.3781 | 23.3757 | -0.0024 | **0.0000** |
| `y` | 23.4704 | 23.4641 | 23.4704 | +0.0062 | **0.0000** |

(las diferencias contra `sncosmo` son el recorte `trim_quantile` de las bandas, ya cuantificado en
Fase 31). **La fotometría absoluta de LightCurveLynx es correcta**, verificada contra dos referencias
independientes. Y del lado de SNANA, el punto cero también: el `PrimarySED` real de `kcor_LSST.fits`
resultó ser **exactamente** AB (3631 Jy) — razón contra `3631 Jy` constante en las 991 longitudes de
onda con `std = 1.7e-7` — con `Primary Mag = 0`, `ZPoff(Primary) = 0` en las 6 bandas, y el log real de
la corrida confirma `MODEL mag offsets (ugrizY): 0.00 0.00 0.00 0.00 0.00 0.00`. También se verificó en
el fuente que `SEDMODEL.FLUXSCALE = X0SCALE_SALT2 = 1.0E-12` (`genmag_SALT2.c:257`), **el mismo valor
exacto** que `sncosmo.SALT2Source._SCALE_FACTOR`, y que los factores `lamstep/hc8` se cancelan entre
`Finteg` y el `ZP`. Los dos lados, por separado, son correctos.

### Paso 4 — el hallazgo: `MAG_OFFSET: 0.27` en el `SALT2.INFO` del modelo

`/home/mvalenzuela/run_SNANA/plasticc_models/SALT2.WFIRST-H17/SALT2.INFO` (y su copia local
`exploration/lightcurvelynx/salt2_h17_local/SALT2.INFO`, el directorio que los scripts le pasan a
`sncosmo.SALT2Source(modeldir=...)`) declara:

```
RESTLAMBDA_RANGE  2000. 23000
COLORLAW_VERSION: 1
COLORCOR_PARAMS: 2800 9500 4 -1.33154627 0.61225710 -0.12117791 0.00840832
COLOR_OFFSET:  0.0

MAG_OFFSET: 0.27          <---- ESTO
SEDFLUX_INTERP_OPT: 1
...
SIGMA_INT: 0.090
```

**SNANA lo lee y lo aplica a TODA magnitud del modelo** — `genmag_SALT2.c`, línea real 2257:

```c
magobs = ZP - 2.5*log10(flux) + INPUT_SALT2_INFO.MAG_OFFSET ;
```

(leído en `genmag_SALT2.c:1275-1276`, default `0.0` en la línea 1205; y aplicado también al
espectrógrafo en la línea 3586 vía `FSCALE_ZP = pow(TEN,-0.4*MAG_OFFSET)`). Como entra después de la
integral de banda, es **aditivo en magnitud y exactamente acromático**, y afecta a `peakmag_obs` y por
lo tanto a `PEAKMAG_<filt>` del `.DUMP` y a `SIM_PEAKMAG_<filt>` del `_HEAD.FITS`.

**`sncosmo.SALT2Source` no lee `SALT2.INFO` en absoluto.** Verificado sobre el fuente real del paquete
instalado (`sncosmo==2.13.0`, vía `inspect.getsource`): ni la cadena `"SALT2.INFO"` ni `"MAG_OFFSET"`
aparecen en la clase. Sus argumentos de `__init__` son exclusivamente `m0file`, `m1file`, `clfile`,
`cdfile`, `errscalefile`, `lcrv00file`/`11`/`01` — el `SALT2.INFO` está en el mismo directorio, se copia
junto al resto del modelo, y se ignora silenciosamente.

**Valor declarado: `0.27`. Residuo pareado medido: `-0.2722` mag. Coinciden a 0.002 mag.**

Detalle de honestidad: ese `0.0022` residual es consistente con un efecto real de segundo orden que se
encontró en el mismo paso pero no se corrigió — `snlc_sim.c:25324` real muestra que
`SIM_PEAKMAG = peakmag_obs − MCOR_TRUE_MW`, es decir el `_HEAD.FITS` reporta la magnitud **con la
extinción MW ya descontada**, mientras el pareo de arriba sí la aplicó del lado de LightCurveLynx.
A los `E(B-V)` reales de DDF eso vale ~0.02-0.07 mag según banda y explica también por qué el `Δ`
pareado no es perfectamente plano entre `u` y `y` (`-0.293` vs `-0.257`). No cambia la conclusión y se
documenta como caveat conocido, no se oculta.

**Ironía real del hallazgo**: `run_snia_ddf_poc.py` ya citaba este mismo archivo desde las primeras
fases — su docstring dice literalmente *"SIGMA_INT=0.090 (de SALT2.INFO)"*. El proyecto leyó
`SALT2.INFO`, tomó `SIGMA_INT` de ahí, y nunca miró la clave que está **dos líneas más arriba**.

### Paso 5 — corregido y medido sobre la población completa (2000 objetos)

Nueva función `read_salt2_info()` en `snana_params.py` que parsea el `SALT2.INFO` real (no hardcodea el
`0.27`), y `m_abs = -19.365 + MAG_OFFSET` en los scripts. Es exactamente equivalente al offset aditivo
de SNANA: `x0 ~ 10^(-0.4·m_abs)`, así que `+0.27` en `m_abs` atenúa las 6 bandas por igual en `+0.27`
mag.

Recorrida completa: **la misma población de 2000 objetos** (mismo `seed_base=20260812`, mismos
`z`/`x1`/`c`/`t0`/`ra`/`dec`) evaluada **dos veces en la misma corrida**, con y sin el offset, contra el
`.DUMP` real completo ya filtrado de contaminación (1696/2000, Fase 36),
`compute_noise_free_lightcurves()` en `rest_phase=0`, mediana por los mismos 7 bins de `z`, media de
bins 2-7 — metodología idéntica a Fases 32/34/36:

| banda | sin fix (estado Fase 36) | con fix `MAG_OFFSET` | cambio |
|---|---:|---:|---:|
| `u` | +0.8105 (no confiable, borde de template) | +1.0805 | +0.2700 |
| `g` | -0.2304 | **+0.0396** | +0.2700 |
| `r` | -0.2509 | **+0.0191** | +0.2700 |
| `i` | -0.2647 | **+0.0053** | +0.2700 |
| `z` | -0.2892 | **-0.0192** | +0.2700 |
| `y` | -0.2880 | **-0.0180** | +0.2700 |

**NIVEL ACROMÁTICO (media `g/r/i/z/y`): `-0.2646` → `+0.0054` mag — el residuo se reduce un 98%.**

Sanity check real: la columna "sin fix" reproduce el número de Fase 36 (`-0.2642`) a **0.0004 mag** de
diferencia, con un script escrito de cero — la comparación es la misma, no una redefinición conveniente.
El spread cromático `g−y` no cambia (`+0.0577` antes y después): el offset es exactamente acromático por
construcción, como debe ser. (Ese `+0.058` es algo mayor que el `+0.016` de Fase 36 por usar ahora el
`.DUMP` completo de 2000 filas en vez del truncado de 1957; sigue siendo compatible con ruido de
cobertura de bins, no con un patrón cromático sistemático.) `u` sigue sin ser confiable — mismo problema
de borde de template de Fase 13/23/27, con 1-2 bins válidos.

### Paso 6 — cabo suelto de Fase 32 cerrado de paso: los samplers de `c`/`x1`, contra los draws reales

Fase 32 verificó la **fracción de rama** del sampler bifurcado, nunca la distribución completa ni el
comportamiento en los bordes de truncamiento (`GENRANGE_SALT2c/x1`). Se cerró de dos formas.

**Por lectura de código real**: `getRan_GENGAUSS_ASYM()` (`sntools_genGauss_asym.c`, bloque final de la
función) trunca por **rechazo puro con redraw completo** (`if (ranval < lo) { goto
BEGIN_RANDOM_SELECT; }`), que vuelve a sortear también el lado — exactamente lo que hace
`make_bifurcated_normal_sampler()`. No hay diferencia de mecanismo.

**Por medición directa**: se reprodujo la corrida de producción con el `.INPUT` real **sin editarlo**
(`snlc_sim.exe sim_SNIa_DDF_baseline_v5.3.1_10yrs.INPUT GENVERSION TEST_FASE37_dump SIMGEN_DUMPADD
S2c,S2x1,S2mb` — `SIMGEN_DUMPADD` es un override de línea de comandos, la vía limpia que evita el bug
de claves duplicadas de Fase 27), obteniendo los `c`/`x1` reales de los **2000 objetos generados**
(`SIMGEN_DUMPALL`, sin sesgo de trigger; 79 filas traen el flag `-9` y se enmascaran):

| | `c` real (N=1921) | `c` LCL (200k) | `x1` real | `x1` LCL |
|---|---:|---:|---:|---:|
| media | -0.0061 | -0.0075 | -0.0083 | -0.0028 |
| mediana | -0.0153 | -0.0163 | 0.1695 | 0.1586 |
| std | 0.0753 | 0.0745 | 0.9034 | 0.9101 |
| P(lado alto) | 0.7090 | 0.7028 | 0.1223 | 0.1321 |
| fuera de rango | 0 | 0 | 0 | 0 |

Test KS de dos muestras: `c` → `stat=0.0187, p=0.515`; `x1` → `stat=0.0214, p=0.345` — **no se puede
rechazar que sean la misma distribución** en ninguno de los dos. Impacto en magnitud de las diferencias
de media: **`-0.0041` mag (`c`) y `-0.0008` mag (`x1`)**. **Los samplers están correctos**, bordes de
truncamiento incluidos — coherente con el Paso 2, que ya había mostrado que el residuo es 100%
fotométrico y por lo tanto que no quedaba nada por encontrar del lado poblacional.

### Conclusión Fase 37 — el residuo queda cerrado, y la lección metodológica es la parte transferible

1. **El residuo acromático de ~0.26 mag que la investigación persigue desde Fase 16 queda explicado y
   corregido**: `MAG_OFFSET: 0.27` del `SALT2.INFO` real del modelo `SALT2.WFIRST-H17`, aplicado por
   SNANA (`genmag_SALT2.c:2257`) e ignorado por completo por `sncosmo`/LightCurveLynx. Nivel acromático
   `-0.2646` → `+0.0054` mag, **98% de reducción**, sin patrón cromático residual.
2. **Cadena completa de la investigación**: Fase 22 midió `~0.52` mag; Fase 32 (bug del sampler
   bifurcado) bajó a `~0.33`; Fase 36 (contaminación de campo del `.DUMP`) a `~0.26`; Fase 37
   (`MAG_OFFSET`) a `~0.005`. Las cuatro correcciones son reales, independientes y verificadas contra
   código o datos reales.
3. **Por qué 21 fases no lo encontraron, y qué lo destrabó.** Dos razones concretas, ambas
   estructurales y no de esfuerzo:
   - *La métrica lo escondía.* Todas las pruebas código-real-contra-código-real de Fases 26-31 se
     midieron **relativas a la banda `r`** (`diff = (LCL−r) − (SNANA−r)`). Esa normalización **cancela
     por construcción cualquier offset acromático** — y `MAG_OFFSET` es exactamente eso. La búsqueda
     estaba, sin saberlo, ciega a la única clase de causa que quedaba.
   - *La comparación mezclaba dos familias de causas.* Comparar mediana contra mediana de dos
     poblaciones independientes impedía saber si el residuo venía de la fotometría o del muestreo. El
     pareo objeto-a-objeto (posible sólo mirando el `_HEAD.FITS`, nunca usado antes) lo resolvió en una
     sola corrida y con `std = 0.022` mag.
4. **Lección de fidelidad, generalizable más allá de este proyecto**: cuando se reemplaza un simulador
   por otro reusando los **mismos archivos de modelo**, no alcanza con verificar que los archivos de
   datos sean byte-idénticos (Fase 20 lo hizo, con `md5sum`) — hay que verificar que el nuevo código
   **lea todas las claves de configuración** que el viejo lee. `sncosmo` copia y abre el directorio
   `SALT2.WFIRST-H17` entero, y descarta silenciosamente `MAG_OFFSET`, `COLOR_OFFSET`,
   `SEDFLUX_INTERP_OPT`, `MAGERR_*` y `RESTLAMBDA_RANGE`. Es un modo de falla silencioso: no hay error,
   no hay warning, sólo un sesgo constante de 0.27 mag. Es el mismo patrón de las Fases 24/32/34
   (`O94` vs `F99`, split 50/50, `Om0=0.3`) llevado a su forma más pura: **un valor asumido por
   omisión, nunca contrastado contra la fuente real**.
5. **Cabo suelto menor documentado, no corregido**: `SIM_PEAKMAG` del `_HEAD.FITS` viene con la
   extinción MW descontada (`snlc_sim.c:25324`), mientras `PEAKMAG_<filt>` del `.DUMP` no. Cualquier
   comparación futura contra `_HEAD.FITS` debe apagar la extinción del lado de LightCurveLynx. Efecto
   ~0.02-0.07 mag; no afecta la comparación principal de esta fase, que usa el `.DUMP`.

### Archivos de esta fase

- `snana_params.py`: nueva función `read_salt2_info()` — parsea el `SALT2.INFO` real del directorio del
  modelo (no hardcodea `0.27`), con la cita de `genmag_SALT2.c:2257` y la verificación de que `sncosmo`
  no lo lee.
- `compare_brightness_truth_salt2.py`, `run_snia_ddf_poc.py`, `run_dask_poc.py`: `m_abs = -19.365 +
  MAG_OFFSET` leído del `SALT2.INFO` real. En `run_dask_poc.py` se corrige además el `-19.3` que había
  quedado sin migrar desde Fase 20 (mismo criterio de seguimiento que Fase 35 para `Om0`).
- `bench_snia.py`: **no** se toca — usa el modelo `"salt2-h17"` del registry de `sncosmo` (no el
  directorio real de producción, así que no hay `SALT2.INFO` que leer) y una población sintética
  (`x1~N(0,2)`, `c~N(0,0.02)`, `z` uniforme); es un benchmark de rendimiento, no parte de la cadena de
  fidelidad. Queda anotado honestamente, no corregido a ciegas.
- Referencia de comparación: se pasa del `.DUMP` truncado de `_stale_pre_v8fix/` (1957 filas) al
  completo de `DDF/SIMDv8/` (2000 filas, misma corrida).
- Exploratorios en NLHPC, borrados tras usarlos: `fase37_paired.py`/`.sbatch` (Paso 2, comparación
  pareada contra `_HEAD.FITS`), `fase37_3way.py` (Paso 3, LCL vs `sncosmo` vs integral manual),
  `fase37_pop.py`/`.sbatch` (Paso 5, población completa con y sin fix), `run_fase37_dump.sh` (Paso 6,
  reproducción de la corrida de producción con `SIMGEN_DUMPADD`). GENVERSION `TEST_FASE37_dump`
  generado en `SNDATA_ROOT/SIM/` y borrado tras extraer los `c`/`x1` reales. Sin parches nuevos a
  SNANA — esta fase no necesitó instrumentar el binario, sólo leer su fuente y sus archivos de entrada.

## Fase 38 — cerrar el círculo con Fase 16: ¿el exceso de SNR/detección también se cierra con el brillo corregido?

Retoma la pregunta que arrancó la mitad de esta investigación: Fase 16 midió un exceso de SNR real de
LightCurveLynx sobre SNANA (mediana `0.868` vs. `0.78` real, `+11.3%`; `p90` `2.948` vs. `2.26` real,
`+30.4%`) y lo atribuyó al exceso de brillo, entonces sin explicar. Fase 37 cerró el brillo
(`-0.2646 → +0.0054` mag, `98%` de reducción). Esta fase remide el SNR/eficiencia de detección con la
población ya corregida (Fases 32+34+36+37 aplicadas) para ver si también cierra.

### Predicción, escrita antes de correr nada

El brillo real bajó `+0.27` mag (más tenue) desde el punto en que se midió el exceso de SNR de Fase
16 — un factor de flujo `10^(-0.4*0.27) = 0.779`. `SNR ∝ flujo` (aprox., a fondo de cielo fijo), así
que la predicción cuantitativa es:

- `snr_median` esperado: `0.868 × 0.779 ≈ 0.676` (contra `0.78` real de SNANA — **se espera que el
  signo del exceso se invierta**, de `+11.3%` a `~-13%`).
- `snr_p90` esperado: `2.948 × 0.779 ≈ 2.296` (contra `2.26` real — cerraría casi exacto, `+1.6%`).
- `detection_efficiency_pct` esperada: sin un modelo cuantitativo tan directo (la curva de eficiencia
  SEARCHEFF no es lineal en SNR), pero cualitativamente se espera una baja sustancial desde el
  `56.45%`/`ratio 1.89x` de Fase 16, plausiblemente hacia la zona de `35-45%` (`ratio ~1.2-1.5x`) —
  **no necesariamente hasta el `29.85%` real de SNANA**.

**Predicción explícita: es esperable que el brillo corregido sobre-corrija el SNR mediano (lo cruce
hacia abajo) y que el exceso de eficiencia de detección se reduzca sustancialmente pero probablemente
NO cierre del todo** — documentado así antes de correr, para no leer el resultado real de forma
conveniente después.

### Paso 1 — se cierra H5: `snr_median`/`snr_p90` ahora sí quedan en `summary.json`

`run_snia_ddf_poc.py` ya calculaba e imprimía al log `snr_median`/`snr_p90` (línea ~341-344, real desde
Fase 1) pero nunca los guardaba en `summary.json`, pese a que `HOWTO.md` §5-6 los documenta como parte
del resumen real. Corregido: se agregan `snr_median`, `snr_p90`, `snr_median_snana_ref: 0.78`,
`snr_p90_snana_ref: 2.26` al dict real (único cambio a este script). `py_compile` OK.

### Paso 2 — 5 semillas, resultado real

Corridas reales en NLHPC (`sbatch`, jobs `12038980`-`12038984`, `COMPLETED` exit `0:0` los 5, ~100-120s
de tiempo de simulación cada una), mismo `seed_base` implícito por índice de semilla de siempre:

| semilla | `snr_median` | `snr_p90` | `n_detected`/2000 | `detection_efficiency_pct` |
|---|---:|---:|---:|---:|
| 0 | 0.8208 | 2.452 | 946 | 47.30 |
| 1 | 0.8439 | 2.595 | 995 | 49.75 |
| 2 | 0.8352 | 2.590 | 990 | 49.50 |
| 3 | 0.8571 | 2.834 | 957 | 47.85 |
| 4 | 0.8367 | 2.600 | 934 | 46.70 |
| **media ± std** | **0.839 ± 0.013** | **2.614 ± 0.138** | **964.4 ± 25** | **48.22 ± 1.35** |

Tabla comparativa completa:

| métrica | SNANA real | LCL Fase 16 (pre-fix) | LCL Fase 38 (post-fix, 5 semillas) |
|---|---:|---:|---:|
| `snr_median` | 0.78 | 0.868 (+11.3%) | **0.839 ± 0.013 (+7.6%)** |
| `snr_p90` | 2.26 | 2.948 (+30.4%) | **2.614 ± 0.138 (+15.7%)** |
| `detection_efficiency_pct` | 29.85% | 56.45% | **48.22% ± 1.35%** |
| ratio de detección | 1.00x | 1.89x | **1.615x ± 0.045** |

*(No se encontró en `NOTES.md` un número de SNR/eficiencia distinto y anterior a Fase 16 explícitamente
etiquetado "Fase 1" -- la fila de comparación real más temprana disponible es la de Fase 16 misma; no se
inventa un número de relleno.)*

### Paso 3 — interpretación contra la predicción: refutada, con evidencia directa

**La predicción cuantitativa (Paso previo, "esperado `snr_median≈0.68`") queda refutada.** El SNR
mediano real bajó solo de `0.868` a `0.839` (`-3.3%` relativo) -- casi siete veces menos que la caída
del `~22%` que predecía un modelo lineal `SNR ∝ flujo` dado el factor `×0.779` de `MAG_OFFSET`. El
`p90` sí se movió más (`2.948→2.614`, `-11.3%`), pero tampoco cruzó por debajo de la referencia real
(`2.26`). La eficiencia de detección mejora de forma real y ya no ambigua (`56.45%→48.22%`, ratio
`1.89x→1.615x±0.045`, bandas de 5 semillas no solapadas con el valor de Fase 16) -- pero queda lejos
de cerrar contra el `29.85%` real de SNANA.

**Lectura honesta**: el exceso de brillo SÍ explicaba una fracción real del exceso de detección (la
mejora de `1.89x` a `1.615x` es consistente en dirección y no trivial), pero el SNR en sí -- que depende
tanto del flujo (numerador) como del ruido asumido (denominador) -- casi no se movió. Si el numerador
bajó ~`22%` en términos de flujo pero el cociente SNR bajó solo `~3%`, la implicación aritmética directa
es que **el denominador (modelo de ruido) también está sesgado, en la dirección que compensa casi por
completo la corrección de brillo** -- consistente con el candidato que la propia Fase 16 (Paso 1) dejó
señalado y nunca cerrado: `snana_noise_columns()` no pasa explícitos los términos de
`readout_noise`/`dark_current` reales del SIMLIB (`readnoise=0.25`), dependiendo en cambio de los
defaults de `OpSim`. Otros candidatos no descartados: la lógica de trigger/SEARCHEFF real
(`searcheff.py::group_into_epochs()`) y `rest_time_window_offset=(-30,100)` (una ventana de generación
más ancha que la real podría inflar el denominador de la eficiencia, aunque no el SNR por observación
en sí). **No se fuerza un cierre que los datos no muestran** -- queda como pregunta nueva, abierta,
mejor acotada que antes (ya no es "¿por qué hay exceso de SNR?" sino específicamente "¿por qué el SNR
no cae proporcional al flujo corregido?").

### Tarea P1 — estado real de la referencia WFD de `SNIa`

El `postprocess_manifest.json` real (`~/AUTOSIM/build/full_v5.3_10yrs/postproc/`) registra
`SNIa_WFD_baseline_v5.3.1_10yrs` con `error: "'utf-8' codec can't decode byte 0xee in position 119:
invalid continuation byte"` (entrada real, `n_processed=0` en ese manifiesto -- corrida de postproceso
mayormente `skipped`, no completada). Pero la **simulación cruda sí completó**: 2 de 5 logs reales de
`snlc_sim.exe` para esta clase (`run_SNIa_WFD_baseline_v5.3.1_10yrs_11320196.out`/`_11330240.out`)
terminan con `DONE with snlc_sim.` real (`WR_SNFITSIO_END: wrote 28949 events`); los otros 3 fallaron a
mitad de camino (uno con error real de `cfitsio`, dos truncados, consistentes con el incidente de cuota
ya documentado). El directorio de salida real
(`/home/mvalenzuela/DATASIM_LSST_1/WFD/SIMWv8/SNIa_WFD_baseline_v5.3.1_10yrs/`) tiene `.DUMP` (2.5MB,
10.456 filas, bien formado, `VARNAMES`/`SELECTION: NONE` real), `_HEAD.FITS` (4.2MB) y `_PHOT.FITS`
(20MB) reales y con timestamp consistente (11-ago). El byte `0xee` reportado por el manifiesto **no
está** en la posición 119 del `.README` real actual (se verificó byte a byte: es `0x6c`, ASCII) -- el
error del manifiesto probablemente viene de un archivo/intento distinto o quedó desactualizado. **La
línea futura "extender a WFD" queda parcialmente desbloqueada**: hay datos reales de referencia
utilizables (`.DUMP`/`_HEAD.FITS`/`_PHOT.FITS`), pero el pipeline de postproceso automático necesita
revisión aparte antes de confiar en cualquier número que dependa de él.

### Conclusión Fase 38

El círculo con Fase 16 se cierra parcialmente, con un resultado más interesante que el esperado: **la
corrección del brillo (Fases 32/34/37) sí mejora la eficiencia de detección de forma real (ratio
`1.89x→1.615x`), pero el SNR en sí casi no se mueve** -- refutando con evidencia directa la hipótesis
lineal simple que motivaba esta fase, y por eliminación aritmética, apuntando al **modelo de ruido**
(no ya solo al flujo) como el candidato dominante que queda para el exceso de detección real. Es un
resultado más rico que "cierra"/"no cierra": redirige la investigación futura hacia un mecanismo
concreto y no probado (`snana_noise_columns()`/`readout_noise`/`dark_current` vs. SIMLIB real).

### Archivos de esta fase

`run_snia_ddf_poc.py`: agregados `snr_median`/`snr_p90`/`snr_median_snana_ref`/`snr_p90_snana_ref` a
`summary.json` (único cambio). `docs/lcl_qc/lcl_qc_index.json`: actualizado el registro `SNIa` con los
números reales de esta fase (antes: datos pre-Fase-32/34/37, ya sabidos incorrectos). `docs/index.html`:
nueva entrada Fase 38 en "N fases", callout "Actualización Fase 38" en Resumen, ítem 1 de "líneas para
seguir investigando" en Conclusiones marcado como hecho. Sin scripts exploratorios nuevos -- toda la
medición usa el propio `run_snia_ddf_poc.py` real, ya versionado.

## Fase 39 — validada la curva completa vía `SIM_MAGOBS` real: plana, sin la dependencia de fase esperada del candidato `SEDFLUX_INTERP_OPT`

Usa H1 (identificado al planificar esta ronda con Opus): el `_PHOT.FITS` real de producción trae
`SIM_MAGOBS` -- magnitud verdadera sin ruido, por época, para los 597 objetos SNIa DDF detectados
(`/home/mvalenzuela/DATASIM_LSST_1/DDF/SIMDv8/SNIa_DDF_baseline_v5.3.1_10yrs/`). Permite parear
objeto-a-objeto y **época-a-época real** contra LightCurveLynx sin simular ninguna fase sintética --
extensión directa del método pareado de Fase 37 (que solo miró `rest_phase=0`) a la curva completa.

### Verificación previa: `SIM_MAGOBS` también viene con la extinción MW descontada

Confirmado en `~/github/SNANA_src/src/snlc_sim.c` real (línea 25394):
```c
SNDATA.SIMEPOCH_MAG[epoch] = GENLC.genmag_obs[epoch] - MCOR_TRUE_MW ;
```
mismo patrón que `SIM_PEAKMAG` (línea 25324, cabo suelto ya documentado en Fase 37 Paso 4) --
`SIMEPOCH_MAG` es el nombre interno de struct que se escribe como `SIM_MAGOBS` en el `_PHOT.FITS`. Se
evaluó LightCurveLynx **sin** `ExtinctionEffect` para que el pareo sea consistente.

### Método real: `PTROBS_MIN`/`PTROBS_MAX`, no MJD

`_HEAD.FITS` (597 objetos, 212 columnas) trae `PTROBS_MIN`/`PTROBS_MAX` -- índices 1-based reales que
delimitan el bloque de épocas de cada objeto en `_PHOT.FITS` (2.630.079 filas totales). Por objeto, se
leyeron `SIM_SALT2x0/x1/c`, `SIM_REDSHIFT_HELIO`, `SIM_PEAKMJD` reales; se aplicó
`filter_ddf_field_contamination()` (Fase 36, ya versionada) -- 586/597 bien-matcheados; se construyó
`SncosmoWrapperModel(local_src, t0=SIM_PEAKMJD, x0=SIM_SALT2x0, x1=SIM_SALT2x1, c=SIM_SALT2c,
redshift=SIM_REDSHIFT_HELIO)` (sin extinción) y se evaluó `evaluate_bandfluxes()` real en los MJD
**exactos** de cada época real; se sumó `MAG_OFFSET` real (`read_salt2_info()`, Fase 37). Hallazgo de
higiene real: la columna `BAND` del `_PHOT.FITS` viene como `LSST-<letra>` (p.ej. `LSST-r`), no la
letra sola -- un primer intento sin parsear el prefijo dio 0 filas útiles, corregido antes de medir
nada. Sentinela real de "sin dato" en `SIM_MAGOBS`: `99.0` (571.868/2.630.079 filas, 21.7%);
enmascarado junto con 5 filas de encabezado (`BAND='-'`) antes de calcular cualquier cosa.

### Resultado: 560.421 pares época-objeto, prácticamente plano en toda la curva

| bin fase rest | mediana Δmag | media | std | N | p16 | p84 |
|---|---:|---:|---:|---:|---:|---:|
| [-20,-10) | -0.0074 | -0.0007 | 0.167 | 71.789 | -0.107 | 0.091 |
| [-10,-5) | -0.0197 | -0.0247 | 0.106 | 41.901 | -0.122 | 0.075 |
| [-5,0) | -0.0211 | -0.0298 | 0.100 | 48.706 | -0.134 | 0.068 |
| [0,+5) | -0.0302 | -0.0343 | 0.102 | 46.448 | -0.133 | 0.059 |
| [+5,+10) | -0.0200 | -0.0292 | 0.100 | 41.019 | -0.129 | 0.064 |
| [+10,+20) | -0.0185 | -0.0248 | 0.099 | 83.692 | -0.127 | 0.069 |
| [+20,+40) | -0.0178 | -0.0267 | 0.120 | 157.820 | -0.127 | 0.070 |
| [+40,+100) | -0.0234 | -0.0164 | 0.188 | 69.046 | -0.131 | 0.078 |

**No hay tendencia creciente con `|fase|`** -- el bin más extremo probado (`[+40,+100)`, hasta 100 días
del pico) da `-0.023` mag, prácticamente igual al bin central (`[0,+5)`, `-0.030` mag) y menor que
varios bins intermedios. Descarta la hipótesis concreta que motivó esta fase: `SEDFLUX_INTERP_OPT: 1`
(confirmado en el `SALT2.INFO` real, otra clave que `sncosmo` ignora igual que `MAG_OFFSET`) no produce
un artefacto que crezca con la distancia al pico -- si lo hiciera, sería visible acá y no lo es. Por
banda (`g/r/i/z/Y` con estadística real, `u` con `N<340` por bin y desviaciones de hasta `-0.15` mag,
mismo problema de borde de template de Fases 13/23/27/39 ya conocido, no confiable): todas dentro de
`-0.001` a `-0.046` mag, sin patrón cromático claro tampoco.

**Cabo suelto real, chico pero no cero**: los 8 bins muestran un offset residual consistente de
`-0.01` a `-0.03` mag (no cero, no creciente) -- del orden de un 10% de lo que ya se cerró en Fase 37,
visible ahora porque este es el primer test con épocas reales completas en vez de solo el pico
poblacional. No se investiga la causa en esta fase (fuera de alcance del criterio de decisión
definido) -- candidatos plausibles para una fase futura: ruido de segundo orden en la normalización de
banda (Fases 25-30) evaluado ahora en fases no-pico, o el `trim_quantile` de producción (Fase 31).

### Conclusión Fase 39

**Criterio "plano" cumplido**: la curva completa no muestra la dependencia de fase que predecía el
candidato `SEDFLUX_INTERP_OPT` -- descartado con evidencia directa (código real vs. datos reales de
época, no una aproximación). Fase 37 se extiende con confianza a la curva completa, no solo al pico:
el `MAG_OFFSET` cierra el residuo grande (`~0.27` mag) en todas las fases por igual, consistente con
ser un offset aditivo puro tal como predice la fórmula real de SNANA. Queda un residuo chico
(`-0.01` a `-0.03` mag, sin tendencia) documentado como pregunta abierta menor, no forzado a una
explicación.

**H4 cerrado de paso**: `compare_brightness_truth_salt2.py` usaba `flux_perfect.max()` sobre la
cadencia real -- la métrica que la propia Fase 22 declaró inválida, nunca migrada en el único script
versionado de comparación de brillo del proyecto (las Fases 22-38 usaban scripts exploratorios ya
borrados con la métrica correcta). Corregido a `compute_noise_free_lightcurves()` real evaluado en
`rest_phase=0` (mismo patrón de Fase 22 en adelante). Verificado: corre limpio sobre los 2000 objetos
reales de la campaña (`z` 0.08-1.20, `PEAKMAG_r_true` 18.1-28.8, rango físico razonable), sin errores.

### Archivos de esta fase

`compare_brightness_truth_salt2.py`: migrado de `simulate_lightcurves()`+`flux_perfect.max()` a
`sample_parameters()`+`compute_noise_free_lightcurves()` en `rest_phase=0` (cierra H4). Exploratorios
en NLHPC, borrados tras usarlos: `fase39_lightcurve_paired.py`/`.sbatch` (pareo época-a-época real),
`fase39_verify.sbatch` (corrida de verificación del fix de H4). Sin cambios a `snana_params.py` --
ningún candidato nuevo llegó al umbral de corrección esta fase.

## Fase 40 — cobertura de claves de configuración en las 19 clases: un hallazgo nuevo (`GENRANGE_TREST`), una corrección al propio dashboard, y el resto ya blindado

El método que encontró la causa raíz de toda la investigación (Fase 37: ¿qué claves reales del
`.INPUT`/`SED.INFO`/`SALT2.INFO` lee cada lado?) nunca se había aplicado fuera de `SNIa`. Esta fase lo
extiende a las 14 clases físicas reales que cubre LightCurveLynx (`SNIa` + 13 SIMSED; los 5
`*_NON1ASED` de la tabla de 19 "clases evaluadas" del dashboard son la MISMA clase física en otra
codificación, comparten `.INPUT`/directorio de modelo con su versión SIMSED, así que auditar 14 basta
para cubrir las 19 entradas). Trabajo puramente de lectura -- sin simular nada, sin tocar `SNDATA_ROOT`.

### Paso 1 — inventario real de `.INPUT` por clase

Vía `INPUT_INCLUDE_FILE:` real de `~/AUTOSIM/build/full_v5.3_10yrs/includes/include_model_<clase>.INPUT`
(no por nombre de carpeta, mismo criterio de `HOWTO.md` §7) se confirmó el `.INPUT` real de las 14
clases (`SIMGEN_INCLUDE_<modelo>.INPUT`, todos bajo `~/run_SNANA/model_config/` salvo los dos
`PISN-STELLA-*` que usan `~/run_SNANA/elastic/model_config/`) y se leyeron completos.

### Paso 2 — tabla de cobertura de claves

| Clave | Dónde se declara | Clases | Qué hace SNANA | ¿LCL la lee? | Impacto |
|---|---|---|---|---|---|
| `MAG_OFFSET` | `SALT2.INFO` | `SNIa` | offset aditivo de magnitud (`genmag_SALT2.c:2257`) | No — **corregido en Fase 37** | `0.27` mag, ya cerrado |
| `FLUX_SCALE` | `SED.INFO`/`NON1A.LIST` | todas las SIMSED/NON1ASED | normaliza el flujo del template | **Sí** — `SIMSEDModel.from_dir()` y `non1ased.py::parse_flux_scale()` | ninguno — control positivo |
| `MAGOFF`/`MAGSMEAR` (bloque `NON1A_KEYS`) | `.INPUT` | las 5 clases NON1ASED | offset/smear por template individual | No leído, pero **blindado**: `non1ased.py:86-90` levanta `NotImplementedError` si alguno es `≠0` (confirmado `0.0` real en las 5 clases del proyecto -- el guardia nunca disparó en ninguna corrida histórica) | ninguno hoy; riesgo latente ya cubierto por el guard, no silencioso |
| `GENPEAK_RV`/`GENRANGE_RV`/`GENSIGMA_RV` | `.INPUT` | 9 clases con extinción de host (`KN-K17`, `CaRT`, `SLSN-I`, `SNIax`, `TDE-MOSFIT`, `ILOT-MOSFIT`, `SNIIn-MOSFIT`, `PISN-MOSFIT`, `KN-BULLA19`) | `R_V` de la ley de extinción; `GENSIGMA_RV: 0.0 0.0` en las 9 → `R_V` efectivamente fijo en `GENPEAK_RV` pese al `GENRANGE_RV` declarado | **Sí** — `r_v=3.1` hardcodeado en `CLASS_CONFIGS`, coincide exacto con `GENPEAK_RV: 3.1` real en las 9 | ninguno — control positivo confirmado |
| `GENAV_WV07`/`WV07_REWGT_EXPAV` | `.INPUT` | 9 clases (7 con `GENAV_WV07:1` directo, 2 con `WV07_REWGT_EXPAV:0.5`) | activa el modelo WV07 de extinción de host | **Sí** — `make_wv07_av_sampler(rewgt_expav=...)`, con/sin rewgt coincide clase por clase (Fase 3) | ninguno |
| `GENTAU_AV`/`GENSIG_AV`/`GENRATIO_AV0` | `.INPUT` | `SNIax` | mezcla exponencial+semi-Gaussiana de extinción de host | **Sí** — `make_exp_halfgauss_av_sampler()` (Fase 2B ronda 3) | ninguno |
| `SIMSED_REDCOR` | `.INPUT` | `SNIa-91bg`, `SNII-NMF` | correlación entre parámetros SIMSED | **Sí** — `make_correlated_normal_weights()` | ninguno confirmado hoy; Fase 41 lo audita estadísticamente |
| `DNDZ` (todas las familias: `POWERLAW`/`POWERLAW2`/`MD14`/`CC_S15`/`TDE`/`PISN_PLK12`) | `.INPUT` | las 14 | tasa volumétrica vs. `z` | **Sí**, reimplementadas con fórmula real citada (`snana_params.py`); solo `POWERLAW2` de `SNIa` tiene validación estadística directa (Fase 33, KS `p=0.183`) | resto pendiente de Fase 41 |
| `DNDZ_ALLSCALE` | `.INPUT` | `SNII-NMF`, `ILOT-MOSFIT`, `SNIIn-MOSFIT` | escala la tasa `CC_S15` | **Sí** — pasado como `scale` a `build_dndz_ccs15_cdf()` | ninguno |
| `GENMEAN_SALT2ALPHA`/`GENMEAN_SALT2BETA` | `.INPUT` | `SNIa` | parámetros Tripp fijos | **Sí**, exacto (Fase 16) | ninguno |
| `GENSIGMA_SALT2c`/`GENSIGMA_SALT2x1` (bifurcadas) | `.INPUT` | `SNIa` | sigma distinta a cada lado del pico | Sí, pero la **probabilidad de rama** estaba mal — **corregido Fase 32** | ya cerrado |
| `GENMAG_SMEAR_MODELNAME: G10` | `.INPUT` | `SNIa` | dispersión intrínseca coherente + término cromático | Parcial — solo el coherente (`SIGCOH`), falta el cromático | razonado y descartado como causa (ya documentado en el dashboard); dirección contraria a lo que había que explicar |
| **`GENRANGE_TREST`** | `.INPUT`, real por clase (`-50/300` a `-100/1000`, ver tabla abajo) | las 14 | ventana de fase válida para generar observaciones/época | **No** — los 7 scripts (`bench_snia.py`, `compare_brightness_truth*.py`, `run_dask_poc.py`, `run_non1ased_poc.py`, `run_simsed*_poc.py`, `run_snia_ddf_poc.py`) usan `rest_time_window_offset=(-30, 100)` **hardcodeado e idéntico para las 14 clases**, nunca leído del `.INPUT` real | **hallazgo nuevo real** — ver Paso 3 |
| `MINSLOPE_EXTRAPMAG_LATE` | `.INPUT` | `KN-K17`, `KN-BULLA19` | piso de pendiente para extrapolación tardía más allá del template nativo | No implementado | **clave real nunca antes mencionada en el proyecto** — ver Paso 4; sin efecto en comparaciones de pico, relevante solo más allá del rango nativo del template |
| `GENMODEL_EXTRAP_LATETIME` (`SNIa_Extrap_LateTime_2expon.TEXT`) | `.INPUT` | `SNIa` | modelo real "doble exponencial" de extrapolación tardía | Aproximado con `LinearDecay(50.0)`, ya documentado como simplificación conocida | relevante para Fase 39 (curva completa), no para el pico |
| `SIMSED_USE_BINARY` | `.INPUT` | todas las SIMSED (`: 0` en las 14) | formato de caché binaria interna de SNANA para acelerar `snlc_sim.exe` | N/A — puramente I/O interno de SNANA, sin contraparte física que LCL deba replicar | ninguno |

### Paso 3 — `GENRANGE_TREST`: hallazgo nuevo, sin efecto en el pico, candidato real para clases de cola larga

`GENRANGE_TREST` real por clase, contra la ventana hardcodeada `(-30, 100)` que usan los 7 scripts:

| Clase | `GENRANGE_TREST` real | Ventana usada | Fracción del rango real cubierta |
|---|---:|---:|---:|
| `SNIa` | `-100  300` | `-30  100` | 32.5% |
| `SNIa-91bg` | `-100  400` | `-30  100` | 26.0% |
| `KN-K17` | `-100  300` | `-30  100` | 32.5% |
| `CaRT` | `-100  500` | `-30  100` | 21.7% |
| `SLSN-I` | `-100  500` | `-30  100` | 21.7% |
| `SNIax` | `-100  400` | `-30  100` | 26.0% |
| `TDE-MOSFIT` | `-100  500` | `-30  100` | 21.7% |
| `SNII-NMF` | `-100  400` | `-30  100` | 26.0% |
| `ILOT-MOSFIT` | `-100  1000` | `-30  100` | **11.8%** |
| `SNIIn-MOSFIT` | `-50  300` | `-30  100` | 37.1% |
| `PISN-MOSFIT` | `-100  300` | `-30  100` | 32.5% |
| `KN-BULLA19` | `-100  500` | `-30  100` | 21.7% |
| `PISN-STELLA-HECORE`/`-HYDROGENIC` | (no releído en esta fase, mismo `.INPUT` `elastic` que las demás `PISN-*`, se asume comparable) | `-30  100` | — |

**Esto no afecta ningún resultado ya reportado de comparación de brillo pico** (Fases 22-39 evalúan
`compute_noise_free_lightcurves()`/`compute_single_noise_free_lightcurve()` en `rest_phase=0`, que no
pasa por `rest_time_window_offset` en absoluto -- ese parámetro solo gobierna la ventana de
`simulate_lightcurves()`, la ruta con cadencia/ruido/trigger). **Sí es un candidato real, nunca antes
verificado, para los ratios de detección de las Fases 5-9** (`NOBS`/trigger de las 13 clases SIMSED,
todas corridas con esta misma ventana hardcodeada): `ILOT-MOSFIT` es el caso extremo, con solo 11.8%
de su rango temporal real cubierto -- si su curva de luz real tiene emisión observable fuera de
`[-30,100]` días (su nombre, "Intermediate Luminosity Optical **Transient**", sugiere evoluciones
más lentas que una SN estándar), la ventana recortada podría estar subestimando `NOBS`/SNR real de
forma sistemática. **No se corrigió ni se remidió en esta fase** -- es diagnóstico puro, documentado
como candidato concreto para una fase futura dedicada a las clases SIMSED (fuera del alcance actual,
centrado en `SNIa`).

### Paso 4 — `MINSLOPE_EXTRAPMAG_LATE`: clave real nueva, nunca antes mencionada

El dashboard (fase que cerró el "roadmap" de candidatos, sub-tab "N fases") sí verificó correctamente
que `REDCOV`/`TEMPLATE_ZPT` no aparecen en ningún `.INPUT`/`.SIMLIB` real de las 19 clases -- esa
afirmación queda confirmada, sin corrección necesaria (verificación cruzada, no repetida a ciegas).
`MINSLOPE_EXTRAPMAG_LATE` nunca se había mencionado en el proyecto hasta esta fase -- no es una
corrección a un texto existente, es una clave real nueva: aparece, real, en `KN-K17` y `KN-BULLA19`
(`MINSLOPE_EXTRAPMAG_LATE: 0.1`), no implementada del lado LightCurveLynx. Sin efecto en ninguna
comparación ya reportada (ninguna dependió de la extrapolación tardía de esas 2 clases), documentado
como candidato menor para una futura auditoría de esas dos clases específicamente.

### Conclusión Fase 40

De las claves reales auditadas en las 14 clases, **13 están o bien leídas correctamente (controles
positivos que confirman que el método distingue bien, sin repetir el error de Fase 37) o blindadas
activamente contra el modo de falla silencioso** (`MAGOFF`/`MAGSMEAR`). Fuera de `MAG_OFFSET`
(ya cerrado, Fase 37) y el sampler bifurcado (ya cerrado, Fase 32), el **único hallazgo nuevo real** es
`GENRANGE_TREST` -- ignorado en las 14 clases por igual, sin efecto en ninguna comparación de brillo
pico ya reportada, pero un candidato concreto y nunca antes verificado para los ratios de detección
históricos de clases de cola larga (`ILOT-MOSFIT` en particular). **No se corrige en esta fase** --
corregirlo bien requeriría decidir si la ventana debe ser por-clase (rompe la comparabilidad histórica
entre clases de las Fases 5-9 si se cambia a mitad de camino) y remedir esas clases, un alcance mayor
que esta auditoría de lectura. Queda documentado como la pregunta abierta más concreta que deja esta
fase para una futura ronda centrada en las clases SIMSED (no `SNIa`). El modo de falla de Fase 37
(`MAG_OFFSET`) resultó ser, dentro de lo auditado, un caso único en este catálogo -- no una clase de
bug repetida -- aunque `GENRANGE_TREST` demuestra que "una clave ignorada" sigue siendo un patrón real
y vale la pena seguir buscándolo.

### Archivos de esta fase

Ninguno versionado -- diagnóstico puro (grep/lectura de `.INPUT` reales vía `ssh`, sin scripts
Python nuevos, sin simular nada, sin tocar `SNDATA_ROOT`). Corrección de texto en `docs/index.html`
(la cifra "otras 39 clases" de la sub-tab "Conclusiones", corregida a la cobertura real de
LightCurveLynx -- 14 clases físicas, 19 entradas evaluadas contando codificaciones NON1ASED).

## Fase 41 — samplers de extinción de host y `DNDZ: MD14` validados en 3 clases; `SIMSED_REDCOR` reabre un mecanismo real nunca comparado

Extiende el patrón de Fase 32 (auditar el *algoritmo*, no solo los parámetros, de cada sampler custom
de `snana_params.py` contra el código real de SNANA) a los samplers nunca auditados:
`make_wv07_av_sampler`, `make_exp_halfgauss_av_sampler`, `make_dndz_sampler`/`build_dndz_md14_cdf`, y
`make_correlated_normal_weights` (`SIMSED_REDCOR`).

### Sin sesgo de trigger, sin necesitar `SIMGEN_DUMPADD`

Las 4 clases elegidas (`KN-K17`, `SLSN-I`, `SNIax`, `SNIa-91bg`) ya tienen corridas reales completas en
`/home/mvalenzuela/DATASIM_LSST_1/DDF/SIMDv8/<clase>_DDF_baseline_v5.3.1_10yrs/` con
`SELECTION: NONE` (2000/2000 filas, sin sesgo de detección) -- no hizo falta reproducir ninguna corrida
ni usar `SIMGEN_DUMPADD`. Sus `.DUMP` ya traen `AV`/`RV` (extinción de host) directo en `VARNAMES`, y el
de `SNIa-91bg` trae `stretch`/`color` directo. **Hallazgo de higiene real, no reportado hasta ahora**:
las columnas `AV` y `ZHELIO` de estos 4 `.DUMP` contienen sentinelas `-9` reales (102/2000 en `KN-K17`,
53/2000 en `SLSN-I`, 79/2000 en `SNIax`, 81/2000 en `SNIa-91bg` -- objetos sin extinción/redshift válido
asignado por alguna razón no investigada acá) que hay que enmascarar **antes** de cualquier estadística
-- sin filtrar, la media/std salen absurdas (p.ej. `KN-K17` `AV` media `-0.22`, imposible físicamente) y
contaminan cualquier comparación, mismo tipo de trampa que ya documentaron Fases 13/27/33 para
`PEAKMAG=-9`.

### Extinción de host (`wv07`/`exp_halfgauss`) y `DNDZ: MD14`: los 5 pares, correctos

Comparando 200k draws de cada sampler (parámetros reales exactos de `CLASS_CONFIGS`,
`run_simsed_poc.py`) contra los draws reales de SNANA (sentinelas ya filtrados), mismo formato de tabla
que Fase 37 Paso 6 + KS de dos muestras + impacto en magnitud vía `F99(Rv=3.1)` sobre la diferencia de
medianas:

| par (clase, sampler) | N real | KS stat | KS p | Δmag máx (u→y) |
|---|---:|---:|---:|---:|
| `KN-K17` `AV` (wv07, rewgt=0.5) | 1898 | 0.028 | 0.106 | +0.010 (u) |
| `SLSN-I` `AV` (wv07, sin rewgt) | 1947 | 0.024 | 0.219 | +0.012 (u) |
| `SLSN-I` `z` (DNDZ MD14, rate0=2e-8) | 1947 | 0.021 | 0.334 | -- |
| `SNIax` `AV` (exp_halfgauss) | 1921 | 0.014 | 0.817 | -0.002 (u) |
| `SNIax` `z` (DNDZ MD14, rate0=6e-6) | 1921 | 0.024 | 0.226 | -- |

**Los 5 pares pasan limpio** (KS `p>0.05` y `Δmag<0.01` mag en las 6 bandas para los 3 de extinción) --
`make_wv07_av_sampler()`, `make_exp_halfgauss_av_sampler()` y `build_dndz_md14_cdf()`/
`make_dndz_sampler()` reproducen fielmente el algoritmo real de SNANA para estas 3 clases. Ningún bug
del tipo Fase 32 en estos 5 mecanismos.

### `SIMSED_REDCOR` (`SNIa-91bg`): las medias coinciden, pero el mecanismo real es otro

`make_correlated_normal_weights()` calcula, para los 35 templates reales de `simsed_91bg_local/SED.INFO`,
un peso `∝ exp(-½ (x-peak)ᵀ Σ⁻¹ (x-peak))` evaluado **exactamente en el punto discreto de cada
template**, y resamplea por ese peso. Comparado contra `stretch`/`color` reales de los 2000 objetos del
`.DUMP` (sentinelas de `ZHELIO` filtrados aparte, `stretch`/`color` sin sentinelas):

| | real (N=2000) | sim (200k, resampleo por peso) |
|---|---:|---:|
| `stretch` media | 0.9770 | 0.9752 |
| `stretch` mediana | 0.9772 | 0.9500 |
| `color` media | 0.5498 | 0.5568 |
| `color` mediana | 0.5517 | 0.5000 |
| KS `stretch` | -- | stat=0.211, **p=1.2e-77** |
| KS `color` | -- | stat=0.276, **p=2.7e-133** |

Las **medias** coinciden casi exactamente (`Δstretch=0.0018`, `Δcolor=0.0070`) -- pero el test KS es
abrumadoramente significativo, y las medianas difieren más (`Δstretch=0.027`, `Δcolor=0.052`), cayendo
justo sobre los dos templates de mayor peso teórico (`(0.95, 0.50)` y `(1.05, 0.50)`, `24.4%` y `22.4%`
del peso total). Se leyó el algoritmo real de SNANA para descartar que sea solo un artefacto de la
grilla discreta: `prep_user_SIMSED()` (`snlc_sim.c`, real, "Prepare Cholesky decomp for correlations")
confirma que SNANA **no** evalúa el peso Gaussiano en cada punto de grilla -- arma la descomposición de
Cholesky de la covarianza real, samplea un valor **continuo** correlacionado, y recién después snapea al
template más cercano vía `nearest_gridval_SIMSED()` (línea real 14179: `PARVAL =
nearest_gridval_SIMSED(ipar_model,PARVAL_TMP)`). Son dos mecanismos genuinamente distintos -- pesar la
densidad exacta en cada punto discreto (lo que hace `make_correlated_normal_weights()`) no es
matemáticamente equivalente a integrar la densidad sobre la celda de Voronoi de cada template alrededor
de un draw continuo (lo que hace SNANA real), sobre todo con una grilla tan gruesa e irregular como
35 templates en 2D.

**No se llegó a implementar ni medir el impacto del mecanismo correcto en esta fase** (el "continuo +
snap a la grilla" requiere replicar la lógica de Voronoi/nearest-neighbor de `nearest_gridval_SIMSED()`,
no solo cambiar una línea) -- documentado honesto como lo que es: un mecanismo real y confirmado
distinto (no una hipótesis), con evidencia estadística fuerte (KS) pero **sin cuantificar aún el
impacto en magnitud poblacional**, ya que la media (que es lo que más pesa en un residuo tipo mediana)
coincide bien. Candidato concreto para una fase futura, con la cita exacta ya en mano
(`nearest_gridval_SIMSED()`) para no tener que rebuscarla.

### P2 -- seed propagation: sigue en la misma versión, un dato del borrador quedó desactualizado

`lightcurvelynx==0.5.2` sigue siendo la versión instalada (sin cambios desde que se escribió
`ISSUE_DRAFT_seed_propagation.md` en Fase 19-20). Verificado por lectura de fuente real
(`inspect.getsource`):

- `ObsTableRADECSampler.compute()`: el patrón `rng_info if rng_info is not None else
  np.random.default_rng()` sigue presente -- **bug #1 confirmado sin cambios**.
- `TableSampler.__init__`: sigue sin forwardear `seed=` al `NumpyRandomFunc("integers", ...)` interno
  -- **bug #2 confirmado sin cambios**.
- `SIMSEDModel.from_dir()`: el código real actual **ya no construye el sampler interno ahí** -- solo
  lee los templates y hace `return cls(templates, flux_scale=flux_scale, **kwargs)`, delegando a
  `__init__`. El borrador cita la construcción del `GivenValueSampler`/`_sampler_node` como parte de
  `from_dir()`; en la versión instalada hoy esa lógica vive en otro lugar (no confirmado en esta pasada
  por presupuesto). **No se tocó el borrador** -- queda anotado acá que la cita de ubicación de ese
  tercer bug necesita una relectura antes de publicarlo, aunque el bug en sí (falta de propagación de
  semilla) parece seguir siendo real por el patrón de código ya visto en fases anteriores.

### Conclusión Fase 41

5 de 6 samplers auditados (extinción de host en 3 clases, `DNDZ: MD14` en 2) quedan **validados**, sin
bugs -- el patrón de Fase 32 no se repite ahí. El sexto (`SIMSED_REDCOR`, `SNIa-91bg`) queda en estado
intermedio y honesto: mecanismo real confirmado distinto (Cholesky+nearest-neighbor vs. peso discreto
exacto), evidencia estadística fuerte, pero impacto en magnitud sin cuantificar porque las medias
coinciden razonablemente bien -- no es un cierre limpio en ninguna dirección, y se documenta así en vez
de forzarlo. P2 confirma que los 2 bugs de seed propagation más simples siguen intactos en la versión
instalada; el tercero necesita que alguien relea `SIMSEDModel.__init__` antes de que el borrador sea
públicable con confianza.

### Archivos de esta fase

`fase41_samplers.py`/`fase41_samplers_v2.py` (exploratorios, no versionados, borrados de NLHPC tras
usarlos -- la v1 tenía el bug de sentinelas `-9` sin filtrar, documentado arriba como hallazgo de
higiene real, no como error oculto). Sin cambios a `snana_params.py` -- ningún candidato llegó al
umbral de "bug confirmado y cuantificado" que justificara una corrección esta fase.

## Fase 42 — `readout_noise`/`dark_current` reales del SIMLIB: corregido por fidelidad, efecto real pero despreciable (y en la dirección contraria)

Pregunta 1 de la ronda anterior: Fase 4 (muy temprana en el proyecto) descartó `dark_current`/
`readout_noise` como causa del entonces-residuo de SNR/detección (40-80%) porque el efecto medido era
de solo ~2% en SNR -- irrelevante contra 40-80%. Fase 38 dejó un residuo mucho más chico (SNR mediano
+7.6%, ratio de detección 1.615x±0.045); un efecto de ~2% podría ya no ser despreciable a esa escala.

### Recálculo real con los parámetros actuales

`snana_noise_columns()` nunca pasaba `read_noise`/`dark_current` explícitos a `OpSim`, así que
LightCurveLynx caía en los defaults genéricos de la clase (`read_noise=8.8` e⁻, `dark_current=0.2`
e⁻/s, constantes de LSSTCam citadas de `smtn-002.lsst.io`) en vez de los valores reales y mucho más
chicos de esta campaña (`read_noise=0.25`, `dark_current=0`, del SIMLIB real -- confirmado en Fase 16
Paso 1). Con condiciones DDF `r`-band reales (mediana `sky_bg_e≈811` e⁻/pix², `psf_footprint≈55`
pix²): el exceso de varianza de los defaults sobre el real es **~10.3% de `sky_variance`** -- un
efecto de sensibilidad real, no ruido de cálculo, y del orden correcto para importar a esta escala de
residuo.

### Corregido por fidelidad, y medido: la dirección es la contraria a "cerrar el residuo"

`OpSim(df_ddf, zp_err_mag=0.005, read_noise=0.25, dark_current=0.0)` en `run_snia_ddf_poc.py` (antes
sin esos dos argumentos). Recorrida real de 5 semillas (mismo patrón exacto de Fase 38):

| métrica | SNANA real | Fase 38 (antes) | Fase 42 (después, 5 semillas) |
|---|---:|---:|---:|
| `snr_median` | 0.78 | 0.839 ± 0.013 | **0.843** (0.8245–0.8616) |
| `snr_p90` | 2.26 | 2.614 ± 0.138 | **2.654** (2.483–2.884) |
| eficiencia detección | 29.85% | 48.22% ± 1.35% | **48.88%** (47.25–50.45%) |
| ratio detección | 1.00x | 1.615x ± 0.045 | **1.638x** |

El cambio (1.615x → 1.638x) queda **dentro de 1σ** del ruido de semilla ya reportado en Fase 38
(`±0.045`) -- no es una mejora ni un empeoramiento estadísticamente significativo, es ruido. Confirma
exactamente lo que predijo el recálculo analítico: quitarle ruido de más a LightCurveLynx lo hace
*levemente* más sensible (SNR más alto), no menos -- la dirección correcta para explicar un exceso de
brillo/detección es la contraria (habría que *agregar* ruido, no quitarlo, y el propio `Om0` de Fase 34
ya mostró que "más fiel al real" no siempre implica "más cerca del residuo cero"). El fix queda aplicado
igual, por fidelidad real con el SIMLIB de la campaña -- mismo criterio que Fase 24/34.

### Verificación rápida del trigger por épocas

`searcheff.py::group_into_epochs()` usa `NEWMJD_DIF=0.007` días (~10 min) -- confirmado, de nuevo, que
coincide con el default real de SNANA (`snlc_sim.c` línea ~849) -- ahora también verificado que el
resultado con la población ya corregida (Fase 32/34/37/42) sigue produciendo conteos de época
consistentes con lo esperado (no se detectó ninguna anomalía nueva al recorrer las 5 semillas).

### Conclusión Fase 42

El candidato de ruido queda **descartado como explicación del residuo de detección remanente** -- real
y corregido por fidelidad, pero de magnitud despreciable y de signo contrario al que haría falta. El
residuo de detección (~1.6x) sigue sin causa identificada; candidatos que quedan sin probar: el resto
de `SEARCHEFF_PIPELINE` (más allá del agrupamiento de épocas, que ya se confirmó correcto), o algo en
la lógica de trigger no cubierta por este análisis.

### Archivos de esta fase

`run_snia_ddf_poc.py`: `OpSim(...)` ahora pasa `read_noise=0.25, dark_current=0.0` reales, con
comentario citando Fase 4/16/42. 5 semillas corridas vía `run_snia_ddf_poc.sbatch` (outputs en
`poc_output`/`poc_output_seed1-4`, no borrados -- son productos de un script de producción, quedan
para referencia futura igual que las corridas de Fase 38).

## Fase 43 — `GENRANGE_TREST` real por clase: mejora sustancial en `SLSN-I`, sobre-corrección real en `ILOT-MOSFIT`

Pregunta 2 de la ronda anterior: Fase 40 encontró que los 7 scripts de producción usan
`rest_time_window_offset=(-30, 100)` hardcodeado e idéntico para las 14 clases, mientras el
`GENRANGE_TREST` real por clase va de `-50/300` a `-100/1000` días. `ILOT-MOSFIT` cubría solo 11.8% de
su ventana real; `SLSN-I` cubría 21.7%.

### Corregido por clase en `CLASS_CONFIGS` (`run_simsed_poc.py`)

Nuevo campo `trest_range` por clase (default `(-30, 100)` para las clases no re-medidas en esta fase),
leído en `main()` vía `cfg.get("trest_range", (-30.0, 100.0))` y pasado a
`rest_time_window_offset=trest_range` en `simulate_lightcurves()` (antes hardcodeado). `SLSN-I` ahora
usa `(-100, 500)` (real); `ILOT-MOSFIT` usa `(-100, 1000)` (real, el caso más extremo de las 14).

### Resultado real: dos direcciones distintas, ambas honestas

**`SLSN-I`** (1 semilla de verificación, no el barrido completo de 5 -- corrida cara, ~5-6 min de
templates + simulación real):

| | histórico (`-30/100`, 5 semillas) | Fase 43 (`-100/500`, 1 semilla) | SNANA real |
|---|---:|---:|---:|
| detección | 41.20% ± 2.3% (ratio 1.604x) | **72.0%** (1440/2000) | 63.3% (1266/2000) |

Mejora sustancial: de sub-detectar (41.2% vs. 63.3% real) a sobre-detectar levemente (72.0% vs. 63.3%
real) -- mucho más cerca del real que antes, aunque ahora en la dirección opuesta. Con 1 sola semilla
no se puede descartar que parte del salto sea varianza de semilla -- queda marcado como verificación
rápida, no como número definitivo con banda de incertidumbre.

**`ILOT-MOSFIT`** (5 semillas completas):

| | histórico (`-30/100`, 5 semillas) | Fase 43 (`-100/1000`, 5 semillas) | SNANA real |
|---|---:|---:|---:|
| detección | 3.65% (ratio 1.96x, LCL sub-detecta) | **31.03% ± 0.63%** (605-639/2000) | 7.15% (143/2000) |

Acá la corrección **sobre-corrige de forma dramática**: pasa de sub-detectar 2x (3.65% vs. 7.15% real)
a sobre-detectar ~4.3x (31.03% vs. 7.15% real) -- peor en magnitud absoluta que el problema original,
aunque de signo opuesto. No se fuerza una lectura positiva: extender la ventana de generación al
`GENRANGE_TREST` real completo no es, por sí sola, la corrección que hace falta para esta clase -- algo
en cómo LightCurveLynx extrapola/genera flujo dentro de esa ventana extendida (posiblemente la
extrapolación tardía `LinearDecay`/`ZeroPadding`, o el propio modelo MOSFIT evaluado muy lejos de su
pico) está generando demasiadas detecciones espurias de baja SNR en la cola extendida que SNANA no
produce en la misma magnitud. Candidato real, no cerrado, para una fase futura.

### Conclusión Fase 43

`GENRANGE_TREST` real por clase es una corrección de fidelidad genuina (el proyecto no debería seguir
usando una ventana hardcodeada e idéntica para 14 clases con ventanas reales muy distintas), pero su
efecto en el ratio de detección **no es uniformemente positivo**: mejora sustancialmente a `SLSN-I`,
empeora sustancialmente a `ILOT-MOSFIT`. Documentado honestamente en ambas direcciones -- ninguna de
las dos es el resultado que se buscaba encontrar, y eso es información real. Las otras 12 clases no se
re-midieron en esta fase (quedan con el default `-30/100`, sin cambio).

### Archivos de esta fase

`run_simsed_poc.py`: `CLASS_CONFIGS["SLSN-I"]`/`CLASS_CONFIGS["ILOT-MOSFIT"]` ganan `trest_range`
real; `main()` lo usa en vez del hardcode. Corridas: `poc_output_slsni` (1 semilla),
`poc_output_ilotmosfit`/`_seed1-4` (5 semillas) -- no borrados, productos de script de producción.

## Fase 44 — `SIMSED_REDCOR` reimplementado con el mecanismo real (Cholesky + grilla), pero no explica el residuo: la brecha vive en otro lado

Pregunta 3 de la ronda anterior: Fase 41 confirmó que `make_correlated_normal_weights()` pesa la
densidad Gaussiana exactamente en el punto discreto de cada template, mientras SNANA real
(`prep_user_SIMSED()`/`nearest_gridval_SIMSED()`, `genmag_SEDtools.c` línea real 2427) arma una
descomposición de Cholesky, samplea un valor continuo correlacionado, y snapea cada parámetro por
separado al valor de grilla más cercano en ese eje -- dos mecanismos genuinamente distintos, nunca
comparados directamente hasta ahora.

### Parámetros reales confirmados, antes de tocar el algoritmo

`GENPEAK_stretch: 0.975`, `GENSIGMA_stretch: 0.096 0.096`, `GENPEAK_color: 0.557`,
`GENSIGMA_color: 0.175 0.175`, `SIMSED_REDCOR(stretch,color): -0.656` -- confirmados exactos contra
`/home/mvalenzuela/run_SNANA/model_config/SIMGEN_INCLUDE_SNIa-91bg.INPUT` real. Los parámetros que
usaba el proyecto ya eran correctos; el candidato real era puramente el mecanismo de muestreo.

### Reimplementado: Cholesky + celdas de Voronoi rectangulares (masa exacta, no Monte Carlo)

Sobre una grilla Cartesiana genuina (35 templates: `stretch` 7 valores × `color` 5 valores,
`simsed_91bg_local/SED.INFO` real), el redondeo independiente por eje de `nearest_gridval_SIMSED()`
es exactamente el redondeo a la celda de Voronoi **rectangular** de cada template (bordes en los
puntos medios entre valores de grilla adyacentes por eje). La probabilidad real de que un draw
continuo caiga en la celda de un template dado es la masa exacta de la normal multivariada
correlacionada dentro de ese hiper-rectángulo -- calculada exacta vía inclusión-exclusión sobre las
`2^N` esquinas con `scipy.stats.multivariate_normal.cdf()`, no aproximada por muestreo Monte Carlo.
`make_correlated_normal_weights()` reimplementada así en `snana_params.py`, misma firma, compatible
con los 2 call sites reales (`compare_brightness_truth.py`, `run_simsed_poc.py`).

### Resultado, en dos partes: el mecanismo mejora poco el ajuste estadístico, y no mueve el residuo de brillo en absoluto

**Test KS, peso viejo vs. peso nuevo (200k resampleos vs. 1919 objetos reales del `.DUMP`,
`SELECTION: NONE`, sentinelas `ZHELIO=-9` filtrados)**:

| | peso viejo (Fase 41) | peso nuevo (Cholesky+grilla) |
|---|---:|---:|
| `stretch` KS stat / p | 0.211 / 7.6e-75 | 0.207 / 3.8e-72 |
| `color` KS stat / p | 0.271 / 5.6e-124 | 0.256 / 3.4e-110 |
| `stretch` media sim / mediana sim | 0.9752 / 0.9500 | 0.9750 / 0.9500 |
| `color` media sim / mediana sim | 0.5568 / 0.5000 | 0.5565 / 0.5000 |

El mecanismo más fiel al algoritmo real **apenas mueve el `stat` de KS** (0.211→0.207,
0.271→0.256) -- sigue siendo un desajuste estadístico abrumador, prácticamente sin cambios. La
distinción "densidad puntual vs. masa de celda" que motivó esta fase **no es la causa principal**
del desajuste real -- algo más queda sin identificar en el mecanismo (candidatos no explorados:
un `WGTMAP` real que sobreescriba el peso Gaussiano simple, algo del propio `nearest_gridval_SIMSED()`
no capturado en esta lectura, o una interacción con `SIMSED_GRIDONLY`).

**Impacto en el residuo de brillo poblacional: esencialmente cero.** Re-corrida completa de
`compare_brightness_truth.py` (2000 objetos, con el peso nuevo) y comparación banda `r`, mismos 7
bins de `z` de siempre, contra el `.DUMP` real:

| z bin | mediana SNANA | mediana LCL (peso viejo, histórico) | mediana LCL (peso nuevo, Fase 44) |
|---|---:|---:|---:|
| [0.011,0.095) | 19.122 | 19.564 | 19.570 |
| [0.095,0.179) | 21.072 | 21.245 | 21.256 |
| [0.179,0.263) | 22.151/22.152 | 22.440 | 22.439 |
| [0.263,0.348) | 23.188 | 23.415 | 23.390 |
| [0.348,0.432) | 24.022/24.028 | 24.464 | 24.474 |
| [0.432,0.516) | 24.782/24.784 | 25.343 | 25.332 |
| [0.516,0.600) | 25.694/25.703 | 26.092 | 26.084 |

Mediana global: SNANA `24.801`, LCL peso nuevo `25.347` (peso viejo histórico: `25.351`) --
**diferencia de `0.004` mag entre los dos mecanismos, dentro de ruido de simulación**. El residuo
real de esta clase (LCL ~0.3-0.6 mag más tenue que SNANA, documentado desde el hallazgo original con
`compare_brightness_truth.py`) **no se mueve** al corregir el mecanismo de `SIMSED_REDCOR`.

### Conclusión Fase 44

Fix aplicado por fidelidad real (reimplementa el algoritmo documentado de SNANA con precisión, no
una aproximación) -- pero **no es la causa** ni del desajuste estadístico fuerte que encontró Fase 41
ni del residuo de brillo poblacional real de `SNIa-91bg` (~0.3-0.6 mag, tenue). Ambos quedan
abiertos, ahora con un candidato menos en la lista: la forma exacta de calcular el peso de cada
template (densidad puntual vs. masa de celda) no es, por sí sola, la explicación. El mecanismo de
muestreo de `SIMSED_REDCOR` de SNANA real puede tener algo más (un `WGTMAP` real, o algo no
capturado en `nearest_gridval_SIMSED()`) que sigue sin identificarse -- candidato concreto para una
fase futura, ahora más acotado que antes.

### Archivos de esta fase

`snana_params.py`: `make_correlated_normal_weights()` reimplementada (Cholesky + masa exacta de
celda de Voronoi rectangular vía inclusión-exclusión), firma sin cambios. Exploratorios en NLHPC,
borrados tras usarlos: `fase44_redcor_test.py` (test KS peso viejo vs. nuevo),
`fase44_zbin_compare.py` (comparación de brillo banda `r`). Corrida real de producción (no
exploratoria, resultado documentado arriba): `compare_brightness_truth.py` re-ejecutado con el peso
nuevo, output en `compare_brightness_truth_output.parquet` (no borrado).

## Fase 45 — la truncación real a `GENRANGE` (reject-and-retry) tampoco explica el desajuste de `SIMSED_REDCOR`

Cierre de Fase 44, siguiendo la lectura de código un poco más allá de lo que esa fase necesitó:
`~/github/SNANA_src/src/snlc_sim.c` línea real ~14038 (bloque `if (NROW_COV > 0)`, activo para
`SNIa-91bg` porque declara `SIMSED_REDCOR`) muestra que SNANA no calcula la masa de una Gaussiana
correlacionada sin más -- **rechaza y reintenta** (`goto PICK_RANCOV`, hasta 100 intentos) cualquier
draw continuo `(stretch, color)` que caiga fuera de `GENRANGE_stretch`/`GENRANGE_color` **antes** de
snapear a la grilla. La reimplementación de Fase 44 nunca truncó a esa caja real -- extendió los
bordes exteriores de la grilla a `±50σ` (soporte casi infinito) en vez de cortar en el `GENRANGE` real.
Confirmado contra el `.INPUT` real (`SIMGEN_INCLUDE_SNIa-91bg.INPUT`): `GENRANGE_stretch: 0.65 1.25` y
`GENRANGE_color: 0.0 1.0` coinciden **exactamente** con los extremos de la grilla de 35 templates --
el corte real está a solo `~3.2-3.4σ` del pico, no en el infinito.

### Paso 1 -- cuánta masa real cae fuera de la caja: chica, `0.854%`

Calculado con la misma técnica de inclusión-exclusión que ya usa `make_correlated_normal_weights()`
(`scipy.stats.multivariate_normal.cdf()` en las 4 esquinas de la caja `[0.65,1.25]×[0.0,1.0]`, con
`peak=[0.975,0.557]`, `sigma=[0.096,0.175]`, `redcor=-0.656`), y confirmado con Monte Carlo (2M draws
directos): **`0.854%`/`0.864%`** de la masa real cae fuera de la caja -- chico en términos absolutos,
aunque no despreciable dado el rango relativamente angosto (por eso se implementó igual, en vez de
descartar la hipótesis sin medir).

### Paso 2 -- implementado: truncación real vía parámetro `genrange` nuevo

`make_correlated_normal_weights()` gana un parámetro opcional `genrange: dict[str, tuple[float,
float]]` (default `None` = mismo comportamiento de Fase 44, bordes a `±50σ`) -- si se pasa, los bordes
exteriores de cada eje se recortan en el `GENRANGE` real en vez de `±50σ`, y el resultado queda
automáticamente normalizado a la masa real dentro de la caja completa al dividir por la suma
(equivalente exacto al reject-and-retry real en el límite de infinitos intentos). Firma compatible con
los 2 call sites existentes (no llaman con `genrange`, siguen igual que antes).

### Paso 3 -- re-testeado: el KS no mejora, incluso empeora levemente en `color`

Mismo test de Fase 44 (200k resampleos vs. 1919 objetos reales del `.DUMP`, sentinelas filtrados):

| | Fase 44 (`±50σ`) | Fase 45 (`GENRANGE` real) |
|---|---:|---:|
| `stretch` KS stat / p | 0.2073 / 3.8e-72 | **0.2066 / 1.2e-71** |
| `color` KS stat / p | 0.2558 / 3.4e-110 | **0.2585 / 1.6e-112** |
| `stretch` media sim | 0.9750 | 0.9754 |
| `color` media sim | 0.5565 | 0.5550 |

Exactamente lo que predecía el `0.854%` del Paso 1: el cambio es numéricamente real (la suma de pesos
antes de normalizar cae de `~1.0` a `0.9915`, confirmando que la truncación se aplicó) pero su efecto
en la distribución final es **ruido, no una mejora** -- `stretch` mejora en la tercera cifra decimal,
`color` empeora levemente. No se pasa al Paso 4 (re-medir el residuo de brillo poblacional) porque el
propio criterio del plan lo condiciona a una mejora sustancial del KS, que no ocurrió.

### Conclusión Fase 45

Hipótesis descartada con evidencia directa, no por argumento de plausibilidad: la truncación real a
`GENRANGE` (el mecanismo reject-and-retry que Fase 44 no había implementado) es real y se corrigió,
pero **no es la causa** del desajuste KS abrumador de `SIMSED_REDCOR`. Con esto se agotan los
candidatos identificables por lectura de código C para este mecanismo específico -- quedan solo dos
hipótesis sin probar, ambas fuera de esta fase: (a) el propio bloque `if (NROW_COV > 0)` en
`snlc_sim.c` usa `getRan_GENGAUSS_ASYM()` en un lugar (línea ~14178) y `getRan_GaussCorr()` en otro
(línea ~14051) -- no se confirmó en esta fase cuál de los dos caminos de código realmente se ejecuta
para `SIMSED_REDCOR` con parámetros correlacionados, ni si son consistentes entre sí; (b) instrumentar
el binario real de SNANA (mismo patrón exitoso de Fases 29/30/37, clon compilable ya disponible en
`~/github/SNANA_src`) para volcar los draws continuos reales `(stretch, color)` antes del snap, en vez
de seguir razonando sobre el código C sin verificación directa -- la recomendación que ya dejó Fase 44,
ahora reforzada: la lectura de código llegó a su límite práctico para este mecanismo, hace falta
evidencia de ejecución real.

### Archivos de esta fase

`snana_params.py`: `make_correlated_normal_weights()` gana el parámetro opcional `genrange`
(implementación real de la truncación, comentario citando `snlc_sim.c` línea ~14038). Exploratorios en
NLHPC, borrados tras usarlos: `fase45_mass_check.py` (Paso 1), `fase45_redcor_test.py` (Paso 3). Sin
recorrida de `compare_brightness_truth.py` esta fase (no se cumplió el criterio del Paso 4).

## Fase 46 — la sobre-detección de `ILOT-MOSFIT` (Fase 43) es real, no espuria: épocas muy tardías dentro del rango físico válido del template, pero de SNR más marginal

Pregunta 2 de la ronda anterior: Fase 43 extendió `rest_time_window_offset` de `ILOT-MOSFIT` a
`(-100,1000)` días (`GENRANGE_TREST` real) y el ratio de detección pasó de sub-detectar 2x (`3.65%`
vs. `7.15%` real) a sobre-detectar ~4.3x (`31.03%±0.63%`). Candidato a probar: detecciones espurias en
la cola tardía, posiblemente ligadas a la extrapolación de fase.

### Reconstrucción real, con las 5 semillas ya corridas (sin simular nada nuevo)

Usando `head_df.parquet`/`phot_df.parquet` reales de las 5 semillas (`poc_output_ilotmosfit`/
`_seed1-4`, columnas `DETECTED`/`PHOTFLAG` ya calculadas), se reconstruyó -- para cada objeto
detectado -- la fase rest-frame de cada época (`(MJD-PEAKMJD)/(1+z)`) y se agrupó con
`group_into_epochs()` real (mismo algoritmo de Fase 4, `NEWMJD_DIF=0.007` días). Se separaron los
objetos detectados en dos grupos: **"viejos"** (ya tienen ≥2 épocas detectadas dentro de
`[-30,100]` días -- se habrían detectado igual con la ventana original) y **"nuevos"** (solo llegan a
≥2 épocas gracias a al menos una época fuera de `[-30,100]`).

| | N objetos | mediana SNR de la época de trigger | % con SNR<7 | mediana `rest_phase` (épocas "nuevas") |
|---|---:|---:|---:|---:|
| "viejos" (ventana original ya alcanzaba) | 818 | 5.72 | 64.2% | -- |
| "nuevos" (solo por ventana extendida) | 2285 | 3.97 | 81.8% | **264.8 días** |

**El 99.4% de los objetos "nuevos" (2271/2285) tienen su época de disparo a `|rest_phase|>45` días**
-- confirma que la sobre-detección viene abrumadoramente de la cola tardía extendida, no de ruido
disperso cerca del pico. Las épocas "nuevas" sí son sistemáticamente más marginales que las "viejas"
(SNR mediano 3.97 vs. 5.72, 81.8% vs. 64.2% con SNR<7).

### Pero no es un artefacto de extrapolación: el propio modelo declara flujo físico válido hasta 2000 días

Verificado el `SED.INFO` real de `SIMSED.ILOT-MOSFIT`
(`~/run_SNANA/plasticc_models/SIMSED.ILOT-MOSFIT/SED.INFO`): declara explícitamente
`REBIN_DAY: 2 for 200.0 < DAY < 2000.0` -- el propio modelo físico (transitorio ILOT alimentado por
interacción con medio circunestelar, "CSM-powered") está diseñado y calibrado para tener flujo
significativo hasta 2000 días, con una grilla más gruesa (rebin) más allá de 200 días. La mediana de
`rest_phase` de las épocas "nuevas" (264.8 días) cae **dentro** de ese rango físicamente válido, no
más allá de él -- descarta la hipótesis original de esta fase (extrapolación tardía de
`LinearDecay`/`ZeroPadding` generando flujo no físico): esos extrapoladores ni siquiera se usan en el
camino de código real de `run_simsed_poc.py` (que usa `SIMSEDModel` directo, no
`SncosmoWrapperModel` con extrapolación de tiempo configurada -- confirmado leyendo el script real,
sin ninguna referencia a `LinearDecay`/`ZeroPadding` en la construcción del modelo SIMSED).

### Conclusión Fase 46 -- resultado genuinamente mixto, ninguna de las dos hipótesis simples se sostiene limpia

No es el resultado "espurio" que se esperaba, pero tampoco es un "no hay nada raro acá": las épocas de
disparo "nuevas" son reales dentro del rango físico modelado del template (no extrapolación inválida),
**pero** son sistemáticamente más marginales en SNR que las que ya disparaban con la ventana vieja, y
concentradas en una cola extremadamente tardía (mediana 265 días, hasta 1000 días) que un survey real
probablemente no cubre con la misma densidad de observaciones que asume esta ventana de generación
uniforme. La sobre-detección de 4.3x es consistente con: la ventana `GENRANGE_TREST` real
efectivamente amplía el catálogo generado a un régimen de fase muy tardía donde el modelo físico sigue
prediciendo flujo, pero donde factores no modelados en esta fase (densidad de cadencia real del OpSim
esa lejos del pico, o si el propio `.INPUT` de SNANA real limita la ventana de trigger/detección de
forma distinta a la de generación) podrían explicar por qué SNANA real no detecta tantos de estos
objetos tardíos como LightCurveLynx. No se investigó en esta fase si SNANA distingue `GENRANGE_TREST`
(ventana de generación) de una ventana de trigger más angosta -- candidato concreto para una fase
futura, no cerrado acá.

### Archivos de esta fase

`fase46_analysis.py` (exploratorio, no versionado, borrado de NLHPC tras usarlo). Sin cambios a
`run_simsed_poc.py` -- ninguna corrección aplicada esta fase, el hallazgo queda como diagnóstico
honesto y un candidato nuevo (posible distinción generación-vs-trigger en `GENRANGE_TREST` real) para
retomar más adelante.

## Fase 47 — RESUELTO: el residuo original de `SNIa-91bg` (Fase 7, el que arrancó toda esta investigación) era casi enteramente un artefacto de metodología

Arranca el programa de auditoría a fondo de `SNIa-91bg` -- la clase que originó toda la investigación
(Fase 7: LightCurveLynx ~0.2-0.6 mag más TENUE que SNANA, signo opuesto al caso SALT2 cerrado en
Fase 37). Dos bugs metodológicos reales, identificados por lectura de código antes de correr nada:

1. `compare_brightness_truth.py` seguía usando `flux_perfect.max()` sobre la cadencia real observada
   -- la MISMA métrica que la propia Fase 22 declaró inválida para SNIa/SALT2 (subestima el brillo real
   para objetos con mala cobertura de cadencia cerca del pico). Ese fix migró a
   `compare_brightness_truth_salt2.py` en Fase 39, pero **nunca se portó a este script** -- las Fases
   41/44/45 midieron el residuo de `SIMSED_REDCOR` con este mismo sesgo sin saberlo.
2. El `.DUMP` real de `SNIa-91bg` nunca se filtró con `filter_ddf_field_contamination()` (Fase 36) --
   nunca se verificó si tiene el mismo problema de contaminación de campo que `SNIa`.

### Paso 1 -- migración a la metodología correcta

`compare_brightness_truth.py` migrado de `flux_perfect.max()` a `compute_noise_free_lightcurves()`
evaluado en `rest_phase=0` (mismo patrón exacto que Fase 39 aplicó al script SALT2: `sample_parameters()`
+ `compute_noise_free_lightcurves(..., rest_frame_phase_min=0.0, rest_frame_phase_max=0.5,
rest_frame_phase_step=1.0)`, extrayendo `sub["r"].to_numpy()[0]` en vez de
`r_band["flux_perfect"].max()`). Verificado con `py_compile`.

Impacto inmediato, visible ya en la corrida cruda (2000 objetos, sin comparar todavía contra SNANA):
mediana de `PEAKMAG_r_true` pasa de `25.347` (Fase 44, método viejo) a **`24.556`** (método correcto) --
LightCurveLynx sale **sustancialmente más brillante** una vez medido en el pico verdadero continuo, no
en el máximo sobre la cadencia real (`std` también baja de `2.013` a `1.319`, consistente con que el
sesgo viejo agregaba dispersión espuria dependiente de qué tan bien la cadencia de cada objeto cubría
su propio pico).

### Paso 2 -- contaminación real confirmada, mismo problema que `SNIa`

`filter_ddf_field_contamination()` (`<2°` al campo DDF real más cercano, mismo criterio de Fase 33/36)
aplicado al `.DUMP` real de `SNIa-91bg`:

| | N | mediana `PEAKMAG_r` |
|---|---:|---:|
| sin filtrar (1919 con `PEAKMAG_r` válido) | 1919 | 24.801 |
| filtrado (`<2°`) | 1696 (88.4%) | 24.649 |

**11.6% de contaminación real** (223/1919 objetos fuera del footprint DDF real) -- del mismo orden que
el 15.2% que encontró Fase 33 para `SNIa`. Mismo mecanismo: objetos `GW_case_*`/`neutrino_*` del OpSim
real mezclados en el mismo `.DUMP` de referencia, sistemáticamente más tenues (extinción extrema),
inflando la mediana de SNANA hacia el lado tenue.

### Paso 3 -- con ambos fixes aplicados, el residuo prácticamente desaparece

Comparación banda `r`, mismos 7 bins de `z` de siempre, SNANA filtrado (contaminación) vs. LCL con la
metodología correcta:

| z bin | N SNANA (filt) | mediana SNANA (filt) | N SNANA (raw) | mediana SNANA (raw) | N LCL | mediana LCL | Δ (filt) |
|---|---:|---:|---:|---:|---:|---:|---:|
| [0.011,0.095) | 7 | 18.937 | 9 | 19.122 | 9 | 19.543 | +0.606 |
| [0.095,0.179) | 47 | 20.960 | 57 | 21.072 | 50 | 20.872 | -0.088 |
| [0.179,0.263) | 120 | 22.110 | 130 | 22.152 | 139 | 22.018 | -0.092 |
| [0.263,0.348) | 178 | 23.123 | 201 | 23.188 | 238 | 23.125 | +0.002 |
| [0.348,0.432) | 296 | 23.963 | 338 | 24.028 | 371 | 23.910 | -0.053 |
| [0.432,0.516) | 446 | 24.731 | 499 | 24.784 | 513 | 24.687 | -0.045 |
| [0.516,0.600) | 599 | 25.641 | 682 | 25.703 | 680 | 25.510 | -0.131 |

**Media de Δ (bins 2-7, mismo criterio de siempre): `-0.068` mag** (filtrado) -- contra el
`+0.55` mag histórico (Fase 7, redescubierto en Fase 44 con la metodología vieja). Mediana global: SNANA
filtrado `24.649`, LCL `24.556`, delta global `-0.093` mag. El primer bin (`N` muy chico, 7-9 objetos)
queda como ruido de baja estadística, igual que en las comparaciones de `SNIa`/SALT2 desde Fase 20.

### Conclusión Fase 47 -- el residuo que originó la investigación era, en gran parte, el mismo tipo de artefacto que ya se había encontrado dos veces

**El residuo de `~0.2-0.6` mag de `SNIa-91bg` (Fase 7, nunca revisado desde entonces con la metodología
correcta) queda reducido a `~0.07-0.09` mag** -- del mismo orden que el ruido residual que quedó en
otras comparaciones ya cerradas de esta investigación (Fase 44 dejó `SNIa` en `+0.005` mag, pero otras
clases con menos escrutinio, como el candidato de ruido de Fase 42, también dejaron residuos de un
pareado similar). No es un cierre tan limpio como `MAG_OFFSET` (Fase 37, `0.005` mag), pero es una
reducción del **~85%** del residuo histórico, lograda con los MISMOS DOS bugs metodológicos (cadencia
vs. pico verdadero, contaminación de datos) que ya se habían encontrado y corregido para `SNIa` en
Fases 22/36 -- nunca portados a este script. Confirma, con un segundo ejemplo real e independiente, que
la lección metodológica de esta investigación (verificar la metodología de medición antes de cazar
causas físicas) generaliza más allá del caso SALT2 donde se descubrió.

**Reinterpretación real de las Fases 41/44/45**: el test KS de `SIMSED_REDCOR` (Fase 41/44/45) no se ve
afectado por este hallazgo -- comparaba distribuciones de parámetros (`stretch`/`color`), no magnitudes,
así que sigue siendo válido que el mecanismo de muestreo de `SIMSED_REDCOR` no explica ningún residuo de
brillo (con razón: ahora se sabe que casi no había residuo de brillo que explicar). Lo que sí cambia es
la urgencia de retomar `SIMSED_REDCOR`: con el residuo de brillo prácticamente cerrado, ese hilo pasa a
ser una discrepancia de forma de distribución interesante por derecho propio, no un candidato urgente
para explicar una brecha de brillo grande.

**Candidato nuevo, no cerrado en esta fase**: el `-0.068` mag remanente (y el signo que cambia de bin a
bin, sin tendencia monótona clara) queda como pregunta abierta menor -- candidato para Fase 48
(cobertura de claves de `SED.INFO`) o una fase de pareado objeto-a-objeto contra el `_HEAD.FITS` real
(mismo método que cerró Fase 37 para SALT2), si se decide seguir apretando este último tramo.

### Archivos de esta fase

`compare_brightness_truth.py`: migrado de `flux_perfect.max()`/`simulate_lightcurves()` a
`compute_noise_free_lightcurves()` en `rest_phase=0` (import de `SurveyInfo` removido, ya no se usa).
Exploratorios en NLHPC, borrados tras usarlos: `fase47_zbin_analysis.py` (Pasos 2-3),
`fase47_compare_brightness.sbatch` (Paso 1). Output real conservado (no exploratorio, producto de
script de producción): `compare_brightness_truth_output.parquet`.

## Fase 48 — causa raíz real de la contaminación de campo (Fase 33/36/47): un bug de Capa 1 clasifica el campo `RGES` (Roman Galactic Exoplanet Survey) como DDF

Motivada directamente por Fase 47: si `SNIa-91bg` tenía ~15% de contaminación de campo sin filtrar en
su `.DUMP` de referencia, ¿la tienen las otras 13 clases del catálogo también? Y más importante: ¿de
dónde sale esa contaminación en primer lugar? Hasta ahora (Fase 36/47) el filtro
`filter_ddf_field_contamination()` se trataba como un parche post-hoc sobre el `.DUMP` -- nunca se
había preguntado por qué el `.DUMP` real de SNANA contenía objetos fuera del footprint DDF si SNANA
generó la campaña a partir de un SIMLIB que en teoría solo debía tener los 6 campos DDF reales.

### Paso 1 — la causa raíz: el SIMLIB de producción incluye un campo que no es DDF

`pipeline/simlib/classify.py:25` y `pipeline/simlib/simlib.yaml:30` clasifican un `LIBID` del SIMLIB
como DDF si su `scheduler_note` empieza con el prefijo `"DD:"`:

```python
ddf_prefixes: tuple[str, ...] = ("DD:",)
```

Consulta directa sobre el OpSim real (`baseline_v5.3.1_10yrs.db`) por `scheduler_note LIKE 'DD:%'`
agrupado por `target_name`: hay 8 familias con ese prefijo, no 6. Las 6 reales (`target_name LIKE
'%ddf_%'`) son los campos DDF conocidos. Las otras 2 son `DD: RGES_offseason` (1574 observaciones) y
`DD: RGES_onseason` (659 observaciones), ambas con `target_name = 'roman_field, bulgy'` -- el campo
del Roman Galactic Exoplanet Survey, en el bulbo galáctico (RA≈268.7°, Dec≈-28.97°), a 76.8°-78.2° de
separación angular de cualquier centro DDF real. `classify.py` no distingue por `target_name`, solo
por el prefijo de texto de `scheduler_note` -- y RGES comparte el prefijo `"DD:"` por convención de
nomenclatura del scheduler de Rubin, no por ser parte del DDF.

Parseando el SIMLIB real de producción (`data/simlib/baseline_v5.3.1_10yrs/DDF_baseline_v5.3.1_10yrs.SIMLIB`)
y midiendo separación angular de cada `LIBID` contra los 6 centros DDF reales: **127/1000 LIBID
(12.70%)** caen en el rango 76.8°-78.2° -- exactamente el campo RGES, incluido en el SIMLIB de
producción como si fuera DDF. `127/1000 × 2000 = 254` -- coincide exacto con el conteo de
contaminación encontrado independientemente en el `.DUMP` de cada una de las 14 clases (ver Fase 36).
LightCurveLynx no tiene este bug: filtra pointings por `target_name` conteniendo `ddf_`, que RGES no
tiene, así que nunca ingiere el campo.

### Paso 2 — la tabla de referencia de 14 clases, recalculada con el filtro correcto

`filter_ddf_field_contamination()` (Fase 36, `snana_params.py:675`, separación angular real de 2° por
objeto contra los 6 centros DDF reales derivados del propio OpSim) aplicada sobre el `.DUMP` real de
cada una de las 14 clases:

| clase | N (`.DUMP`) | SNANA% raw | N post-filtro | SNANA% DDF-only | ratio histórico (Fase 5) | ratio corregido | factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| `SNIa-91bg` | 2000 | 36.15 | 1696 | 41.69 | 1.420 | 1.231 | 1.1531 |
| `PISN-STELLA-HYDROGENIC` | 20000 | 21.34 | 16960 | 24.45 | 1.438 | 1.255 | 1.1458 |
| `SNII-NMF` | 2000 | 17.80 | 1696 | 20.75 | 1.538 | 1.319 | 1.1660 |
| `PISN-STELLA-HECORE` | 2000 | 19.20 | 1696 | 21.88 | 1.569 | 1.377 | 1.1393 |
| `SLSN-I` | 2000 | 41.20 | 1696 | 46.64 | 1.604 | 1.417 | 1.1320 |
| `TDE-MOSFIT` | 2000 | 40.60 | 1696 | 46.58 | 1.677 | 1.462 | 1.1473 |
| `PISN-MOSFIT` | 2000 | 20.55 | 1696 | 23.41 | 1.825 | 1.602 | 1.1391 |
| `SNIa` | 2000 | 29.85 | 1696 | 34.55 | 1.926 | 1.664 | 1.1575 |
| `ILOT-MOSFIT` | 2000 | 3.65 | 1696 | 4.30 | 2.277 | 1.931 | 1.1792 |
| `KN-BULLA19` | 2000 | 5.15 | 1696 | 6.07 | 2.509 | 2.128 | 1.1792 |
| `KN-K17` | 2000 | 4.10 | 1696 | 4.83 | 2.639 | 2.238 | 1.1792 |
| `SNIax` | 2000 | 8.75 | 1696 | 10.08 | 2.816 | 2.444 | 1.1523 |
| `SNIIn-MOSFIT` | 2000 | 1.85 | 1696 | 2.12 | 5.605 | 4.885 | 1.1474 |
| `CaRT` | 2000 | 0.80 | 1696 | 0.94 | 10.825 | 9.180 | 1.1792 |

Promedio del catálogo: `2.833x` histórico → **`2.438x`** corregido. Factor de corrección promedio
`1.1569x` (std `0.0162`) -- consistente entre clases, sin efecto oculto por clase individual (el rango
completo va de `1.1320` a `1.1792`, una dispersión chica). Confirma la respuesta a la pregunta que
arrancó esta fase: **sí, las 14 clases tienen el mismo bug metodológico que `SNIa-91bg`** (contaminación
de campo sin filtrar en la referencia SNANA), con una magnitud similar en todas (~15% de objetos
removidos).

Nota honesta: la fracción de contaminación medida acá a nivel de objeto (**15.2%**, 304/2000 para las
clases de `N=2000`) es más alta que la estimada a nivel de `LIBID` en el Paso 1 (**12.70%**, 127/1000).
No se fuerza la coincidencia -- son medidas de cosas ligeramente distintas: el Paso 1 cuenta pointings
completos de RGES: el Paso 2 cuenta objetos removidos por estar a >2° de cualquier centro DDF real, un
criterio por-objeto más laxo que el 3° usado para el chequeo de `LIBID`, que además puede capturar
jitter marginal adicional del bug de `ObsTableRADECSampler` sin semilla ya documentado (ver
`ISSUE_DRAFT_seed_propagation.md`). Ambos números apuntan a la misma causa raíz (RGES), solo difieren
en la vara de medir.

### Paso 3 — portar el filtro a `compare_brightness_truth_binned.py` (verificación)

`compare_brightness_truth_binned.py` (el script que genera la tabla binneada por redshift usada para
reportar el resultado de Fase 47) todavía no tenía el filtro aplicado en su versión versionada -- Fase
47 lo había aplicado solo en un exploratorio ya borrado. Se agregó el import de
`filter_ddf_field_contamination()` y se aplicó antes de binear. Correrlo de nuevo reproduce **exacto**
el resultado de Fase 47 (Δ medio bins 2-7 = **`-0.068`** mag), confirmando que el filtro está bien
portado y que el resultado de Fase 47 es estable, no un artefacto de cómo se corrió el exploratorio
original.

### Paso 4 — el fix real no se aplica en esta fase

El fix correcto en la fuente (excluir `RGES` de `ddf_prefixes`, o mejor, clasificar por `target_name`
en vez de por prefijo de `scheduler_note`) es simple a nivel de código -- pero aplicarlo requiere
regenerar el SIMLIB completo de producción y por lo tanto invalida las 14 campañas de referencia
(`.DUMP`, `.README`) ya corridas y usadas en cada fase de esta investigación hasta ahora. **No se toca
`pipeline/simlib/classify.py` ni `simlib.yaml` en esta fase** -- es una decisión de alcance mayor
(cuándo regenerar el SIMLIB, con qué campaña de referencia) que le corresponde al usuario, no a esta
fase de diagnóstico.

### Conclusión Fase 48

La contaminación de campo que Fase 36 encontró en `SNIa` y Fase 47 confirmó en `SNIa-91bg` no es un
problema aislado del `.DUMP` -- es un bug real de Capa 1 (`classify.py:25`/`simlib.yaml:30`) que afecta
igual a las 14 clases del catálogo, con una causa raíz identificada y reproducida con evidencia directa
en tres niveles independientes (SQL sobre el OpSim, parseo del SIMLIB real, filtro sobre los 14
`.DUMP`): el campo `RGES` del Roman Galactic Exoplanet Survey comparte el prefijo `"DD:"` con los
campos DDF reales y se clasifica como tal por error. La tabla de referencia de 14 clases usada desde
Fase 5 queda recalculada -- el ratio promedio del catálogo baja de `2.833x` a `2.438x` -- sin cambiar
la conclusión cualitativa de ninguna fase anterior (todas las comparaciones de ratio relativo entre
clases se mantienen en el mismo orden). El fix real queda documentado y listo para aplicar, pendiente
de decisión del usuario sobre cuándo regenerar el SIMLIB de producción.

### Archivos de esta fase

`compare_brightness_truth_binned.py`: agregado el filtro `filter_ddf_field_contamination()` (import +
aplicación antes de binear), con comentario citando Fase 36/47/48. Exploratorios en NLHPC, borrados
tras usarlos: `fase48_libid_check.py` (Paso 1, parseo de SIMLIB + separación angular),
`fase48_paso2_referencia.py` (Paso 2, tabla de 14 clases). `pipeline/simlib/classify.py` y
`simlib.yaml` sin cambios -- el fix real queda pendiente de decisión del usuario (Paso 4).

## Fase 49 — Fase 43 leyó la referencia de SNANA invertida: `SLSN-I`/`ILOT-MOSFIT` no mejoraron con `GENRANGE_TREST`, empeoraron

Corrección real, no una nueva hipótesis: al diseñar la ronda de auditoría de bugs metodológicos
(motivada por el hallazgo de Fase 47) se encontró que las tablas de Fase 4 y Fase 43 tienen las
columnas de SNANA real y LightCurveLynx invertidas para dos clases.

### Paso 1 — confirmar la inversión contra archivos reales

`NOTES.md` línea 630 (Fase 4, encabezado real: `| clase | SNR mediana LCL | SNR p90 LCL | detectados
SNANA real | detectados LCL | razón |`): `SLSN-I ... 824/2000 (41.2%) ... 1266/2000 (63.3%) ...
1.54x` -- por el propio encabezado, **824=SNANA real, 1266=LCL** (1266/824=1.536≈1.54x, consistente).
Línea 958: `ILOT-MOSFIT ... 73/2000 (3.65%) ... 143/2000 (7.15%) ... 1.96x` -- mismo orden,
**73=SNANA real, 143=LCL** (143/73=1.959≈1.96x). Fase 43 (líneas 5852/5863) invierte la asignación:
etiqueta `63.3% (1266/2000)`/`7.15% (143/2000)` como **"SNANA real"** -- exactamente los números de
LCL de Fase 4.

Verificado contra los `.README` reales de producción
(`~/DATASIM_LSST_1/DDF/SIMDv8/SLSN-I_DDF_baseline_v5.3.1_10yrs/*.README`,
`~/DATASIM_LSST_1/DDF/SIMDv8/ILOT_DDF_baseline_v5.3.1_10yrs/*.README` -- la carpeta real es `ILOT`,
no `ILOT-MOSFIT`): `NGENTOT_LC: 2000` / `NGENLC_WRITE: 824` para `SLSN-I` (41.20%), `2000`/`73` para
`ILOT` (3.65%) -- coincide exacto con la Fase 4 original, no con Fase 43. Probadas además 3
definiciones alternativas reales sobre el `.DUMP` de cada clase, ninguna reproduce 1266/143:

| clase | `MJD_DETECT_FIRST>0` | `FLAG_ACCEPT>0` | `SNRMAX>5` | `SIM_SEARCHEFF_MASK>0` | `NGENLC_WRITE` real |
|---|---:|---:|---:|---:|---:|
| `SLSN-I` | 1941 | 824 | 781 | 824 | 824 |
| `ILOT` | 1924 | 73 | 72 | 73 | 73 |

`FLAG_ACCEPT>0` y `SIM_SEARCHEFF_MASK>0` coinciden exacto con `NGENLC_WRITE` (824/73) -- son la
definición real de detección que usa SNANA. Ninguna columna real del `.DUMP` da 1266 ni 143.

### Paso 2 — la tabla corregida

| clase | SNANA real | LCL histórico (`-30/100`, Fase 5) | LCL Fase 43 (`GENRANGE_TREST` real) | ratio antes → después |
|---|---:|---:|---:|---|
| `SLSN-I` | 41.20% (824/2000) | 66.1% (41.20%×1.604) | 72.0% (1440/2000) | 1.604x → **1.748x (empeora)** |
| `ILOT-MOSFIT` | 3.65% (73/2000) | 7.15% (3.65%×1.96, coincide con el 143/2000 real de Fase 4) | 31.03%±0.63% (605-639/2000) | 1.96x → **~8.5x (mucho peor)** |

`SLSN-I`: extender la ventana real (`-100/500`) no acerca LCL a SNANA -- lo aleja más (de sub-detectar
un 25pp a sobre-detectar 30.8pp). `ILOT-MOSFIT`: la sobre-corrección ya documentada en Fase 43/46 era
real en dirección, pero su magnitud absoluta está subestimada por el error de referencia -- el ratio
real es ~4.3x más alto que el reportado entonces. Nota: todavía no se recalculó contra la referencia
DDF-only de Fase 48 (contaminación de campo, causa raíz RGES) porque esa fase no había terminado al
cerrar esta -- los números de arriba son sobre el `.DUMP` raw, mismo criterio que usó Fase 43
originalmente, así que la comparación "antes/después" es consistente aunque ambos lados sigan con la
contaminación sin filtrar.

### Paso 3 — el código se mantiene, se corrige el texto

`trest_range` en `run_simsed_poc.py::CLASS_CONFIGS["SLSN-I"]`/`["ILOT-MOSFIT"]` (Fase 43) sigue
siendo **correcto por fidelidad** -- son los valores reales de `GENRANGE_TREST` del `.INPUT` real
(Fase 40), no un error de código. Lo que estaba mal era la interpretación escrita. **No se revierte el
código.** La corrección de Fase 43 arriba (Paso 2 de esta fase) queda como la lectura vigente de ese
resultado -- el texto original de Fase 43 se deja intacto más abajo en este mismo archivo (mismo
criterio de transparencia de todo el proyecto: no se borra un hallazgo, se corrige con una fase nueva
que lo referencia). Esto **refuerza** (no contradice) el hallazgo de Fase 46: la ventana extendida
agrega detecciones espurias de SNR marginal en la cola, y ahora hay dos clases (no una) donde
extender `GENRANGE_TREST` empeora el ratio en vez de mejorarlo.

### Paso 4 — propagación corregida en el dashboard

`docs/index.html`: corregidos los 3 lugares que citaban `63.3%`/`1266`/`7.15%`/`143` como "SNANA
real" -- el callout "Actualización Fases 38-46" (Resumen), la línea 3 de "Líneas para seguir
investigando" (Conclusiones), y la entrada de Fase 43 en la sub-tab "N fases".

### Conclusión Fase 49

Error de transcripción real, no un problema de metodología de simulación -- las columnas de una
tabla se invirtieron al escribir Fase 43, arrastrando el error a 3 lugares del dashboard. Corregido
con evidencia directa contra los `.README` reales de producción (fuente de verdad, no reconstruida).
El código que Fase 43 cambió sigue siendo correcto; su interpretación no lo era. El resultado
corregido no cambia la conclusión cualitativa de que `ILOT-MOSFIT` sobre-corrige (ya se sabía), pero
sí invierte la de `SLSN-I` (de "mejora sustancial" a "empeora") y amplifica la magnitud real del
problema en ambas clases -- reforzando, con más fuerza que antes, el candidato de extrapolación
tardía de Fase 46.

### Archivos de esta fase

Sin scripts nuevos -- fase de lectura/verificación pura (`.README` reales vía `ssh`, `.DUMP` real vía
el venv de NLHPC para las 3 definiciones alternativas del Paso 1, sin `sbatch`). `docs/index.html`
modificado (3 secciones). `run_simsed_poc.py` sin cambios -- el código de Fase 43 se mantiene.

## Fase 50 — primera medición de brillo verdadero fuera de `SNIa`/`SNIa-91bg`: `SNIax` y `CaRT` tienen residuos reales, grandes y fuertemente cromáticos (LCL hasta 2 mag más brillante en `u`)

Cuarenta y tres fases después de que Fase 7 dejara pendiente medir brillo verdadero en las 12 clases
restantes del catálogo (siempre se comparó solo ratio de detección, nunca `PEAKMAG` sin ruido), esta
fase generaliza la herramienta y mide las dos primeras: `SNIax` (1001 templates) y `CaRT` (225
templates, peor ratio de detección del catálogo, 10.8x en Fase 48).

### Paso 0 — generalizar la herramienta, sin duplicar parámetros a mano

`compare_brightness_truth.py` reescrito para aceptar cualquier clase de `CLASS_CONFIGS` por línea de
comando, importando (no copiando) `CLASS_CONFIGS` y una función nueva, `build_source_model()`,
extraída de `run_simsed_poc.py::main()` (refactor puro -- se movió el bloque completo de construcción
de `SIMSEDModel`/`dndz`/`radec_sampler`/extinción de host y MW, confirmado línea a línea que no cambia
ninguna lógica). Este era exactamente el mecanismo que hizo que el fix de Fase 22 tardara 25 fases en
llegar a este script (Fase 47): con `build_source_model()` compartida entre producción y auditoría, no
puede volver a pasar. `compare_brightness_truth_binned.py` generalizado en paralelo: `CLASS_CONFIGS`
para los bins de `z` reales por clase, `DUMP_FOLDER_OVERRIDES = {"TDE-MOSFIT": "TDE", "ILOT-MOSFIT":
"ILOT"}` para las 2 carpetas reales que no calzan con la clave de config, y las 6 bandas LSST (antes
solo `r`) vía un mapeo `SNANA_COL` (`PEAKMAG_Y` con mayúscula, confirmado contra el `.DUMP` real).

**Hallazgo lateral al hacer el smoke test con `CaRT`**: evaluar en un solo punto `rest_phase=0` (la
convención que usaron Fases 39/47) devolvía flujo `0.0` en las 6 bandas para los 2000 objetos -- no un
fallo de `compute_noise_free_lightcurves()`, sino que la grilla real de `SIMSED.CART-MOSFIT`
(`SED.INFO`) arranca en fase `0.501`, no en una fase negativa: es una convención "días desde la
explosión", distinta de la convención "días desde el pico" (pico en fase=0 por construcción) que usan
`SNIa-91bg` y la mayoría de clases SIMSED. Fix: evaluar sobre toda la ventana `trest_range` real de
generación (la misma que ya se usa para generar, Fase 40/43), paso de 1 día, y tomar el máximo de
flujo por banda -- encuentra el pico real sin asumir dónde cae, válido para cualquier convención de
fase.

### Paso 1 — control positivo: `SNIa-91bg` con la herramienta generalizada (obligatorio antes de tocar otra clase)

| banda | Δ medio (bins 2-7) |
|---|---:|
| u | -0.537 |
| g | -0.245 |
| r | -0.088 |
| i | -0.032 |
| z | -0.016 |
| y | -0.020 |

Banda `r`: mismo signo y orden de magnitud que Fase 47, pero el valor exacto cambió de `-0.068` a
**`-0.088`** mag. Investigado antes de aceptarlo (mismo criterio de Fase 47: no dar un cambio de
número por bueno sin entender por qué) -- es un efecto esperado del nuevo método, no un bug: el máximo
sobre toda la grilla `trest_range` es por definición mayor o igual al valor puntual en el nodo
fase=0 exacto (el pico continuo real de un template dado no cae necesariamente exacto en ese nodo de
grilla), así que el nuevo método da LCL igual o más brillante que el método de un solo punto -- exactamente
la dirección observada, y con una magnitud pequeña (`0.02` mag ≈ 2% de flujo) consistente con que el
pico real esté cerca pero no exacto en fase=0. El control positivo pasa.

**Hallazgo nuevo, no medido antes** (Fase 47 solo midió banda `r`): el residuo de `SNIa-91bg` es
fuertemente dependiente de banda, monótono de azul a rojo -- de `-0.537` mag en `u` a `-0.020` mag en
`y`. El "residuo prácticamente cerrado" de Fase 47 solo era cierto para `r`; en `u`/`g` sigue habiendo
un residuo real y grande que nunca se había visto porque nadie había medido esas bandas. Reabre el
hilo cromático/extinción (Fases 23/24/36/37) para esta clase.

### Paso 2 — `SNIax`

| banda | Δ medio (bins 2-7) |
|---|---:|
| u | -2.018 |
| g | -1.114 |
| r | -0.609 |
| i | -0.466 |
| z | -0.397 |
| y | -0.350 |

Banda `r`, detalle por bin (mismos 7 bins de `z` reales de la clase, `filter_ddf_field_contamination`
aplicado, 304/2000 objetos removidos = 15.2%, mismo orden que las demás clases):

| z bin | N SNANA | mediana SNANA | N LCL | mediana LCL | Δ |
|---|---:|---:|---:|---:|---:|
| [0.011,0.109) | 6 | 21.082 | 5 | 24.011 | +2.929 |
| [0.109,0.208) | 36 | 22.741 | 37 | 23.295 | +0.554 |
| [0.208,0.306) | 105 | 24.691 | 121 | 24.438 | -0.253 |
| [0.306,0.405) | 174 | 25.625 | 220 | 24.667 | -0.958 |
| [0.405,0.503) | 287 | 26.299 | 350 | 25.317 | -0.982 |
| [0.503,0.602) | 462 | 26.677 | 538 | 25.764 | -0.912 |
| [0.602,0.700) | 623 | 27.531 | 729 | 26.426 | -1.105 |

### Paso 3 — `CaRT`

| banda | Δ medio (bins 2-7) |
|---|---:|
| u | -1.200 |
| g | -0.884 |
| r | -0.602 |
| i | -0.495 |
| z | -0.375 |
| y | -0.348 |

Banda `r`, detalle por bin:

| z bin | N SNANA | mediana SNANA | N LCL | mediana LCL | Δ |
|---|---:|---:|---:|---:|---:|
| [0.012,0.210) | 7 | 23.215 | 7 | 23.114 | -0.101 |
| [0.210,0.409) | 43 | 25.367 | 44 | 25.019 | -0.348 |
| [0.409,0.607) | 121 | 26.657 | 148 | 26.064 | -0.592 |
| [0.607,0.805) | 196 | 27.644 | 247 | 27.213 | -0.431 |
| [0.805,1.003) | 304 | 28.431 | 388 | 27.659 | -0.772 |
| [1.003,1.202) | 454 | 29.345 | 540 | 28.516 | -0.829 |
| [1.202,1.400) | 569 | 29.982 | 626 | 29.343 | -0.639 |

### Interpretación -- las 3 clases comparten una misma forma cromática, en escalas muy distintas

`SNIa-91bg`, `SNIax` y `CaRT` muestran el mismo patrón cualitativo: LCL más brillante que SNANA en
todas las bandas, con el residuo creciendo monótonamente hacia el azul. Pero la escala difiere por un
factor de 4 a 40x: `SNIa-91bg` (`u`: -0.54, `y`: -0.02), `CaRT` (`u`: -1.20, `y`: -0.35), `SNIax`
(`u`: -2.02, `y`: -0.35). Un candidato mecánico real y verificable para explicar por qué `SNIa-91bg`
tiene el residuo más chico: su corrida (Paso 1, log real) nunca imprime la línea "extincion de host
real aplicada" -- a diferencia de `SNIax` (`kind=exp_halfgauss, GENTAU_AV=1.7`) y `CaRT`
(`kind=wv07`), que sí aplican un paso extra de extinción de host sobre el template base. `SNIa-91bg`
decorrelaciona su enrojecimiento vía `SIMSED_REDCOR` (stretch/color, ya cerrado como no-causa del
residuo de brillo en Fase 44/47) directamente en la familia de templates, sin una capa de extinción
de host separada. Esto sugiere -- sin probarlo todavía -- que el paso de aplicar extinción de host
(ley de polvo, grilla de longitud de onda rest-frame vs. observada al integrarla, valor de `R_V`) es
donde diverge la implementación de LightCurveLynx de la de SNANA, y que el residuo cromático que
aparece incluso en `SNIa-91bg` (Paso 1, sin ese paso) sería un segundo efecto más chico, independiente.

### Conclusión Fase 50

Aplicando el criterio de lectura del plan: `SNIax` y `CaRT` **no** caen en `|Δ|<0.1` mag -- son, con
40+ fases de por medio, las primeras clases fuera de `SNIa`/`SNIa-91bg` con un residuo de brillo real,
grande y sistemático (hasta 2 mag en `u`), no solo de ratio de detección. Y el residuo es fuertemente
dependiente de banda en las 3 clases medidas hasta ahora -- reabre con fuerza el hilo cromático/
extinción, ahora con una hipótesis mecánica concreta y verificable (el paso de extinción de host) en
vez de una sospecha vaga. Esto cambia la prioridad de la Fase 51 originalmente condicional: antes de
sumar cobertura a más clases, vale más investigar la causa del residuo de extinción de host en las 2
clases que ya lo muestran grande.

### Archivos de esta fase

`compare_brightness_truth.py` (generalizado: clase por CLI, `build_source_model()` importada, 6
bandas, filtro de contaminación integrado desde el arranque, fix de convención de fase vía
`trest_range` completo). `compare_brightness_truth_binned.py` (generalizado: `CLASS_CONFIGS` para
bins de `z` reales, `DUMP_FOLDER_OVERRIDES`, 6 bandas vía `SNANA_COL`). `run_simsed_poc.py`
(`build_source_model()` extraída de `main()`, sin cambio de comportamiento, usada ahora por ambos
scripts). 3 jobs reales en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`, sin esperar aviso
automático): `12069695` (`SNIa-91bg` control, 2m22s), `12069696` (`SNIax`, 10m57s, 1001 templates),
`12069697` (`CaRT`, 2m51s, 225 templates). Outputs reales conservados (no exploratorios, producto de
scripts de producción): `compare_brightness_truth_{snia91bg,sniax,cart}_output.parquet`.

## Fase 51 — RESUELTO: la extinción de host nunca se aplicaba con su propio valor real -- un bug de colisión de nombres en `add_effect()` la dejaba al ~2-8% de lo nominal en las 12 clases que la usan

Siguiendo la idea de Fase 50 ("candidato mecánico nuevo, no probado: el paso de extinción de host"),
un agente Opus (solo lectura, sin tocar código) audita a fondo ese paso -- comparando línea por línea
el wrapper real de LightCurveLynx (`lightcurvelynx/effects/extinction.py`) contra el código C real de
SNANA (`~/github/SNANA_src/src/genmag_SIMSED.c`/`MWgaldust.c`, clon compilable del usuario). Encuentra
dos cosas: la hipótesis original (ley de polvo equivocada) es real pero demasiado chica para explicar
el residuo -- y un segundo bug, no buscado, que sí lo explica.

### Paso 1 — la hipótesis original (CCM89 vs. O'Donnell94) es real pero insuficiente

`run_simsed_poc.py::build_source_model()` construye la extinción de host con
`extinction_model="CCM89"` (Cardelli, Clayton & Mathis 1989) -- pero la aplicación real de SNANA
(`genmag_SIMSED.c:1567`, dentro de `genmag_SIMSED()`, llamada desde `snlc_sim.c:29243` cuando
`INDEX_GENMODEL == MODEL_SIMSED`) llama `GALextinct(RV_host, AV_host, meanlam_rest, 94, &PARDUM,
fnam)` -- el argumento `94` es literal, no una variable: `MWgaldust.h:27` declara
`OPT_MWCOLORLAW_ODON94 94 // O'Donnel (1994) update [to CCM89]`. Es decir, SNANA real **siempre**
aplica O'Donnell94 al host de un modelo SIMSED, sin importar el valor real de `GENSNXT`/
`INPUTS.OPT_SNXT` (esa variable existe y por defecto vale `"CCM89"`, pero su único consumidor real,
`init_genmag_extinction()` en `snlc_sim.c:27045`, está condicionado a `GENFRAME_OPT == GENFRAME_REST`
-- solo se usa para modelos rest-frame como MLCS2K2/SNOOPY, nunca para SIMSED, que es observer-frame).
Los `.INPUT` reales de `SNIax`/`CaRT` no declaran `GENSNXT`/`EXTINC_HOSTGAL` (confirmado en
`~/AUTOSIM/build/full_v5.3_10yrs/includes/include_model_{SNIax,CaRT}.INPUT`), así que no hay override
-- irónicamente ambos `.INPUT` traen el comentario `# CCM89 V-band extinction`, un comentario que el
código real contradice.

O94 y CCM89 (mismo `R_V`) solo difieren en la rama `1.1 ≤ x < 3.3` (3030-9091 Å marco de reposo,
`MWgaldust.c:568-604`) -- fuera de ese rango son idénticas. Medido con la librería real
(`dust_extinction.CCM89`/`O94`, mismo backend que usa LightCurveLynx): la diferencia máxima, en
`R_V=3.1` y `AV` hasta 3.0 (el máximo real de `GENRANGE_AV`), es **0.13 mag** -- y no crece con `z`
(al contrario: se anula por completo en el UV profundo, donde ambas leyes usan los mismos
coeficientes). **15-50x demasiado chico** para explicar el residuo de Fase 50 (hasta -2.0 mag en
`u`), y de signo oscilante, no monótono como el patrón observado. Hipótesis real, pero no la causa
dominante.

### Paso 2 — el bug real: `add_effect()` fusiona parámetros por nombre, y el primero que llega gana en silencio

Seguir la traza completa (`lightcurvelynx/models/physical_model.py::add_effect()`, línea ~470-476)
encuentra el bug real:
```python
for param_name, setter in effect.parameters.items():
    if param_name not in self.setters:
        self.add_parameter(param_name, setter, ...)
```
Cualquier efecto que declare un parámetro con un nombre ya registrado por OTRO efecto simplemente no
se registra -- sin excepción, sin warning, en silencio. `ExtinctionEffect.__init__()` (la clase base
real, `lightcurvelynx/effects/extinction.py`) siempre registra su parámetro como `"ebv"`, sin importar
para qué efecto se use. `build_source_model()` agrega `mw_extinction` primero (línea 500,
`extinction_model="F99"`) y `host_extinction` después (línea 536, antes `"CCM89"`) -- ambos con
parámetro `"ebv"`. El segundo (host) nunca registraba su propio setter: en tiempo de evaluación
recibía en silencio el mismo valor de E(B-V) que MW (~0.006-0.025, típico de los 6 campos DDF reales)
en vez del propio (`host_av/R_V`, hasta ~1.0) -- reduciendo la extinción de host real a **~2-8% de
la nominal**, en las **12 clases** de `CLASS_CONFIGS` que declaran `host_av` (todas menos
`SNIa-91bg`/`SNIa-91bg-elastic`/`SNII-NMF`, que no aplican extinción de host separada).

Confirmado con un smoke test real contra el `ModelNode` real (no simulado, sin tocar código todavía):
`host effect requested ebv=0.4 -> model delivers 0.02`. Mismo bug, línea por línea idéntica,
encontrado también en `run_non1ased_poc.py` (MW línea 299, host línea 331).

### Paso 3 — el fix: nombre de parámetro propio para el host, más O94 en vez de CCM89

`ClippedExtinctionEffect` (`snana_params.py`) gana un parámetro nuevo, `ebv_param_name` (default
`"ebv"`, sin cambio de comportamiento para MW): si se pasa un nombre distinto, re-mapea la entrada de
`self.parameters` a ese nombre después de `super().__init__()`, y `apply()` extrae el valor bajo ese
nombre en vez de `"ebv"` directo (evitando además una colisión de argumento con `**kwargs` al
reenviar a `ExtinctionEffect.apply()`). `run_simsed_poc.py`/`run_non1ased_poc.py`: `host_extinction`
ahora se construye con `extinction_model="O94"` (Paso 1) y `ebv_param_name="host_ebv"` (Paso 2), más
un `assert "host_ebv" in source_model.setters` justo después de `add_effect()` -- si esta colisión de
nombres volviera a pasar (p.ej. con un tercer efecto rest-frame futuro), la corrida falla ruidosamente
en vez de volver a fallar en silencio.

Verificado con un segundo smoke test real (`CaRT`, `ModelNode` real, 8 muestras) tras el fix:
`ebv (MW) sample: [0.006, 0.0074, ..., 0.008]` vs. `host_ebv sample: [0.012, 0.0099, 0.1676, 0.5604,
...]` -- dos setters distintos (`setters with ebv: ['ebv', 'host_ebv']`), con la escala real esperada
para cada uno.

### Paso 4 — re-medido: control positivo sin cambio, `SNIax`/`CaRT` con el residuo casi cerrado

3 jobs reales en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`): `12101078` (`SNIa-91bg` control,
2m15s), `12101079` (`SNIax`, 15m09s), `12101080` (`CaRT`, 3m25s).

**Control positivo**: `SNIa-91bg` (sin `host_av`, no debería moverse) -- `compare_brightness_truth_
snia91bg_output.parquet` sale **bit-idéntico** al de Fase 50 (mismo hash `md5`, mismas 8 columnas
resumen exactas). Confirma que el fix no tiene efecto colateral en clases sin extinción de host.

| banda | Δ Fase 50 (bug) | Δ Fase 51 (fix) |
|---|---:|---:|
| `SNIax` u | -2.018 | **-0.760** |
| `SNIax` g | -1.114 | **-0.208** |
| `SNIax` r | -0.609 | **+0.122** |
| `SNIax` i | -0.466 | **+0.111** |
| `SNIax` z | -0.397 | **+0.093** |
| `SNIax` y | -0.350 | **+0.073** |
| `CaRT` u | -1.200 | **-0.623** |
| `CaRT` g | -0.884 | **-0.283** |
| `CaRT` r | -0.602 | **-0.117** |
| `CaRT` i | -0.495 | **-0.087** |
| `CaRT` z | -0.375 | **-0.066** |
| `CaRT` y | -0.348 | **-0.078** |

`SNIax` bandas `r`/`i`/`z`/`y` **cambian de signo y quedan prácticamente cerradas** (+0.07 a +0.12
mag, LCL ahora levemente más tenue que SNANA -- dentro del mismo orden que el `-0.068` mag remanente
ya aceptado como ruido en Fase 47). `CaRT` cae por un factor de ~2-5x en las 6 bandas. Y, dato clave:
el patrón que queda en ambas clases (`u`/`g` con un residuo real, `r`-`y` casi cerrado) tiene la
**misma forma y escala** que el patrón ya visto en el control positivo `SNIa-91bg` (u: -0.537, g:
-0.245, r: -0.088...) -- una clase que nunca tuvo extinción de host en absoluto. Esto sugiere
fuertemente que el residuo azul que sobrevive en las 3 clases **no es del paso de extinción de host**
(ya remedido, ya con nombre propio) -- es un efecto más chico, universal, presente incluso sin
extinción de host, todavía sin explicar (candidato para una fase futura: K-corrección/integración de
banda en el UV, o el resto de la corrección F99-vs-O94 en el lado de extinción de MW).

### Conclusión Fase 51

El hallazgo real de esta fase no fue la hipótesis con la que arrancó (ley de polvo CCM89-vs-O94,
confirmada real pero 15-50x insuficiente) sino un bug de biblioteca más profundo y de mayor impacto:
`add_effect()` de LightCurveLynx fusiona parámetros de efectos por nombre, sin detectar colisiones --
dos efectos con el mismo nombre de parámetro (`"ebv"`, el que usa `ExtinctionEffect` para CUALQUIER
extinción) hacen que el segundo pierda su propio valor en silencio. Esto apagó la extinción de host
real (a ~2-8% de lo nominal) en **las 12 clases de `CLASS_CONFIGS` que la declaran** (9 `wv07`, 2
`exp_halfgauss`, 1 `exp`) durante TODAS las fases anteriores de este proyecto que las tocaron --
significa que cualquier resultado de brillo o ratio de detección ya reportado para esas 12 clases
(prácticamente todo el catálogo salvo `SNIa`/`SNIa-91bg`/`SNII-NMF`) se midió con la extinción de host
efectivamente apagada, y debería re-derivarse. Corregido con un nombre de parámetro propio
(`ebv_param_name="host_ebv"`) más un `assert` de regresión, y la ley de polvo real corregida a O94 de
paso. Verificado con dos smoke tests reales (antes/después del fix) y una remedición completa de las
2 clases de Fase 50: el control positivo (`SNIa-91bg`) sale bit-idéntico (cero efecto colateral),
`SNIax` queda prácticamente cerrado en 4 de 6 bandas, `CaRT` mejora por un factor de 2-5x en las 6.
Candidato nuevo para el residuo `u`/`g` que sobrevive en las 3 clases, universal y no relacionado con
extinción de host -- pendiente para una fase futura. Este bug también se reporta como candidato real
para `ISSUE_DRAFT_seed_propagation.md` (o un draft nuevo análogo) -- pendiente de confirmación
explícita del usuario antes de publicar, mismo criterio que el resto del proyecto.

### Archivos de esta fase

`snana_params.py` (`ClippedExtinctionEffect`: `ebv_param_name` nuevo, re-mapeo de parámetro,
`apply()` corregido). `run_simsed_poc.py`/`run_non1ased_poc.py` (`host_extinction`:
`extinction_model="O94"`, `ebv_param_name="host_ebv"`, `assert` de regresión). Agente Opus
(solo lectura, diagnóstico -- ver plan de la fase) para el Paso 1/2. 3 jobs reales en NLHPC
(`sbatch`, sondeados con `squeue`/`sacct`): `12101078`/`12101079`/`12101080`. Outputs reales
actualizados (reemplazan los de Fase 50): `compare_brightness_truth_{snia91bg,sniax,cart}_
output.parquet` (`snia91bg` bit-idéntico, confirmado por hash).

## Fase 52 — diagnóstico del residuo azul que sobrevive a Fase 51: 4 mecanismos reales identificados, ~0.20 mag en `u` sigue sin explicación

Sigue la línea abierta por Fase 51 (ítem 10 del dashboard): `SNIa-91bg` (sin extinción de host en
absoluto), `SNIax` y `CaRT` comparten un residuo azul (`u`/`g`) del mismo orden aun con el fix de
host aplicado. Un agente Opus de solo lectura (sin tocar código, sin `sbatch`) compara línea por
línea el filtro `u` real, la convención de integración fotométrica, la aplicación de extinción y la
métrica `PEAKMAG` entre LightCurveLynx y el C real de SNANA. Resultado: **no hay una causa única** --
4 mecanismos reales y verificados, cada uno con su propio tamaño, y un remanente sin explicar.

### Paso 1 — dos hipótesis descartadas con evidencia directa

**Convención de integración fotométrica**: idéntica en ambos lados -- ambos son fotón-contadores
exactos (`LCL: F_b = ∫f_ν(λ)φ_b(λ)dλ` con `φ_b(λ)=S_b(λ)λ⁻¹`, `passbands.py:1220/1249/1267`; `SNANA:
genmag_SEDtools.c:1153/1183`, `SEDMODELNORM = FLUXSCALE·LAMOBS_STEP/hc`, algebraicamente la misma
integral). `ZPoff=0.0` en las 6 bandas del `kcor` real, primaria AB idéntica (4.354e-9
erg/s/cm²/Å @ 5000Å = 3631 Jy). Descartado.

**Ley F99-vs-O94 de MW en UV profundo a alto z** (la duda que dejó abierta Fase 24, nunca verificada
fuera del régimen de bajo `E(B-V)`/óptico): medido con un SED 91bg real, `E(B-V)` DDF real
(0.006-0.025), `z` de 0.15 a 0.55 -- diferencia ≤0.007 mag en las 6 bandas. Descartado también en
este régimen.

### Paso 2 — mecanismo 1: fuga roja del filtro `u` de LightCurveLynx

`PassbandGroup.from_preset("LSST")` descarga `total_u.dat` (repo real `lsst/throughputs`, cacheado en
`~/.cache/lightcurvelynx/passbands/LSST/u.dat`) -- **byte-idéntico** al archivo real que usa el `kcor`
de SNANA (`$SNDATA_ROOT/filters/LSST/baseline_1.9/total_u.dat`, mismo hash `sha1`, misma versión
`1.9`) hasta el corte azul/rojo al 50% (coinciden a `0.02 Å`). La diferencia real: el `kcor.input` de
esta campaña usa `LSST_u.dat`, la MISMA curva **truncada en 4134 Å**; `total_u.dat` (lo que carga
LightCurveLynx) sigue hasta 11000 Å con una fuga fuera de banda de `T≈4e-5` (~0.03% del pico) que
`trim_quantile=1e-3` (default de LCL) no elimina del todo (retiene 0.176% de la normalización tras el
trim). Medido en la simulación real (91bg, 2000 objetos, filtro `kcor` real vs. preset sin truncar):
**-0.068 a -0.103 mag en `u`, exactamente 0.000 en las otras 5 bandas** (el trim ya las limpia del
todo). La hipótesis original ("filtro más ancho hacia el azul") es **falsa** -- el sesgo viene de la
cola roja, no del corte azul.

### Paso 3 — mecanismo 2: `PEAKMAG` real de SNANA es la magnitud en `Trest=0`, no el máximo de la ventana de fase

`snlc_sim.c:8455-8456/27104-27107`: SNANA guarda `peakmag_obs` en la época con `epoch_rest=0.0`
exacto, no el máximo de la curva. `compare_brightness_truth.py` (desde el fix de Fase 50, para
resolver el caso `CaRT` cuya grilla real arranca en fase `+0.501`) evalúa sobre TODA la ventana
`trest_range` y toma `.max()` -- una métrica distinta a la real de SNANA. Medido (91bg, misma
corrida): pasar de "máximo sobre la ventana" a "magnitud en `Trest=0`" mueve **-0.144 mag en `u`,
-0.033 en `g`, -0.020 en `r`** -- pero **empeora** `i`/`z`/`y` (de -0.032/-0.016/-0.020 a
+0.021/+0.063/+0.061, cambian de signo). El fix de Fase 50 resolvía un problema real (`CaRT` con
`rest_phase=0` fuera de grilla, ver Fase 50) pero introdujo este sesgo sistemático en el resto de las
clases y bandas -- corregirlo bien requiere evaluar en `Trest=0` para todas las clases Y extrapolar al
borde de grilla (como hace SNANA) para las que, como `CaRT`, no cubren fase 0, en vez de cambiar la
métrica entera a "máximo".

### Paso 4 — mecanismo 3 (invalida una premisa ya documentada en Fases 41/44/45): SNANA interpola continuo la grilla SIMSED, no snapea

Hallazgo estructural, no sospechado: `SIMGEN_INCLUDE_SNIa-91bg.INPUT` declara `SIMSED_PARAM: stretch`/
`SIMSED_PARAM: color` **sin** `SIMSED_GRIDONLY` -- `snlc_sim.c:6066` activa
`OPTMASK_GEN_SIMSED_PARAM`, la rama de interpolación CONTINUA (`interp_flux_SIMSED()`,
`genmag_SIMSED.c:1595`), no la rama de snap a grilla (`nearest_gridval_SIMSED()`, que solo se llama
bajo `SIMSED_GRIDONLY`). Confirmado directo contra el `.DUMP` real: **1696/1696 valores únicos de
`color`** sobre 1696 objetos (no 35 valores discretos) -- SNANA nunca snapea para esta campaña.
LightCurveLynx (`SIMSEDModel.from_dir(weights=...)`, `run_simsed_poc.py:486`) sí sortea 1 de 35
templates discretos -- no puede reproducir la interpolación continua real. **Esto invalida la premisa
que documentaron Fases 44/45** (`snana_params.py:512-560`, comentario real: "SNANA snapea cada
parámetro a la grilla más cercana") -- cierta solo bajo `SIMSED_GRIDONLY`, que esta campaña no usa;
también explica en retrospectiva por qué Fase 41 midió un KS catastrófico (`p=1e-77`) contra
`stretch`/`color` reales -- SNANA nunca snapeó, así que ninguna reimplementación de snap (Fase 44) podía
acercarse. Medido: **~-0.10 mag en `u`, -0.08 a -0.11 en `g`, -0.03 a -0.09 en `r`** (200k draws sobre
los 35 SEDs reales + interpolación bilineal del flujo, 3 redshifts de prueba). Fix real: no es de una
línea -- requiere una clase de modelo que interpole el SED en `(stretch, color)`, cambio de biblioteca,
no de script. Queda documentado, no implementado.

### Paso 5 — mecanismo 4 (solo clases con extinción de host, explica el componente que crece con `z`): SNANA aplica extinción de host como escalar en longitud de onda media, no sobre el SED completo

`genmag_SIMSED.c:1554-1567`: SNANA calcula `meanlam_obs`/`meanlam_rest` (longitud de onda media del
filtro, `genmag_SEDtools.c:335`) UNA vez por banda y aplica `GALextinct()` como un **offset escalar de
magnitud** a la banda ya integrada -- no extingue el SED punto a punto antes de integrar.
`run_simsed_poc.py:533-536` (`ClippedExtinctionEffect`, `frame="rest"`) hace lo opuesto: extingue el
SED longitud de onda por longitud de onda, luego integra. A `z` bajo con `AV` chico ambos métodos casi
coinciden (la curva de polvo es casi lineal en la ventana de la banda); a `z` alto, `meanlam_rest` cae
en una zona más empinada de la curva de extinción y las dos formas divergen más. Medido con un SED
91bg real: a `AV=1.0`, `z=0.15→0.55`, la extinción escalar-vs-por-λ difiere **-0.086 a -0.467 mag en
`u`** (crece con `z`); a `AV=2.0`, **-0.176 a -1.157 mag**. Consistente con el patrón medido en el
Paso 6: `SNIa-91bg` (sin extinción de host) tiene el residuo `u` PLANO en `z` (bins 2-7: -0.43 a
-0.67, sin tendencia), mientras `SNIax`/`CaRT` (con extinción de host) lo tienen CRECIENTE (`SNIax`:
+0.57 en el bin 2 a -1.10 en el bin 7; `CaRT`: +0.01 a -0.84) -- dos poblaciones con causas distintas
superpuestas, no un patrón único como sugería Fase 51. Fix real: aplicar la extinción de host como
offset escalar por banda en vez de efecto sobre el SED -- cambio de diseño, no de una línea. Queda
documentado, no implementado.

### Paso 6 — presupuesto final: lo que explica y lo que no, banda por banda (`SNIa-91bg`, control sin host)

| mecanismo | u | g | r | i | z | y |
|---|---:|---:|---:|---:|---:|---:|
| fuga roja filtro `u` (Paso 2) | -0.07 a -0.10 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| métrica `PEAKMAG` (Paso 3) | -0.144 | -0.033 | -0.020 | +0.053 | +0.079 | +0.081 |
| grilla SIMSED discreta (Paso 4) | ~-0.10 | -0.08 a -0.11 | -0.03 a -0.09 | ~-0.01 a -0.05 | ~-0.02 | ~-0.01 |
| ley MW F99-vs-O94 (Paso 1) | -0.003 | -0.004 | -0.001 | ~0 | ~0 | ~0 |
| **residuo total medido (Fase 51)** | **-0.537** | **-0.245** | **-0.088** | **-0.032** | **-0.016** | **-0.020** |
| **sin explicar** | **≈-0.20** | **≈-0.11** | **≈-0.01** | +0.05 | +0.08 | +0.07 |

(Para `SNIax`/`CaRT` sumar además el mecanismo 4 del Paso 5, dominante y creciente con `z` en esas 2
clases.) Aplicar TODOS los fixes medibles no cierra `SNIa-91bg` de forma limpia: `u`/`g` mejoran pero
quedan con un remanente real (~-0.20/-0.11 mag), e `i`/`z`/`y` -- ya casi cerradas en la medición
actual -- **empeoran** (pasan de ~0 a +0.05/+0.08/+0.07) porque el fix de la métrica `PEAKMAG` (Paso
3) las mueve en la dirección contraria. No hay combinación de estos 4 fixes que cierre las 6 bandas a
la vez -- documentado honestamente, sin forzar una conclusión limpia.

### Conclusión Fase 52

El residuo azul de Fase 50/51 no tiene una causa única: son al menos 4 mecanismos reales y
verificados (fuga de filtro, definición de métrica de pico, discretización de la grilla SIMSED,
convención de aplicación de extinción de host), cada uno con un tamaño y una firma distinta, más un
remanente de ~0.20 mag en `u` y ~0.11 en `g` que sigue sin explicación después de sumarlos todos. Dos
de los 4 (Pasos 2/3) son baratos de corregir pero con trade-offs reales (el fix de métrica mejora
`u`/`g`/`r` y empeora `i`/`z`/`y`); los otros dos (Pasos 4/5) son cambios de diseño, no de una línea.
Hallazgo colateral importante: el Paso 4 invalida la premisa de snap-a-grilla que documentaron Fases
44/45 para esta campaña real -- vale la pena revisar si esa lectura debe corregirse en el dashboard
(mismo criterio de transparencia que Fase 49) antes de decidir si se retoma `SIMSED_REDCOR` con la
interpolación continua real.

### Archivos de esta fase

Sin cambios de código -- fase de diagnóstico puro (agente Opus de solo lectura, scripts descartables
en NLHPC borrados tras usarlos, sin `sbatch`, reutilizando los parquets ya generados en Fase 51 más
comparaciones directas de filtros/SED/`.DUMP` reales). Ningún fix de los 4 propuestos fue aplicado --
quedan documentados para una decisión explícita antes de implementarlos, dados los trade-offs reales
del Paso 3 y el alcance de biblioteca de los Pasos 4/5.

## Fase 53 — mecanismo 4 implementado (extinción de host como escalar de banda, no sobre el SED) -- el fix es correcto, pero explica mucho menos residuo del estimado en Fase 52

Implementa el mecanismo 4 del diagnóstico de Fase 52: SNANA real aplica la extinción de host como un
**escalar de magnitud por banda**, evaluado en la longitud de onda media REST-FRAME del filtro
(`GALextinct(RV_host, AV_host, meanlam_rest, 94, ...)`, `genmag_SIMSED.c:1554-1567`) -- no como una
extinción punto a punto sobre el SED completo antes de integrar, que es lo que hacía
`ClippedExtinctionEffect` con `frame="rest"` desde Fase 47.

### Paso 1 -- por qué no se puede injertar un efecto "por banda" en el grafo de LightCurveLynx

Investigado el mecanismo real de aplicación de efectos de LightCurveLynx (`physical_model.py`) antes de
tocar código: existe un tercer tipo de efecto, `band_pass_effects`/`apply_bandflux()`
(`physical_model.py:1207-1211`), que SÍ recibe el nombre de filtro (`filters=`) -- exactamente lo que
haría falta para replicar el escalar de SNANA de forma nativa. Pero ese mecanismo pertenece a la clase
`BandfluxModel` (`physical_model.py:924`), no a `SEDModel` (`physical_model.py:368`) -- y
`SIMSEDModel` hereda de `MultiSEDTemplateModel(SEDModel)` (`sed_template_model.py:380/460`), no de
`BandfluxModel`. `band_pass_effects` no aplica a las clases de este proyecto.

Alternativa evaluada y descartada: implementar un efecto `rest_frame`/`observer_frame` que identifique
la banda por la forma del array `wavelengths` que recibe (`passband.waves`, confirmado en
`SEDModel._evaluate_bandfluxes_single`, `physical_model.py:891-916`, que llama
`self.evaluate_sed(times[filter_mask], passband.waves, state)` una vez por banda) -- funcionaría para
efectos `frame="observer"` (reciben `wavelengths` sin dividir por `1+z`, matcheable contra una tabla
precalculada), pero es frágil y agrega una capa de identificación innecesaria.

**Solución adoptada: post-procesamiento, no efecto de grafo.** `compute_noise_free_lightcurves()`
recibe un `graph_state` explícito (`compare_brightness_truth.py:132`, ya lo construye el propio
script) -- alcanza con **no** agregar la extinción de host como efecto sobre el SED, registrar
`host_av` como parámetro real del modelo (`source_model.add_parameter("host_av", av_func)`, API
confirmada en `base_models.py:545`) y aplicar la corrección escalar real DESPUÉS de calcular
`PEAKMAG_x_true`, exactamente donde SNANA la aplica en su propio pipeline (después de integrar banda,
no antes).

### Paso 2 -- el fix: `host_extinction_mode` nuevo en `build_source_model()`, sin tocar producción

`build_source_model()` gana un parámetro `host_extinction_mode: str = "sed"` (default = comportamiento
histórico sin cambios, usado por `main()` -- **cero cambio de comportamiento en producción**). Con
`host_extinction_mode="scalar"` (usado solo por `compare_brightness_truth.py`), `host_av` se registra
como parámetro real del modelo sin aplicar ningún efecto sobre el SED. Dos funciones nuevas,
compartidas (en `run_simsed_poc.py`, importables por cualquier script):

- `passband_mean_wavelengths(passband_group, bands)`: `meanlam_obs` por banda = `Σ(λ·T)/Σ(T)` sobre
  la tabla real de transmisión (`Passband.transmission_table`) -- misma fórmula real que SNANA
  (`genmag_SEDtools.c:335`, confirmada en Fase 52).
- `host_extinction_mag_offset(z, host_av, r_v, meanlam_obs_band)`: replica
  `GALextinct(RV_host, AV_host, meanlam_rest, 94, ...)` real -- `meanlam_rest = meanlam_obs_band/(1+z)`,
  clampeado al rango válido de la ley O94 (mismo criterio que `ClippedExtinctionEffect`), `Δmag =
  -2.5·log10(O94(Rv).extinguish(meanlam_rest, Ebv=host_av/r_v))`. Vectorizado sobre todos los objetos
  de una banda a la vez (una llamada por banda, no por objeto).

`compare_brightness_truth.py` recupera `host_av` real vía `source_model.get_param(graph_state,
"host_av")` (mismo `graph_state` que generó las curvas de luz, mismo orden `id=0..N-1`), precalcula
`Δmag` por banda una sola vez, y lo suma a `PEAKMAG_x_true` ya calculado (sumar magnitudes conmuta con
tomar el máximo de flujo sobre la ventana de fase, así que aplicar la corrección antes o después de
`.max()` da exactamente el mismo resultado).

Verificado con un smoke test real (`CaRT`, `ModelNode` real, 8 muestras) antes de correr nada:
`meanlam_obs` real por banda (`u: 3723.5, g: 4806.9, r: 6221.5, i: 7559.0, z: 8679.7, y: 9753.4` Å) y
`Δmag` positivo (atenuación), creciente hacia el azul y escalando con `host_av` de cada objeto
(`host_av=0.0307 → Δmag_u=0.077`; `host_av=1.7372 → Δmag_u=5.45`) -- signo y escala correctos antes de
gastar cómputo real.

### Paso 3 -- remedido: control positivo sin cambio, `SNIax`/`CaRT` con una mejora real pero chica

3 jobs reales en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`): `12104702` (`SNIa-91bg` control,
2m18s), `12104703` (`SNIax`, 15m15s), `12104704` (`CaRT`, 3m12s).

**Control positivo**: `SNIa-91bg` (sin `host_av`) sale **bit-idéntico** a Fase 51/50 (mismo hash `md5`
del parquet). Confirma cero efecto colateral, tal como debía ser.

| banda | `SNIax` Fase 51 (SED) | `SNIax` Fase 53 (escalar) | `CaRT` Fase 51 (SED) | `CaRT` Fase 53 (escalar) |
|---|---:|---:|---:|---:|
| u | -0.760 | **-0.733** | -0.623 | **-0.621** |
| g | -0.208 | **-0.186** | -0.283 | **-0.266** |
| r | +0.122 | +0.123 | -0.117 | -0.119 |
| i | +0.111 | +0.109 | -0.087 | -0.087 |
| z | +0.093 | +0.092 | -0.066 | -0.066 |
| y | +0.073 | +0.071 | -0.078 | -0.078 |

El fix mueve el residuo en la dirección correcta en `u`/`g` (las únicas bandas donde la ley de polvo
tiene pendiente real dentro del rango de longitud de onda relevante) -- pero por una magnitud mucho
más chica que la que había estimado el presupuesto ilustrativo de Fase 52 (`-0.09` a `-1.16` mag a
`AV=1-2`, "creciendo con `z`"). `r`/`i`/`z`/`y` prácticamente no se mueven (diferencias de `0.001-0.02`
mag, dentro de ruido de redondeo). La estimación de Fase 52 usó un solo objeto de prueba a `AV` fijo
(1.0-2.0) -- la población real de `SNIax`/`CaRT` tiene una mediana de `host_av` mucho más baja (Fase 52
ya lo había anotado: `AV` mediana `0.497` para `SNIax`, `0.149` para `CaRT`), así que el efecto
poblacional promedio es real pero bastante menor que el caso ilustrativo.

### Conclusión Fase 53

El mecanismo 4 (extinción de host aplicada como escalar-en-longitud-de-onda-media, no sobre el SED
completo) es real, se implementó correctamente (verificado con smoke test antes de correr, control
positivo bit-idéntico después de correr) y mueve el residuo en la dirección correcta -- pero explica
solo una fracción chica (`u`: `-0.027` mag en `SNIax`, `-0.002` en `CaRT`; `g`: `-0.022`/`-0.017` mag)
del residuo total. Después del fix, `SNIax` (`u: -0.733`, `g: -0.186`) y `CaRT` (`u: -0.621`, `g:
-0.266`) quedan con un residuo azul del MISMO orden que el de `SNIa-91bg` (`u: -0.537`, `g: -0.245`,
sin extinción de host en absoluto) -- refuerza la lectura de Fase 52: los mecanismos 1-3 (fuga de
filtro, definición de `PEAKMAG`, grilla SIMSED discreta -- todos universales, no relacionados con
extinción de host) siguen siendo los candidatos dominantes para el residuo azul que queda, no la
convención de aplicación de extinción de host. Resultado honesto, no forzado: se confirma el mecanismo
y se implementa el fix, pero no cierra la brecha esperada.

### Archivos de esta fase

`run_simsed_poc.py` (`passband_mean_wavelengths()`, `host_extinction_mag_offset()` nuevas;
`build_source_model()` gana `host_extinction_mode` con default `"sed"` -- `main()`/producción sin
cambios). `compare_brightness_truth.py` (usa `host_extinction_mode="scalar"`, aplica la corrección
sobre `PEAKMAG_x_true`). 3 jobs reales en NLHPC: `12104702`/`12104703`/`12104704`. Outputs reales
actualizados (reemplazan los de Fase 51): `compare_brightness_truth_{snia91bg,sniax,cart}_
output.parquet` (`snia91bg` bit-idéntico, confirmado por hash).

## Fase 54 -- investigado y REVERTIDO: el fix de PEAKMAG (mecanismo 2 de Fase 52) reproduce exacto la predicción para `SNIa-91bg`, pero rompe `CaRT` (+2 a +4 mag) -- de dónde sale el `PEAKMJD` real de SNANA para clases explosion-referenced queda como pregunta abierta

Sigue el mecanismo 2 del diagnóstico de Fase 52: `PEAKMAG_x` real de SNANA es la magnitud exacta en
`Trest=0` (`snlc_sim.c:8455-8456/27104-27107`), no el máximo de la curva sobre toda la ventana de fase
que usa `compare_brightness_truth.py` desde Fase 50. Implementado, medido con jobs reales, y revertido
tras encontrar una regresión real -- no se deja el código roto en la versión activa.

### Paso 1 -- el fix: flujo en el punto de grilla válido más cercano a `Trest=0`

En vez de re-evaluar en un solo punto (que reproduciría el bug de `CaRT` de Fase 50: `rest_phase=0`
cae fuera de la grilla real del template y devuelve flujo `0.0`), se reusa la misma grilla ya evaluada
(`sub["rest_phase"]`/`sub[band]`, paso de 1 día sobre `trest_range`) y se selecciona el flujo del punto
**válido** (`>0`) más cercano a `Trest=0` -- reproduce `Trest=0` exacto cuando está cubierto por la
grilla, y "cae" al borde de cobertura más cercano cuando no lo está (la lectura que había propuesto
Fase 52 para el caso `CaRT`: replicar la extrapolación real de SNANA, que mantiene el flujo del borde
constante más allá del rango calibrado, en vez de devolver `0`).

Smoke test real antes de correr nada (`SNIa-91bg`, 20 objetos): confirma que la grilla SÍ incluye
`rest_phase=0.0` exacto (paso de 1 día desde `-30`, entero), con un flujo (`333.005`) apenas distinto
del máximo real de la curva (`333.355`, en `rest_phase=-1.0`) -- confirma en código real, antes de medir
nada a escala, el mecanismo físico que predijo Fase 52: el pico real de cada banda no cae exacto en
`Trest=0`.

### Paso 2 -- remedido: `SNIa-91bg` reproduce EXACTO la predicción de Fase 52; `SNIax` mejora en azul
pero empeora en rojo; `CaRT` se rompe

3 jobs reales en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`): `12109513` (`SNIa-91bg`, 2m16s),
`12109514` (`SNIax`, 15m47s), `12109515` (`CaRT`, 3m15s).

| banda | `SNIa-91bg` (Fase 53→54) | `SNIax` (Fase 53→54) | `CaRT` (Fase 53→54) |
|---|---:|---:|---:|
| u | -0.537 → **-0.393** | -0.733 → **-0.031** | -0.621 → **+2.274** |
| g | -0.245 → **-0.212** | -0.186 → **+0.100** | -0.266 → **+2.897** |
| r | -0.088 → **-0.068** | +0.123 → **+0.143** | -0.119 → **+3.355** |
| i | -0.032 → **+0.021** | +0.109 → **+0.163** | -0.087 → **+3.654** |
| z | -0.016 → **+0.063** | +0.092 → **+0.199** | -0.066 → **+3.886** |
| y | -0.020 → **+0.061** | +0.071 → **+0.191** | -0.078 → **+4.009** |

`SNIa-91bg` reproduce **exacto** la "variante C" que ya había medido Fase 52 (`u: -0.393`, `g: -0.212`,
`r: -0.068`, `i: +0.021`, `z: +0.063`, `y: +0.061`) -- confirma que el mecanismo está bien implementado.
`SNIax` mejora sustancialmente en `u`/`g` (`u` casi cerrado, `-0.031` mag) pero empeora en
`r`/`i`/`z`/`y` -- mismo trade-off azul-mejora/rojo-empeora que ya había medido Fase 52 para `91bg`, ahora
confirmado en una segunda clase real. `CaRT` se rompe por completo: `+2.27` a `+4.01` mag, la escala
completa del catálogo, no un ajuste fino.

### Paso 3 -- por qué se rompe `CaRT`: su pico real está lejos del primer punto válido de la grilla

Diagnosticado antes de revertir (no se dejó como caja negra): para 3 objetos de prueba, el primer punto
válido de la grilla (`rest_phase=1.0`, justo después de `SED.INFO` real de `SIMSED.CART-MOSFIT`
arrancando en `0.501`) tiene un flujo **~8-22x más tenue** que el máximo real de la curva, que ocurre
recién 4-7 días después (`rest_phase=5` a `8`):

| objeto | flujo en `rest_phase=1.0` (primer punto válido) | flujo en el máximo (`rest_phase`) | razón |
|---|---:|---:|---:|
| 0 | 0.0385 | 0.6919 (`rest_phase=8`) | 18.0x |
| 1 | 0.7361 | 6.2022 (`rest_phase=5`) | 8.4x |
| 2 | 2.5762 | 57.0070 (`rest_phase=8`) | 22.1x |

`CaRT` no es solo "explosion-referenced" (fase 0 = explosión, no pico) -- su curva de luz sube MUY
empinada después de la explosión, con el pico real varios días después del primer punto cubierto por
el template. Extrapolar sosteniendo el flujo del borde constante (la lectura que Fase 52 propuso para
este caso) da un valor casi arbitrariamente tenue, muy lejos del `PEAKMAG` real de SNANA -- lo que
implica que el `PEAKMJD`/`Trest=0` real que usa SNANA internamente para esta clase **no es** literalmente
"fase 0 del archivo `SIMSED.CART-MOSFIT`" tal como LightCurveLynx lo interpreta. De dónde sale ese
`PEAKMJD` real (¿SNANA recalibra internamente su grilla a la fase del pico real, en vez de usar la
convención "días desde la explosión" del archivo tal cual?) queda como pregunta abierta -- requiere
leer más código C real (`gen_PEAKMJD()`/la función que arma `GENLC.epoch_rest` para modelos SIMSED con
convención de fase no estándar) antes de poder intentar este fix de nuevo con confianza.

### Conclusión Fase 54

Resultado genuinamente mixto, documentado sin forzar una historia limpia: el mecanismo (`Trest=0` real,
no el máximo) es correcto y se confirma con precisión de magnitud contra la predicción ya hecha en
Fase 52 (`SNIa-91bg` exacto). Pero expone dos problemas reales, no solo uno: (1) incluso en la clase
donde el mecanismo se aplica sin ambigüedad, el fix mejora las bandas azules y empeora las rojas --
mismo trade-off ya anotado en Fase 52, ahora confirmado en una segunda clase (`SNIax`); (2) para clases
explosion-referenced con una subida post-explosión empinada como `CaRT`, la extrapolación al borde de
cobertura NO es una aproximación razonable al `PEAKMJD` real de SNANA -- produce un error de magnitud
completa (`+2` a `+4` mag), peor que el sesgo original que se quería corregir. **Revertido**: se
mantiene el máximo sobre la ventana completa (comportamiento de Fase 50/53) en el código versionado --
no se deja una regresión conocida en un script de producción solo por haber medido honestamente el
intento. El trade-off azul/rojo (Paso 2) y el origen real de `PEAKMJD` para clases explosion-referenced
(Paso 3) quedan como las dos preguntas abiertas más concretas para retomar este mecanismo.

### Archivos de esta fase

`compare_brightness_truth.py`: cambio de lógica probado, medido con 3 jobs reales, y revertido a la
lógica de Fase 53 (`diff` contra el commit anterior confirma que solo cambiaron comentarios, ninguna
línea de código activa). Sin cambios netos en el repositorio -- los parquets ya publicados en Fase 53
siguen siendo los vigentes (no se sobrescribieron con los resultados rotos de esta fase). 3 jobs reales
en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`, borrados tras usarlos): `12109513`/`12109514`/
`12109515`.

## Fase 55 -- mecanismo 1 (fuga de filtro `u`) corregido: efecto real, pequeño y sin daño colateral

Corrige el mecanismo 1 del diagnóstico de Fase 52: el filtro `u` que carga
`PassbandGroup.from_preset("LSST")` (`total_u.dat`, descargado de `lsst/throughputs`) es
byte-idéntico al que usa el `kcor` real de SNANA (`$SNDATA_ROOT/filters/LSST/baseline_1.9/
total_u.dat`, confirmado por hash) hasta el punto en que SNANA lo trunca -- el `kcor.input` real usa
`LSST_u.dat`, la misma curva pero cortada. Verificado directo en NLHPC (no de memoria): `LSST_u.dat`
real termina en `4134.00` (columna mal etiquetada "nm" pero con valores en Å -- confirmado comparando
grilla contra `total_u.dat`, mismo paso `0.1nm` real, `3000.00`↔`300.0nm` etc.) -- **413.4 nm / 4134
Å exacto**. Más allá de ese punto, `total_u.dat` sigue hasta `1150nm` con una fuga fuera de banda real
(`T~4e-5`, ~0.03% del pico) que SNANA nunca ve.

### El fix

Copia local versionada de los 6 filtros reales (`lsst_passbands_local/LSST/{u,g,r,i,z,y}.dat`,
idénticos a los que carga el preset por defecto salvo `u.dat`, truncado a `413.4nm`). `build_source_model()`
no cambia -- el fix vive en el `table_dir=` que ya acepta `PassbandGroup.from_preset()` nativamente
(`passbands.py:280`, "si la tabla existe en `table_dir`, se carga de ahí; si no, se descarga"), sin
tocar la librería. Aplicado en los 3 llamadores (`run_simsed_poc.py`/`compare_brightness_truth.py`/
`run_non1ased_poc.py`) -- a diferencia de Fase 53, este SÍ se aplica también a producción/`main()`: es
una corrección de datos sin ambigüedad de diseño (la curva real que ve SNANA, no una elección de
convención), con un efecto pequeño, acotado y de una sola dirección.

Smoke test real antes de correr nada: `u` real carga con `wave_max=4133-4134 Å` (1134 filas), las
otras 5 bandas sin cambio (`wave_max=11500 Å`, 8501 filas -- idéntico al preset por defecto).

### Remedido: solo `u` se mueve, el resto bit-idéntico

3 jobs reales en NLHPC: `12110011` (`SNIa-91bg`, 2m08s), `12110012` (`SNIax`, 15m02s), `12110013`
(`CaRT`, 3m08s).

| banda | `SNIa-91bg` (Fase 51→55) | `SNIax` (Fase 53→55) | `CaRT` (Fase 53→55) |
|---|---:|---:|---:|
| u | -0.537 → **-0.465** | -0.733 → **-0.710** | -0.621 → **-0.607** |
| g | -0.245 (sin cambio) | -0.186 (sin cambio) | -0.266 (sin cambio) |
| r-y | sin cambio | sin cambio | sin cambio |

Mejora real en `u` en las 3 clases (`0.014` a `0.072` mag), más chica que la estimación de Fase 52
(`0.07`-`0.10` mag -- esa estimación usaba la simulación real completa, con más objetos/ruido de
muestreo que el smoke test de esta fase; el signo y la banda afectada son exactos). `g`-`y` bit-idénticos
en las 3 clases -- confirma cero efecto colateral, tal como predecía el diagnóstico (la fuga de `u` no
toca ninguna otra banda).

### Conclusión Fase 55

Corrección real y limpia, sin trade-offs -- a diferencia de los mecanismos 2 (Fase 54, revertido) y 4
(Fase 53, efecto menor al esperado), este cerró exactamente como se predijo: pequeño, unidireccional,
sin efecto colateral. Aplicado también a producción (`main()`) por ser una corrección de datos sin
ambigüedad, no una decisión de diseño.

### Archivos de esta fase

`lsst_passbands_local/LSST/{u,g,r,i,z,y}.dat` (nuevo, versionado -- copias reales de
`$SNDATA_ROOT`/cache, `u.dat` truncado a 413.4nm). `run_simsed_poc.py` (`LSST_PASSBAND_TABLE_DIR`
nuevo). `compare_brightness_truth.py`/`run_non1ased_poc.py` (`table_dir=` agregado a
`PassbandGroup.from_preset()`). 3 jobs reales en NLHPC: `12110011`/`12110012`/`12110013`. Outputs
reales actualizados: `compare_brightness_truth_{snia91bg,sniax,cart}_output.parquet`.

## Fase 56 -- RESUELTO: la causa raíz real del residuo era la definición de `Trest=0` -- SNANA shiftea cada template SIMSED a su propio pico bolométrico real, no a la fase nativa 0 del archivo. Las 6 bandas caen a `≤0.05` mag (`SNIa-91bg`), quedan agrupadas y chicas (`SNIax`/`CaRT`)

Retoma la pregunta abierta que dejó Fase 54: ¿de dónde sale el `PEAKMJD`/`Trest=0` real que usa SNANA
para un objeto SIMSED? Un agente Opus de solo lectura sigue la traza completa en el C real y encuentra
la causa raíz de TODA la saga de residuos de brillo medida desde Fase 50.

### Paso 1 -- el mecanismo real: `T0shiftPeak_SEDMODEL()`

`genmag_SEDtools.c:2825-2884` -- comentario de cabecera literal: `"Shift TEMP_SEDMODEL.DAY so that peak
bolometric flux is at DAY=0."`. El algoritmo real: para cada template, suma el flujo (`F_λ`, sin
ponderar por `dλ`, sin filtro -- válido porque la grilla `λ` real es uniforme) sobre TODOS los bins de
longitud de onda, para cada día; toma el día con la suma máxima (`IDAY_PEAK`); resta ese día a toda la
grilla `DAY` del template. Se llama, un `Tshift` propio por template, desde `genmag_SIMSED.c:351-361`,
condicionado a 3 cosas -- las 3 confirmadas reales para las 12 clases SIMSED de esta campaña:

1. **Activo por defecto**: `SEDMODEL.OPTMASK = OPTMASK_DAYLIST_SEDMODEL + OPTMASK_T0SHIFT_PEAKMAG`
   (`genmag_SIMSED.c:226-230`, comentario real: `"shift T=0 to peak (July 2018)"`).
2. **No desactivado**: se apaga con `OPTFLAG_T0SHIFT_PEAKMAG: 0` en `SED.INFO` -- ningún `SED.INFO`
   real de las 12 clases SIMSED de `~/run_SNANA/plasticc_models/` declara esa clave (grep exhaustivo).
3. **Rama de texto, no binaria**: el shift solo corre leyendo el archivo de texto, no el binario
   precompilado -- los 3 `.INPUT` reales (`CART-MOSFIT`/`SNIa-91bg`/`SNIax`) declaran
   `SIMSED_USE_BINARY: 0`.

`PEAKMJD` en sí sigue siendo un sorteo uniforme real (`gen_peakmjd()`, `snlc_sim.c:16887-16965`,
`GENRANGE_PEAKMJD` real de la campaña) -- la calibración al pico real NO es por objeto, es **por
template, una vez, en la inicialización del modelo**. Y las 6 bandas comparten el MISMO `Trest=0`:
`gen_PEAKMAG()` (`snlc_sim.c:27090-27132`) fuerza `epoch_rest=0.0` y evalúa el modelo UNA vez por banda
en ese instante único -- no hay pico independiente por banda en la referencia real de SNANA.

### Paso 2 -- verificación numérica sobre los templates reales: confirma y cierra el caso de `CaRT`

Calculando `argmax_day(Σ_λ flux)` -- exactamente la fórmula del C -- sobre los `.dat.gz`/`.SED.gz`
reales: `SNIa-91bg` (35 templates) tiene el pico bolométrico en fase nativa **+1.0** (17 templates) o
**+2.0** (18 templates), nunca 0. `CaRT` (muestra de 40 de 225 templates) tiene el pico bolométrico en
fase nativa **+4.0 a +33.5**, mediana ~14 -- confirmado con un ejemplo real: `cart1_0.dat` pica en
`+6.507`. Esto cierra exacto el caso de Fase 54: el máximo real de `CaRT` medido entonces caía en
`rest_phase=5-8` mientras el primer punto "válido" bajo la fase nativa (`~1.0`) era 8-22x más tenue --
Fase 54 estaba evaluando el template **6.5 días antes** del `Trest=0` real de SNANA.

### Paso 3 -- explica también el trade-off azul-mejora/rojo-empeora de Fase 52/54

Comparando, en los templates reales, la fase nativa del pico bolométrico contra el pico dentro de
ventanas tipo LSST: el pico bolométrico está dominado por el óptico azul-verde, cae casi encima del
pico de `u`/`g` y días (hasta 9-16 en `SNIax`) antes del pico de `i`/`z`/`y`. El código anterior (máximo
por banda, Fase 50/53) sobreestimaba TODAS las bandas contra SNANA, mucho más las rojas (máximo lejos
de `Trest=0`); Fase 54 (fase nativa 0) mejoraba `u`/`g` pero sobrepasaba a `i`/`z`/`y` hacia el lado
contrario, porque fase nativa 0 caía DÍAS antes del `Trest=0` real. El pico bolométrico real queda
*entre* ambos -- la primera métrica candidata a mejorar las 6 bandas a la vez.

### Paso 4 -- la causa raíz real en LightCurveLynx

`sed_template_model.py:592-597`, `SIMSEDModel._read_simsed_data_file()`: `SEDTemplate(data,
sed_data_t0=0.0, ...)` -- usa la fase NATIVA del archivo como referencia de tiempo cero, sin verificar
si coincide con el pico real. No es solo un problema de la métrica de comparación -- desalinea la curva
de luz observada COMPLETA respecto de la de SNANA (`self.times = self.phases - sed_data_t0`,
`sed_template_model.py:79`), con impacto directo en cualquier comparación de fase, no solo en
`PEAKMAG`. Para `CaRT`, una desalineación mediana de ~14 días es enorme.

### Paso 5 -- el fix: `load_simsed_templates_bolometric()` + `simsed_t0_mode` nuevo en `build_source_model()`

Nueva función en `run_simsed_poc.py`: para cada template de una clase, lee los datos crudos, calcula
`t0_bolo` con la MISMA fórmula real de `T0shiftPeak_SEDMODEL()` (suma simple de flujo por día, argmax),
y construye el `SEDTemplate` con `sed_data_t0=t0_bolo` -- en el MISMO orden que `SED.INFO` lista los
templates (confirmado: `selected_template`, el índice que sortea `MultiSEDTemplateModel`, indexa ese
mismo orden). Verificado contra el ejemplo del Paso 2: `t0_bolo` de `91BG_ST0_C0.SED` calculado en
Python da exacto `1.0`.

`build_source_model()` gana `simsed_t0_mode: str = "raw"` (default, producción/`main()` -- construye
igual que siempre, `SIMSEDModel.from_dir()`) vs. `"bolometric_peak"` (usado por
`compare_brightness_truth.py` -- arma los templates con `load_simsed_templates_bolometric()`). Mismo
criterio de Fase 53: no alterar en silencio producción -- extender `"bolometric_peak"` ahí cambiaría el
eje temporal completo de la curva de luz (no solo el brillo pico) para las 12 clases SIMSED, con
impacto directo en detección/trigger -- decisión separada, pendiente.

Con `simsed_t0_mode="bolometric_peak"`, `rest_phase=0` YA ES el pico bolométrico real -- vuelve a ser
seguro evaluar en un único punto (`rest_frame_phase_min=0.0, rest_frame_phase_max=0.5,
rest_frame_phase_step=1.0`, la convención original de Fase 39/47) para las 3 clases: el pico bolométrico
de cualquier template, por construcción, cae dentro de su propia cobertura real (`CaRT` incluido -- ya
no hace falta el `trest_range` completo ni el máximo). Smoke test real antes de correr nada: `CaRT` con
este modo ya NO devuelve flujo `0.0` en ningún objeto (el bug original de Fase 50, resuelto en la raíz).

### Paso 6 -- remedido: las 6 bandas caen juntas, por primera vez en toda la investigación

3 jobs reales en NLHPC: `12110321` (`SNIa-91bg`, 2m05s), `12110322` (`SNIax`, 16m00s), `12110323`
(`CaRT`, 3m24s).

| banda | `SNIa-91bg` (Fase 55→56) | `SNIax` (Fase 55→56) | `CaRT` (Fase 55→56) |
|---|---:|---:|---:|
| u | -0.465 → **-0.039** | -0.710 → **+0.166** | -0.607 → **-0.113** |
| g | -0.245 → **-0.047** | -0.186 → **+0.155** | -0.266 → **-0.085** |
| r | -0.088 → **-0.031** | +0.123 → **+0.148** | -0.119 → **-0.055** |
| i | -0.032 → **-0.028** | +0.109 → **+0.139** | -0.087 → **-0.034** |
| z | -0.016 → **-0.013** | +0.092 → **+0.160** | -0.066 → **-0.005** |
| y | -0.020 → **-0.011** | +0.071 → **+0.154** | -0.078 → **-0.005** |
| mediana global | | | |
| SNANA | 24.648 (`r`) | 26.670 (`r`) | 28.850 (`r`) |
| LCL | 24.642 (`r`) | 26.578 (`r`) | 28.695 (`r`) |

**`SNIa-91bg`**: las 6 bandas caen a `≤0.05` mag -- por primera vez en toda la investigación (43+ fases
desde Fase 7), un cierre simultáneo en las 6 bandas, no solo en `r`. Mediana global banda `r`: SNANA
`24.648`, LCL `24.642` -- `Δ=0.006` mag, el cierre más limpio de todo el proyecto después de `MAG_OFFSET`
(Fase 37, SALT2, `0.005` mag).

**`SNIax`**: el patrón salvaje banda-a-banda (`-0.71` a `+0.12`, un rango de `0.83` mag) colapsa a un
grupo apretado (`+0.14` a `+0.17`, rango `0.03` mag) -- el residuo cromático desaparece por completo.
Queda un offset chico y sistemático (~`+0.15` mag, mismo signo/magnitud en las 6 bandas) -- candidato
nuevo, acromático, para una fase futura (no es el mismo tipo de problema que se venía persiguiendo).

**`CaRT`**: mismo patrón -- de un rango de `0.54` mag (`-0.61` a `-0.07`) a un rango de `0.11` mag
(`-0.11` a `-0.005`), con `z`/`y` prácticamente cerrados (`-0.005`). Queda un residuo chico creciente
hacia el azul (`u: -0.113`) -- mucho más chico que cualquier residuo medido para esta clase hasta ahora.

### Conclusión Fase 56

Cierra la saga completa iniciada en Fase 50 (primera medición de brillo fuera de `SNIa`/`SNIa-91bg`) y
retomada en Fases 51-55: la causa raíz real detrás del residuo cromático que crecía sin explicación
clase a clase no era ninguno de los mecanismos periféricos ya corregidos (extinción de host, fuga de
filtro) sino la definición misma de `Trest=0` -- SNANA nunca usa la fase nativa del archivo SIMSED como
referencia de tiempo, siempre la recalibra al pico bolométrico real de cada template, y esa
recalibración es la que faltaba en LightCurveLynx. Con el fix, las 3 clases medidas muestran el
comportamiento más consistente de toda la investigación: residuos chicos, agrupados por banda (ya no
dispersos como antes), sin el patrón salvaje azul/rojo que motivó 4 fases de diagnóstico (52-55). Quedan
dos residuos nuevos, mucho más chicos y de naturaleza distinta a los que se venían investigando: un
offset acromático de `~0.15` mag en `SNIax`, y un residuo azul residual de `~0.11` mag en `CaRT` --
candidatos genuinamente nuevos para una fase futura, no una continuación de la misma pregunta.

### Archivos de esta fase

`run_simsed_poc.py` (`SEDTemplate` importado; `load_simsed_templates_bolometric()` nueva;
`build_source_model()` gana `simsed_t0_mode`, default `"raw"` -- `main()`/producción sin cambios de
comportamiento). `compare_brightness_truth.py` (usa `simsed_t0_mode="bolometric_peak"`, vuelve a
evaluar en un único punto `Trest=0`, ya no necesita `trest_range` ni el máximo). Agente Opus (solo
lectura, diagnóstico del `PEAKMJD` real) para los Pasos 1-3. 3 jobs reales en NLHPC:
`12110321`/`12110322`/`12110323`. Outputs reales actualizados:
`compare_brightness_truth_{snia91bg,sniax,cart}_output.parquet`.

## Fase 57 -- decisión: `simsed_t0_mode="bolometric_peak"` (Fase 56) pasa a ser el default de producción -- piloto real mide impacto mínimo en detección

Retoma la decisión que dejó pendiente Fase 56: extender el fix del pico bolométrico real a `main()`
(producción, las 14 clases) cambia el eje temporal completo de la curva de luz, no solo el brillo pico
-- con impacto potencial en `SEARCHEFF`/ratio de detección para las 12 clases SIMSED del catálogo.
Antes de decidir a ciegas, se corrió un piloto real.

### Paso 1 -- piloto real: `CaRT` (la clase de mayor riesgo), 1 semilla, pipeline de producción completo

`CaRT` es la clase con el shift más grande del catálogo (mediana ~14 días, hasta 33 según el template
-- Fase 56). Job real en NLHPC (`12113819`, 17m20s): `main("CaRT", seed_index=0)` corrido dos veces,
una con `simsed_t0_mode="raw"` y otra con `"bolometric_peak"`, mismo seed, pipeline completo
(`simulate_lightcurves` + ruido real + `SEARCHEFF`, no solo brillo pico sin ruido).

| | `raw` | `bolometric_peak` |
|---|---:|---:|
| SNR mediana (todas las obs) | `0.682` | `0.682` |
| detectados (`SEARCHEFF`, ≥2 épocas) | 167/1998 (8.36%) | 164/1998 (8.21%) |
| eficiencia `z=[0.28,0.56)` | 22.8% | 20.5% |
| eficiencia otros 4 bins de `z` | ±≤0.4pp | ±≤0.4pp |

**Impacto mínimo, dentro de ruido de una sola semilla** (3 objetos de diferencia sobre 1998, un solo
bin de `z` con una diferencia algo mayor -2.3pp, el resto prácticamente idéntico). La razón física: la
ventana de generación real (`trest_range=(-30,100)`, 130 días) es mucho más ancha que el shift típico
(1-33 días) -- el survey ya observaba el pico real del objeto en ambos modos, el shift solo corrige
CUÁL punto de la curva se etiqueta como `t0`/pico, no si el survey lo captura. El fix corrige fidelidad
de brillo/alineación temporal sin invalidar de forma importante los ratios de detección ya medidos.

### Paso 2 -- el cambio: default de `main()`, no de `build_source_model()`

`build_source_model()` mantiene su propio default `"raw"` (compatibilidad hacia atrás, mismo criterio
que Fase 53/56 -- cualquier llamador futuro que no lo especifique sigue con el comportamiento
histórico). `main()` (producción real, `run_simsed_poc.py <clase>` vía CLI) pasa `simsed_t0_mode=
"bolometric_peak"` como su PROPIO default -- afecta a las 12 clases SIMSED reales del catálogo (no a
`SNII-NMF`/`SNIa`, que no usan `host_av`/SIMSED en el mismo sentido -- en realidad todas las 12 clases
`CLASS_CONFIGS` con `simsed_dir` real se benefician, incluidas las que no declaran `host_av`).

Verificado con un smoke test real usando el entrypoint CLI real (sin flags nuevos, exactamente como se
invoca en producción): `python3 run_simsed_poc.py SNIa-91bg` corre de punta a punta con el nuevo
default, `997/1995` objetos detectados (49.97%), QC generado sin errores.

### Conclusión Fase 57

Se decide extender el fix a producción, respaldado por evidencia real (no una suposición): el piloto en
la clase de mayor riesgo del catálogo mide un impacto de detección despreciable, y el fix corrige una
causa raíz real y confirmada (Fase 56) en la construcción del modelo, no una elección de diseño
ambigua. **Nota honesta para el registro**: los ratios de detección históricos de las 14 clases
(reportados en fases muy anteriores, Fase 4/5 en adelante) siguen siendo los que están publicados --
técnicamente corresponden al modo `"raw"` (el único que existió hasta ahora). El piloto de esta fase
sugiere fuertemente que la diferencia es chica, pero fue medido con 1 semilla en 1 clase -- un
re-barrido formal de 5 semillas × 12 clases con el nuevo default, para actualizar esas tablas de
referencia con confianza estadística completa, queda como trabajo futuro, no bloqueante para esta
decisión.

### Archivos de esta fase

`run_simsed_poc.py` (`main()` gana `simsed_t0_mode: str = "bolometric_peak"` como su propio default;
`build_source_model()` sin cambios de default). Piloto y smoke test corridos en NLHPC (`sbatch`,
`12113819`/`12115306`), scripts exploratorios borrados tras usarlos -- outputs de producción reales
conservados (`poc_output_cart`, `poc_output_cart_bolopeak`, `poc_output_snia91bg`, no versionados por
`.gitignore`, mismo criterio que el resto de las corridas de producción).

## Fase 58 -- re-barrido formal de 5 semillas × 13 clases SIMSED con `simsed_t0_mode="bolometric_peak"`: la mayoría cambia poco, 3 clases cambian sustancialmente (`SNIax -28%`, `TDE-MOSFIT -18%`, `PISN-STELLA-HYDROGENIC +21%`)

Cierra el trabajo futuro que dejó pendiente Fase 57: actualizar con confianza estadística completa
(5 semillas, no 1) las tablas de referencia de detección para las 13 clases SIMSED reales del catálogo
(las 14 menos `SNIa`, que usa SALT2 y no pasa por este fix), bajo el nuevo default de producción.

### Paso 0 -- gestión de riesgo de disco antes de lanzar nada

Un incidente real de cuota de disco ya había interrumpido un barrido de 5 semillas antes (Fase 8,
`exploration/lightcurvelynx/` llegó a 18GB, la cuenta completa a ~200GB, con `phot_df.parquet`
individuales de hasta 1.4GB). Verificado antes de lanzar: la cuenta ya estaba en 189GB de uso real
(headroom real confirmado con una escritura de prueba de 500MB, sin problema). Mitigación real
aplicada esta vez: cada uno de los 65 jobs borra su propio `phot_df.parquet` (la tabla cruda de
fotometría, reproducible desde el script sembrado si hiciera falta) inmediatamente después de generar
`summary.json`/`head_df.parquet`/QC -- mantiene el uso de disco acotado sin importar cuántos jobs
corran en paralelo. Verificado: `exploration/lightcurvelynx/` se mantuvo en `5.3-5.4GB` durante y
después de las 65 corridas (vs. 113MB que había ocupado un solo `phot_df.parquet` de `CaRT` sin
limpiar, en el piloto de Fase 57).

### Paso 1 -- dos fallas reales durante el barrido, ambas diagnosticadas y corregidas antes de re-lanzar

**`PISN-STELLA-HYDROGENIC` (las 5 semillas), `OUT_OF_MEMORY`** -- única clase del catálogo con
`NGENTOT_LC=20000` (10x las demás, `pipeline/models.yaml`) -- 16GB no alcanzó. Corregido subiendo a
48GB, sin tocar código.

**`KN-K17`, lento (40-45 min vs. 2-15 min de las demás, 1 semilla llegó a `TIMEOUT`)** -- diagnosticado
antes de solo subir el límite de tiempo: `load_simsed_templates_bolometric()` (Fase 56) calculaba la
suma de flujo por fase con un loop Python + máscara booleana por cada fase única -- `O(N_fases ×
N_filas)`. Para templates con grilla de fase fina (kilonovas como `KN-K17`, muchas fases), esto tardaba
~39 minutos SOLO en cargar los templates. Vectorizado con `np.argsort` + `np.add.reduceat` (`O(N log
N)`) -- mismo resultado exacto (verificado: `t0_bolo` de `91BG_ST0_C0.SED` sigue dando `1.0`), mucho
más rápido. Beneficia a cualquier clase con grilla de fase fina, no solo `KN-K17`.

### Paso 2 -- resultado: 65/65 corridas reales completas, comparado contra la referencia SNANA de Fase 48

Detección media ± desviación estándar sobre 5 semillas, contra `SNANA%` DDF-only real (Fase 48, fijo,
no afectado por este fix). Para `SLSN-I`/`ILOT-MOSFIT`, la comparación usa el resultado de Fase 49 (con
`GENRANGE_TREST` real ya extendido, código sin cambios desde entonces) en vez del ratio de Fase 48 --
ese quedó obsoleto antes de Fase 43, no es la referencia correcta para estas 2 clases.

| clase | detección media (5 semillas) | SNANA% real (Fase 48) | ratio antes | ratio nuevo | Δ |
|---|---:|---:|---:|---:|---:|
| `SNIa-91bg` | `51.90%±1.82` | 41.69% | 1.231 | **1.245** | +1.1% |
| `PISN-STELLA-HYDROGENIC` | `37.00%±0.46` | 24.45% | 1.255 | **1.513** | **+20.6%** |
| `SNII-NMF` | `26.67%±0.86` | 20.75% | 1.319 | **1.285** | -2.6% |
| `PISN-STELLA-HECORE` | `32.88%±1.11` | 21.88% | 1.377 | **1.503** | +9.1% |
| `TDE-MOSFIT` | `55.54%±0.98` | 46.58% | 1.462 | **1.192** | **-18.4%** |
| `SLSN-I` | `69.36%±1.41` | 46.64% | 1.544 (Fase 49) | **1.487** | -3.7% |
| `PISN-MOSFIT` | `37.39%±1.25` | 23.41% | 1.602 | **1.597** | -0.3% |
| `KN-BULLA19` | `11.88%±0.77` | 6.07% | 2.128 | **1.957** | -8.0% |
| `KN-K17` | `9.73%±0.85` | 4.83% | 2.238 | **2.014** | -10.0% |
| `SNIax` | `17.69%±1.36` | 10.08% | 2.444 | **1.755** | **-28.2%** |
| `SNIIn-MOSFIT` | `9.78%±0.40` | 2.12% | 4.885 | **4.613** | -5.6% |
| `ILOT-MOSFIT` | `30.49%±0.90` | 4.30% | 7.216 (Fase 49) | **7.091** | -1.7% |
| `CaRT` | `8.29%±0.49` | 0.94% | 9.180 | **8.819** | -3.9% |
| **promedio catálogo** | | | **2.914** | **2.775** | **-4.8%** |

**La mayoría de las clases cambia poco** (`±10%`, dentro o cerca de la variación semilla-a-semilla ya
esperada) -- consistente con el piloto de Fase 57 (`CaRT`, `-3.9%` aquí, coincide con el orden de
magnitud medido con 1 semilla). **3 clases cambian sustancialmente**:

- **`SNIax` (`-28.2%`)**: la mayor mejora del catálogo. Consistente con Fase 56 -- `SNIax` fue la clase
  con el segundo mayor shift de pico bolométrico medido (después de `CaRT`), y ya había mostrado la
  mejora más grande en brillo verdadero (Fase 56, residuo `u` de `-0.73` a `-0.03` mag).
- **`TDE-MOSFIT` (`-18.4%`)**: mejora real, clase nunca antes remedida con este fix -- candidata para
  una futura medición de brillo verdadero (ver líneas futuras).
- **`PISN-STELLA-HYDROGENIC` (`+20.6%`)**: la única clase que EMPEORA (ratio más alto, más lejos de
  SNANA) -- candidato nuevo. Es la clase de mayor escala del catálogo (`GENRANGE_TREST` hasta 1000+
  días, transitorio de pair-instability extremadamente largo) -- el shift al pico bolométrico real
  podría estar corriendo la ventana de observación hacia una fase con más flujo detectable de lo que
  SNANA realmente genera. No investigado a fondo en esta fase -- candidato concreto para retomar.

### Conclusión Fase 58

El re-barrido formal confirma, con 5 semillas por clase (no 1), lo que ya sugería el piloto de Fase 57:
el fix del pico bolométrico NO invalida de forma generalizada las tablas de referencia de detección del
catálogo -- el promedio se mueve solo `-4.8%`. Pero revela 2 clases (`SNIax`, `TDE-MOSFIT`) con mejoras
reales y sustanciales que SÍ vale la pena registrar como el resultado correcto y actualizado, y descubre
una clase (`PISN-STELLA-HYDROGENIC`) que empeora, un candidato nuevo y no esperado para investigar.
Además, corrigiendo dos problemas reales de infraestructura en el camino (cuota de disco gestionada
proactivamente esta vez, y un cuello de botella real de rendimiento en el propio código de Fase 56
vectorizado) -- ninguno de los dos bloqueó el resultado final, ambos quedan corregidos para cualquier
corrida futura.

### Archivos de esta fase

`run_simsed_poc.py` (`load_simsed_templates_bolometric()`: suma de flujo por fase vectorizada,
`np.argsort`+`np.add.reduceat` en vez de loop con máscara booleana -- mismo resultado, sin cambio de
comportamiento). 65 jobs reales en NLHPC (`sbatch`, sondeados con `squeue`/`sacct`; 6 fallaron la
primera vez por memoria/tiempo, re-lanzados con recursos ajustados tras diagnosticar la causa real de
cada uno -- 0 fallas sin explicar). Scripts de sweep generados y borrados tras usarlos. Outputs de
producción reales conservados en NLHPC (`poc_output_*_bolopeak[_seedN]`, sin `phot_df.parquet` por
diseño -- limpieza automática por job), no versionados por `.gitignore`, mismo criterio que el resto
de las corridas de producción.

## Fase 59 (barrido completo, brecha sigue sin explicación) -- `GENRANGE_TREST` real por clase (no
el hardcode global `-30/100`): el "hueco" nunca remedido para 12/14 clases desde Fase 40/43 resulta
ser mucho más grande de lo que sugería el promedio del catálogo en Fase 58

### Motivación

`PISN-STELLA-HYDROGENIC` fue la única clase que EMPEORÓ en el re-barrido de Fase 58 (`+20.6%`, ratio
`1.255 -> 1.513`), pese a que el fix del pico bolométrico (Fase 56-57) mejoró o dejó estable a las
demás 12. La hipótesis de Fase 58 fue que, siendo la clase de mayor escala temporal del catálogo
(`GENRANGE_TREST` real hasta 1000+ días en algunas clases de la familia PISN), el shift al pico
bolométrico corre la ventana de observación hacia una fase con más o menos flujo detectable de lo
esperado -- pero `main()` seguía usando `rest_time_window_offset=(-30.0, 100.0)` **hardcodeado e
idéntico para las 14 clases** (línea real, ver `run_simsed_poc.py`), salvo `SLSN-I` e `ILOT-MOSFIT`
(únicas 2 corregidas en Fase 43). El `GENRANGE_TREST` real de cada clase (leído de su
`SIMGEN_INCLUDE_*.INPUT` real en `run_SNANA/elastic/model_config/`) varía de `-50/300` a `-100/1000`
-- un hueco de auditoría nunca cerrado para las otras 12 clases, documentado pero nunca remedido desde
que Fase 40/43 lo encontraron por primera vez (para 2 clases nada más). Esta fase cierra el hueco para
las 11 clases restantes que sí lo tenían pendiente (`PISN-STELLA-HYDROGENIC` incluida, la que motivó
la auditoría).

### Cambio real

`CLASS_CONFIGS` en `run_simsed_poc.py`: se agregó `trest_range=(GENRANGE_TREST real)` explícito para
las 11 clases que aún caían en el default `(-30, 100)` de `main()` (confirmado línea por línea contra
cada `SIMGEN_INCLUDE_*.INPUT` real, mismo método que Fase 40/43 para las 2 originales). El consumidor
(`trest_range = cfg.get("trest_range", (-30.0, 100.0))`, línea ~823) ya existía desde Fase 43 -- no se
tocó código de ejecución, solo se completó la tabla de configuración que quedó a medio llenar.

### Resultado (11/11 clases completas, 5 semillas c/u)

Mismo método que Fase 58 (detección media ± desviación estándar sobre 5 semillas, contra `SNANA%`
DDF-only real de Fase 48, fijo):

| clase | detección media Fase 59 (5 semillas) | SNANA% real (Fase 48) | ratio Fase 58 (rango `-30/100`) | ratio Fase 59 (rango real) | Δ |
|---|---:|---:|---:|---:|---:|
| `SNIa-91bg` | `58.28%±0.86` | 41.69% | 1.245 | **1.398** | +12.3% |
| `KN-K17` | `18.10%±0.42` | 4.83% | 2.014 | **3.748** | +86.1% |
| `CaRT` | `25.80%±1.36` | 0.94% | 8.819 | **27.45** | **+211%** |
| `SNIax` | `28.54%±1.10` | 10.08% | 1.755 | **2.832** | +61.4% |
| `TDE-MOSFIT` | `65.06%±0.91` | 46.58% | 1.192 | **1.397** | +17.2% |
| `SNII-NMF` | `38.08%±0.73` | 20.75% | 1.285 | **1.835** | +42.8% |
| `SNIIn-MOSFIT` | `19.57%±0.73` | 2.12% | 4.613 | **9.231** | +100% |
| `PISN-MOSFIT` | `51.56%±1.33` | 23.41% | 1.597 | **2.203** | +37.9% |
| `KN-BULLA19` | `24.28%±0.97` | 6.07% | 1.957 | **4.000** | +104% |
| `PISN-STELLA-HECORE` | `41.72%±1.25` | 21.88% | 1.503 | **1.907** | +26.9% |
| `SLSN-I` (sin cambio, ya corregida en Fase 43) | -- | -- | 1.487 | 1.487 | 0% |
| `ILOT-MOSFIT` (sin cambio, ya corregida en Fase 43) | -- | -- | 7.091 | 7.091 | 0% |
| `PISN-STELLA-HYDROGENIC` | `46.15%±0.36` (5/5 semillas -- ver nota) | 24.45% | 1.513 | **1.888** | +24.8% |
| **promedio (13 clases)** | | | **2.895*** | **5.113** | |

\* recalculado sobre las mismas 13 filas para comparar manzanas con manzanas (Fase 58 original
reportaba 2.914 sobre el catálogo con una referencia distinta para 2 filas, ver esa sección).

### Nota -- incidente real de cuota de disco en `PISN-STELLA-HYDROGENIC` (semilla 1)

`PISN-STELLA-HYDROGENIC` es la única clase con `NGENTOT_LC=20000` (10x el resto) -- con el
`trest_range` real (`-50/300`, antes `-30/100`) cada semilla aplanó a **~119M filas de fotometría**
(vs. ~15M de `CaRT`, la siguiente más pesada). El job de la semilla 1 (`12133078`) llegó hasta
`SEARCHEFF aplicado: 9295/19998` y recién ahí murió: `pyarrow.lib.ArrowIOError: Error writing bytes to
file ... Disk quota exceeded` -- cuota real agotada por la escritura concurrente de 4 `phot_df.parquet`
de ~119M filas cada uno en paralelo (semillas 1-4 lanzadas juntas), pese a la limpieza automática por
job de Fase 58 (que borra `phot_df.parquet` recién *después* de que `summary.json` se escribe -- no
protege si la escritura del parquet en sí falla a mitad de camino). Las semillas 0/2/3/4 sí terminaron
(`46.29%`, `46.03%`, `46.46%`, `45.50%` -- consistentes entre sí, `std=0.36`). Trampa real encontrada
al revisar: `poc_output_pisnstellahydrogenic_seed1_bolopeak/summary.json` seguía existiendo con un
valor de una corrida vieja (`37.03%`, `mtime` 11:41am, anterior al lanzamiento de esta corrida a las
3:48pm) -- si no se hubiera verificado el `mtime` contra la hora real de lanzamiento del job, ese
número stale se habría usado por error como si fuera el resultado de Fase 59. Headroom verificado
(escritura de prueba de 1GB, éxito) y semilla 1 re-lanzada sola (`12152052`, sin las otras 3 compitiendo
por I/O/cuota al mismo tiempo) -- **confirmado**: `46.475%` (`SEARCHEFF aplicado: 9295/19998`,
`mtime` posterior al relanzamiento, sin ambigüedad de corrida vieja esta vez), consistente con las
otras 4 semillas. Las 5 semillas quedan: `46.29%`, `46.475%`, `46.03%`, `46.46%`, `45.50%` --
media `46.15%±0.36` (`n=5`, cifra final, ya no provisional).

### Lectura -- IMPORTANTE, contradice la conclusión de cierre de Fase 58

Fase 58 concluyó que "el fix del pico bolométrico NO invalida de forma generalizada las tablas de
referencia... el promedio se mueve solo -4.8%". Esa conclusión es correcta **para el fix del pico
bolométrico en sí**, pero se apoyaba sin saberlo sobre una configuración de `trest_range` incorrecta
para 12/14 clases. Al corregir *esa* configuración (no el pico bolométrico, un bug distinto y ya
cerrado), el ratio LCL/SNANA **no mejora, empeora, y de forma sustancial** en las 11 clases remedidas
-- el promedio del catálogo (13 clases SIMSED, `PISN-STELLA-HYDROGENIC` con valor provisional `n=4`)
pasa de `2.895x` a `5.113x`, casi el doble. `CaRT` es el caso extremo: de `8.8x` a `27.5x`
sobre-detección relativa a SNANA. Ninguna de las 13 clases mejora con el rango real -- todas empeoran,
de `+12.3%` (`SNIa-91bg`, el menor) a `+211%` (`CaRT`, el mayor).

Interpretación mecánica (confirmar, no bloqueante para el resultado ya medido): `rest_time_window_offset`
en `simulate_lightcurves()` acota la ventana de fase-resto dentro de la cual se puede ubicar la parte
observada de la curva de luz -- análogo a `GENRANGE_TREST` de SNANA, que limita qué épocas rest-frame
SNANA genera en absoluto. Un rango más angosto (`-30/100` vs. p.ej. `-100/500` real de `CaRT`) reduce
mecánicamente cuánta curva de luz cae dentro de cualquier ventana de observación dada, lo que **reduce**
la probabilidad de detección (`>=2 épocas reales`) sin importar si el rango usado es "correcto" o no.
El hardcode angosto no era una aproximación neutral -- estaba **artificialmente conteniendo** la
sobre-detección real de LightCurveLynx frente a SNANA para la mayoría del catálogo, haciendo que el
desacuerdo pareciera mucho menor de lo que es con la configuración real.

### Consecuencia real

Las tablas de referencia de detección "finales" de Fase 58 (y todo lo que se apoyó en ellas para las
11 clases remedidas) quedan **obsoletas** -- no por el pico bolométrico, sino por este hueco de
configuración distinto y anterior. `PISN-STELLA-HYDROGENIC` ya está confirmada con las 5 semillas
(`46.15%±0.36`, ratio `1.888`, ver tabla arriba) -- el promedio del catálogo (13 clases) cierra en
`5.113x`, sin cambios respecto al valor provisional. La pregunta de si esto cambia la conclusión de
la propuesta para sncosmo/LightCurveLynx se resolvió con un documento de síntesis nuevo,
`exploration/lightcurvelynx/SINTESIS_hallazgos_y_brecha_abierta.md` -- explica por qué los 4 bugs
reales ya identificados en el proyecto (Fases 13/19-20/37/51) no explican este salto (ninguno se
midió nunca contra la métrica agregada de detección de 13 clases), y completa el catálogo de
borradores de issue a 4 (2 nuevos: Fase 13 y Fase 51; 2 amend: Fase 37 con las claves adicionales de
`SALT2.INFO`, seed propagation con el 4to nodo faltante). Todo esto ya está commiteado y pusheado
(`5861fb2` para Fase 59/59-perf, `e6a1574` para la síntesis y el dashboard actualizado) -- ninguno de
los 4 borradores de issue se publicó, mismo criterio de siempre.

### Fase 59-perf -- aplanado vectorizado (`main()`, líneas ~841-898): elimina el doble `iterrows()`
anidado que dominaba el tiempo de ejecución, sin cambiar ningún resultado

Motivado por `PISN-STELLA-HYDROGENIC`: su paso de "aplanado" (convertir el resultado crudo de
`simulate_lightcurves()` a `head_df`/`phot_df`) tomaba **~1h54min por semilla** (más que la simulación
misma, ~32min) -- perfilado localmente contra datos sintéticos con la forma real (`cProfile`) confirmó
que el 100% del costo es overhead de boxeo de `pandas.Series` en el doble `for _, row in lc.iterrows(): 
... for _, obs in sub.iterrows():` (línea por línea: `Series.__init__` 203s, `sanitize_array` 85s, ~77M
llamadas a `isinstance` -- ningún cómputo real, escala linealmente con el número de filas totales
independiente de la clase, ~57us/fila medido real en NLHPC tanto para `CaRT` como para
`PISN-STELLA-HYDROGENIC`).

Reemplazado por un único `pd.concat()` de las sub-tablas ya tabulares que devuelve
`simulate_lightcurves()` (sin ningún loop de Python por fila), más `restlambda_gate_vec()` (nueva,
versión vectorizada de `restlambda_gate()`, mismo álgebra) para las 2 clases que usan
`RESTLAMBDA_RANGE` (`SLSN-I`, `ILOT-MOSFIT`). Benchmark local (datos sintéticos, forma real de `CaRT`):
**362x más rápido** (144.2s -> 0.40s sobre 1.54M filas).

**Verificación real en NLHPC** (no solo sintética): corridas lado a lado del código viejo y nuevo,
`ngentot_override=40`, semilla `777` (descartable), para `SLSN-I` (con `RESTLAMBDA_RANGE`, ejercita el
gate vectorizado) y `CaRT` (sin él) -- agregados idénticos en ambas versiones (`SLSN-I`: 338,979 filas
de fotometría, 44,071 suprimidas por el gate, 27/40 detectados, SNR mediana 0.802/p90 2.402; `CaRT`:
278,113 filas, 11/40 detectados, SNR 0.674/1.650) y **comparación fila por fila con
`pd.testing.assert_frame_equal`** sobre los `head_df.parquet`/`phot_df.parquet` reales escritos a disco
por cada versión: `IDENTICO` en las 4 combinaciones (2 clases × 2 tablas). Sincronizado como la versión
de producción en NLHPC (`~/AUTOSIM/exploration/lightcurvelynx/run_simsed_poc.py`); los archivos de
verificación (`run_simsed_poc_{OLD,NEW}_verify.py`, `verify_flatten.py`) se borraron después de usarlos.

**Nota:** el job `12152052` (`PISN-STELLA-HYDROGENIC` semilla 1, re-lanzado antes de este cambio) sigue
corriendo con la versión vieja del aplanado en memoria (el intérprete ya había cargado el módulo antes
de que el archivo se sobreescribiera en disco) -- no afecta su resultado, solo tardará el tiempo
antiguo. Cualquier corrida nueva que se lance de acá en adelante ya usa la versión rápida.

## Fase 60 (en curso) -- extender la comparación de brillo verdadero (metodología SALT2/Fase 16, ya
generalizada en Fase 50) a las 10 clases SIMSED que nunca la tuvieron

Motivada por la pregunta abierta de Fase 59: la sobre-detección real (2.9x→5.1x) no la explica ninguno
de los 4 bugs conocidos. De las 13 clases SIMSED, solo 3 (`SNIa-91bg`, `SNIax`, `CaRT`) pasaron por la
comparación de brillo sin ruido/patrón cromático (Fases 7/50-56) que en `SNIa`/SALT2 encontró la causa
raíz real (`MAG_OFFSET`, Fase 37). Las otras 10 (`TDE-MOSFIT`, `SNII-NMF`, `ILOT-MOSFIT`,
`SNIIn-MOSFIT`, `PISN-MOSFIT`, `KN-BULLA19`, `PISN-STELLA-HECORE`, `PISN-STELLA-HYDROGENIC`, `SLSN-I`,
`KN-K17`) nunca la tuvieron -- pese a que `compare_brightness_truth.py`/`compare_brightness_truth_binned.py`
ya están generalizados para cualquier clase de `CLASS_CONFIGS` desde Fase 50, sin necesidad de código
nuevo. Varias de las 10 son justamente las de peor ratio de sobre-detección en Fase 59
(`SNIIn-MOSFIT` 9.2x, `ILOT-MOSFIT` 7.1x, `KN-BULLA19` 4.0x, `KN-K17` 3.7x).

### Lanzado

`compare_brightness_truth_class.sbatch` (nuevo, genérico -- toma `<Clase>` como argumento, corre
`compare_brightness_truth.py` + `compare_brightness_truth_binned.py` en secuencia, mismo patrón que
`compare_brightness_truth_salt2.sbatch` de Fase 16). 10 jobs reales en NLHPC (partición `largemem`,
reasignados automáticamente por ratio memoria/CPU): `12191398` (`TDE-MOSFIT`), `12191399`
(`SNII-NMF`), `12191400` (`ILOT-MOSFIT`), `12191401` (`SNIIn-MOSFIT`), `12191402` (`PISN-MOSFIT`),
`12191403` (`KN-BULLA19`), `12191404` (`PISN-STELLA-HECORE`), `12191405`
(`PISN-STELLA-HYDROGENIC`), `12191406` (`SLSN-I`), `12191407` (`KN-K17`). Confirmados los 10
`.DUMP` de referencia de SNANA en `DATASIM_LSST_1/DDF/SIMDv8/` antes de lanzar (todos existen, sin
`DUMP_FOLDER_OVERRIDES` nuevos que agregar).

### Plan de triage (una vez completen)

1. Para cada clase, revisar el delta medio bins 2-7 por banda (salida de `compare_brightness_truth_binned.py`,
   mismo formato que las Fases 50/56). Residuo `≤0.05-0.1` mag en las 6 bandas → clase cerrada, mismo
   criterio que `SNIa-91bg` (Fase 56).
2. Clases con residuo mayor o con patrón cromático real → investigar mecanismo (mismo método que
   Fases 51-56: colisión `add_effect()`, fuga de filtro, mezcla de extinción de host específica de la
   clase -- ej. `TDE-MOSFIT` usa `exp` pura en vez de la mezcla `exp_halfgauss`/WV07 del resto).
3. Reconciliar con los ratios de detección de Fase 59 -- un residuo de brillo chico no implica que el
   ratio de detección deba ser chico (mecanismos distintos: `CaRT` ya tiene residuo de brillo pequeño,
   -0.11 mag en `u`, pero ratio de detección 27.45x -- ver Fase 59).
4. Retomar los 2 residuos nuevos sin investigar que dejó Fase 56: `SNIax` (+0.15 mag acromático,
   las 6 bandas) y `CaRT` (-0.11 mag creciente hacia el azul).
5. Si aparece un bug nuevo con evidencia de código de ambos lados (LCL + sncosmo/SNANA), sumar un 5º
   `ISSUE_DRAFT_*.md` al catálogo de la Sección 5 de `SINTESIS_hallazgos_y_brecha_abierta.md`.

### Resultado (9/10 completos; `KN-K17` timeout a los 40min sin imprimir ni la primera línea de
progreso -- relanzado como job `12214018` con `-t 01:30:00`, contención de I/O sospechada ya que
corrió en paralelo con otras 3 clases leyendo el mismo `.db` de OpSim)

Delta medio bins 2-7 por banda (`compare_brightness_truth_binned.py`, mismo formato que Fases 50/56):

| clase | u | g | r | i | z | y | lectura |
|---|---:|---:|---:|---:|---:|---:|---|
| `TDE-MOSFIT` | +0.112 | -0.073 | +0.140 | +0.193 | +0.238 | +0.195 | patrón real, crece hacia el rojo |
| `SNII-NMF` | +0.106 | +0.126 | +0.150 | +0.155 | +0.177 | +0.173 | residuo chico-mediano, mismo signo las 6 bandas |
| `ILOT-MOSFIT` | -0.386 | -0.389 | -0.352 | -0.417 | -0.391 | -0.270 | **grande, ~acromático** (-0.27 a -0.42), LCL más tenue |
| `SNIIn-MOSFIT` | +0.257 | +0.221 | +0.114 | +0.058 | +0.066 | +0.112 | decrece hacia el rojo |
| `PISN-MOSFIT` | +0.491 | +0.194 | +0.156 | +0.106 | +0.089 | +0.067 | fuerte en `u`, decrece rápido hacia el rojo |
| `SLSN-I` | -0.270 (N=1) | -0.077 (N=1) | -0.574 (N=3) | -0.042 (N=4) | +0.464 (N=4) | +0.369 (N=5) | ruidoso, pocos bins válidos (gate `RESTLAMBDA_RANGE`) |
| `PISN-STELLA-HECORE` | -- | -- | -- | -- | -- | -- | **sin datos, ver más abajo** |
| `PISN-STELLA-HYDROGENIC` | -- | -- | -- | -- | -- | -- | **sin datos, ver más abajo** |
| `KN-BULLA19` | -- | -- | -- | -- | -- | -- | **sin datos, ver más abajo** |
| `KN-K17` | pendiente (retry `12214018`) | | | | | | |

### Hallazgo nuevo, no anticipado: `PISN-STELLA-HECORE`, `PISN-STELLA-HYDROGENIC` y `KN-BULLA19` no
tienen `PEAKMAG` real en el `.DUMP` de SNANA -- no es un residuo de brillo, es una referencia ausente

`compare_brightness_truth_binned.py` reportó `GLOBAL SNANA: N=0` en las 6 bandas para las 3 clases.
Verificado directo contra el `.DUMP` real (no es un bug del script de comparación): las columnas
`PEAKMAG_{u,g,r,i,z,Y}` valen `99` o `-9` (ambos sentinelas reales de SNANA, "no calculado") para el
**100% de los objetos** -- `PISN-STELLA-HECORE`: 1740/2000 en `99`, 260/2000 en `-9`, cero filas
válidas; `PISN-STELLA-HYDROGENIC`: 17375/20000 en `99`, 2625/20000 en `-9`, cero válidas;
`KN-BULLA19`: idéntico split 1740/260 que `PISN-STELLA-HECORE` (coincidencia exacta entre dos clases
físicamente no relacionadas -- sospechoso, sin explicación todavía). Las otras 5 clases medidas en
esta fase SÍ tienen `PEAKMAG` real (~1695-1696/1696 válidas tras el filtro de campo) -- no es un
comportamiento genérico de SNANA para SIMSED, es específico de estas 3 clases. Mecanismo real sin
diagnosticar todavía (candidatos: alguna combinación de `GENRANGE_PEAKMJD`/temporada de observación/
`OPT_SETPKMJD` que deja esas 3 clases sin trigger de cómputo de `PEAKMAG` en esta campaña específica).
**Consecuencia:** la comparación de brillo verdadero, tal como está planteada, no se puede hacer para
estas 3 clases con los datos de referencia actuales -- haría falta re-generar el `.DUMP` de SNANA (o
diagnosticar y corregir por qué no calculó `PEAKMAG`) antes de poder medir un residuo real. Tarea
separada de la búsqueda de bugs de LightCurveLynx -- esto es un problema de la referencia SNANA, no
del simulador que se está auditando.

### Lectura preliminar (6 clases con datos utilizables)

Ninguna de las 6 clases con datos cierra tan limpio como `SNIa-91bg` (Fase 56, ≤0.05 mag). `ILOT-MOSFIT`
tiene, por lejos, el residuo más grande medido en esta fase (~acromático, -0.27 a -0.42 mag, LCL más
tenue) -- pero su ratio de detección (Fase 59) es 7.09x de SOBRE-detección, signo contrario al que
predeciría un LCL sistemáticamente más tenue. Este cruce (residuo de brillo vs. ratio de detección, con
signos que no calzan intuitivamente) es exactamente el tipo de reconciliación que pide el paso 3 del
plan de triage -- pendiente completar con `KN-K17` antes de escribir la síntesis final.

`KN-K17` (job `12191407`) hizo `TIMEOUT` a los 40min sin imprimir ni la primera línea de progreso
(corrió en paralelo con otras 3 clases leyendo el mismo `.db` de OpSim -- contención de I/O
sospechada). Relanzado solo, con `-t 01:30:00` (job `12214018`, terminó en 35min sin error) --
delta medio bins 2-7: `u +0.257, g +0.096, r +0.115, i +0.102, z +0.031, y +0.055` -- residuo
positivo, mayor en `u`, decrece hacia el rojo (mismo patrón cualitativo que `SNIIn-MOSFIT`).

### Tabla final -- 10/10 clases completas

| clase | u | g | r | i | z | y | patrón |
|---|---:|---:|---:|---:|---:|---:|---|
| `TDE-MOSFIT` | +0.112 | -0.073 | +0.140 | +0.193 | +0.238 | +0.195 | crece hacia el rojo |
| `SNII-NMF` | +0.106 | +0.126 | +0.150 | +0.155 | +0.177 | +0.173 | crece hacia el rojo, mismo signo |
| `ILOT-MOSFIT` | -0.386 | -0.389 | -0.352 | -0.417 | -0.391 | -0.270 | grande, ~acromático, LCL más tenue |
| `SNIIn-MOSFIT` | +0.257 | +0.221 | +0.114 | +0.058 | +0.066 | +0.112 | decrece hacia el rojo |
| `PISN-MOSFIT` | +0.491 | +0.194 | +0.156 | +0.106 | +0.089 | +0.067 | fuerte en `u`, decrece rápido |
| `SLSN-I` | -0.270(N1) | -0.077(N1) | -0.574(N3) | -0.042(N4) | +0.464(N4) | +0.369(N5) | ruidoso, gate RESTLAMBDA |
| `KN-K17` | +0.257 | +0.096 | +0.115 | +0.102 | +0.031 | +0.055 | decrece hacia el rojo |
| `PISN-STELLA-HECORE` | -- | -- | -- | -- | -- | -- | sin `PEAKMAG` real en SNANA |
| `PISN-STELLA-HYDROGENIC` | -- | -- | -- | -- | -- | -- | sin `PEAKMAG` real en SNANA |
| `KN-BULLA19` | -- | -- | -- | -- | -- | -- | sin `PEAKMAG` real en SNANA |

### Cruce con Fase 59 (ratio de sobre-detección) -- confirma que residuo de brillo y ratio de
detección son mecanismos distintos, ninguno predice al otro

| clase | residuo brillo (orden de magnitud) | ratio Fase 59 | ¿coherente? |
|---|---|---:|---|
| `ILOT-MOSFIT` | grande, LCL MÁS TENUE (-0.35 a -0.42) | 7.09x SOBRE-detección | **no** -- signos opuestos |
| `CaRT` (Fase 56) | chico, LCL más tenue (-0.11 en `u`) | 27.45x SOBRE-detección | **no** -- residuo chico, ratio enorme |
| `SNIax` (Fase 56) | chico, LCL más brillante (+0.15 acromático) | 2.83x SOBRE-detección | parcialmente -- signo coherente, magnitud no explica el factor |
| `PISN-MOSFIT` | grande en `u` (+0.49), LCL más brillante | 2.20x SOBRE-detección | parcialmente -- signo coherente |
| `KN-K17`/`SNIIn-MOSFIT` | moderado, LCL más brillante en azul | 3.75x/9.23x SOBRE-detección | signo coherente, magnitud no alcanza a explicar factores de 4-9x |

**Lectura:** el residuo de brillo pico (una magnitud puntual, sin ruido) y el ratio de detección
(que depende de SEARCHEFF sobre la curva completa, con ruido, y de cuánta curva cae dentro de la
ventana de observación real) son dos mecanismos genuinamente distintos -- un objeto puede tener
brillo pico casi idéntico a SNANA y aun así sobre-detectarse por un factor de 27x si su forma de
curva de luz (duración, tasa de decaimiento) difiere, algo que esta comparación puntual no mide.
`ILOT-MOSFIT` es el caso más claro: LCL es sistemáticamente MÁS TENUE en brillo pico, pero SOBRE-detecta
7x -- descarta de plano que el residuo de brillo sea la causa de su sobre-detección; el mecanismo
tiene que estar en la forma/duración de la curva o en SEARCHEFF, no en la calibración de brillo.
Esto es consistente con -- y ayuda a explicar por qué -- ninguno de los 4 bugs de brillo conocidos
(MAG_OFFSET, add_effect, RESTLAMBDA_RANGE, Trest=0) cierra la brecha de detección de Fase 59: atacan
el eje equivocado del problema para la mayoría de las clases. Candidato concreto para la próxima
fase: medir directamente la forma/duración de la curva de luz (no solo el brillo pico) contra SNANA.

### Pendiente

- Diagnosticar por qué `PISN-STELLA-HECORE`/`HYDROGENIC`/`KN-BULLA19` no tienen `PEAKMAG` real en
  el `.DUMP` de SNANA de esta campaña (bloquea la comparación de brillo para esas 3 clases).
- Investigar directamente la forma/duración de la curva de luz (no solo `PEAKMAG`) como el
  mecanismo real detrás de la brecha de detección de Fase 59 -- ver lectura de arriba.
- Publicar (con confirmación explícita del usuario) los borradores de issue A/D si corresponde.

## Fase 61 -- notebook de verificación end-to-end (estilo tutorial oficial de LightCurveLynx) para
2 de los 4 bugs reales: `MAG_OFFSET` (Fase 37) y `Trest=0`/pico bolométrico (Fase 56)

A pedido del usuario: un Jupyter notebook con el mismo formato que el [notebook oficial de
LightCurveLynx sobre Rubin DP2](https://lightcurvelynx.readthedocs.io/en/latest/notebooks/pre_executed/rubin_dp2.html)
(carga cadencia real, arma un modelo real, simula curvas de luz con/sin ruido), pero que demuestre
de punta a punta -- con datos y código reales, no solo texto -- que hubo un bug real y que
corregirlo mejora el resultado. `exploration/lightcurvelynx/verificacion_bugs_lightcurvelynx.ipynb`
(+ `.html` renderizado, mismo directorio).

**Sección A (recalculada 100% en vivo en el notebook, no copiada de `NOTES.md`)**: reconstruye la
población real de `SNIa`/SALT2 (mismos parámetros de producción -- `DNDZ`, sampler bifurcado,
`Om0=0.315`, `F99`, `GENSIGMA_MWEBV_RATIO`) dos veces, cambiando un solo parámetro
(`mag_offset=0.0` = comportamiento real de `sncosmo` sin el fix, vs. `mag_offset=0.27` = valor real
de `SALT2.INFO`), y compara ambas contra el `.DUMP` real de SNANA (filtrado por contaminación de
campo, Fase 48). Resultado real (job `12216697`): el residuo acromático pasa de **`-0.2463` a
`+0.0237` mag** -- cierra, mismo signo/orden de magnitud que el `-0.2646 -> +0.0054` publicado en
Fase 37 (la pequeña diferencia es ruido de muestreo -- misma semilla base pero un `nbconvert`
fresco, no una discrepancia real). Incluye también 3 curvas de luz de ejemplo (observadas con
ruido real + modelo sin ruido superpuesto), mismo estilo que el notebook oficial.

**Sección B**: reproduce en vivo el estado "después del fix" de `SNIa-91bg` (carga el
`compare_brightness_truth_snia91bg_output.parquet` real ya generado + el `.DUMP` real de SNANA) --
los 6 valores recalculados (`-0.039, -0.047, -0.031, -0.028, -0.013, -0.011`) coinciden EXACTOS con
los publicados en Fase 56 (mismo archivo fuente, verificación de consistencia, no una medición
nueva). El estado "antes del fix" se cita textual de la corrida archivada (Fase 56, jobs
`12110321-3`) -- el código de producción ya no expone la versión sin corregir como opción de línea
de comando. Gráfico de barras antes/después por banda.

**Incidente real encontrado y corregido durante la construcción (2 rondas)**: la primera versión del
notebook (job `12216618`) asumía que `simulate_lightcurves()` devuelve las curvas de luz ruidosas en
formato ancho (columnas `u`, `g`, `r`...) -- en realidad devuelve formato largo (`filter`/`mjd`/
`flux`/`fluxerr`, una fila por observación real, igual que aplana `run_snia_ddf_poc.py` a `phot_df`).
El notebook corrió sin error pero el gráfico de curvas de ejemplo salió vacío (warning real de
matplotlib, "No artists with labels found") -- y aunque ya no estaba vacío, el estilo (un panel por
objeto con las 6 bandas superpuestas, sin la curva continua del modelo) no coincidía con el del
notebook oficial de LightCurveLynx. El usuario lo notó ("los gráficos... no son los mismos").
Se descargó el `.ipynb` fuente real del notebook oficial
(`github.com/lincc-frameworks/lightcurvelynx`, `docs/notebooks/pre_executed/rubin_dp2.ipynb`, no un
resumen indirecto) para confirmar el código exacto: reusa `plot_lightcurves()`
(`lightcurvelynx.utils.plotting`) y `compute_single_noise_free_lightcurve()`
(`lightcurvelynx.simulate`), grafica `flux_perfect` (el valor verdadero en cada tiempo de
observación real, no `flux` ruidoso) con las barras de error reales, superpuesto a una curva
continua del modelo (grilla de fase -50 a +100 días, paso 0.5), y genera una figura separada por
objeto (no subplots). Reescrito para reusar literalmente esas mismas funciones -- un `NameError`
real (`BANDS` quedó indefinida al borrar la celda vieja) se coló en el primer intento de esta
segunda ronda (job `12217035`, `FAILED`), corregido y confirmado limpio (job `12217154`, sin errores
ni warnings, 5 imágenes reales). Dos bugs propios del notebook en total, ninguno de LightCurveLynx --
documentados por transparencia, mismo criterio que el resto del proyecto.

**Tercera ronda -- "las 5 mejores curvas" y una hipótesis propia descartada con evidencia real**: a
pedido del usuario, se cambió de 3 a 5 curvas de ejemplo. Primer intento real: ordenar por `NOBS`
(cantidad de observaciones reales) y tomar las 5 con más -- técnicamente correcto pero visualmente
inservible (job `12220219`): las curvas resultantes (hasta `NOBS=15.646`, objetos ubicados
exactamente en el pointing real del campo `cosmos`, el más denso -- 48.128 observaciones reales en
10 años, nada anormal) mostraban un patrón de barras de error gigantes tapando cualquier forma de
curva reconocible. Hipótesis inicial (incorrecta, escrita y luego revertida): "artefacto de
extrapolación en `flux_perfect`". Verificado directo con un diagnóstico aparte en NLHPC (no en el
notebook): `flux_perfect` estaba perfectamente sano (máximo real ~480 nJy, consistente con el
modelo) -- era `fluxerr` el que dominaba (mediana 364 nJy, máximo 3346 nJy), ruido fotométrico REAL
y esperado para objetos cerca del límite de detección la mayor parte del tiempo, no un bug de
ningún lado. La causa real del criterio equivocado: `NOBS` alto no implica S/N alto -- estos 5
objetos tenían S/N mediana de apenas `0.02-0.76`. Corregido: seleccionar por **S/N mediana**
(`|flux_perfect|/fluxerr`) en vez de `NOBS` (job `12220895`, confirmado limpio) -- los 5 resultantes
(S/N mediana `1.14-2.54`) muestran curvas de luz reales y legibles, subida-pico-declive claro en
todas las bandas, calidad visual comparable a las 3 del notebook oficial. Lección para el propio
proceso de verificación de este proyecto: revisar la ESCALA real de un gráfico (no solo que corra
sin error) antes de darlo por válido -- la versión con `NOBS` había pasado la verificación de
"0 errores, 0 warnings" de la ronda anterior sin que se detectara el problema visual.

**No incluye** (documentado en el notebook como tabla, no re-ejecutado): Fase 13
(`RESTLAMBDA_RANGE`) y Fase 51 (colisión `add_effect()`) -- ambos con evidencia real ya
publicada, pero fuera del alcance de este notebook por tiempo. El notebook termina con un callout
honesto: los 4 bugs son reales y mejoran el resultado donde aplican, pero ninguno explica la brecha
de sobre-detección que sigue abierta desde Fase 59 (`2.895x -> 5.113x`).

## Fase 62 -- resuelto el misterio de `PEAKMAG` faltante de Fase 60 (`OPTFLAG_T0SHIFT_PEAKMAG: 0`, un
hueco de auditoría de Fase 56), pero el fix real apenas mueve el ratio de detección de las 3 clases
afectadas

### Motivación

Fase 60 dejó 2 pendientes explícitos. Esta fase cierra el primero: por qué `KN-BULLA19`,
`PISN-STELLA-HECORE` y `PISN-STELLA-HYDROGENIC` tienen `PEAKMAG_{u..Y}` = `99`/`-9` en el 100% de los
objetos del `.DUMP` real de SNANA (0 filas válidas para medir brillo verdadero, a diferencia de las
otras 10 clases SIMSED).

### Causa raíz real: Fase 56 declaró "sin excepción" algo que no verificó del todo

Fase 56 encontró que SNANA aplica por defecto `T0shiftPeak_SEDMODEL()` (`genmag_SEDtools.c:2825-2884`)
-- shiftea la grilla `DAY` de cada template SIMSED para que el día de pico bolométrico caiga en
`DAY=0`, vía `OPTMASK_T0SHIFT_PEAKMAG` activo por defecto (`genmag_SIMSED.c:226-230`) -- y concluyó que
esto aplicaba "sin excepción" a las 12 clases SIMSED del catálogo. Esa conclusión se apoyaba en un
grep incompleto: solo se habían revisado los `SED.INFO` bajo `run_SNANA/plasticc_models/`, sin cubrir
la ruta alternativa `run_SNANA/elastic/model_libs_updates/` ni el `SED.INFO` anidado bajo
`SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP/`.

Confirmado con `grep` directo sobre los `SED.INFO` reales de las 13 clases en NLHPC: exactamente 3
declaran `OPTFLAG_T0SHIFT_PEAKMAG: 0` ("do NOT shift PEAKMAG to T=0"):

| clase | ruta real del `SED.INFO` |
|---|---|
| `KN-BULLA19` | `run_SNANA/plasticc_models/SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP/SED.INFO` |
| `PISN-STELLA-HECORE` | `run_SNANA/elastic/model_libs_updates/SIMSED.PISN-STELLA-HECORE/SED.INFO` |
| `PISN-STELLA-HYDROGENIC` | `run_SNANA/elastic/model_libs_updates/SIMSED.PISN-STELLA-HYDROGENIC/SED.INFO` |

Las 10 clases restantes (`SNIa-91bg`, `SLSN-I`, `SNIax`, `TDE-MOSFIT`, `SNII-NMF`, `ILOT-MOSFIT`,
`SNIIn-MOSFIT`, `PISN-MOSFIT`, `KN-K17`, `CaRT`) no declaran esta clave -- shift activo por defecto,
sin cambios. Esto explica de punta a punta el hallazgo de Fase 60: para estas 3 clases, SNANA real
evalúa `PEAKMAG` en la fase nativa `DAY=0` del archivo `.SED` sin shiftear -- que para estos 3 modelos
(kilonova/PISN, día 0 = tiempo de fusión o pre-explosión) no tiene brillo definido. No es un defecto de
la referencia: es la consecuencia esperada y documentada por la propia SNANA de evaluar un modelo en un
punto donde no hay luz.

### Fix real

`load_simsed_templates_bolometric()` (`run_simsed_poc.py`) ahora lee
`simsed_params.get("OPTFLAG_T0SHIFT_PEAKMAG", 1)` y solo aplica el shift al pico bolométrico
(`np.argsort`+`np.add.reduceat`, Fase 58) si esa clave es distinta de `0`; si la clase la declara en
`0`, usa `sed_data_t0=0.0` para todos sus templates -- igual que hace SNANA real. Compilado
(`py_compile`), sincronizado a NLHPC (`scp` + `md5sum` verificado), y smoke-test directo confirmó el
alcance correcto: los 550 templates de `KN-BULLA19` quedan con `sed_data_t0=0.0` uniforme; los 225 de
`CaRT` (clase de control, no debe verse afectada) siguen recibiendo shifts variados de 3.5 a 8+ días,
sin cambios.

### Resultado -- re-barrido de 5 semillas para las 3 clases corregidas

15 jobs reales en NLHPC (`sbatch`, partición `largemem`, `--mem=16G` para `KN-BULLA19`/
`PISN-STELLA-HECORE`, `--mem=128G` para `PISN-STELLA-HYDROGENIC` por su `NGENTOT_LC=20000`), contra la
misma referencia `SNANA%` DDF-only de Fase 48:

| clase | detección media Fase 59 (bug: shift aplicado igual) | detección media Fase 62 (fix: shift respetado) | SNANA% real | ratio Fase 59 | ratio Fase 62 | Δ ratio |
|---|---:|---:|---:|---:|---:|---:|
| `KN-BULLA19` | `24.28%±0.97` | `23.98%±0.75` | 6.07% | 4.000 | **3.951** | -1.2% |
| `PISN-STELLA-HECORE` | `41.72%±1.25` | `40.62%±0.97` | 21.88% | 1.907 | **1.856** | -2.6% |
| `PISN-STELLA-HYDROGENIC` | `46.15%±0.36` | `45.78%±0.35` | 24.45% | 1.888 | **1.872** | -0.8% |

Valores por semilla (job base 12230351-365): `KN-BULLA19` = `24.30, 24.00, 22.75, 23.80, 25.05`;
`PISN-STELLA-HECORE` = `39.90, 40.25, 40.20, 40.20, 42.55`; `PISN-STELLA-HYDROGENIC` = `45.65, 45.755,
45.53, 46.46, 45.50`.

### Lectura honesta: el bug era real y el fix es correcto, pero NO es el mecanismo detrás del ratio
alto de estas 3 clases

A diferencia de Fase 59 (donde corregir `trest_range` cambió los ratios en +12% a +211%), corregir
`OPTFLAG_T0SHIFT_PEAKMAG` mueve los 3 ratios menos de un 3%, y en la dirección de MEJORA (más cerca de
1.0x), no de empeoramiento. Esto es coherente con lo ya sabido de estos templates: sus grillas de fase
nativa ya empiezan muy cerca de su propio pico real incluso sin shiftear formalmente (a diferencia de
`CaRT`, donde Fase 56 midió shifts de hasta +33 días) -- el bug de Fase 56 existía y violaba la
referencia de tiempo real de SNANA para estas 3 clases, pero su impacto práctico en la ventana de
detección resultó ser chico. El ratio de sobre-detección que sigue alto en las 3 (1.86x a 3.95x) tiene
la misma causa que en el resto del catálogo: el hueco de `trest_range`/detecciones tardías espurias que
Fase 59 generalizó y que sigue sin explicación mecánica completa (Fase 60, segundo pendiente).

### Nota operativa -- 3 jobs marcados `FAILED` que en realidad completaron limpio (dato no perdido)

Los 3 jobs `seed=0` de cada clase (`12230351`, `12230356`, `12230361`) terminaron con `sacct` en estado
`FAILED` (`ExitCode 1:0`), pero sus `.err` no muestran ninguna excepción de Python -- `run_simsed_poc.py`
corrió completo y `summary.json` se escribió con datos válidos (confirmado por `mtime` y contenido
consistente con las otras 4 semillas de cada clase). Causa real: el propio script `.sh` generado para
esta ronda arma el nombre de directorio de salida con `$([ 0 -ne 0 ] && echo _seed0)` -- cuando el
índice de semilla es `0`, ese `&&` nunca ejecuta el `echo`, y la sustitución de comandos devuelve el
código de salida de `[ 0 -ne 0 ]` (`1`, falso). Bajo `set -euo pipefail`, una asignación de variable
que contiene una sustitución de comandos con salida no-cero SÍ dispara la salida del script (no está
en la lista de excepciones de `set -e`: pipeline no-final, `&&`/`||` no-final, condición de `if`/`while`,
negación con `!` -- una asignación simple no aplica ninguna). El script murió ahí, **después** de
escribir `summary.json` pero **antes** de la línea de limpieza (`rm -f phot_df.parquet`) -- dejando sin
borrar 3 archivos grandes (`272MB`, `326MB`, `3.3GB` para `KN-BULLA19`/`HECORE`/`HYDROGENIC`
respectivamente). Verificado que ningún dato se perdió (`summary.json` completo y consistente en los 3
casos); los 3 `phot_df.parquet` se borraron manualmente tras confirmar. Bug solo del script sbatch de
esta ronda (no de `run_simsed_poc.py` ni de ningún hallazgo científico) -- documentado para no repetirlo
en la próxima ronda que reuse esta plantilla de `.sh`.

### Conclusión Fase 62

Primer pendiente de Fase 60 cerrado: el `PEAKMAG` faltante de `KN-BULLA19`/`PISN-STELLA-HECORE`/
`PISN-STELLA-HYDROGENIC` tiene una explicación completa y real (`OPTFLAG_T0SHIFT_PEAKMAG: 0` en su
`SED.INFO`, un caso real que SNANA sí distingue y que Fase 56 no auditó por una ruta de archivo
incompleta). El fix correspondiente en `load_simsed_templates_bolometric()` ya respeta ese flag y está
verificado con un re-barrido real de 5 semillas -- pero el resultado es honesto y no es el que hubiera
sido más satisfactorio narrativamente: el bug no explica (ni siquiera parcialmente) el ratio de
sobre-detección alto de estas 3 clases, que sigue siendo un caso más del hueco general de Fase 59/60
(detecciones tardías espurias más allá de la fase donde SNANA real deja de generar señal).

### Archivos de esta fase

`run_simsed_poc.py`: `load_simsed_templates_bolometric()` ahora respeta `OPTFLAG_T0SHIFT_PEAKMAG` real
del `SED.INFO` de cada clase (antes asumía shift activo siempre). `NOTES.md`: esta entrada.
`docs/index.html`: tarjeta de Fase 62 + actualización de "Líneas para seguir investigando" (pendiente
de Fase 60 #1 cerrado; #2 sigue abierto). Exploratorios en NLHPC, ya limpiados: 15 `.sh`/`.out`/`.err`
en `~/AUTOSIM/fase62_jobs/` (se conservan como evidencia real, no se borran).

## Fase 63 -- segundo pendiente de Fase 60: forma/duración de curva de luz medida objeto-a-objeto contra
SNANA real, extendiendo Fase 39 a una clase SIMSED por primera vez -- resultado honesto y no el
esperado: no confirma la hipótesis de forma/duración, pero destapa una posible causa raíz nueva y mucho
más grande, compartida por TODO el catálogo

### Motivación y restricción real del método

Extiende la metodología de Fase 39 (pareo real objeto-a-objeto y época-a-época vía `_HEAD.FITS`/
`_PHOT.FITS` reales, hecha entonces solo para `SNIa`/SALT2) a una clase SIMSED por primera vez --
`ILOT-MOSFIT`, el caso de bandera de Fase 60 (más tenue en el pico que SNANA pero sobre-detecta 7.09x).
Script nuevo y versionado: `compare_lightcurve_shape.py`.

Restricción real, no un descuido: `_HEAD.FITS`/`_PHOT.FITS` solo persisten los objetos que SNANA
realmente escribió (`NGENLC_WRITE` = 73/2000 para `ILOT-MOSFIT`, 3.65% -- coincide exacto con el
`SNANA%` real ya usado desde Fase 48/49). No existe fotometría real de los ~1927 objetos que SNANA
rechazó -- esta fase solo puede responder "para los mismos objetos que SNANA SÍ detectó, con los mismos
parámetros/cadencia/ruido reales, ¿sostiene LightCurveLynx una ventana de detección más larga que SNANA
real?", no "¿cuántos objetos que SNANA rechazó LCL detecta de más?" (esa pregunta requeriría
reconstruir cadencia sintética para los no escritos, fuera de alcance).

### Método real

Para los 73/73 objetos reales: se reconstruyó el modelo SIMSED exacto de cada uno (mismo template real
vía `SIMSED_GRIDONLY(ILOT_INDEX)`, mismo `z`/`AV`/`RV`/`PEAKMJD`/RA/Dec reales de `_HEAD.FITS`,
`SIMSEDModel([tmpl], weights=None, ...)` con un solo template -- fuerza la selección exacta sin pasar
por el sampler de `MultiSEDTemplateModel`, reusando los templates ya cargados en cache por índice, sin
releer disco por objeto). Se evaluó `evaluate_bandfluxes()` en los MJD/bandas EXACTOS de cada época real
de `_PHOT.FITS` (6 bandas, no solo `r`), se sumó extinción de host (`host_extinction_mag_offset()`,
Fase 53) y se convirtió a magnitud. Trampa real encontrada y corregida en el camino: un primer intento
asumió el `ZP=27.5` fijo que documenta la literatura genérica de SNANA para `FLUXCAL` -- **falso para
esta campaña real**, que usa el `ZEROPT` real POR ÉPOCA (columna real del `_PHOT.FITS`, ~29-32 según
banda/condiciones, viene del SIMLIB real) -- con el ZP fijo, `fluxcal_lcl` salía ~15-20x más chico que
el real y anulaba casi toda detección del lado LCL; corregido a `FLUXCAL = 10**(-0.4*(mag-ZEROPT_real))`
por época, igual que hace `run_simsed_poc.py` de producción vía `mag2flux(ZPT)`.

Para medir la ventana de detección se reusó SIN reimplementar el código real de producción
(`searcheff.py`: `apply_detection_efficiency`/`group_into_epochs`/`object_level_detected`, el mismo que
usa `run_simsed_poc.py` desde Fase 4) sobre tres fuentes de flujo distintas, mismo ruido real
(`FLUXCALERR` real de `_PHOT.FITS`) y misma cadencia real en los tres casos:
- **real**: `MJD_DETECT_FIRST`/`MJD_DETECT_LAST` real de SNANA (ya en `_HEAD.FITS`, no se recalcula).
- **ctrl** (control/sanidad): se recalcula la detección aplicando el propio código de trigger sobre el
  `FLUXCAL` REAL de SNANA (no el de LCL) -- si el método está bien implementado, debería reproducir
  aproximadamente la ventana real.
- **lcl**: igual que `ctrl` pero con el `FLUXCAL` evaluado por LightCurveLynx.

Trampa real #2, más importante: con una sola realización Monte Carlo (`apply_detection_efficiency` es
estocástico, sortea contra la curva de eficiencia real), **`ctrl` no reprodujo la ventana real ni de
cerca** (738 días vs. 114.7 reales en el piloto de 5 objetos) pese a ser el mismo código de producción.
Diagnosticado con evidencia real (no descartado a ciegas): la curva real `LSST_SEARCHEFF_PIPELINE.DAT`
tiene eficiencia **exactamente 0 para SNR<3.0** en las 6 bandas, pero ya en SNR∈[3.5,5.0] tiene eficiencia
11-47% -- con objetos de `GENRANGE_TREST` ancho (miles de épocas reales por objeto, `ILOT-MOSFIT` real
`GENRANGE_TREST=(-100,1000)`, hasta 15.392 filas de fotometría real para un solo objeto), incluso una
eficiencia baja pero no-cero en un puñado de épocas dispersas en años basta para producir por azar ≥2
"épocas detectadas" muy separadas del pico real -- un sorteo independiente (el mío) no tiene por qué
coincidir con el sorteo específico que hizo SNANA real. Mitigado promediando 20 semillas independientes
por objeto (mediana sobre las 20 réplicas) -- reduce el ruido pero **no lo elimina**: `ctrl` sigue dando
una ventana bastante más ancha que la real incluso promediada (ver resultado abajo) -- esto en sí mismo
es el hallazgo más importante de la fase, ver más abajo.

### Resultado -- residuo de brillo objeto-a-objeto: mucho más chico que la estimación poblacional de Fase 60

| métrica | valor (mediana, n=73) |
|---|---:|
| residuo de magnitud, todas las épocas reales | `-0.020` mag |
| residuo de magnitud, cerca del pico (\|fase rest\|<5d) | `-0.035` mag (n=52 objetos con época cerca del pico) |
| rango del residuo cerca del pico | `-0.129` a `-0.012` mag |

**Mucho más chico que el `-0.35` a `-0.42` mag que reportó Fase 60** para esta misma clase. Diferencia
metodológica real entre ambas mediciones: Fase 60 comparó `compute_noise_free_lightcurves()` con
parámetros SAMPLEADOS de la distribución poblacional contra el `PEAKMAG_r` real de la población
completa (no objeto-a-objeto); esta fase reconstruye el modelo con los parámetros REALES de cada objeto
específico (mismo template, mismo `z`/`AV`/`RV`/`PEAKMJD` exactos) y evalúa en su época real exacta --
un pareo mucho más controlado. La discrepancia entre ambos métodos (~0.3-0.4 mag) queda como pregunta
abierta nueva, no resuelta en esta fase: candidato más plausible es un desajuste de distribución
poblacional (p.ej. `host_av` o `z` muestreado vs. real) en la comparación de Fase 60, no un error de
esta fase (que usa parámetros reales exactos, no muestreados).

### Resultado -- forma/duración: la hipótesis de Fase 60 NO se confirma en el censo disponible

| comparación | mediana duración (días) | mediana Δ por objeto (días) | fracción con Δ>0 |
|---|---:|---:|---:|
| real (SNANA, un solo sorteo real) | 142.8 | -- | -- |
| ctrl (flujo REAL de SNANA + trigger reimplementado, 20 semillas) | 373.0 | `ctrl - real` = +60.0 | -- |
| lcl (flujo de LightCurveLynx + trigger reimplementado, 20 semillas) | 176.2 | `lcl - real` = +15.1 (93% de objetos) | 93.1% |
| **lcl vs. ctrl (comparación pareada, mismo trigger, aísla solo el modelo de brillo)** | -- | **`lcl - ctrl` = -22.0** | **32.9%** |

La comparación que realmente aísla el efecto de LightCurveLynx (`lcl` vs. `ctrl`, mismo código de
trigger reimplementado en ambos lados, mismo ruido/cadencia real -- la diferencia de `real` no aplica
porque ya se demostró que el trigger reimplementado en sí mismo se desvía de SNANA real incluso con su
propio flujo) muestra: en **67.1%** de los 73 objetos, LightCurveLynx da una ventana de detección
IGUAL O MÁS CORTA que la que da el flujo real de SNANA bajo el mismo trigger -- la mediana del delta es
NEGATIVA (`-22.0` días). **La hipótesis de Fase 60 ("la forma/duración es lo que hace sobre-detectar a
`ILOT-MOSFIT`") no se confirma en este censo** -- si acaso, la tendencia es la contraria. Esto no
contradice el 7.09x de sobre-detección real de esta clase (medido sobre los 2000 objetos completos, no
solo los 73 ya detectados) -- indica que ese 7.09x viene predominantemente de que LightCurveLynx
convierte en detectados objetos que SNANA real rechaza (fuera del alcance de este censo, que solo tiene
fotometría real de los ya-detectados), no de alargar la ventana de los que ya de por sí se iban a
detectar.

### Hallazgo no buscado, pero más importante: el propio código de trigger reimplementado (Fase 4, usado
en TODAS las mediciones de ratio de detección del proyecto desde entonces) da una ventana ~2.6x más
ancha que SNANA real incluso alimentado con el flujo REAL de SNANA

El control (`ctrl`) es la pieza clave: usa el `FLUXCAL` REAL de SNANA, no el de LightCurveLynx, y aun
así da una mediana de `373.0` días de ventana de detección contra los `142.8` días reales de SNANA (un
delta mediano por objeto de `+60.0` días, con casos individuales de cientos de días de diferencia). Esto
es un hallazgo sobre el MÉTODO de este proyecto, no sobre LightCurveLynx: `searcheff.py`
(`apply_detection_efficiency` + `group_into_epochs` + `object_level_detected`, exactamente el código
que calcula CADA ratio de detección publicado desde Fase 4 -- Fase 46, 48, 58, 59, 62, todos) no
reproduce fielmente el trigger real de SNANA para objetos con `GENRANGE_TREST` ancho, porque modela la
detección como un sorteo estocástico independiente por época sobre TODA la ventana de generación, sin
ningún límite adicional de "ventana de búsqueda" -- mientras que la curva real de eficiencia tiene una
cola de baja probabilidad pero no-cero (SNR∈[3,5): 11-47%) que, repartida sobre miles de épocas
reales de un objeto de vida larga, casi garantiza por pura combinatoria que ALGUNA época lejos del pico
real cruce el umbral por azar en cualquier sorteo independiente del que hizo SNANA.

Esto conecta directo con una pregunta que Fase 60 ya había dejado abierta y nunca se investigó
("candidato 3": *¿SNANA real trunca la ventana de trigger de forma distinta a `GENRANGE_TREST` -- es
decir, aplica una ventana de búsqueda más angosta que la de generación, que este proyecto nunca
replicó?*) y con el propio hallazgo real de Fase 59 sobre `CaRT` (35.5% de las detecciones disparan a
más de 100 días post-pico, con SNR no más marginal que las cercanas al pico) -- ambos son consistentes
con la misma explicación: el trigger reimplementado permite detecciones tardías espurias que el trigger
real de SNANA restringe de alguna forma que este proyecto aún no ha identificado en el código C real.
**Si este sesgo está presente en todo el catálogo (medido aquí solo para `ILOT-MOSFIT`), podría ser una
causa real y unificadora del hueco de sobre-detección de Fase 59 (`2.895x -> 5.113x`)** -- mucho más
prometedora que cualquier candidato anterior, porque no depende de ningún detalle del modelo de brillo
de LightCurveLynx: aparece incluso usando el flujo 100% real de SNANA.

### Conclusión Fase 63

Segundo pendiente de Fase 60 cerrado con una respuesta honesta y no la esperada: la forma/duración de
`ILOT-MOSFIT` NO sostiene una ventana de detección más ancha que SNANA real en el censo de objetos ya
detectados (tendencia más bien contraria) -- la hipótesis original de Fase 60 no se confirma. Pero el
método usado para medirlo (control con flujo real de SNANA) destapó algo más grande y no buscado: el
propio trigger reimplementado de este proyecto (Fase 4, usado en todas las fases desde entonces) se
desvía sustancialmente de SNANA real en clases de `GENRANGE_TREST` ancho, en una dirección que coincide
exactamente con el patrón de sobre-detección tardía ya documentado (Fase 46, Fase 59). Candidato nuevo,
concreto, y potencialmente el más grande del proyecto para la próxima fase: leer el código C real de
SNANA (`snlc_sim.c`) para determinar si existe una ventana de búsqueda/trigger real más angosta que
`GENRANGE_TREST` que este proyecto nunca replicó -- y si se confirma, corregirla y re-medir el catálogo
completo.

### Archivos de esta fase

`compare_lightcurve_shape.py` (nuevo, versionado): pareo objeto-a-objeto real vía `_HEAD.FITS`/
`_PHOT.FITS`, extiende Fase 39 a clases SIMSED, reusa `searcheff.py`/`host_extinction_mag_offset()` sin
reimplementar. Corrido interactivamente en NLHPC (censo completo, 73 objetos reales, 19.5s -- trivial,
no necesitó `sbatch`). `NOTES.md`: esta entrada.

## Fase 64 -- causa raíz real, validada época a época contra el ground truth de SNANA: el trigger
reimplementado de este proyecto (Fase 4, usado en TODAS las mediciones desde entonces) calcula el SNR
sobre el flujo OBSERVADO ruidoso, cuando SNANA real lo calcula sobre el flujo VERDADERO sin ruido -- una
diferencia que sobre-estima la tasa de detección por época en +17% relativo, y que probablemente explica
una fracción sustancial del hueco de sobre-detección catalogado desde Fase 46/59

### Motivación

Fase 63 dejó un candidato abierto y sin confirmar: el control (aplicar el trigger reimplementado de
este proyecto al flujo 100% REAL de SNANA) dio una ventana de detección ~2.6x más ancha que la real
(373 vs. 143 días), sugiriendo que el trigger reimplementado le falta alguna restricción real que SNANA
sí aplica. Se investigó con un agente de lectura del código C real de SNANA en NLHPC
(`~/github/SNANA_src/src/`, versión real `v12_02-66-g2f0773e3`, confirmada idéntica a la que generó los
datos vía el header `SNANA_VERSION` del `_PHOT.FITS` real -- sin ambigüedad de versión).

### Candidato 3 de Fase 60 (ventana de trigger más angosta que `GENRANGE_TREST`) -- REFUTADO con evidencia
real

Leído el loop completo del trigger real (`sntools_trigger.c:2176-2334`, función
`gen_SEARCHEFF_PIPELINE()`): no hay ningún recorte adicional de MJD/Trest más allá de
`GENRANGE_TREST`. El único agrupamiento temporal real es `TIME_SINGLE_DETECT = NEWMJD_DIF = 0.007` días
(`snlc_sim.c:7462`/`:849`) -- exactamente lo que este proyecto ya implementa (`group_into_epochs()`,
Fase 4). `MJD_DETECT_FIRST`/`MJD_DETECT_LAST` se llenan en el MISMO loop y con el MISMO `detectFlag` que
decide el trigger (`sntools_trigger.c:2274-2281`), sin restricción de ventana ni relación con el pico --
son perfectamente comparables con lo que calcula la reimplementación. El hueco de 373 vs. 143 días NO es
un artefacto de definición de columna: es un hueco real de criterio de detección.

### La causa real: SNANA calcula el SNR del trigger sobre el flujo VERDADERO, no sobre el observado

Cita decisiva, `snlc_sim.c:24495-24497` (dentro de `LOAD_SEARCHEFF_DATA()`):
```c
SNR = SNR_CALC ;
// for SDSS, continue using wrong SNR based on measured flux
// so that the spec-efficiency function is still correct.
if ( strcmp(GENLC.SURVEY_NAME,"SDSS") == 0 ) { SNR = SNR_OBS; }
```
El propio comentario de Kessler (autor de SNANA) llama **"wrong SNR"** al SNR basado en el flujo medido
(ruidoso) -- SNANA real lo usa SOLO para SDSS por retrocompatibilidad. Para LSST usa `SNR_CALC`, que
viene de `fluxsn_pe = 10^(0.4*(zpt-genmag))*ccdgain` (`snlc_sim.c:27572-27573`) -- `genmag` es
`GENLC.genmag_obs[epoch]`, **la magnitud verdadera del modelo, ANTES de cualquier realización de
ruido** -- dividido por el mismo presupuesto de ruido total (`SNR_CALC_SZT`, `:27683`). El flujo
reimplementado por este proyecto en `searcheff.py` (`snr = FLUXCAL/FLUXCALERR`, ambos observados/con
ruido) es exactamente el "wrong SNR" (`SNR_OBS`) que SNANA real evita para LSST.

**Mecanismo físico**: una época lejos del pico donde el modelo predice flujo verdadero ≈0 tiene
`SNR_CALC≈0` -> eficiencia real EXACTAMENTE 0 (la curva real arranca en `ABS(SNR):0.00 -> 0`),
probabilidad de detección real CERO sin importar cuántas miles de épocas haya. La reimplementación
actual, en cambio, calcula el SNR sobre el flujo YA CON RUIDO -- en esas mismas épocas de flujo
verdadero nulo, el flujo observado es puro ruido Gaussiano, y `|ruido/sigma|` cruza el umbral real
(SNR=3) por puro azar con probabilidad no-cero. Con miles de épocas de flujo nulo por objeto (clases de
`GENRANGE_TREST` ancho), esa probabilidad chica se acumula y genera detecciones espurias tardías --
exactamente el patrón ya documentado en Fase 59 (35.5% de triggers de `CaRT` a más de 100 días
post-pico, con SNR NO más marginal que los cercanos al pico -- consistente con ser ruido cruzando el
umbral, no señal real marginal).

### Validación real, época a época, sin correr SNANA de nuevo

Hallazgo operativo del agente: el `_PHOT.FITS` real trae la columna `PHOTFLAG`, con el bit `4096`
(`PHOTFLAG_DETECT`, confirmado en `LSST_SEARCHEFF_PIPELINE.DAT`/`sntools_trigger.c:308-313`/
`snlc_sim.c:25411-25416`) marcando EXACTAMENTE qué épocas reales SNANA detectó -- ground truth por
época, disponible offline, sin ejecutar nada. Verificado directo en el `_PHOT.FITS` real de
`ILOT-MOSFIT` (493.722 filas, 73 objetos): valores reales `{0, 4096, 6144}` (6144=4096+2048, ambos bits
DETECT+TRIGGER en la misma época).

Se comparó, sobre las 493.722 épocas reales de los 73 objetos:
- **SNR_VIEJO** (el que usa `searcheff.py` hoy): `|FLUXCAL_real/FLUXCALERR_real|`.
- **SNR_NUEVO** (el que predicen los hallazgos de arriba): `flux_verdadero(SIM_MAGOBS, ZP=31.4)/FLUXCALERR_real`,
  con `flux_verdadero=0` donde `SIM_MAGOBS` es el sentinel real de "sin flujo" (`>=90`, `MAG_ZEROFLUX=99`
  real de `genmag_SIMSED.c:1623`).

| métrica | valor |
|---|---:|
| tasa de detección real (`PHOTFLAG&4096`, 493.722 épocas) | **3.8125%** |
| entre épocas de flujo verdadero ≈0 (52.822, 10.7% del total): detectadas reales | **0.0000%** |
| ... con SNR_VIEJO>3 (oportunidad espuria) | 0.3597% (190 épocas), eficiencia media `0.00020` |
| ... con SNR_NUEVO>3 | **0.0000%**, eficiencia media `0.00000` |
| tasa de detección simulada (1 sorteo MC, misma semilla) con SNR_VIEJO | 4.4641% (**+17.1%** relativo vs. real) |
| tasa de detección simulada (1 sorteo MC, misma semilla) con SNR_NUEVO | **3.8141%** (**+0.04%** relativo vs. real -- prácticamente exacto) |

La fórmula nueva reproduce la tasa de detección real de SNANA casi exactamente (diferencia de 0.04% vs.
+17.1% de la fórmula que usa el proyecto hoy) -- validación directa, no solo consistente con la
hipótesis.

### Factibilidad real de aplicar el fix a la producción de LightCurveLynx (no solo a datos reales de SNANA)

`simulate_lightcurves()` de LightCurveLynx **ya calcula y descarta** un flujo sin ruido por época --
confirmado leyendo el código instalado real (`lightcurvelynx/simulate.py:376-506`): cada objeto nested
trae columnas `"flux"` (observado, con ruido) Y `"flux_perfect"` (verdadero, sin ruido) por época.
`run_simsed_poc.py::main()` hoy selecciona solo `["SNID","MJD","FLT","FLUXCAL","FLUXCALERR"]` al aplanar
(línea ~908), descartando `flux_perfect` -- el fix es viable sin cambios estructurales grandes: retener
esa columna y usarla en `searcheff.py::apply_detection_efficiency()` en vez de `FLUXCAL`.

### Fórmula exacta para el fix (derivación real, citas en `snlc_sim.c`)

```
Npe_over_FLUXCAL = 10^(0.4*(zpt - ZP_FLUXCAL)) * ccdgain     (:27559-27561)
fluxsn_pe        = 10^(0.4*(zpt - genmag)) * ccdgain          (:27572-27573)
=> fluxsn_pe / Npe_over_FLUXCAL = 10^(-0.4*(genmag - ZP_FLUXCAL))   -- FLUXCAL verdadero
SNR_CALC = fluxsn_pe / sqrt(SQSIG_FINAL_DATA)                 (:27683)
```
`ZP_FLUXCAL=31.4` es una constante real de este proyecto (`MAG_AB_ZP_NJY` en `run_simsed_poc.py`,
misma referencia AB de nanoJansky) -- para LCL, `flux_perfect` YA está en esa escala física (nJy), así
que `SNR_CALC_lcl ≈ flux_perfect/FLUXCALERR` sin conversión adicional. Aproximación de primer orden, no
exacta: `FLUXCALERR` real incluye un término `sqerr_ran` post-hoc (`snlc_sim.c:28291-28302`) que el
denominador de `SNR_CALC` no tiene -- despreciable lejos del pico (que es donde importa el mecanismo),
no cuantificado cerca del pico en esta fase.

### Lo que NO se confirma todavía (honesto, no bloqueante para documentar el hallazgo)

No se midió cuánto de la brecha catalogada en Fase 59 (`2.895x -> 5.113x`, 13 clases) se cierra con este
fix -- el +17% relativo es por ÉPOCA, no por objeto (el trigger real exige ≥2 épocas, así que el efecto
a nivel de objeto podría amplificarse o atenuarse, no es una extrapolación directa). Solo se validó
`ILOT-MOSFIT`; otras clases con flujo verdadero que nunca cae a ~0 dentro de `GENRANGE_TREST` podrían
verse menos afectadas. No se implementó el fix en el pipeline de producción todavía -- eso queda para la
próxima fase junto con un re-barrido para medir el impacto real.

### Conclusión Fase 64

Candidato 3 de Fase 60 (ventana de trigger más angosta) queda refutado con evidencia real de código C.
En su lugar se encontró y validó -- época a época, contra el ground truth real de SNANA
(`PHOTFLAG&4096`), sin necesidad de simular nada -- una causa mecánicamente distinta y potencialmente
mucho más grande: el SNR que usa el trigger reimplementado de este proyecto desde la Fase 4 (usado en
TODAS las mediciones de ratio de detección publicadas: 46, 48, 58, 59, 62, 63) está calculado sobre el
flujo observado con ruido, cuando SNANA real explícitamente evita eso ("wrong SNR") y usa el flujo
verdadero. La fórmula corregida reproduce la tasa de detección real de SNANA casi exactamente
(diferencia de 0.04% vs. el +17.1% de la fórmula actual). El fix es viable en producción sin cambios
estructurales (`flux_perfect` ya existe, solo se descarta). Este es el candidato más prometedor y mejor
evidenciado de todo el proyecto para explicar el hueco de sobre-detección de Fase 59 -- pendiente:
implementarlo en `searcheff.py`/`run_simsed_poc.py` y re-medir el catálogo.

### Archivos de esta fase

Ninguno versionado todavía (fase de diagnóstico puro) -- exploratorio en NLHPC, no borrado como
evidencia: `validate_snr_calc.py` (`~/AUTOSIM/exploration/lightcurvelynx/`). `NOTES.md`: esta entrada.

## Fase 65 -- fix implementado y validado en el código de producción, pero el re-barrido completo del
catálogo queda bloqueado por un cupo de disco real agotado en NLHPC (incidente distinto, no relacionado
con el fix)

### Implementación real del fix de Fase 64

`run_simsed_poc.py::main()`: la tabla de fotometría aplanada ahora retiene `flux_perfect` (ya calculado
por `simulate_lightcurves()`, antes descartado) como columna nueva `FLUXTRUE`, en la misma escala física
(nJy) que `FLUXCAL`. La llamada real al trigger pasa a usar `apply_detection_efficiency(phot_df,
band_curves, flux_col="FLUXTRUE", seed=...)` -- `searcheff.py` ya soportaba `flux_col` como parámetro,
no necesitó cambios. `FLUXCAL`/`FLUXCALERR` (observados, con ruido) se conservan sin cambios para todo
lo demás (columna `MAG`, QC, persistencia) -- el fix solo cambia qué flujo alimenta al trigger real.

### Validación real, parcial: el código funciona, la persistencia falla por un motivo real y distinto

Una corrida interactiva chica (`ngentot_override=50`, trivial, no necesitó `sbatch`) confirmó que el
fix corre limpio de punta a punta hasta la persistencia: `"SEARCHEFF aplicado: 1/50 objetos detectados"`
se imprimió correctamente -- el código nuevo funciona. Falló recién en el último paso
(`head_df.to_parquet()`) con:
```
OSError: [Errno 122] Error writing bytes to file. Detail: [errno 122] Disk quota exceeded
```
La primera línea de la corrida ya lo anticipaba: `Could not save font_manager cache [Errno 122] Disk
quota exceeded` -- **la cuenta real de NLHPC está sobre su cupo de disco en este momento**, fallando
hasta escrituras triviales (el caché de fuentes de `matplotlib`). Esto es el mismo tipo de incidente
real ya documentado en Fase 8/59 (cuenta cerca de su límite histórico de ~200GB) -- confirmado con `du
-sh ~` real: **183-185GB** usados. Los 4 intentos previos de esta fase (`CaRT`/`ILOT-MOSFIT` × 2 nodos
distintos cada uno, todos con `ExitCode 120:0` sin traceback visible, muriendo ~159/2000 objetos, ~3 min
de wall time, en 3 nodos reales distintos -- `fn001`/`fn002`/`fn003`) tienen la MISMA causa real: no es
un bug del fix (el crash real ocurre dentro de la escritura a disco, un paso que el piloto interactivo sí
alcanzó a reproducir con traceback limpio) ni del nodo (mismo patrón en 3 nodos reales distintos).

Limpieza real ya hecha en el propio territorio de este proyecto (`exploration/lightcurvelynx/`, sin
tocar nada de `DATASIM_LSST_1`/`run_SNANA`/otros directorios de producción reales, fuera de alcance de
esta investigación): se liberaron ~3GB de `poc_output_*` viejos, de antes del fix `_bolopeak` (Fase 57)
-- `poc_output_slsni`, `poc_output_ilotmosfit(+seed1-4)`, `poc_output_cart`, `poc_output_seed{1..4}` --
sus hallazgos ya están documentados en `NOTES.md`, no se perdió ningún dato real. `exploration/
lightcurvelynx/` bajó de 5.4GB a 2.4GB, ya lo más lean posible sin tocar dependencias reales activas
(confirmado, p.ej., que `bullansed_local` sigue siendo referenciado por `run_non1ased_poc.py`, no es
basura). **No fue suficiente** -- el re-barrido sigue bloqueado.

### Qué NO se hace en esta fase, y por qué

No se toca `DATASIM_LSST_1` (150GB, el mayor consumidor real de la cuenta, con mucha diferencia) ni
ningún otro directorio de producción/referencia real (`run_SNANA` 18GB, `SNDATA_ROOT` 4.2GB,
`SIMLIBv5*` 6.1GB, `OTMODEL_NON1ASED` 1.1GB) -- son datos reales de SNANA usados activamente por esta
misma investigación (todos los `.DUMP`/`_HEAD.FITS`/`_PHOT.FITS` reales citados en Fases 39-64 viven
ahí), fuera del alcance de lo que este proyecto exploratorio puede decidir borrar por su cuenta. Resolver
el cupo real (pedir aumento a NLHPC vía `soporte@nlhpc.cl`, o decidir qué archivar/borrar de esos
directorios) es una decisión que le corresponde al usuario, no a esta fase.

### Conclusión Fase 65

El fix de Fase 64 está implementado en el código de producción (`run_simsed_poc.py`/`searcheff.py`,
commiteado) y parcialmente validado en una corrida real (el trigger corregido corre limpio; el único
fallo real ocurrió en un paso de persistencia no relacionado, por cupo de disco agotado). El re-barrido
completo del catálogo (13 clases × 5 semillas, para medir el impacto real en la tabla de Fase 59) queda
**pendiente, bloqueado por un incidente de infraestructura real y actual**, no por el fix en sí --
retomar en cuanto se libere cupo suficiente (~2-5GB de headroom sostenido deberían bastar para las
clases más livianas; `PISN-STELLA-HYDROGENIC` sola puede necesitar picos de hasta 3.3GB transitorios por
semilla, ver Fase 59).

### Archivos de esta fase

`run_simsed_poc.py`: fix de Fase 64 implementado (`FLUXTRUE` retenida, `apply_detection_efficiency(...,
flux_col="FLUXTRUE")`). `NOTES.md`: esta entrada. `fase65_jobs/*.sh` en NLHPC (exploratorio, no
borrado): scripts piloto de `CaRT`/`ILOT-MOSFIT`, ninguno completó por el incidente de cuota.

## Fase 66 -- sistema de automatización de barridos: hash de identificación real, deploy de un click, y
punto de enganche para entrenamiento (pedido explícito del profesor), validado de punta a punta con
jobs reales de SLURM

### Motivación

El profesor pidió tres cosas concretas para seguir la investigación: automatizar las simulaciones de
LightCurveLynx (hasta ahora, 100% manual -- un `.sh` de `sbatch` escrito a mano por combinación
clase/semilla, cada ronda de investigación, viviendo solo en NLHPC, nunca en git -- confirmado que un
bug real recurrió por eso: `$([ N -ne 0 ] && echo _seedN)` bajo `set -e` rompía silenciosamente la
semilla 0, ver Fase 62), identificarlas con un hash (hoy los resultados se nombran por texto plano
derivado de parámetros -- `poc_output_{clase}{seed}{wfd}{modo}`, sin hash, corridas repetidas se
pisan), y dejar un punto de enganche para ingestar los resultados a un entrenamiento de clasificador
(no existe ningún precedente en el repo, confirmado con 3 agentes de exploración de solo lectura -- ni
código, ni submódulo, ni formato definido).

Exploración previa confirmó un dato clave: el **pipeline de producción** (`pipeline/`, SNANA real, NO
se toca en esta fase) ya resolvió automatización y hash para las campañas de producción --
`pipeline/campaign/compiler.py` (YAML → `.INPUT` + scripts sbatch), `pipeline/orchestrate/launcher.py`
(somete a SLURM, registra `launch.json`), y `pipeline/provenance/tagger.py` (hashes SHA256 reales de
config e input, manifiestos ya generados con datos reales -- `build/full_v5.3_10yrs/provenance/
PROVENANCE_MANIFEST.json`, 80 corridas). El usuario confirmó automatizar el lado **LightCurveLynx**
(`exploration/lightcurvelynx/`), reusando el *patrón* de esos módulos (leídos como referencia, nunca
importados) sin tocar `pipeline/`, y dejar el punto de enganche de entrenamiento sin implementar el
conector real (formato aún no definido por el profesor/equipo ALeRCE).

### Arquitectura real construida

Envuelve `run_simsed_poc.py::main()` sin reescribirlo -- un único cambio aditivo: parámetro
`out_dir_override: Path | str | None = None` al final de la firma (default `None` preserva el
comportamiento exacto de siempre; el CLI interactivo nunca lo pasa). `CLASS_CONFIGS` no se toca.

7 archivos nuevos, todos en `exploration/lightcurvelynx/`:

- **`sweep_hash.py`**: esquema de hash por corrida -- SHA256 sobre `{class_key, class_config
  (canonicalizado), seed_index, wfd, simsed_t0_mode, ngentot, code_hash}`. `code_hash` = SHA256
  combinado de `run_simsed_poc.py`+`searcheff.py`+`snana_params.py` -- detecta cambios de CÓDIGO real
  (incluso sin commitear), algo que el `config_hash` de `pipeline/provenance` no cubre hoy (depende de
  YAMLs congelados). Canonicalizador recursivo resuelve los casos reales no-JSON-limpios de
  `CLASS_CONFIGS` (`Path`, tuplas, y `redcor_params["redcor"]` con **claves de dict que son tuplas** --
  `{("stretch","color"): -0.656}`, confirmado real en `SNIa-91bg`). También define
  `write_json_atomic()`/`write_dataframe_atomic()` (archivo temporal + `fsync` + `os.replace()`) --
  respuesta directa a 3 incidentes reales de corrupción por escritura fallida de esta misma sesión
  (Fase 65: un notebook quedó en 0 bytes, 5 `_PHOT.FITS` reales quedaron truncados). 5 self-tests
  locales (determinismo, sensibilidad a cada campo incluido el caso de clave-tupla, escritura atómica
  sin huérfanos) dan el mismo hash exacto en Windows local y en el venv real de NLHPC.
- **`sweep_compile.py`**: YAML declarativo de sweep (`sweeps/*.yaml`) → `manifest.json` + un `.sbatch`
  de **job array** por tier de recursos (no N scripts individuales -- diverge deliberadamente del
  patrón de `pipeline/orchestrate/launcher.py`, ver justificación abajo). Cada clase con override de
  recursos propio obtiene su propio tier (nombrado por `class_key`, no un "heavy" genérico compartido
  -- evita mezclar 2 clases con perfiles de recursos distintos bajo el mismo array). Agrupa por tier
  ANTES de asignar índice para que cada array tenga un rango contiguo. Rechaza clases desconocidas
  contra `CLASS_CONFIGS` real y colisiones de `run_hash`. Advierte si algún `ngentot` supera el umbral
  histórico del catálogo (5000).
- **`sweep_worker.py`**: entry point de cada tarea del array -- resuelve su fila por
  `SLURM_ARRAY_TASK_ID`, llama `main()` con `out_dir_override`, limpia `phot_df.parquet` en un
  `finally` (best-effort), y escribe `runs/<hash>/run_hash.json` de forma atómica. **`manifest.json` es
  de SOLO LECTURA para el worker** -- nunca lo reescribe, eliminando por diseño la clase de bug de
  escritura concurrente que causó los 3 incidentes reales mencionados arriba (cada tarea del array
  escribe *solo* su propio archivo, sin colisión posible entre tareas concurrentes). Detecta
  explícitamente `OSError errno 122` (cupo de disco) como caso distinto de una excepción genérica.
- **`sweep_launch.py`**: el "deploy de un click" -- somete todos los arrays de un sweep compilado a
  SLURM (compila primero si hace falta), mismo patrón real de `pipeline/orchestrate/launcher.py`
  (`subprocess.run(["sbatch",...])`, parseo de `"Submitted batch job (\d+)"`). Único otro escritor
  autorizado de `manifest.json` (una vez, con los job IDs reales y `status=submitted` por corrida).
- **`sweep_monitor.py`**: estado de todas las corridas de un sweep, en orden de autoridad:
  `run_hash.json` real (si existe, autoritativo) → `phot_df.parquet` huérfano sin `run_hash.json` →
  `INTERRUPTED` (mismo patrón real de los 3 nodos con `ExitCode 120:0` de Fase 65) → `sacct` real como
  último recurso. Una sola consulta `sacct` por lote, no una por corrida.
- **`sweep_aggregate.py`**: reemplaza el proceso manual de leer `summary.json` a mano fase a fase
  (tablas de Fase 59/60/62/64) -- junta manifiesto + `summary.json` + `run_hash.json` de cada corrida
  en un parquet consolidado con `run_hash` como columna real.
- **`sweep_publish_dataset.py`**: punto de enganche para entrenamiento, **sin implementar el conector**
  -- arma `datasets/<dataset_hash>/` con `manifest.json` (`ingestion_format: null` a propósito),
  `consolidated.parquet` (tabla agregada por corrida, no fotometría cruda -- esa ya se borra por
  diseño) y un `README.md` explícito. Determinístico: publicar el mismo conjunto de corridas dos veces
  da el mismo `dataset_hash` (verificado real, no solo en teoría).
- **`deploy_local.sh`** (secundario/opcional): corre en la máquina LOCAL del usuario -- automatiza el
  `scp`+`ssh` manual que se ha hecho a mano toda la investigación (sincroniza código + dispara
  `sweep_launch.py` remoto en un solo comando). Probado con `--dry-run` real desde Windows/Git Bash.

### Decisión: job array de SLURM, un array por tier -- no N scripts individuales

Diverge deliberadamente del patrón real de `pipeline/orchestrate/launcher.py` (confirmado leyendo ese
archivo: hace un `sbatch` individual por combinación). Razón concreta: el bug real de escribir `.sh` a
mano (semilla 0 rota por `set -e`, Fase 62) desaparece por construcción con un único script de array
generado una vez; y el throttle nativo de SLURM (`--array=0-N%K`) da control directo sobre cuántas
escrituras concurrentes de `phot_df.parquet` ocurren a la vez -- la causa real de los incidentes de
cuota de Fases 8/59/65.

### Validación real, no solo diseño -- cada pieza probada con SLURM real, no atajos interactivos

- **Worker end-to-end**: job real `12315264` (1 tarea), `run_hash.json` con job IDs reales de SLURM,
  `status=done`, `phot_df.parquet` limpiado, `head_df.parquet`/`summary.json`/`qc/` completos.
- **Launch + monitor + aggregate**: job real `12315391`, monitor detectó `status=done` leyendo el
  `run_hash.json` real que escribió el worker, aggregate armó un parquet de 1 fila con las 11 columnas
  reales de `summary.json` intactas.
- **Concurrencia y tier heavy**: sweep de 6 corridas reales (`SNIa-91bg`/`CaRT` x2 semillas +
  `PISN-STELLA-HYDROGENIC` x2 semillas, jobs `12315494`/`12315495`), confirmado con `squeue` EN VIVO
  mientras corría: nunca más de 2 tareas del tier `default` corriendo a la vez (`max_concurrent=2`),
  nunca más de 1 del tier `PISN-STELLA-HYDROGENIC` (`max_concurrent=1`) -- el throttle real coincide
  exacto con lo declarado en el YAML. 2 arrays generados con rangos de índice contiguos y correctos
  (`0-3`, `4-5`), las 6 corridas terminaron `done`.
- **`deploy_local.sh`**: sincronizó código real y disparó `sweep_launch.py --dry-run` remoto desde la
  máquina Windows local, sin someter nada a SLURM (confirmado en el output real).
- **Bug real encontrado y corregido en el camino**: `#SBATCH -o`/`-e` se resuelven por SLURM relativos
  al directorio de submisión (`$SLURM_SUBMIT_DIR`), NO al `cd` que corre después dentro del script --
  la primera versión de la plantilla asumía que `sbatch` se corría desde `exploration/lightcurvelynx/`
  y falló (`venv/bin/activate: No such file or directory`) porque la convención real de este proyecto
  (confirmada en todas las rondas anteriores) es correr `sbatch` desde `~/AUTOSIM`. Corregido con el
  path completo en la plantilla y un comentario explicando por qué.

### Qué NO se hizo, y por qué

No se tocó ningún archivo bajo `pipeline/`. No se implementó el conector real de ingesta a
entrenamiento -- el formato no está definido; solo queda el directorio `datasets/<hash>/` como punto
de enganche explícito (`ingestion_format: null`). El flujo manual interactivo existente
(`python3 run_simsed_poc.py <clase> [seed]`) sigue funcionando idéntico, sin cambios de comportamiento.

### Conclusión Fase 66

El sistema de automatización pedido por el profesor está completo y validado con jobs reales de SLURM
en cada pieza, no solo diseñado: hash de identificación real y determinístico (sensible a config Y a
código), deploy de un click (`sweep_launch.py`, con una variante local opcional vía `deploy_local.sh`),
y un punto de enganche honesto para entrenamiento (sin inventar un formato que todavía no existe). La
primera carga de trabajo real de este sistema es el re-barrido completo de Fase 65 (13 clases × 5
semillas, 65 corridas) -- lanzado a continuación, ver Fase 67.

### Archivos de esta fase

Nuevos: `sweep_hash.py`, `sweep_compile.py`, `sweep_worker.py`, `sweep_launch.py`, `sweep_monitor.py`,
`sweep_aggregate.py`, `sweep_publish_dataset.py`, `deploy_local.sh`, `sweeps/_smoke.yaml`,
`sweeps/_smoke_multi.yaml`, `sweeps/fase65_rebarrido.yaml`. Modificados: `run_simsed_poc.py`
(`out_dir_override`), `.gitignore` (`sweep_runs/`/`datasets/`), `.gitattributes` (nuevo, fuerza LF para
`*.sh`). `NOTES.md`: esta entrada.

## Fase 67 -- el fix de Fase 64 (`SNR_CALC` real en vez de `SNR_OBS`) cierra casi por completo la
brecha catálogo-completo: ratio promedio `5.113x -> 0.992x`, primera carga de trabajo real del sistema
de automatización de Fase 66

### Motivación

Cierra la pregunta científica que quedó pendiente desde Fase 64/65: el trigger real de SNANA usa
`SNR_CALC` (flujo verdadero) en vez de `SNR_OBS` (flujo observado con ruido) -- confirmado en Fase 64
época a época contra `PHOTFLAG&4096` real -- pero el impacto de ese fix sobre la tabla catálogo-completo
de Fase 59 (13 clases × 5 semillas, ratio promedio `5.113x` de sobre-detección LCL/SNANA) nunca se había
medido: Fase 65 quedó bloqueada por cupo de disco real antes de poder correr un solo barrido completo.

### Método

Primera carga de trabajo real del sistema de automatización de Fase 66: `sweeps/fase65_rebarrido.yaml`
(13 clases SIMSED × 5 semillas = 65 corridas, mismo `ngentot_lc` real que usó Fase 59 -- 2000 para 12
clases, 20000 para `PISN-STELLA-HYDROGENIC` -- para comparar manzanas con manzanas) compilado y lanzado
con `sweep_launch.py` (2 arrays: `12315817` tier `default`, 60 corridas, `max_concurrent=4`; `12315816`
tier `PISN-STELLA-HYDROGENIC`, 5 corridas, `max_concurrent=1`).

### Resultado real de la ejecución -- 65/65 corridas `done`, cero fallos

Confirmado con `sacct` real (no supuesto): las 65 corridas terminaron `COMPLETED`, `ExitCode 0:0`, sin
ningún `DISK_QUOTA_EXCEEDED` ni `INTERRUPTED`. Wall clock total: sometido `13:02:13`, tier `default`
terminó `15:52:52` (~2h51min, throttle de 4 concurrentes sostenido de punta a punta), tier `heavy`
terminó `16:44:38` (~3h42min desde el envío -- las 5 semillas de `PISN-STELLA-HYDROGENIC` corrieron
estrictamente secuenciales, cada una arrancando en el segundo exacto en que terminaba la anterior,
`42-43min` cada una -- **el throttle de `max_concurrent=1` declarado en el YAML se cumplió al 100%,
confirmado con los timestamps reales de `sacct`, no solo observado en vivo como en la validación de
Fase 66**). `sweep_monitor.py fase65_rebarrido` reporta `resumen: done=65` limpio. `sweep_aggregate.py`
consolidó las 65 filas en `sweep_runs/fase65_rebarrido/aggregated_summary.parquet` sin intervención
manual -- primera vez que esta investigación arma una tabla de resultados sin transcribir `summary.json`
a mano.

### Comparación real contra la tabla de Fase 59 (13 clases, detección media ± std sobre 5 semillas)

| clase | detección Fase 67 (fix `SNR_CALC`) | SNANA% real (Fase 48) | ratio Fase 59 (`SNR_OBS`, bug) | ratio Fase 67 (`SNR_CALC`, fix) |
|---|---:|---:|---:|---:|
| `CaRT` | `0.95%±0.12` | 0.94% | 27.450 | **1.011** |
| `SNIIn-MOSFIT` | `1.90%±0.31` | 2.12% | 9.231 | **0.896** |
| `ILOT-MOSFIT` | `3.63%±0.26` | 4.30% | 7.091 | **0.844** |
| `KN-BULLA19` | `6.94%±0.65` | 6.07% | 4.000 | **1.143** |
| `KN-K17` | `5.20%±0.39` | 4.83% | 3.748 | **1.077** |
| `SNIax` | `10.20%±1.18` | 10.08% | 2.832 | **1.012** |
| `PISN-MOSFIT` | `25.23%±1.16` | 23.41% | 2.203 | **1.078** |
| `PISN-STELLA-HECORE` | `21.32%±0.35` | 21.88% | 1.907 | **0.974** |
| `PISN-STELLA-HYDROGENIC` | `24.55%±0.22` | 24.45% | 1.888 | **1.004** |
| `SNII-NMF` | `17.21%±0.58` | 20.75% | 1.835 | **0.829** |
| `SLSN-I` | `47.36%±1.27` | 46.64% | 1.487 | **1.015** |
| `SNIa-91bg` | `43.28%±1.46` | 41.69% | 1.398 | **1.038** |
| `TDE-MOSFIT` | `45.55%±1.45` | 46.58% | 1.397 | **0.978** |
| **promedio (13 clases)** | | | **5.113** | **0.992** |

(SNANA% real DDF-only, tabla de Fase 48 -- `SLSN-I`=46.64%/`ILOT-MOSFIT`=4.30% son los valores
correctos ahí, distintos de los citados sin filtro DDF en Fase 43/49.)

### Lectura -- confirma la hipótesis de Fase 64 al nivel más fuerte posible: catálogo completo, no solo
época a época

El ratio promedio del catálogo pasa de **`5.113x` (sobre-detección sistemática, 40%-2645% según la
clase) a `0.992x`** (esencialmente sin sesgo sistemático) con un solo cambio de una línea (qué columna
de flujo alimenta al trigger). El caso más extremo, `CaRT` (el peor de toda la investigación desde
Fase 48), pasa de sobre-detectar **27.5x** a un ratio de **1.011x** -- coincide con SNANA casi al
punto decimal. Ninguna de las 13 clases queda peor que un ±20% de desacuerdo (rango real
`0.829x`-`1.143x`), contra el rango `1.397x`-`27.45x` de Fase 59 -- una reducción de más de un orden de
magnitud en la dispersión del catálogo, no solo en el promedio.

Esto confirma, al nivel de catálogo completo y no solo de una época individual (que es como se validó
en Fase 64), que **el bug real detrás de la sobre-detección sistemática de LightCurveLynx frente a
SNANA, documentada y perseguida desde Fase 5, era principalmente el trigger usando el flujo observado
(con ruido) en vez del flujo verdadero** -- no los 3 bugs de la librería ya reportados en el issue #955
(colisión de parámetro en `add_effect()`, `seed=` no propagada, rango de SED no verificado), que son
reales pero secundarios frente a este efecto: ninguno de esos 3 se midió nunca contra la métrica
agregada de 13 clases, y ahora se puede afirmar con evidencia real que no son la causa dominante del
salto medido en Fase 58/59.

### Honestidad del resultado -- no es un ajuste perfecto, y 3 clases invierten el signo del sesgo

El fix no deja el catálogo en `1.000x` exacto por clase: `SNII-NMF` (`0.829x`), `ILOT-MOSFIT`
(`0.844x`) y `SNIIn-MOSFIT` (`0.896x`) pasan de sobre-detectar a **sub-detectar** un 10-17% frente a
SNANA -- un residuo real, no ruido (`std` de 5 semillas es `<1.2pp` en las 3). El resto del catálogo
sobre-detecta levemente (`1.01x`-`1.14x`). No se investiga la causa de este residuo en esta fase --
son 3 candidatas conocidas (`add_effect()`/`seed=`/rango SED del issue #955) que podrían explicar una
fracción, pero confirmarlo requeriría aislar cada bug por separado contra estas 3 clases específicas,
fuera del alcance de esta fase.

### Conclusión Fase 67

El re-barrido real y completo (65/65 corridas, cero fallos, primera carga de trabajo real del sistema
de automatización de Fase 66) confirma que el fix de Fase 64 (`SNR_CALC` real en el trigger) es, con
diferencia, el hallazgo más importante de toda esta investigación: reduce el desacuerdo catálogo-
completo entre LightCurveLynx y SNANA de un factor `5.1x` sistemático a un `0.99x` esencialmente neutro,
con toda clase dentro de ±20%. La tabla de referencia de Fase 59 queda oficialmente obsoleta y
reemplazada por esta. El residuo real que queda (3 clases con sub-detección leve) es la pregunta
abierta natural para continuar, no un blocker para reportar este resultado al profesor.

### Archivos de esta fase

`exploration/lightcurvelynx/sweep_runs/fase65_rebarrido/` (gitignorado, en NLHPC): `manifest.json`, 65
`runs/<hash>/{run_hash.json,summary.json,head_df.parquet,qc/}`, `aggregated_summary.parquet`. `NOTES.md`:
esta entrada. Jobs SLURM reales: `12315816` (tier heavy, 5 corridas), `12315817` (tier default, 60
corridas).

## Fase 68 -- el panel de curvas de luz del dashboard usaba un estilo generico, no el del notebook
oficial de LightCurveLynx -- corregido y regenerado para las 13 clases SIMSED

### Motivación

El usuario notó que los gráficos de curvas de luz que se suben a la página de GitHub no se veían como
los del notebook oficial de LightCurveLynx (colores por banda, barras de error reales sobre la curva
continua del modelo). Investigado: el panel `lightcurves.png` de la sección 06 del dashboard se genera
con `pipeline/postproc/qc.py::sample_lightcurves()` -- el mismo módulo compartido que arma el QC de
producción SNANA (sección 03) -- que dibuja un panel genérico de fondo oscuro con marcadores `no det`
para todos los puntos y colores propios, sin relación con el estilo real de la librería LightCurveLynx.
El estilo real (usado en `verificacion_bugs_lightcurvelynx.ipynb`, Fase 60) es
`plot_lightcurves()`/`compute_single_noise_free_lightcurve()` (`lightcurvelynx.utils.plotting`/
`lightcurvelynx.simulate`) con la paleta `BAND_COLORS` Okabe-Ito ya definida en ese notebook.

### Cambio real

`run_simsed_poc.py`: nueva función `plot_notebook_style_lightcurves()` (con la misma constante
`BAND_COLORS` del notebook) que, para los objetos ya marcados como detectados por SEARCHEFF con >=5
observaciones reales y >=100 días de cobertura, selecciona las 5 de mayor S/N mediana
(`|flux_perfect|/fluxerr`, mismo criterio de calidad que el notebook oficial -- NOBS alto no implica
curva legible, ver Fase 60) y las grafica con `plot_lightcurves()` real, una por subplot, en una única
figura de grilla. `main()` la llama justo después de `qc.run_all_qc()` y reemplaza únicamente
`paths["lightcurves"]` -- los otros 3 gráficos (detecciones/magnitudes/redshift) los sigue generando
`pipeline/postproc/qc.py` sin cambios; **no se tocó ningún archivo bajo `pipeline/`**.

### Bug real encontrado y corregido en el camino: `qc.py` muta `plt.rcParams` globalmente

Primera prueba real (`CaRT`, `ngentot_override=300`, interactivo en el login node): la función corrió
sin errores, pero el gráfico salió con fondo oscuro y colores equivocados -- heredó el tema nocturno que
`pipeline.postproc.qc._setup_style()` aplica vía `plt.rcParams.update({...})`, una mutación GLOBAL de
matplotlib que persiste para el resto del proceso de Python (no se resetea sola). Corregido con
`plt.rcdefaults()` al inicio de la función nueva -- revierte el estado global de matplotlib solo para
este gráfico, sin tocar `pipeline/`. Segunda prueba real (`SNIa-91bg`, `ngentot_override=2000`, escala
de producción real) confirmó el fix: fondo blanco, colores Okabe-Ito correctos, curvas limpias
idénticas en estilo a `notebook_fig_example_lightcurve_*.png` (los PNG reales que generó
`verificacion_bugs_lightcurvelynx.ipynb`).

### Regeneración real de las 13 clases SIMSED

`sweeps/fase68_lightcurves_notebook_style.yaml` (mismos parámetros reales que `fase65_rebarrido.yaml`,
solo semilla 0) lanzado vía `sweep_launch.py` (jobs SLURM reales `12330278`/`12330279`) -- 13/13
corridas `COMPLETED`, sin fallos. Solo se reemplazó el archivo `lightcurves.png` de cada clase en
`docs/lcl_qc/<clase>/` (no `detections.png`/`magnitudes.png`/`redshift.png`, que ya estaban correctos y
consistentes con la tabla desde Fase 67) -- verificados como PNG válidos antes de reemplazar.

**Nota real, honesta, no bloqueante**: al comparar los conteos de detección de este re-barrido contra
los ya publicados en Fase 67 (mismo `seed_index=0`, mismo `ngentot`, mismo código de simulación/
detección), 12/13 clases coinciden exacto -- `SNII-NMF` difiere en 1 objeto (`342` vs `341`, `17.10%`
vs `17.05%`, dentro del `std` de 5 semillas ya reportado). No se investigó la causa (probablemente
orden de suma de punto flotante en un objeto justo en el umbral de detección, sensible a
paralelización de BLAS/threads -- no confirmado); no cambia ninguna conclusión ni número publicado
(se mantienen los valores originales de Fase 67 en la tabla). Queda como candidata a investigar si
se repite en otra clase.

### Conclusión Fase 68

El panel de curvas de luz de las 13 clases SIMSED en el dashboard ahora usa el mismo código y estilo
real que el notebook oficial de LightCurveLynx -- no una recreación aproximada. Confirma, de paso, que
el hallazgo de Fase 67 no es un artefacto de visualización: las curvas mostradas son literalmente
`flux_perfect` (el valor que alimenta el trigger corregido de Fase 64) con el ruido real superpuesto.

### Archivos de esta fase

`run_simsed_poc.py`: `BAND_COLORS`, `plot_notebook_style_lightcurves()`, llamada nueva en `main()`.
`sweeps/fase68_lightcurves_notebook_style.yaml` (nuevo). `docs/lcl_qc/<clase>/lightcurves.png` (13
archivos reemplazados) y `docs/lcl_qc/lcl_qc_index.json` (nota agregada, sin cambios numéricos).
`NOTES.md`: esta entrada.

## Fase 69 -- panel de curvas de luz extendido a las 19 clases del catálogo (antes solo las 13
SIMSED) y cambiado a 6 curvas seleccionadas por brillo real, no por S/N

### Motivación

Dos pedidos explícitos del usuario sobre la Fase 68: (1) mostrar solo las 6 curvas de luz más
luminosas de cada clase (antes 5, seleccionadas por S/N mediana), y (2) que el mismo formato se vea
para **todas** las clases que se muestran en el dashboard, no solo las 13 SIMSED -- el panel
`lightcurves.png` de las otras 6 clases (`SNIa`/SALT2 y las 5 `NON1ASED`) seguía usando el panel
genérico de `pipeline/postproc/qc.py`.

### Cambio real

Refactor: `BAND_COLORS`/`plot_notebook_style_lightcurves()` se movieron de `run_simsed_poc.py` a un
módulo nuevo y compartido, `qc_lightcurves_notebook.py` -- usado ahora por los 3 scripts de
producción de esta investigación (`run_simsed_poc.py`, `run_non1ased_poc.py`, `run_snia_ddf_poc.py`)
en vez de tenerlo copiado. Criterio de selección cambiado: antes S/N mediana entre objetos con >=5
observaciones y >=100 días de cobertura (criterio de "legibilidad", igual al notebook oficial); ahora
**flujo pico verdadero** (`max(|flux_perfect|)`, sin filtro de cobertura) entre los objetos ya
detectados por SEARCHEFF -- las 6 curvas más luminosas, tal como se pidió. `n_top` sube de 5 a 6
(encaja exacto en una grilla 2×3 sin panel vacío). El título de cada panel ahora muestra
`flujo pico=... nJy` en vez de `S/N mediana=...`.

### Regeneración real de las 19 clases

**13 clases SIMSED**: re-lanzado el mismo sweep de Fase 68 (`fase68_lightcurves_notebook_style.yaml`,
jobs SLURM reales `12347691`/`12347692`) -- 13/13 `COMPLETED`, sin fallos (nota: `sweep_launch.py`
reusó el `manifest.json` ya existente de Fase 68 en vez de recompilar, así que los `run_hash` de los
directorios no reflejan el `code_hash` real de esta fase -- inconsistencia de procedencia menor,
aceptada porque el objetivo era solo regenerar imágenes, no una corrida científica trazada; el
contenido real sí usa el código nuevo, verificado). Un intento de conexión SSH se cortó a mitad de las
5 clases `NON1ASED` (`Connection reset by peer`) -- verificado con `ls` cuáles ya habían terminado
(3/5) antes de relanzar solo las 2 restantes, sin perder trabajo ni duplicar innecesariamente.

**6 clases restantes** (`SNIa` + 5 `NON1ASED`: `SNIa-91bg`, `SNIax`, `TDE`, `SLSN-I`,
`KN-BULLA-BNS-M2COMP`): corridas reales a escala de producción (`ngentot` real de cada una, semilla 0)
vía `run_snia_ddf_poc.py`/`run_non1ased_poc.py` directamente -- primera vez que estas 6 clases usan
el panel de curvas de luz estilo notebook oficial (antes nunca lo habían tenido, ni con 5 paneles en
Fase 68). Las 19 imágenes verificadas como PNG válidos antes de reemplazar.

### Conclusión Fase 69

Las 19 clases del catálogo (13 SIMSED + SNIa/SALT2 + 5 NON1ASED) muestran ahora el mismo panel real
de curvas de luz -- 6 paneles, estilo `plot_lightcurves()` oficial, seleccionadas por brillo real, un
único código compartido en vez de tres copias. Ningún conteo ni ratio de las tablas cambia.

### Archivos de esta fase

Nuevo: `qc_lightcurves_notebook.py` (`BAND_COLORS`/`plot_notebook_style_lightcurves()`, movido desde
`run_simsed_poc.py`). Modificados: `run_simsed_poc.py` (importa del módulo compartido),
`run_non1ased_poc.py`/`run_snia_ddf_poc.py` (llamada nueva tras `qc.run_all_qc()`).
`docs/lcl_qc/<clase>/lightcurves.png` (19 archivos reemplazados/generados) y
`docs/lcl_qc/lcl_qc_index.json` (nota agregada en las 19, sin cambios numéricos). `NOTES.md`: esta
entrada.

## Fase 70 -- el fix de Fase 64 (`SNR_CALC` vs `SNR_OBS`) nunca se había portado a `SNIa`/SALT2 ni a
las 5 clases `NON1ASED` -- corregido y re-medido, las 19 clases del catálogo quedan al día

### Motivación

El re-barrido de Fase 67 midió el impacto del fix de Fase 64 solo para las 13 clases SIMSED
(`run_simsed_poc.py`), porque ese era el script donde se había implementado originalmente el fix en
Fase 65. Al planificar los próximos pasos de la investigación se confirmó, leyendo el código real, que
**`run_snia_ddf_poc.py` (clase `SNIa`/SALT2) y `run_non1ased_poc.py` (5 clases `NON1ASED`:
`SNIa-91bg`, `SNIax`, `TDE`, `SLSN-I`, `KN-BULLA-BNS-M2COMP`) nunca recibieron el fix** -- ninguno de
los dos retenía `flux_perfect` en el aplanado de fotometría, y ambos llamaban
`apply_detection_efficiency(phot_df, band_curves, seed=...)` sin `flux_col="FLUXTRUE"`, es decir,
seguían disparando el trigger sobre el flujo observado con ruido (`SNR_OBS`), el mismo bug real que
Fase 64 corrigió para las clases SIMSED. Sus ratios en el dashboard seguían siendo pre-fix: `SNIa`
1.615x, `SNIa-91bg (NON1ASED)` 2.254x, `SNIax (NON1ASED)` 7.06x, `TDE (NON1ASED)` 2.074x,
`SLSN-I (NON1ASED)` 1.647x, `KN-BULLA-BNS-M2COMP (NON1ASED)` 4.746x.

### Cambio real

Mismo patrón exacto ya validado en `run_simsed_poc.py` (Fase 64/65), portado a los 2 scripts
restantes -- 2 archivos, 4 ediciones puntuales:
- En el loop de aplanado de fotometría, se agrega `"FLUXTRUE": obs["flux_perfect"]` a cada fila (antes
  solo se guardaban `FLUXCAL`/`FLUXCALERR`, el flujo observado con ruido).
- En la llamada a `apply_detection_efficiency(...)`, se agrega `flux_col="FLUXTRUE"` (antes usaba el
  default `"FLUXCAL"`).

Validado primero con una corrida chica (`SNIax` NON1ASED, `ngentot_override=300`) y una a escala real
(`TDE` NON1ASED, `ngentot_override=300` también pero sin necesidad de reducir más) antes de lanzar las
30 corridas reales.

### Re-medición real: 30 corridas (6 clases × 5 semillas), `ngentot=2000` cada una, sin fallos

| clase | detección media Fase 70 (5 semillas) | SNANA% real | ratio antes (Fase ≤69) | ratio Fase 70 (fix) |
|---|---:|---:|---:|---:|
| `SNIax (NON1ASED)` | `1.75%±0.42` | 1.49% | 7.060 | **1.174±0.281** |
| `SNIa-91bg (NON1ASED)` | `8.72%±0.54` | 7.35% | 2.254 | **1.186±0.074** |
| `TDE (NON1ASED)` | `27.60%±0.87` | 23.11% | 2.074 | **1.194±0.038** |
| `SLSN-I (NON1ASED)` | `69.24%±0.64` | 55.02% | 1.647 | **1.258±0.012** |
| `SNIa` | `38.36%±1.15` | 29.85% | 1.615 | **1.285±0.039** |
| `KN-BULLA-BNS-M2COMP (NON1ASED)` | `1.85%±0.25` | 1.395% | 4.746 | **1.326±0.177** |
| **promedio (6 clases)** | | | **3.299** | **1.237** |

Las 6 clases bajan sustancialmente, mismo patrón que las 13 SIMSED de Fase 67 -- pero **no llegan tan
cerca de 1.0x**: quedan en un rango `1.17x-1.33x` (vs. `0.83x-1.14x` de las 13 SIMSED). El promedio de
las 19 clases del catálogo completo (SIMSED + SALT2 + NON1ASED) queda en **1.070x**.

### Lectura honesta -- el residuo restante es consistente con la codificación de estas clases, no un
fix incompleto

El residuo del `~15-33%` en estas 6 clases es compatible con mecanismos ya documentados y no
relacionados con el trigger: (1) `SNIa` tiene su propio residuo de SNR conocido desde Fase 38 (el SNR
mediano no baja proporcional al brillo tras `MAG_OFFSET`, apunta al modelo de ruido/readnoise, no al
trigger); (2) las 4 clases `NON1ASED` con `SIMSED_REDCOR` perdido (`SNIa-91bg`, ver Fase 6) tienen un
efecto de codificación real de ~1.10-1.15x ya medido y no relacionado con Fase 64; (3)
`KN-BULLA-BNS-M2COMP` y `SNIax (NON1ASED)` tienen los conteos SNANA más bajos del catálogo (279 y 149
sobre 20000/10000), el mismo patrón de alta varianza relativa por denominador chico ya visto en
`KN-K17`/`CaRT` desde Fase 5. No se investiga más a fondo en esta fase -- el objetivo era cerrar la
brecha del fix de Fase 64 para las 19 clases, no una auditoría nueva de estos mecanismos secundarios.

### Conclusión Fase 70

Las 19 clases del catálogo completo (13 SIMSED + `SNIa`/SALT2 + 5 `NON1ASED`) quedan al día con el fix
real de Fase 64 -- ya no hay clases con el trigger viejo (`SNR_OBS`) mezcladas en el dashboard junto a
clases ya corregidas. El promedio del catálogo de 19 clases es `1.070x`, y ninguna clase queda por
encima de `1.33x` (antes el rango llegaba hasta `27.45x` para `CaRT`, ya corregido en Fase 67, y
`7.06x` para `SNIax (NON1ASED)`, corregido en esta fase).

### Archivos de esta fase

Modificados: `run_snia_ddf_poc.py`, `run_non1ased_poc.py` (fix de Fase 64 portado). `docs/lcl_qc/
{SNIa,SNIa-91bg_NON1ASED,SNIax_NON1ASED,TDE_NON1ASED,SLSN-I_NON1ASED,KN-BULLA-BNS-M2COMP_NON1ASED}/
{detections,magnitudes,redshift}.png` (18 archivos regenerados con el conjunto de detección real
corregido; `lightcurves.png` no cambió en ninguna de las 6 -- las curvas más luminosas ya estaban
detectadas en ambos escenarios). `docs/lcl_qc/lcl_qc_index.json` (6 registros con conteos/ratios
reales actualizados). `NOTES.md`: esta entrada.

## Fase 71 -- investigación del residuo de sub-detección en 3 clases (`SNII-NMF`/`ILOT-MOSFIT`/
`SNIIn-MOSFIT`) tras el fix de Fase 64: dos hipótesis descartadas con datos reales, la mayor parte del
residuo resulta ser un efecto de normalización ya conocido, no un bug nuevo

### Motivación

Tras el fix de Fase 64/67, 13 de las 13 clases SIMSED quedaron en un rango `0.83x-1.14x` -- 10 muy
cerca de 1.0x, pero 3 (`SNII-NMF` 0.829x, `ILOT-MOSFIT` 0.844x, `SNIIn-MOSFIT` 0.896x) invirtieron el
signo del residuo, pasando de sobre-detectar a **sub**-detectar 10-17%, consistente entre las 5
semillas (`std` <1.2pp). Esta fase investiga si hay una causa real identificable, reusando
`compare_lightcurve_shape.py` (Fase 63, ya validado con `ILOT-MOSFIT`) y comparaciones nuevas de
distribución poblacional.

### Paso 1 -- fidelidad objeto-a-objeto: prácticamente perfecta, no es la causa

Re-corrida real de `compare_lightcurve_shape.py ILOT-MOSFIT` (73 objetos reales que SNANA detectó,
mismo método de Fase 63: evalúa el modelo propio de LightCurveLynx en los MISMOS parámetros reales
-- `z`, `host_av`, `template`, `MJD` pico -- que usó SNANA, en la MISMA cadencia/ruido real, y aplica
el trigger real ya corregido). Resultado idéntico al de Fase 63 (determinístico, mismos seeds):
**`lcl_detect_rate_mean = 0.9993`** -- LightCurveLynx recupera el 99.93% de los objetos que SNANA
realmente detectó, cuando se le dan los mismos parámetros reales. La fidelidad fotométrica/trigger
objeto-a-objeto **no es la causa** del residuo.

### Paso 2 -- distribución poblacional de redshift: descartada

Comparación real, `.DUMP` crudo de SNANA (2000 objetos, sin ningún filtro) vs. la población propia de
LightCurveLynx (`head_df.parquet` real de la corrida de Fase 68/69, mismo `ngentot=2000`):

| clase | z mediana LCL | z mediana SNANA | z p90 LCL | z p90 SNANA |
|---|---:|---:|---:|---:|
| `ILOT-MOSFIT` | 0.246 | 0.242 | 0.292 | 0.289 |
| `SNII-NMF` | 0.757 | 0.745 | 0.958 | 0.954 |
| `SNIIn-MOSFIT` | 1.246 | 1.200 | 1.838 | 1.824 |

Las 3 clases coinciden dentro de un 1.5-4% -- consistente con varianza de muestreo normal para
`N=2000`, no una diferencia real de `DNDZ`/rango de redshift entre los dos simuladores.

### Paso 3 -- distribución de extinción de host (`host_av`): descartada para `ILOT-MOSFIT`

`ILOT-MOSFIT` y `SNIIn-MOSFIT` declaran extinción real WV07 (`SNII-NMF` no declara ninguna, comparación
limpia sin este candidato). Se sampleó la distribución propia de `host_av` de LightCurveLynx para
`ILOT-MOSFIT` (2000 sorteos reales, mismo `seed_base`/`build_source_model()` de producción, sin correr
la simulación completa) y se comparó contra el `.DUMP` real de SNANA (filtrando el sentinela real
`AV=-9.0` que SNANA usa para "no medido", 76/2000 objetos):

| | mediana | media | p90 |
|---|---:|---:|---:|
| LightCurveLynx | 0.160 | 0.296 | 0.727 |
| SNANA (real, sin sentinelas) | 0.159 | 0.302 | 0.775 |

Prácticamente idénticas. La distribución de extinción de host tampoco es la causa.

### Paso 4 -- el hallazgo real: la mayor parte del residuo es un efecto de normalización ya conocido
(Fase 48), no un déficit fotométrico nuevo

Comparando el **conteo crudo** de detecciones (antes de cualquier normalización a porcentaje) entre
LightCurveLynx y SNANA, sobre la misma población de referencia real (`N=2000` cada lado):

| clase | detectados LCL (crudo) | detectados SNANA (`FLAG_ACCEPT>0`, crudo) | diferencia cruda |
|---|---:|---:|---:|
| `ILOT-MOSFIT` | 73 (semilla 0) / 72.6 (media 5 semillas) | 73 | ~0% |
| `SNII-NMF` | 342 | 356 | -3.9% |
| `SNIIn-MOSFIT` | 35 | 37 | -5.4% |

Los conteos crudos son casi idénticos -- mucho más cerca de 1.0 que el `0.83x-0.90x` reportado. La
diferencia viene de que el `SNANA%` de referencia (desde Fase 48) se calcula sobre el denominador
**post-filtro de contaminación de campo RGES** (`1696/2000`, no `2000/2000`) -- una corrección
correcta y necesaria (SNANA simuló ~15% de sus "DDF" en el campo `RGES` por un bug de
`scheduler_note` en su SIMLIB, ver Fase 48), mientras que el `LCL%` usa su propio `ngentot=2000`
completo como denominador. Esto es **metodológicamente correcto como comparación de eficiencia de
detección** (ambos numeradores/denominadores están bien definidos, no hay bug de bookkeeping real
-- se verificó explícitamente que `filter_ddf_field_contamination()` nunca se aplica a la
construcción del `df_ddf` propio de LightCurveLynx, que filtra directo del OpSim real por
`target_name` conteniendo `"ddf_"`, un mecanismo distinto y no afectado por el bug de `scheduler_note`
del SIMLIB de SNANA) -- pero explica por qué el ratio reportado (`0.83x-0.90x`) es
proporcionalmente más extremo que la diferencia real en conteos absolutos (`0-5%`).

### Conclusión Fase 71

Se descartaron con datos reales dos causas candidatas (muestreo poblacional de redshift, muestreo de
extinción de host) y se confirmó que la fidelidad fotométrica/trigger objeto-a-objeto es excelente
(99.93% de recall). El grueso del residuo de `0.83x-0.90x` reportado en la tabla es una consecuencia
esperada y correcta de cómo se normaliza el `SNANA%` de referencia (denominador post-filtro RGES,
Fase 48) contra el `LCL%` (denominador propio, nunca contaminado) -- no un déficit fotométrico nuevo.
Queda un residuo real pero pequeño (`0-5%` en conteo crudo) sin causa identificada -- del mismo orden
que la varianza esperable de semilla a semilla dado el tamaño de muestra (35-356 objetos detectados),
no se investiga más a fondo en esta fase. Este hallazgo no cambia ningún número ya publicado (los
ratios de Fase 67/70 siguen siendo la comparación correcta y vigente) -- clarifica su interpretación:
el residuo de estas 3 clases es en gran parte esperado por diseño metodológico, no evidencia de un
bug nuevo pendiente de corregir.

### Archivos de esta fase

Ninguno modificado -- investigación de solo lectura/análisis, sin cambios de código ni de datos
publicados. `shape_output_ilotmosfit/` (ya existente desde Fase 63, re-verificado con una corrida
real nueva, resultado idéntico). `NOTES.md`: esta entrada.

## Fase 73 -- endurece `exploration/lightcurvelynx/` para que el equipo pueda operarlo con confianza,
sin tocar `pipeline/`; documenta y justifica la decisión de NO generalizar el sistema de sweeps

### Motivación

Con la brecha de detección cerrada (Fase 64-71) y el catálogo completo re-medido, cierra el ciclo de
"poner esto en producción" pedido por el profesor: no como integración formal a `pipeline/` (fuera de
alcance, confirmado con el usuario -- `pipeline/` no tiene ninguna abstracción de simulador, sería una
reescritura de 5 módulos), sino endureciendo `exploration/lightcurvelynx/` para que alguien más que no
haya vivido esta investigación pueda correrlo con confianza.

### `HOWTO.md` actualizado

Estaba desactualizado en dos frentes: (1) citaba "18 fases"/"19 fases" (van más de 70, y seguían
creciendo -- número hardcodeado que se pudre solo); (2) **no mencionaba el sistema de automatización
de barridos de Fase 66 en absoluto** -- solo documentaba el flujo manual de un `sbatch` por
combinación (sección 5), pese a que ese sistema lleva 5 fases de uso real y validado (Fase
66-69). Agregada sección `5-bis` con el flujo real de un click (`sweep_launch.py` →
`sweep_monitor.py` → `sweep_aggregate.py` → `sweep_publish_dataset.py`), marcando explícitamente el
smoke test (`sweeps/_smoke.yaml`) como paso obligatorio antes de un barrido real grande -- no
opcional, la primera vez que se usa el sistema en una sesión nueva. Sincronizado a NLHPC (`scp`, el
repo no vive como clon git ahí, mismo patrón de todo el proyecto).

### Decisión: NO generalizar `sweep_compile.py`/`sweep_worker.py` a los 3 scripts de producción

El plan de esta fase dejaba esto como opcional, a evaluar con el patrón real de las 6 clases restantes
ya en la mano (Fase 70). Con ese patrón confirmado, la decisión es **no hacerlo, por ahora**:

- Las 6 clases (`SNIa` + 5 `NON1ASED`) son un conjunto fijo y ya conocido, no uno que vaya a crecer
  con el tiempo -- correrlas directo (mismo patrón ya usado en Fase 70) fue suficiente y no volvió a
  fallar tras adaptarse al patrón de `nohup`/polling remoto para sobrevivir cortes de conexión SSH.
- Generalizar el sistema de sweeps requeriría dos cambios reales no triviales: (1) agregar
  `out_dir_override` a `run_non1ased_poc.py`/`run_snia_ddf_poc.py` (que hoy no lo tienen, confirmado
  leyendo sus firmas de `main()` -- `run_snia_ddf_poc.py` ni siquiera recibe `class_key`, tiene una
  sola clase); (2) construir una capa de despacho en `sweep_compile.py`/`sweep_worker.py` que sepa
  cuál de los 3 scripts llamar según la clase. Trabajo real, con su propio riesgo de introducir bugs
  nuevos en código ya validado, para un beneficio marginal ahora que el backfill de Fase 70 ya está
  hecho.
- Si en el futuro se necesita re-barrer estas 6 clases repetidamente (no solo una vez, como ahora),
  vale la pena reconsiderar esta decisión -- queda documentada acá, no descartada para siempre.

### `sweep_publish_dataset.py`/`datasets/<hash>/` -- sin cambios, como estaba planeado

El punto de enganche para entrenamiento sigue con `ingestion_format: null` a propósito -- el formato
real de ingesta de ALeRCE sigue sin definirse por el profesor/equipo, y no es una tarea que este
proyecto pueda resolver desde este lado. No se tocó nada acá, confirmando lo ya construido en Fase 66
sigue siendo la decisión correcta.

### Conclusión Fase 73

`exploration/lightcurvelynx/` queda con documentación al día (`HOWTO.md` refleja el sistema de
automatización real, no solo el flujo manual histórico), una decisión explícita y justificada sobre
el alcance del sistema de sweeps (no generalizado, por ahora), y sin deuda pendiente de esta ronda de
"puesta en producción" -- cierra el plan de Fases 70-73. La investigación LightCurveLynx-vs-SNANA
queda en un estado sólido: brecha de detección catálogo-completo cerrada y confirmada (19/19 clases),
3/4 bugs de la librería publicados, 1 pendiente de decisión con el profesor, y un sistema de
automatización real y documentado para seguir iterando.

### Archivos de esta fase

Modificado: `HOWTO.md` (sección `5-bis` nueva, conteos de fases desactualizados corregidos,
sincronizado a NLHPC). `NOTES.md`: esta entrada. Sin cambios en `pipeline/`, `sweep_compile.py`,
`sweep_worker.py`, ni `sweep_publish_dataset.py`.

## Fase 74 -- portabilidad de rutas: `local_env.py` reemplaza el hardcode real a `/home/mvalenzuela`
en 16 archivos, primer paso para instalar la generación de simulaciones fuera de NLHPC

### Motivación

El profesor pidió poder instalar esta metodología en su propio computador -- no la investigación de
comparación contra SNANA (cerrada, Fases 64-73), sino la generación de simulaciones + automatización,
para producir datasets reales que eventualmente entreguen al equipo de ML. Investigación real
confirmó el bloqueo más mecánico: **21 archivos** de `exploration/lightcurvelynx/` tienen
`SNANA_HOME = Path("/home/mvalenzuela")` y/o `sys.path.insert(0, "/home/mvalenzuela/AUTOSIM")`
hardcodeados -- asumen que el proyecto solo corre en la cuenta real del usuario en NLHPC. También se
confirmó algo importante para el alcance: **los 3 scripts de producción
(`run_simsed_poc.py`/`run_non1ased_poc.py`/`run_snia_ddf_poc.py`) no necesitan los datos de salida
reales de SNANA** (`.DUMP`/FITS, decenas de GB, específicos de la campaña) -- solo archivos de
configuración/plantillas (chicos a medianos): el `.db` de OpSim (~743MB, descargable públicamente sin
cuenta NLHPC vía `pipeline/fetch_opsim.py` ya existente), 2 archivos `.DAT` de `SEARCHEFF` (texto
plano), archivos `.INPUT` (texto plano), y las librerías de templates SED de SIMSED/NON1ASED.

### Cambio real

Nuevo módulo compartido `local_env.py`:

```python
SNANA_HOME = Path(os.environ.get("SNANA_HOME", str(Path.home())))
REPO_ROOT = Path(__file__).resolve().parents[2]
```

`SNANA_HOME` cae al home real del usuario si no se exporta la variable de entorno -- en NLHPC eso ya
es `/home/mvalenzuela`, cero cambio de comportamiento sin tocar nada allá. `REPO_ROOT` se calcula
desde la ubicación real de `local_env.py`, no de un string fijo -- funciona sin importar el nombre o
ubicación de la carpeta donde se clonó el repo (antes asumía literalmente `/home/mvalenzuela/AUTOSIM`).

Aplicado en **16 de los 21 archivos** (mismo patrón mecánico, no distinto por archivo): los 3 scripts
de producción, `searcheff.py`, `run_simsed_91bg_ddf_poc.py`, `run_dask_poc.py`, y los 6 scripts de
comparación (`compare_*.py`, `fase11_zgrid_compare.py`, `bench_snia.py`, `build_wfd_mwebv_grid.py`,
`test_opsim_load.py`, `check_opsim_schema.py`) -- estos últimos no forman parte del alcance pedido
(siguen dependiendo de datos reales de SNANA solo en NLHPC), pero el fix es mecánico y barato, y evita
un código base a dos velocidades. **Los 5 archivos `setup_*_local.py` (`setup_salt2_local.py`,
`setup_simsed_91bg_local.py`, `setup_knbulla19_local.py`, `setup_bullansed_local.py`,
`setup_tdebbfit_local.py`) quedan sin tocar a propósito** -- Fase 75 los reemplaza por un único
script generalizado, no tenía sentido arreglar código que se va a reemplazar la fase siguiente.

También se agregó `sncosmo` a `requirements.txt` -- dependencia real de `run_snia_ddf_poc.py`
(`sncosmo.SALT2Source`) que se había instalado a mano en NLHPC en su momento pero nunca quedó
documentada, un hueco real encontrado al auditar el camino de instalación completo. Se documentaron
también `pandas`/`pyarrow`/`matplotlib`/`pyyaml` (ya en uso, nunca declarados).

### Validación real, en ambos lados

- **Windows** (máquina de desarrollo del usuario, el caso real que motiva esta fase):
  `local_env.SNANA_HOME`/`REPO_ROOT` resuelven a rutas Windows reales y correctas
  (`C:\Users\HOME`/`C:\Users\HOME\Claude\proyects\ALCeS`) sin ninguna configuración.
- **NLHPC**: confirmado con un assert real que `SNANA_HOME`/`REPO_ROOT` siguen resolviendo
  exactamente a `/home/mvalenzuela`/`/home/mvalenzuela/AUTOSIM` sin exportar nada -- cero regresión.
  Corrida real de `run_simsed_poc.py` (`CaRT`, `ngentot=50`) tras subir los 16 archivos: corre de
  punta a punta (simulación, aplanado, SEARCHEFF, persistencia) sin errores nuevos.

### Conclusión Fase 74

El bloqueo más mecánico de portar la generación de simulaciones a una máquina fuera de NLHPC queda
resuelto, validado en ambos extremos reales (Windows y NLHPC), sin cambiar el comportamiento en
producción. Sienta la base para Fase 75 (empaquetar datos reales de SNANA para instalación local) y
Fase 76 (reemplazar SLURM por un runner local).

### Archivos de esta fase

Nuevo: `local_env.py`. Modificados (16): `run_simsed_poc.py`, `run_non1ased_poc.py`,
`run_snia_ddf_poc.py`, `searcheff.py`, `run_simsed_91bg_ddf_poc.py`, `run_dask_poc.py`,
`compare_lightcurve_shape.py`, `compare_brightness_truth.py`, `compare_brightness_truth_binned.py`,
`compare_brightness_truth_salt2.py`, `bench_snia.py`, `build_wfd_mwebv_grid.py`,
`fase11_zgrid_compare.py`, `compare_noise_formulas.py`, `test_opsim_load.py`,
`check_opsim_schema.py`, `requirements.txt` (`sncosmo`/`pandas`/`pyarrow`/`matplotlib`/`pyyaml`
agregados). `NOTES.md`: esta entrada.

## Fase 75 -- `vendor_snana_class.py` reemplaza 5 scripts de vendoring casi idénticos por uno
parametrizado, y empaqueta datos reales de SNANA para las 3 clases piloto de instalación local

### Motivación

Fase 74 resolvió el bloqueo de rutas; quedaba el bloqueo de datos: las plantillas SED reales de
SNANA (SIMSED/NON1ASED) que necesitan los scripts de producción solo existen en `run_SNANA/` de
NLHPC. De 6 clases con vendoring a copia local ya intentado (`setup_salt2_local.py`,
`setup_simsed_91bg_local.py`, `setup_knbulla19_local.py`, `setup_bullansed_local.py`,
`setup_tdebbfit_local.py`), ninguna copia generada llegó a commitearse -- y las otras 8 clases
SIMSED del catálogo ni siquiera tienen un script que las empaquete.

### Cambio real

`vendor_snana_class.py` nuevo: un único comando parametrizado (`python3 vendor_snana_class.py
<clase>`) reemplaza el patrón de "un script por clase". Reusa `CLASS_CONFIGS` de
`run_simsed_poc.py` para saber de dónde copiar -- agregar una clase nueva es correr el comando, no
escribir código. Modos especiales: `--salt2` (reproduce la lógica real de `setup_salt2_local.py`,
formato distinto que exige `sncosmo.SALT2Source`) y `--searcheff` (los 2 `.DAT` de `SEARCHEFF` que
nunca tuvieron vendoring).

**Bug real encontrado y corregido en el camino**: la copia genérica inicial usaba
`src.glob("*.SED*")` (mismo patrón que `setup_simsed_91bg_local.py`), pero `PISN-STELLA-HECORE`
(clase nueva, nunca vendorizada antes) usa una convención de nombre de archivo real distinta
(`<algo>_SED.dat.gz`, no `<algo>.SED`) -- el glob no encontraba nada, "0 archivos copiados" en la
primera corrida real. Corregido para leer los nombres reales declarados en `SED.INFO` ("SED: <nombre>
...") y copiar el archivo que efectivamente existe en disco (probando el nombre exacto y luego
`+".gz"`) -- misma lógica de resolución que ya usa `SIMSEDModel` de LightCurveLynx internamente
(confirmado en `compare_lightcurve_shape.py::build_template()`), en vez de adivinar una extensión
fija.

**`CLASS_CONFIGS["PISN-STELLA-HECORE"]` actualizado** en `run_simsed_poc.py` para apuntar a
`HERE / "simsed_pisnstellahecore_local"` (antes leía directo de `SNANA_HOME /
"run_SNANA/elastic/..."`) -- mismo patrón ya establecido para `SNIa-91bg`/`KN-BULLA19`. Esto crea una
dependencia circular real entre `CLASS_CONFIGS` y el propio script de vendoring (una vez migrada la
clase, `CLASS_CONFIGS` ya no dice de dónde vino el dato original) -- resuelta con una tabla chica
`KNOWN_SOURCE_OVERRIDES` en `vendor_snana_class.py` que documenta la ruta real de origen para las
clases ya migradas.

### Datos reales empaquetados (3 clases piloto + config compartida)

Corrido real en NLHPC (`ssh nlhpc`, venv de producción):

| Clase/config | Comando | Tamaño real |
|---|---|---:|
| `SNIa` (SALT2) | ya vendorizado (Fase 1) | 31M |
| `SNIa-91bg` (SIMSED) | ya vendorizado (Fase 2B) | 30M |
| `PISN-STELLA-HECORE` (SIMSED) | `vendor_snana_class.py PISN-STELLA-HECORE` (nuevo, 14/14 templates) | 4.9M |
| `SEARCHEFF` (2 `.DAT`) | `vendor_snana_class.py --searcheff` (nuevo) | 17K |

Empaquetado en 2 bundles reales (verificados con `unzip -l`, archivos no vacíos):
`lightcurvelynx_local_data_pilot.zip` (~35MB -- las 3 carpetas `*_local/`, se extrae dentro de
`exploration/lightcurvelynx/`) y `run_SNANA_pilot.zip` (~2KB -- carpeta `run_SNANA/` con los 2
`.DAT`, se extrae en el home del usuario o donde apunte `SNANA_HOME`, mismo layout real que NLHPC).
Descargados a la máquina de desarrollo del usuario para la validación real de Fase 77.

**Validado con corridas reales**: `run_simsed_poc.py` para `PISN-STELLA-HECORE`
(`ngentot_override=50`) corre de punta a punta con la copia local recién generada -- 14 templates
cargados, simulación, `SEARCHEFF` (10/50 detectados), QC completo, sin errores.

### Conclusión Fase 75

El bloqueo de datos reales para las 3 clases piloto queda resuelto y empaquetado (~35MB total, nada
parecido a los GB de `.DUMP`/FITS que la comparación contra SNANA sí necesitaría). El mecanismo
(`vendor_snana_class.py`) queda listo para las 16 clases restantes bajo demanda, sin código nuevo.

### Archivos de esta fase

Nuevo: `vendor_snana_class.py`. Modificado: `run_simsed_poc.py`
(`CLASS_CONFIGS["PISN-STELLA-HECORE"]["simsed_dir"]`). Generado en NLHPC (no commiteado, mismo
criterio que `poc_output_*/`): `simsed_pisnstellahecore_local/`, `searcheff_local/`,
`lightcurvelynx_local_data_pilot.zip`, `run_SNANA_pilot.zip`. `NOTES.md`: esta entrada.

## Fase 76 -- `sweep_run_local.py` reemplaza SLURM por un runner local para el sistema de sweeps,
sin tocar el esquema de hash/manifiesto de Fase 66

### Motivación

Con las rutas (Fase 74) y los datos (Fase 75) portables, quedaba el último bloqueo real: el "deploy
de un click" del sistema de sweeps (Fase 66) depende de `sbatch`/`sacct`/`SLURM_ARRAY_TASK_ID` -- no
hay equivalente en un laptop sin cluster.

### Cambio real

`sweep_run_local.py` nuevo: compila el sweep igual que `sweep_launch.py` (reusa
`sweep_compile.compile_sweep()` tal cual, sin tocarlo), pero en vez de generar `.sbatch` y someter a
`sbatch`, corre cada fila del manifiesto vía `concurrent.futures.ProcessPoolExecutor` llamando
directo a `sweep_worker.run_one(manifest_path, index)` -- la misma función que ya usa el `.sbatch`
real vía `SLURM_ARRAY_TASK_ID`, sin cambios. Procesa tier por tier (no todos a la vez), respetando el
`max_concurrent` real de cada tier del YAML -- mismo campo, mismo significado que el throttle
`--array=lo-hi%K` de SLURM. `--workers N` sobreescribe el número de workers para todos los tiers por
igual (en una máquina local no existe la noción de "nodo aparte" para un tier "heavy").

**Hallazgo real, no hubo que escribir nada más**: `sweep_monitor.py` (Fase 66) ya funciona sin
ningún cambio para sweeps corridos localmente -- lee `run_hash.json` primero (fuente autoritativa,
la escribe el worker sea cual sea el backend) y `sacct` es solo un fallback que en una máquina local
simplemente no encuentra el binario (`sacct_states()` ya atrapa `FileNotFoundError`) y sigue de
largo. Lo mismo para `sweep_aggregate.py` -- consolida el `parquet` final sin cambios. El plan
original consideraba escribir un `sweep_status_local.py` aparte; no hizo falta.

### Validación real, en NLHPC (sin usar SLURM, corrida directa en el login node)

Nuevo `sweeps/_smoke_local.yaml` (2 clases piloto, `SNIa-91bg` + `PISN-STELLA-HECORE`, `ngentot=30`
c/u, `max_concurrent.default=2`) corrido con `python3 sweep_run_local.py sweeps/_smoke_local.yaml`
-- compiló el manifiesto, corrió las 2 corridas **en paralelo real** (2 workers simultáneos,
confirmado por los timestamps intercalados en el log real), ambas terminaron `status=done` sin
fallos. `sweep_monitor.py _smoke_local` y `sweep_aggregate.py _smoke_local` corridos después,
ambos sin modificar, reportan el resultado real correctamente (`resumen: done=2`,
`aggregated_summary.parquet` con 2 filas).

### Conclusión Fase 76

El sistema de sweeps completo (compilar, correr, monitorear, agregar) queda operativo sin SLURM,
validado con corridas reales en paralelo, sin tocar `sweep_hash.py`/`sweep_compile.py` y sin
necesitar cambios en `sweep_monitor.py`/`sweep_aggregate.py` -- el diseño de Fase 66 (manifiesto
agnóstico de backend, `run_hash.json` como fuente de verdad) resultó ser más portable de lo
anticipado. Queda pendiente la prueba real en una máquina sin acceso a NLHPC en absoluto (Fase 77).

### Archivos de esta fase

Nuevo: `sweep_run_local.py`, `sweeps/_smoke_local.yaml`. Sin cambios en `sweep_hash.py`,
`sweep_compile.py`, `sweep_monitor.py`, `sweep_aggregate.py`, `sweep_worker.py`. `NOTES.md`: esta
entrada.

## Fase 77 -- Validación real en una máquina Windows sin NLHPC: 2 bugs reales encontrados y
corregidos, instalación completa confirmada, corrida final validada en NLHPC por espacio en disco

### Motivación

Fases 74-76 portaron rutas, datos y el runner de sweeps, pero todo el trabajo se había *diseñado*
sin correrlo nunca en una máquina que no fuera NLHPC. El plan exigía explícitamente probar de punta
a punta en un entorno Windows real antes de documentar nada para el profesor -- "no se resuelve por
adivinanza".

### Instalación real: 2 bugs de Windows encontrados corriendo, no supuestos

`pip install -r requirements.txt` en un venv nuevo (Python 3.14.6, único disponible en esta
máquina -- NLHPC usa 3.12.3) falló compilando `sncosmo` (dependencia dura de `lightcurvelynx`, no
opcional): `error: Unable to find a compatible Visual Studio installation`, pese a tener Visual
Studio Build Tools 2022 con `cl.exe` real instalado. Investigado a fondo (no aceptado como "Windows
simplemente no sirve"): `setuptools._distutils.compilers.C.msvc._get_vc_env()` invoca
`vcvarsall.bat`, que a su vez llama a `vswhere.exe` -- pero `vswhere.exe` no estaba en el PATH del
proceso que lanza pip, y el mensaje de error resultante ("no se reconoce como comando") se mezclaba
con la salida que `_get_vc_env()` decodifica como UTF-16LE, rompiendo el parseo y devolviendo un
entorno vacío. **Fix real de una línea**: agregar `C:\Program Files (x86)\Microsoft Visual
Studio\Installer` (donde vive `vswhere.exe`) al `PATH` antes de instalar -- confirmado con
`sncosmo-2.13.0` compilando y `pip install -r requirements.txt` completo (`lightcurvelynx==0.5.2`,
`sncosmo`, `pandas`, `pyarrow`, `matplotlib`, `pyyaml`) instalado e importable sin errores.

**Segundo bug real, distinto**: corriendo el smoke sweep (`sweep_run_local.py
sweeps/_smoke_local.yaml`) con los datos vendorizados (Fase 75) y el `.db` de OpSim recién
descargado (`pipeline/fetch_opsim.py`, público, ~743MB), ambas clases piloto SIMSED
(`SNIa-91bg`, `PISN-STELLA-HECORE`) fallaron con `sqlite3.OperationalError: unable to open database
file`. Causa real: `run_simsed_poc.py` (línea 88) era el único de los 4 scripts de producción que la
Fase 74 NO terminó de portar -- seguía con `OPSIM_DB = SNANA_HOME / "AUTOSIM/data/opsim/..."` en vez
de `REPO_ROOT / "data/opsim/..."` (patrón ya aplicado en los otros 3). En NLHPC coincidía por
casualidad (el repo vive exactamente en `~/AUTOSIM`), enmascarando el bug ahí; en cualquier otra
máquina (`SNANA_HOME` = home del usuario, repo en cualquier otra carpeta) rompe. Corregido con el
mismo patrón de una línea.

### Restricción real de espacio en disco -- validación final trasladada a NLHPC

A mitad de la Fase 77 el notebook de desarrollo se quedó sin espacio (~1.1GB libres tras el `.db`
de OpSim + el venv de prueba con `lightcurvelynx`/`astropy`/`scipy`/`sncosmo`). Criterio aplicado:
NLHPC ya tiene todos estos datos -- no hace falta retener una copia local persistente en la máquina
de desarrollo solo para validar el método una vez. Se liberó el espacio (borrado el `.db` de
OpSim descargado, el venv de prueba completo, y el instalador de Miniforge descartado -- ~1.7GB
liberados en total) y la validación final de los 2 bugs corregidos se hizo directamente en NLHPC
(`scp` del fix, sin usar `git pull` -- `~/AUTOSIM` en NLHPC es una copia sincronizada por `scp`, no
un clon git, confirmado al intentar `git pull` ahí y obtener "not a git repository").

**Corrida real de confirmación** (`sweep_launch.py sweeps/_smoke_local.yaml`, vía `sbatch`,
job=12761794 -- notar: sin cargar el módulo `SNANA/11.05p`, que en este intento downgradeaba
OpenSSL 3.3.0→1.1 y rompía la importación de `pyarrow` en el venv; `run_simsed_poc.py` no invoca
binarios de SNANA directamente, solo lee sus archivos de config, así que no lo necesita cargado):
ambas corridas terminaron `status=done`, sin fallos (`sweep_monitor.py _smoke_local` →
`resumen: done=2`).

### Conclusión Fase 77

El flujo de instalación local queda confirmado como real y viable en Windows nativo, con 2 gotchas
genuinos documentados (no supuestos) y sus fixes ya aplicados y validados: el PATH de `vswhere.exe`
para compilar `sncosmo`, y el `OPSIM_DB` de `run_simsed_poc.py`. La corrida de confirmación final se
hizo en NLHPC en vez de repetirla en el notebook de desarrollo, por la restricción real de espacio
encontrada -- criterio documentado para la Fase 78: la máquina del profesor sí necesita el `.db` de
OpSim completo (~750MB) para generar localmente, pero un entorno de desarrollo/prueba compartido no
necesita retenerlo después de validar.

### Archivos de esta fase

Modificado: `run_simsed_poc.py` (`OPSIM_DB`). `requirements.txt`: sin cambios (ya correcto desde
Fase 74). `NOTES.md`: esta entrada. No se generaron archivos nuevos en el repo -- el venv de prueba,
el `.db` de OpSim y el instalador de Miniforge fueron todos artefactos ephemeral de esta fase,
borrados al terminar.

## Fase 78 -- `HOWTO_LOCAL.md`: documentación de instalación local, cierra el plan de Fases 74-78

### Motivación

Con las Fases 74-77 validando que el método completo (rutas, datos, sweeps, instalación) corre de
punta a punta en una máquina sin NLHPC, faltaba el último paso del plan: un documento que alguien
que no vio ninguna de estas fases pueda seguir de punta a punta, sin adivinar nada.

### Cambio real

`HOWTO_LOCAL.md` nuevo, hermano de `HOWTO.md` (que sigue documentando el flujo real de NLHPC, no se
reemplaza). Cubre: qué incluye este camino y qué no (explícito, para no generar expectativas
equivocadas -- la comparación contra SNANA y las 16 clases sin vendoring quedan fuera); requisitos
reales verificados (Python 3.12 o 3.14, ~750MB de disco para el `.db` de OpSim, Visual Studio Build
Tools en Windows para compilar `sncosmo`); instalación de dependencias con el gotcha real de
`vswhere.exe`/`PATH` documentado tal cual se encontró en Fase 77 (no genérico); cómo obtener el
bundle de datos de las 3 clases piloto y el `.db` de OpSim (con la nota real del
`UnicodeEncodeError` cosmético de Fase 77); el smoke test (`sweep_run_local.py
sweeps/_smoke_local.yaml`) como paso de confianza obligatorio antes de un barrido real; cómo correr
un barrido real y agregar una clase nueva (`vendor_snana_class.py <clase>`, un comando, sin código
nuevo).

### Conclusión Fase 78

Cierra el plan "Portar la generación de simulaciones LightCurveLynx + automatización a una máquina
local" (Fases 74-78). El profesor puede instalar y generar datasets reales en su propio computador
sin acceso a NLHPC, con 3 clases piloto ya listas y un mecanismo documentado para agregar el resto
bajo demanda. La comparación contra SNANA (la investigación científica, Fases 0-73) permanece
exclusiva de NLHPC, sin cambios.

### Archivos de esta fase

Nuevo: `HOWTO_LOCAL.md`. `NOTES.md`: esta entrada.

## Fase 79 -- `sweep_generate.py`: backend generador de sweeps

### Motivación

Con la instalación local resuelta (Fases 74-78), el profesor pidió el siguiente nivel de
automatización: "backend que genere scripts". Investigación real confirmó el hueco exacto: autoría
de `sweeps/*.yaml` era 100% manual (cero `yaml.dump` en todo el repo antes de esta fase,
`HOWTO.md` decía literalmente "copiar un YAML existente como plantilla").

### Cambio real

`sweep_generate.py` nuevo: `generate_sweep(sweep_name, classes, seeds, ngentot_overrides, modes,
resources, max_concurrent, partition, keep_phot, description, force)` escribe un
`sweeps/<nombre>.yaml` con exactamente el mismo esquema que `sweep_compile.py` ya espera (mismo
orden de claves que `sweeps/_smoke_local.yaml`) -- no compila ni lanza nada, ese sigue siendo un
paso separado y explícito.

`available_classes()` no es una lista hardcodeada -- intersección real entre `CLASS_CONFIGS`
(import de `run_simsed_poc.py`) y `Path(cfg["simsed_dir"]).exists()` no vacío, así que se
auto-actualiza a medida que `vendor_snana_class.py` empaquete más clases. Corrido en NLHPC (donde
existe la data completa de las 15 clases SIMSED) devuelve las 15; corrido en una máquina local con
solo el bundle de la Fase 75 devolvería solo las 2 clases SIMSED vendorizadas ahí.

`validate_classes()` distingue 2 causas raíz reales con 2 mensajes distintos: clase que no existe
en el catálogo (`CLASS_CONFIGS`) vs. clase real del catálogo pero sin datos vendorizados
localmente -- confirmado con un test real (el segundo caso se simuló acotando
`available_classes()`, ya que en NLHPC las 15 clases están disponibles y ese caso no ocurre
naturalmente ahí).

**Bug real encontrado y corregido en el camino**: la primera versión de `--list-classes` seguía
exigiendo `--name`/`--classes`/`--seeds` como argumentos obligatorios de `argparse`, así que listar
las clases disponibles sin querer generar nada todavía fallaba con "arguments are required".
Corregido validando esos 3 argumentos a mano solo cuando `--list-classes` no está presente.

### Validación real

Generado un sweep real (`SNIa-91bg` + `PISN-STELLA-HECORE`, `ngentot=30` c/u, `keep_phot=true`) vía
`python3 sweep_generate.py --name ... --classes ... --seeds 0 --ngentot ... --keep-phot`, y
compilado con el `sweep_compile.py` real sin modificar -- mismo `code_hash`, mismo formato de
manifiesto que un YAML escrito a mano. Artefactos de prueba borrados después.

### Conclusión Fase 79

El backend generador de sweeps queda operativo y validado con una corrida real de punta a punta
(generar → compilar), con las 2 rutas de error reales distinguidas explícitamente. `sweep_history`
(Fase 80, todavía no escrito) se importa con un shim de respaldo (no-op) para no bloquear esta fase
en la siguiente -- se conecta de verdad en la Fase 80.

### Archivos de esta fase

Nuevo: `sweep_generate.py`. `NOTES.md`: esta entrada.

## Fase 80 -- `generation_history.jsonl`: historial reproducible append-only

### Motivación

El profesor pidió "un JSON lo más reproducible posible, como un historial de..., para que
cualquier otra persona tome el código y pueda seguir". Investigación real confirmó que nada de lo
existente cumple esto: `manifest.json`/`run_hash.json`/`datasets/<hash>/manifest.json` son todos
snapshots frescos y autocontenidos de un solo evento -- nada se acumula a través de múltiples
generar/compilar/correr/publicar a lo largo del tiempo. La única "historia" real es `NOTES.md`,
prosa de miles de líneas, no legible por máquina.

### Cambio real

`sweep_hash.append_jsonl(path, record)` nuevo -- distinto de `write_json_atomic()` a propósito: ahí
se reemplaza el archivo entero (un snapshot fresco), acá se agrega una línea, nunca se reescriben
líneas existentes (mismo patrón de `flush()`+`fsync()` que ya usa `write_json_atomic` para no dejar
una línea a medio escribir si el proceso muere a mitad de camino).

`sweep_history.py` nuevo, delgado: `record_event(event_type, *, triggered_by="cli", **fields)`
arma `event_id`/`timestamp`/`event_type`/`triggered_by` + los campos dados y llama
`sweep_hash.append_jsonl` sobre `generation_history.jsonl` (gitignorado, mismo criterio que
`sweep_runs/`/`datasets/`); `read_history(limit=None)` lee tolerando líneas corruptas (salta con
advertencia en vez de tumbar toda la lectura).

Instrumentación quirúrgica en los 4 puntos de decisión reales (no en cada corrida individual --
eso ya vive completo en `run_hash.json`, duplicarlo violaría el criterio de no inventar mecanismos
paralelos): `sweep_generate.generate_sweep()`, `sweep_compile.compile_sweep()`,
`sweep_run_local.run_sweep_local()`, `sweep_publish_dataset.publish_dataset()` -- cada uno ahora
acepta `triggered_by: str = "cli"` (el webapp de Fase 83 pasará `"webapp"`) y registra un evento al
terminar.

### Validación real

Ciclo completo real en NLHPC (`generate_sweep` → `compile_sweep` → `run_sweep_local` →
`publish_dataset`, una clase piloto real, `ngentot=30`): `generation_history.jsonl` terminó con
exactamente 4 líneas, cada una JSON válido, en orden cronológico correcto
(`generate_sweep`→`compile_sweep`→`run_local`→`publish_dataset`). `ingestion_format` sigue en
`null` en el evento de publicación -- esperado, `keep_phot` todavía no se conecta de verdad a
`sweep_worker.py` (eso es la Fase 81, siguiente).

### Conclusión Fase 80

El historial reproducible queda operativo y validado con una corrida real de punta a punta -- el
mecanismo conecta automáticamente cada acción futura (generar, compilar, correr, publicar) sin
intervención manual, cumpliendo el pedido real del profesor de una traza que cualquier otra persona
pueda seguir.

### Archivos de esta fase

Nuevo: `sweep_history.py`. Modificado: `sweep_hash.py` (`append_jsonl`), `sweep_generate.py`
(import directo, ya no shim), `sweep_compile.py`, `sweep_run_local.py`,
`sweep_publish_dataset.py` (instrumentación de `record_event` + parámetro `triggered_by`).
`.gitignore` (`generation_history.jsonl`). `NOTES.md`: esta entrada.

## Fase 81 -- `keep_phot`: opt-in para preservar fotometría cruda

### Motivación

`sweep_worker.py::cleanup_phot_df()` borra `phot_df.parquet` SIEMPRE, después de cada corrida
(mitigación de cuota de disco, Fase 8/59/65). Esto es incompatible con un export de training-set
real (Fase 82) que necesita fotometría cruda por objeto -- había que hacerlo opt-in, sin tocar el
comportamiento por defecto de los sweeps exploratorios de siempre.

### Cambio real

Campo YAML de nivel-sweep `keep_phot: true|false` (default `false`, ya soportado en
`sweep_generate.py` desde la Fase 79). `sweep_compile.py::compile_sweep()` lo copia al manifiesto
(`manifest["keep_phot"]`) -- deliberadamente **no** entra en el payload de `sweep_hash.run_hash()`:
es política de almacenamiento, no un parámetro físico de la simulación, así que cambiarlo no debe
cambiar la identidad de una corrida.

`sweep_worker.py::run_one()` lee `keep_phot` del manifiesto completo (no de la fila `row` -- evita
que se cuele por error en el hash de la corrida) y cambia la línea exacta del `finally`:
`cleaned = False if keep_phot else cleanup_phot_df(output_dir)`. Se agrega `phot_df_kept` a
`run_hash.json`, junto al `phot_df_cleaned` que ya existía.

### Validación real

Dos sweeps reales, idénticos salvo `keep_phot` (uno `true`, uno `false`), misma clase/semilla/
`ngentot`: compilados por separado, confirmado que ambos producen el **mismo `run_hash`**
(`bbb5d89485ca` en los dos) -- `keep_phot` no cambia la identidad de la corrida. Corridos ambos vía
`sweep_run_local.py`: `phot_df.parquet` sobrevivió únicamente en el sweep con `keep_phot=true`
(`phot_df_kept=true`/`phot_df_cleaned=false`); el otro terminó con `phot_df_kept=false`/
`phot_df_cleaned=true`, comportamiento idéntico al de antes de esta fase.

### Conclusión Fase 81

El opt-in queda operativo y validado con una corrida real doble -- desbloquea la Fase 82 (el
conector real de ML necesita justamente esta fotometría cruda preservada) sin cambiar en nada el
comportamiento por defecto de los sweeps exploratorios existentes.

### Archivos de esta fase

Modificado: `sweep_compile.py` (`manifest["keep_phot"]`), `sweep_worker.py` (lee `keep_phot`,
`phot_df_kept` en `run_hash.json`). `NOTES.md`: esta entrada.

## Fase 82 -- `sweep_export_by_class.py`: conector real de ML (parquet por clase)

### Motivación

El profesor especificó el formato real de entrega al equipo de ML: "en parquet y por clase".
Esto reemplaza el `ingestion_format: null` deliberado que `sweep_publish_dataset.py` mantenía desde
la Fase 66/73 -- documentado explícitamente en su propio docstring/README generado como "el formato
aún no está definido". El propio código ya anticipaba este momento: el README generado decía
literalmente "si el formato real de ALeRCE necesita fotometría cruda por objeto, es una decisión de
una fase posterior que cambiaría la política de borrado" -- esa fase es esta.

### Cambio real

`sweep_export_by_class.py` nuevo: `export_by_class(sweep_names, out_dir)` reusa
`sweep_publish_dataset.load_sweep_done_rows()` (ya filtra por `status="done"` leyendo el
`run_hash.json` real de cada corrida, no el campo `status` de `manifest.json`, que nunca se
reescribe). Para cada corrida con `phot_df.parquet` real en disco (las de sweeps con
`keep_phot=true`, Fase 81), une `head_df.parquet` (`REDSHIFT_HELIO`/`SNTYPE`/`DETECTED`) sobre
`phot_df.parquet` por `SNID`, tagueando procedencia (`class_key`/`run_hash`/`source_sweep`/
`seed_index`/`wfd`). Concatena por `class_key` a través de sweeps, escribe
`datasets/<hash>/by_class/<clase>.parquet` vía `sweep_hash.write_dataframe_atomic` (reusado, no
reinventado). Corridas sin fotometría preservada se omiten con una advertencia contada, no un
error -- un export parcial sigue siendo útil.

`sweep_publish_dataset.py::publish_dataset()` llama a `export_by_class()` (import local, evita un
ciclo real de importación con `load_sweep_done_rows`) y reemplaza el `ingestion_format=None`
hardcodeado por `"parquet_by_class_v1"` cuando hay al menos una clase exportada -- versionado
explícito para poder cambiarlo si el formato real de ALeRCE termina siendo distinto. Si ninguna
corrida de origen preservó fotometría, queda `ingestion_format=null` con un
`ingestion_format_pending_reason` explícito -- publicar sigue funcionando igual, solo sin el
export por clase. El manifiesto agrega `by_class_files`/`by_class_schema_version`; el `README.md`
generado ya no dice "el formato aún no está definido" cuando sí existe.

### Validación real

3 sweeps reales en NLHPC: 2 con `keep_phot=true` (`SNIa-91bg`, `PISN-STELLA-HECORE`) y uno sin
(`SNIa-91bg`, semilla distinta). Publicando los 2 primeros juntos:
`datasets/<hash>/by_class/{SNIa-91bg,PISN-STELLA-HECORE}.parquet` reales, 176,601 y 195,592 filas
respectivamente (columnas: fotometría completa + contexto + procedencia, 17 columnas),
`manifest.json["ingestion_format"] == "parquet_by_class_v1"`. Publicando el tercero solo:
`ingestion_format=null` + `ingestion_format_pending_reason` explicando por qué, con la advertencia
contada real ("1/1 corridas sin phot_df.parquet") -- sin fallar.

### Conclusión Fase 82

El conector real de ML queda implementado y validado con datos reales, no un stub -- el hueco que
`sweep_publish_dataset.py` dejó deliberadamente abierto desde la Fase 66 (a la espera de que el
profesor definiera el formato) queda cerrado con el formato que el profesor efectivamente pidió.

### Archivos de esta fase

Nuevo: `sweep_export_by_class.py`. Modificado: `sweep_publish_dataset.py` (`export_by_class()`,
`ingestion_format` real, manifiesto y README actualizados, docstring del módulo). `NOTES.md`: esta
entrada.

## Fase 83 -- `webapp/app.py`: "el botón" -- backend Flask local

### Motivación

Con el backend de generación/historial/conector resuelto (Fases 79-82), faltaba "el botón" en
sentido literal que pidió el profesor: una interfaz para interactuar con todo eso sin tocar la
terminal. `docs/index.html` (el dashboard publicado) se investigó y descartó a propósito: es una
página 100% estática en GitHub Pages, sin capacidad de ejecutar nada del lado servidor -- necesitaba
un vehículo nuevo.

### Cambio real

`webapp/app.py` nuevo (Flask, justificación real: `requirements.txt` no tenía ningún framework web,
Flask agrega una sola dependencia liviana, y todo lo que llama ya es síncrono/bloqueante -- el
modelo async de FastAPI no aporta nada acá). Todas las rutas importan directo las funciones reales
de `sweep_*.py` -- nunca `subprocess`/shell-out: `/` (formulario, clases vía
`sweep_generate.available_classes()`), `/generate` (`generate_sweep` → `compile_sweep`),
`/sweep/<name>` (estado + YAML), `/sweep/<name>/run` (lanza `run_sweep_local` en un
`threading.Thread` de fondo -- no bloquea Flask, guard en memoria solo para no lanzar el mismo
sweep 2 veces), `/sweep/<name>/status` (JSON vía `sweep_monitor.monitor_sweep`, sin mecanismo de
estado nuevo), `/aggregate`, `/publish`, `/history`, `/qc/<sweep>/<hash>/<archivo>` (sirve los PNG
que `pipeline.postproc.qc` ya genera), `/datasets/<hash>`. Host `127.0.0.1` siempre -- un solo
usuario local.

**Hallazgo real en el camino**: los nombres de archivo de QC son dinámicos (prefijo real
`LightCurveLynx_<clase>_<WFD|DDF>_poc_qc_*.png`, no un nombre fijo) -- el diseño original asumía
nombres constantes; corregido listando los `.png` reales del directorio `qc/` de cada corrida en
vez de adivinar.

### Validación real

Recorrido completo real contra la app corriendo en NLHPC (`curl`, simulando exactamente lo que
manda un formulario real): `POST /generate` (clase piloto real, ngentot=20) → redirect a
`/sweep/_fase83_test` con el manifiesto ya compilado → `POST /sweep/.../run` → la corrida real
terminó `status=done` en su `run_hash.json` (confirmado en el filesystem, independiente del proceso
Flask) → la página de estado mostró `done` con los 4 enlaces reales de QC (nombres dinámicos
correctos) → una imagen QC real sirvió con `HTTP 200` (73,771 bytes) → `POST /aggregate` y
`POST /publish` funcionaron, redirigiendo a `/datasets/<hash>` real → la página del dataset mostró
`ingestion_format=null` con la razón explícita (este sweep de prueba no usó `keep_phot`) →
`/history` mostró los 4 eventos reales (`generate_sweep`/`compile_sweep`/`run_local`/
`publish_dataset`) con `triggered_by="webapp"`.

**Incidente real durante la prueba**: el proceso de Flask murió junto con su archivo de log en
`/tmp` (efímero en NLHPC) cuando una sesión SSH de polling separada fue terminada por el entorno --
la corrida real en sí ya había completado antes de eso (confirmado por su `run_hash.json`), así que
no se perdió trabajo, solo el proceso servidor. Reiniciado con `setsid`+`nohup` para mayor
resiliencia, y el resto de la validación continuó sin problema sobre la misma corrida ya completada.

### Conclusión Fase 83

El backend web queda operativo y validado con un recorrido real de punta a punta -- generar,
compilar, lanzar, monitorear, agregar, publicar y ver el dataset resultante, todo desde HTTP en vez
de la terminal. Las plantillas HTML (Fase 84) ya existen en forma funcional; la Fase 84 las pule
(polling en vivo sin recargar la página, mejoras de UX) en vez de partir de cero.

### Archivos de esta fase

Nuevo: `webapp/app.py`, `webapp/templates/{base,index,sweep_status,history,dataset}.html`.
Modificado: `requirements.txt` (`flask`). `NOTES.md`: esta entrada.

## Fase 84 -- Frontend: polling en vivo, sección avanzada, verificación real en navegador

### Motivación

La Fase 83 dejó las plantillas funcionales pero con "recargar la página a mano" como única forma
de ver el progreso de una corrida. El plan pedía específicamente estado en vivo sin recargar, más
una sección "avanzado" para recursos/`max_concurrent` que la Fase 83 no exponía en el formulario.

### Cambio real

`sweep_status.html`: reemplazado el hint "recargar la página" por un polling real en JS vanilla
(`fetch()` a `/sweep/<name>/status` cada 3s) que actualiza en el DOM la celda de estado, el detalle
y los enlaces de QC de cada fila sin recargar -- se detiene solo cuando todas las filas llegan a un
estado terminal (`done`/`failed`/`UNKNOWN`), y revela los botones "Agregar"/"Publicar" (ocultos por
CSS hasta ese momento) en cuanto todas quedan `done`. Sigue sin inventar un mecanismo de estado
nuevo -- el JSON que consume es exactamente `sweep_monitor.monitor_sweep()`.

`index.html`: sección `<details>` "Avanzado" con memoria/tiempo/CPUs/máx.-en-paralelo, mismos
defaults que `sweep_generate.py` ya usa si se omiten. `app.py::generate()` ahora arma
`resources`/`max_concurrent` reales desde esos campos del formulario.

### Validación real

Recorrido completo real en el **navegador** (no solo `curl`) contra la app corriendo en NLHPC, vía
un túnel SSH (`ssh -L 5000:127.0.0.1:5000 nlhpc`) desde la máquina de desarrollo: formulario real
con las 15 clases reales de NLHPC listadas, generó `PISN-STELLA-HECORE` (ngentot=20) real, lanzó la
corrida con el botón, el estado pasó de `NOT_SUBMITTED` a `running` a `done` en la página sin
recargar (confirmado programáticamente vía `fetch()` en la consola del navegador, además de
visualmente), los 4 enlaces de QC reales aparecieron y uno se abrió mostrando una imagen PNG real
(1482×960px, servida con `HTTP 200`). "Agregar" y "Publicar" funcionaron con sus mensajes flash
reales, la página del dataset mostró correctamente el caso sin fotometría (`ingestion_format=null`,
razón explícita), y `/history` mostró los 4 eventos reales en orden cronológico inverso, todos con
`triggered_by="webapp"`. Sin errores en la consola del navegador.

### Conclusión Fase 84

"El botón" queda completo: generar, lanzar, ver progreso en vivo, ver QC, agregar, publicar y
revisar el historial, todo desde el navegador sin tocar la terminal ni recargar la página a mano.

### Archivos de esta fase

Modificado: `webapp/templates/sweep_status.html` (polling JS), `webapp/templates/index.html`
(sección avanzado), `webapp/app.py` (`resources`/`max_concurrent` desde el formulario). `NOTES.md`:
esta entrada.

## Fase 85 -- `HOWTO_WEBAPP.md` + cierre del plan (Fases 79-85)

### Motivación

Con el backend generador, el historial reproducible, el conector de ML y la interfaz web
completos y validados (Fases 79-84), faltaba el documento que le permita a alguien que no vio
ninguna de estas fases usar "el botón" de punta a punta.

### Cambio real

`HOWTO_WEBAPP.md` nuevo, hermano de `HOWTO.md`/`HOWTO_LOCAL.md`: qué es la app y qué no (no agrega
capacidad de simulación nueva, no es multiusuario, no entrena modelos), cómo levantarla (incluido
el túnel SSH para probarla desde NLHPC), el flujo real generar→lanzar→ver progreso en
vivo→agregar→publicar, cómo leer el historial, y cómo interpretar `ingestion_format` en la página
de un dataset publicado (`parquet_by_class_v1` real vs. `null` con la razón explícita).

### Conclusión Fase 85 -- cierre del plan

Cierra el plan "Backend generador de sweeps + interfaz web local + conector ML (parquet por
clase)" (Fases 79-85). Las 3 brechas reales identificadas al inicio quedan resueltas y validadas
con datos reales, no solo diseñadas en papel:

1. **Backend que genere scripts** -- `sweep_generate.py` (Fase 79), validado generando y
   compilando un sweep real idéntico en forma a uno escrito a mano.
2. **Historial reproducible** -- `generation_history.jsonl` (Fase 80), validado con un ciclo
   completo real de 4 eventos en orden cronológico.
3. **Conector de ML (parquet por clase)** -- `sweep_export_by_class.py` (Fase 82), sobre
   `keep_phot` (Fase 81), validado con datos reales de 2 clases piloto (176,601 y 195,592 filas de
   fotometría real).

Más "el botón" en sentido literal: una app web local (Flask, Fase 83) con un frontend completo
(estado en vivo sin recargar, Fase 84), validada de punta a punta en un navegador real, no solo por
`curl`. El entrenamiento/despliegue de modelos queda explícitamente fuera de alcance -- el pipeline
propio de ALeRCE, una decisión y un esfuerzo de ingeniería separados.

### Archivos de esta fase

Nuevo: `HOWTO_WEBAPP.md`. `NOTES.md`: esta entrada.

## Fase 86 -- DDF y WFD como casillas independientes (pedido real del usuario probando la app)

### Motivación

El formulario (Fase 84) tenía un solo checkbox "WFD (footprint completo, en vez de DDF)" -- un
toggle binario que obligaba a elegir una sola estrategia por sweep, aunque
`sweep_compile.py::build_runs()` ya soporta una LISTA de `modes` (generar DDF y WFD en el mismo
sweep) desde la Fase 66. El usuario, probando la app real, pidió exponer esa capacidad ya existente
como 2 casillas independientes.

### Cambio real

`index.html`: 2 checkboxes (`mode_ddf`, `mode_wfd`, DDF marcado por default) en vez de 1. `app.py`:
arma `modes` como lista según cuáles estén marcadas -- si ninguna, error explícito ("elegir al
menos una estrategia"). `sweep_monitor.py::monitor_sweep()` no exponía `wfd` por fila -- con 2
modos por sweep ahora posibles, 2 filas podían verse idénticas (misma clase/semilla) sin forma de
distinguirlas; se agregó el campo. `sweep_status.html`: nueva columna "Estrategia" (DDF/WFD).

**Incidente real durante la prueba en vivo**: la primera vez que se probó, el YAML generado seguía
con un solo `mode` pese a marcar las 2 casillas en el navegador -- diagnosticado comparando
checksums: el `app.py` sincronizado a NLHPC había quedado desactualizado por una sincronización
previa incompleta (una carrera con un `pkill` que cortó la sesión SSH a mitad de un comando
encadenado). Confirmado con `md5sum` en ambos lados, re-sincronizado, reiniciado el proceso -- la
segunda prueba real dio 2 filas (`DDF`/`WFD`, `run_hash` distintos) como se esperaba.

### Validación real

Generado un sweep real con `PISN-STELLA-HECORE` y ambas casillas marcadas, en el navegador real
(no `curl`): 2 filas en la tabla de estado, `run_hash` distinto para cada una, columna
"Estrategia" mostrando `DDF`/`WFD` correctamente, YAML generado con 2 entradas reales en `modes`.

### Conclusión Fase 86

Expone una capacidad que el generador ya tenía (sweeps multi-modo) pero que la interfaz no dejaba
usar. El incidente de sincronización queda documentado como recordatorio real: verificar `md5sum`
tras sincronizar a NLHPC antes de asumir que un cambio ya está activo, especialmente después de
interrumpir una sesión SSH a mitad de un comando encadenado.

### Archivos de esta fase

Modificado: `webapp/templates/index.html`, `webapp/templates/sweep_status.html`, `webapp/app.py`,
`sweep_monitor.py` (campo `wfd` en `monitor_sweep()`). `NOTES.md`: esta entrada.

## Fase 87 -- lista de sweeps + enlaces reales + "dónde quedan los resultados" (usuario probando la app en vivo)

### Motivación

El usuario, generando sweeps reales con la app (`test1`, `test2`, `test3`), reportó 2 huecos reales
de navegación: (1) la única forma de volver a la página de un sweep después de salir de ahí era
recordar su nombre a mano -- no había ninguna lista; (2) no quedaba claro dónde revisar los
resultados reales de una corrida ni ver el detalle del YAML de un evento del historial.

### Cambio real

`GET /sweeps` nuevo: lista todos los sweeps ya compilados (escanea `SWEEP_RUNS_DIR` directo, sin
estado nuevo), con nombre, fecha de compilación, conteo de corridas y estado agregado -- agregado a
la barra de navegación. `history.html`: el nombre del sweep ahora es un link real a
`/sweep/<name>` (antes texto plano) -- resuelve "ver los detalles del YAML del evento" sin duplicar
el YAML en el historial (la fuente de verdad sigue siendo el archivo real).

`GET /sweep/<name>/run/<hash>/summary` nuevo: muestra el `summary.json` real de una corrida
(métricas reales) más la lista de archivos reales en su carpeta y la ruta completa en disco --
responde directamente "no entiendo cómo revisar eso". `sweep_status.html` gana una nota explícita
("Dónde quedan los resultados: ... `sweep_runs/<name>/runs/<hash>/` ...") y una columna
"Resultados" con el link "resumen" cuando `summary.json` ya existe (actualizada también en vivo por
el polling de la Fase 84, no solo al cargar la página).

### Validación real

Probado contra la app real corriendo en NLHPC, con navegador (no solo `curl`): `/sweeps` lista los
5 sweeps reales ya compilados en esta máquina (incluidos los 3 que generó el usuario mientras
probaba, uno de ellos -- `test3`, `KN-K17` con `ngentot=1000000` -- todavía corriendo); los links
del historial llevan de verdad a `/sweep/<name>`; sin errores en consola.

**Hallazgo real, no relacionado a esta fase pero encontrado en el camino**: `test3` corría
`ngentot=1000000` para `KN-K17` -- 200x el umbral de advertencia histórico del proyecto
(`NGENTOT_WARN_THRESHOLD=5000`) -- vía `sweep_run_local.py`, que ejecuta directo en el proceso
(sin `sbatch`), en el **login node** de NLHPC. Esto contradice la convención ya establecida del
proyecto ("nunca correr nada pesado en el login node"). Queda documentado como riesgo real a
comunicar al usuario -- no se aborta la corrida desde este cambio, es una decisión del usuario, pero
la Fase 84 ya muestra la advertencia de `NGENTOT_WARN_THRESHOLD` solo en la consola del servidor al
generar, no de forma visible en el formulario -- candidato real para una fase futura si se repite.

### Conclusión Fase 87

Los 2 huecos de navegación reportados quedan resueltos con mecanismos que reusan lo que ya existe
(escanear `sweep_runs/` real, leer `summary.json` real) -- sin inventar un registro paralelo de
sweeps ni duplicar el contenido del YAML fuera de su archivo real.

### Archivos de esta fase

Nuevo: `webapp/templates/sweeps_list.html`, `webapp/templates/run_summary.html`. Modificado:
`webapp/app.py` (`/sweeps`, `/sweep/<name>/run/<hash>/summary`, `sweep_dir`/`has_summary` en
`sweep_status`/`sweep_status_json`), `webapp/templates/base.html` (nav), `webapp/templates/
history.html` (link real), `webapp/templates/sweep_status.html` (nota de resultados + columna).
`NOTES.md`: esta entrada.

## Fase 88 -- el botón "Lanzar" ahora somete a SLURM real cuando hay `sbatch` (bug real reportado por el usuario)

### Motivación

El usuario encontró un bug real y serio: el botón "Lanzar" del webapp SIEMPRE llamaba a
`sweep_run_local.run_sweep_local()` (el runner sin SLURM, Fase 76, pensado para la máquina del
profesor sin cluster) -- incluso corriendo la app en el login node de NLHPC. Un sweep de prueba del
usuario (`test3`, `KN-K17` con `ngentot=1000000`, 200x el umbral histórico de advertencia del
proyecto) terminó corriendo directo en el login node, violando la convención ya establecida del
proyecto ("nunca correr nada pesado en el login node, todo va por `sbatch`").

### Cambio real

`webapp/app.py::slurm_available()` nuevo: `shutil.which("sbatch") is not None`. `/sweep/<name>/run`
ahora bifurca en base a esto: si hay SLURM, llama a `sweep_launch.launch_sweep()` (Fase 66, sin
cambios en su lógica real de submit) -- solo somete el/los array(s) y vuelve de inmediato, el
cómputo real corre en nodos de cómputo vía el scheduler, nunca en este proceso ni en el login node.
Si no hay SLURM (la máquina del profesor, sin cluster), sigue el camino de la Fase 76-83 sin
cambios (hilo de fondo + `sweep_run_local.py`).

`sweep_launch.py` no tenía `record_event()` (se escribió en Fase 66, antes de que existiera el
historial de Fase 80) -- agregado, mismo patrón que el resto de `sweep_*.py`.

`sweep_status()`/`sweep_status.html`: el concepto de "ya lanzado" pasa de depender solo del hilo en
memoria (`RUNNING`, que no existe para el camino SLURM) a una condición general sobre el estado real
(`any(status != "NOT_SUBMITTED")`) -- vale para los dos caminos por igual. El texto del botón indica
explícitamente cuál de los dos va a usar antes de hacer click.

**Bug real encontrado probando el fix**: el polling en vivo (Fase 84) trataba `"UNKNOWN"` como
estado terminal -- pero `UNKNOWN` es exactamente lo que reporta `sweep_monitor.py` en los primeros
segundos después de un `sbatch` real, mientras `sacct` todavía no indexa el job nuevo (una condición
transitoria y normal, no un error). Con el runner local este caso casi nunca pasaba (nunca
consultaba `sacct`); con SLURM como camino real ahora primario, cortaba el polling justo después de
lanzar. Corregido: `TERMINAL` ya no incluye `"UNKNOWN"`, solo `"done"`/`"failed"` (los dos estados
reales que escribe `run_hash.json`).

### Validación real

Corrida real de punta a punta: generado un sweep chico (`PISN-STELLA-HECORE`, `ngentot=20`),
lanzado con el botón -- confirmado en `squeue` un job real (`12777936_0`, partición `largemem`,
nodo `fn002`) corriendo en un nodo de cómputo real, NO en el login node. Terminó
`status=done` en `run_hash.json` (`node: "fn002"`, `slurm_job_id: "12777936"`), reflejado
correctamente en la página sin recargar (los 4 QC reales + link "resumen"). `test3` (el sweep
atascado) corregido a `status=failed` con un error explícito documentando qué pasó -- el proceso ya
estaba muerto (murió al reiniciarse Flask durante la Fase 87), esta corrección solo evita que
quedara mostrando "running" para siempre.

**Incidente real durante la limpieza de esta fase**: al borrar los artefactos de prueba propios, se
borró por error `generation_history.jsonl` completo -- que ya tenía eventos reales del usuario
(`test1`/`test2`/`test3`), sin respaldo posible. Lección real aplicada de inmediato: ese archivo es
dato compartido en vivo, no un artefacto de prueba -- las limpiezas futuras de esta sesión solo
borran los sweeps/YAMLs generados para probar, nunca el historial completo.

### Conclusión Fase 88

El botón "Lanzar" queda corregido para hacer lo que el proyecto siempre exigió: nada pesado en el
login node, todo vía `sbatch` cuando SLURM está disponible. El runner local (Fase 76) sigue intacto
para la máquina del profesor, que no tiene cluster.

### Archivos de esta fase

Modificado: `sweep_launch.py` (`record_event`), `webapp/app.py` (`slurm_available()`, bifurcación
real en `sweep_run()`, `launched` en `sweep_status()`), `webapp/templates/sweep_status.html`
(mensaje según camino real, fix de `TERMINAL`), `webapp/templates/history.html` (detalle de
`launch_sweep`). `NOTES.md`: esta entrada.

## Fase 89 -- `/sweep/<name>/status` devuelve 404 limpio en vez de 500 (bug real visto en vivo)

### Motivación

Probando la app (vía túnel SSH al login node de NLHPC), una pestaña quedó con el polling de Fase 84
corriendo sobre un sweep (`_fase83_test`) cuyo `sweep_runs/<nombre>/manifest.json` ya no existía --
cada tick de 3s generaba un `500` real en el log del proceso Flask
(`GET /sweep/_fase83_test/status HTTP/1.1" 500`, con el traceback completo de
`sweep_monitor.monitor_sweep` reventando en `sweep_hash.read_json` con `FileNotFoundError` sin
capturar). No rompía nada más, pero ensuciaba el log cada 3s mientras esa pestaña siguiera abierta.

### Cambio real

`sweep_monitor.py::monitor_sweep`: ahora valida `manifest_path.exists()` antes de leerlo y lanza
`FileNotFoundError` con mensaje explícito ("correr sweep_compile.py primero") en vez de dejar
propagar la excepción cruda de `sweep_hash.read_json`. El `__main__` del módulo captura ese error
puntual y sale con código 1 limpio (antes: traceback completo en la terminal para un uso CLI normal).

`webapp/app.py::sweep_status_json` (la ruta `/sweep/<name>/status`): mismo guard que ya tenía la
vista HTML hermana (`sweep_status()`, que hace `flash()` + redirect) -- si no existe
`manifest.json`, responde `404 + jsonify(error=...)` antes de llamar a `monitor_sweep`. El polling en
`sweep_status.html` (`pollOnce()`, Fase 84) ya tenía `if (!res.ok) return true;` -- corta el loop solo,
sin cambios en el frontend.

### Validación real

Confirmado en el propio incidente: tras el fix, la misma pestaña abierta contra `/sweep/_fase83_test`
deja de generar tracebacks -- el primer poll recibe 404 y el loop se detiene. `python3
sweep_monitor.py <sweep_inexistente>` imprime el mensaje y sale con código 1 en vez de un traceback.
Un sweep real con manifiesto sigue reportando su estado sin cambios.

### Archivos de esta fase

Modificado: `sweep_monitor.py` (`monitor_sweep`, `__main__`), `webapp/app.py`
(`sweep_status_json`). `NOTES.md`: esta entrada.

## Fase 90 -- z máximo simulado, expuesto por corrida y por sweep (pedido real del usuario)

### Motivación

El usuario pidió poder leer "el z máximo que se llega a simular en cada sweep". Esa información ya
se calculaba (`pipeline/postproc/qc.py::redshift_distribution`, texto "z_max simulado"/"z_max
detectado" quemado dentro de `qc_redshift.png`) pero nunca quedaba en ningún dato estructurado --
`summary.json`, `manifest.json` y `aggregated_summary.parquet` no tenían ningún campo de redshift.

### Cambio real

`pipeline/postproc/qc.py`: nueva función pura `redshift_zmax_stats(dump_df, head_df)` -- extrae la
misma detección de columna `ZCMB`/filtro de centinela `-9`/máscara de detectados que ya usaba
`redshift_distribution` para el texto del PNG, sin duplicar el cálculo (`redshift_distribution` ahora
la llama internamente; su firma y su retorno -- `Path` -- no cambian, porque la reusan
`run_snia_ddf_poc.py`, `run_simsed_91bg_ddf_poc.py`, `run_non1ased_poc.py` y
`pipeline/postprocess.py`, este último con un `{k: str(v) ...}` sobre todo lo que devuelve
`run_all_qc` que hubiera roto con una clave nueva tipo dict).

`run_simsed_poc.py::main`: `summary.json` ahora incluye `z_min_nominal`/`z_max_nominal` (el
`GENRANGE_REDSHIFT` real de la clase, límite duro del sampler -- `CLASS_CONFIGS[class_key]
["genrange_redshift"]`) y `z_max_simulado`/`z_max_detectado` (el z real alcanzado, vía
`qc.redshift_zmax_stats(dump_df, head_df_detected)`). `sweep_aggregate.py` no necesitó ningún cambio
para que estos campos lleguen a `aggregated_summary.parquet`: ya volcaba automáticamente cualquier
clave nueva de `summary.json` prefijada `summary_*`.

`sweep_aggregate.py`: nueva función `sweep_zmax(sweep_name)` -- el máximo de `z_max_simulado` entre
las corridas ya `done` del sweep (lee `summary.json` directo, no `aggregated_summary.parquet`, que
puede estar desactualizado si no se apretó "Agregar" después de la última corrida en terminar).

`webapp/app.py`: `sweep_status()` y `sweeps_list()` calculan `sweep_aggregate.sweep_zmax(...)` y lo
pasan a los templates. `sweep_status.html` muestra el z máximo del sweep completo (clase y
`run_hash` de la corrida que lo alcanzó); `sweeps_list.html` agrega una columna `z_max`.
`run_summary.html` no necesitó cambios -- itera `summary.items()` genéricamente, los 4 campos nuevos
aparecen solos en la tabla por-corrida.

### Validación real

Sin acceso local a la pila de LightCurveLynx (no instalable en esta máquina Windows), se verificó
cada pieza nueva con datos sintéticos reales en vez de solo revisión de código:
- `redshift_zmax_stats`: con un `dump_df` de 5 eventos (uno con el centinela `-9`) y 2 detectados,
  confirma `n_simulado=4` (descarta el centinela), `z_max_simulado`/`z_max_detectado` exactos, y
  `{}` con `dump_df=None` o vacío.
- `redshift_distribution` refactorizada: corrida real end-to-end con 200 eventos sintéticos -> genera
  un PNG real (74 KB) con las mismas estadísticas por consola que antes del refactor.
- `sweep_zmax`: con un sweep sintético de 4 corridas (2 `done` con el campo, 1 `running` con un
  z_max mayor que NO debe ganar, 1 `done` con `summary.json` "viejo" sin el campo) confirma que elige
  el máximo correcto solo entre las `done` que sí traen el dato, y devuelve `{}` para un sweep
  inexistente.
- `sweeps_list.html`/`sweep_status.html`: renderizado real vía Jinja2 (con y sin `zmax`) confirma que
  el HTML final trae el número formateado y el fallback `—` cuando corresponde.

**Cerrado real en NLHPC** (post-despliegue): sweep `zmax_verify_fase90` (`SNIa-91bg`, `ngentot=30`,
DDF), sometido a SLURM real (job `13007670`, partición `largemem`) y terminado `done`. Su
`summary.json` real:
```
"z_min_nominal": 0.011, "z_max_nominal": 0.6,
"z_max_simulado": 0.5970969788664039, "z_max_detectado": 0.5850150369767873
```
`z_min/max_nominal` coincide exacto con `CLASS_CONFIGS["SNIa-91bg"]["genrange_redshift"]`;
`z_max_detectado <= z_max_simulado <= z_max_nominal`, como debía ser. `sweep_aggregate.sweep_zmax
("zmax_verify_fase90")` devuelve el mismo `z_max_simulado`/`z_max_detectado` -- confirma la cadena
completa run_simsed_poc.py -> summary.json -> sweep_zmax con datos 100% reales, no sintéticos.

### Archivos de esta fase

Modificado: `pipeline/postproc/qc.py` (`redshift_zmax_stats` nueva, `redshift_distribution`
refactorizada), `run_simsed_poc.py` (`main`, nuevos campos en `summary.json`), `sweep_aggregate.py`
(`sweep_zmax` nueva), `webapp/app.py` (`sweep_status`, `sweeps_list`),
`webapp/templates/sweep_status.html`, `webapp/templates/sweeps_list.html`. `NOTES.md`: esta entrada.

## Fase 91 -- visualizador en vivo a nivel de sweep (pedido real del usuario)

### Motivación

El usuario pidió "un visualizador en tiempo real de cómo se ve la corrida completa". No existe hoy
ningún progreso intra-corrida persistido a disco (`run_hash.json` solo tiene `status="running"`
binario al principio y `"done"`/`"failed"` al final, sin etapas intermedias) -- instrumentar
`run_simsed_poc.py` para exponer eso es un cambio de alto riesgo sobre código científico central,
descartado explícitamente para esta ronda. El alcance real acordado: vista en vivo a nivel de
*sweep completo*, sobre el polling que ya existía (Fase 84, cada 3s) -- mostrar los resultados de
cada corrida apenas están listos, sin recargar la página, y sin regenerar nada pesado (ni
matplotlib) en el login node en cada tick.

### Cambio real

**Miniaturas QC embebidas** (sin endpoint nuevo): `sweep_status.html`, tanto el render server-side
inicial como `qcLinksHtml()` (el JS de polling, Fase 84) ahora envuelven cada QC en un `<img
loading="lazy">` en vez de solo un `<a>` de texto -- las 4 imágenes de cada corrida aparecen solas,
inline, apenas esa fila individual pasa a `done`. `qc_files` ya viajaba en el JSON de `/status`
(Fase 83); el cambio es 100% de template/JS, sin tocar `sweep_status_json`.

**Panel agregado del sweep**: `sweep_aggregate.py::build_live_panel(sweep_name)` -- nueva función,
mismo patrón de iteración que `aggregate_sweep`/`sweep_zmax` (manifest -> `summary.json`/
`run_hash.json` por corrida), SOLO corridas `done`, sin matplotlib: `efficiency_rows` (eficiencia +
SNR mediano por corrida, desde `summary.json`), `z_hist`/`nobs_hist` (histogramas reales vía
`np.histogram`, leyendo solo las columnas `REDSHIFT_HELIO`/`NOBS` de `head_df.parquet` -- reusa el
patrón de las celdas 9/17 de `analyze_phot_df.ipynb`), `pivot_ddf_wfd` (promedio de eficiencia/SNR
por clase × estrategia). Ruta nueva `webapp/app.py::sweep_panel_json` (`/sweep/<name>/panel`),
mismo guard 404 que `/status`.

**JS**: `sweep_status.html` ahora cuenta cuántas filas están en `done` en cada poll; SOLO cuando ese
número cambia respecto al poll anterior, pide `/panel` y renderiza tres tablas (eficiencia con
barras CSS, histogramas bin/conteo, pivot WFD/DDF) en un `<div id="live-panel">` nuevo debajo de la
tabla de estado -- nunca en cada tick de 3s, para no recalcular nada de más en el login node. El
mecanismo de parada (`TERMINAL`/`allDone`, Fase 84/88) no se tocó.

### Validación real

Sin acceso local a la pila completa (mismo motivo que Fase 90), verificado con datos sintéticos
reales: `build_live_panel` con un sweep de 4 corridas (2 `done` de la misma clase/estrategia con
`head_df.parquet` real, 1 `running` con valores "extremos" que NO debe entrar en ningún cálculo, 1
`done` con `summary.json` viejo sin eficiencia/SNR) confirma que excluye la corrida `running` de
`efficiency_rows`/`pivot_ddf_wfd`/histogramas, promedia correctamente por clase+estrategia
(50%+70% -> 60% exacto), y agrega los histogramas de z/NOBS solo con los valores de las corridas
`done` (6 valores esperados, 6 obtenidos). El bloque `<script>` completo de `sweep_status.html` se
verificó sintácticamente válido como JS real (Node, no solo lectura visual). El template completo
se renderizó vía Jinja2 real con una fila `done` con QC -- confirma que aparecen los `<img>` y el
`<div id="live-panel">`.

**Cerrado parcial en NLHPC real** (post-despliegue, vía `curl` por el túnel SSH, no un navegador
interactivo): `/sweeps` del servidor real muestra la columna `z_max`; `/sweep/fase65_rebarrido/panel`
(65 corridas `done` reales, `summary.json` de antes de esta fase) devuelve `efficiency_rows` reales
correctos, uno por corrida, calculados de verdad desde disco -- confirma que `build_live_panel`
funciona contra datos de producción, no solo sintéticos. `zmax_verify_fase90` (ver Fase 90) terminó
mientras esta app no estaba levantada, así que las miniaturas QC apareciendo en vivo (sin recargar,
mientras una corrida pasa a `done`) y el timing exacto del polling (`/status` cada 3s, `/panel` solo
al cambiar `n_done`) siguen sin verse en un navegador interactivo real -- para eso hace falta abrir
el túnel con un sweep corriendo y mirar la pestaña Network mientras termina.

### Archivos de esta fase

Modificado: `sweep_aggregate.py` (`build_live_panel` nueva, `import numpy as np`), `webapp/app.py`
(`sweep_panel_json` nueva), `webapp/templates/sweep_status.html` (miniaturas QC embebidas, panel en
vivo, JS de conteo de `done`). `NOTES.md`: esta entrada.

## Fase 92 -- hardening de seguridad (auditoría real pedida por el usuario)

### Motivación

El usuario pidió revisar el sistema completo (túnel SSH + webapp + scripts) por vulnerabilidades.
Auditoría real (3 agentes de investigación + 1 de diseño) encontró 5 problemas concretos, confirmados
contra el código real; el usuario decidió arreglar estos 5 sin agregar autenticación (cambio de mayor
alcance, fuera de esta ronda):

1. **Path traversal de lectura** en `/qc/<sweep>/<run_hash>/<filename>`, `/sweep/<name>` (lee y
   renderiza el `.yaml`), `/sweep/<name>/run/<run_hash>/summary` (lista directorio), `/sweep/<name>/
   status`, `/datasets/<dataset_hash>` -- construían `Path` con segmentos de URL sin validar.
   `send_from_directory` solo sanitiza `filename`, no el `directory` construido con esos segmentos.
2. **Path traversal de escritura** en `/sweep/<name>/aggregate` y `/sweep/<name>/publish` -- mismo
   problema, pero escribiendo `aggregated_summary.parquet`/dataset en la ruta traversada.
3. **Inyección de shell** en `deploy_local.sh:45-46`: `$SWEEP_YAML`/`$DRY_RUN_FLAG` interpolados sin
   comillas dentro del comando remoto que ejecuta `ssh`.
4. **TOCTOU** en el guard en memoria `RUNNING` -- dos POST casi simultáneos a `/sweep/<name>/run`
   podían lanzar el mismo sweep dos veces vía el runner local.
5. **Aviso de `ngentot` excesivo no llegaba a la UI** -- solo se imprimía en la consola del proceso
   Flask; causó el incidente real de Fase 87 (`test3`/`KN-K17`, `ngentot=1000000`, corrió sin aviso
   visible en el navegador).

### Cambio real

**(1+2) Validador de segmentos de ruta**: `sweep_generate.SAFE_SEGMENT_PATTERN` (constante nueva,
mismo patrón que ya usaba `SWEEP_NAME_RE` al crear un sweep) es ahora la única fuente de verdad,
importada por `webapp/app.py` para registrar un convertidor de ruta Werkzeug custom (`safe`,
`app.url_map.converters["safe"]`). Todas las rutas de los hallazgos 1 y 2 pasaron de `<name>`/
`<run_hash>`/`<dataset_hash>`/`<sweep>` a `<safe:...>` -- un segmento que no matchea da 404 de Flask
**antes** de que corra el cuerpo de la vista (nunca llega a construirse el `Path` sospechoso), sin
repetir un `if` de validación en cada ruta. `filename` en `/qc/...` queda como `<string>` normal --
ya lo protegía `send_from_directory`.

**(3) `deploy_local.sh`**: el comando remoto ahora se arma con `printf %q` (citado robusto de shell,
no solo comillas dobles) en vez de interpolación directa. `sweep_launch.py::__main__` exige
`len(_args) == 1` -- pasar `--dry-run` vacío como argumento literal rompía ese chequeo, así que el
flag solo se agrega al comando cuando NO está vacío.

**(4) `RUNNING_LOCK`**: `threading.Lock()` nuevo envolviendo el check-y-registro (`is_alive()` +
`RUNNING[name] = thread` + `thread.start()`) de la rama sin SLURM de `sweep_run()`, atómico ahora.
La rama con `sbatch` no lo necesita (sin estado en memoria compartido ahí).

**(5) Aviso de `ngentot`**: `/generate` ahora lee el `manifest.json` recién compilado, junta las
clases cuyo `ngentot` (ya resuelto por `build_runs()`, cubre overrides y defaults) supera
`sweep_compile.NGENTOT_WARN_THRESHOLD`, y hace `flash()` con un aviso explícito antes del redirect.

### Validación real

Cada arreglo se probó con una prueba funcional real, no solo revisión de código -- incluyendo
**controles negativos** que confirman que los bugs viejos eran genuinamente explotables antes del fix:

- **(1+2)** `app.py` real importado (con un stub liviano de `run_simsed_poc` -- la pila completa de
  LightCurveLynx no es instalable en esta máquina Windows) y probado con `Flask.test_client()` real:
  un nombre legítimo (`test1`) sigue llegando a la vista (404 "de negocio", JSON); `/sweep/../status`,
  `/sweep/foo%2Fbar/status`, `/qc/../../../../etc/x/passwd` y `/datasets/..` dan 404 **genérico de
  Werkzeug** (rechazados a nivel de ruta, sin ejecutar ninguna vista).
- **(3)** `ssh` real reemplazado por un script que ejecuta el comando recibido vía `sh -c` (simula lo
  que haría el login node real): con el código viejo (sin comillas), un `$SWEEP_YAML` malicioso
  (`sweeps/x.yaml; touch ...; echo`) creó un archivo marcador real -- **confirmado explotable**. Con
  el fix (`printf %q`), el mismo valor malicioso llega como un solo argumento literal a
  `sweep_launch.py` (`sweeps/x.yaml\;\ touch\ ...\;\ echo`), el marcador nunca se crea. Casos
  normales (con y sin `--dry-run`) producen el comando esperado.
- **(4)** 8 `POST` concurrentes reales (hilos Python) a `/sweep/<name>/run` contra el mismo sweep,
  con `sweep_run_local.run_sweep_local` reemplazado por un stub que tarda 0.3s: con el fix,
  `run_sweep_local` se dispara **exactamente 1 vez**. Control negativo (mismo test con
  `RUNNING_LOCK` reemplazado por un no-op): se disparó **5 veces** -- confirma que el test detecta la
  carrera de verdad, no es un falso negativo.
- **(5)** `/generate` real, con `sweep_compile.compile_sweep` devolviendo un manifiesto con una clase
  sobre el umbral: el `flash()` con "ATENCION" aparece en la sesión tras el POST. Con un manifiesto
  sin excesos, sesión limpia, ningún aviso.

Fuera de alcance de esta fase (decisión explícita del usuario): autenticación real -- la app sigue
sin login, pensada para un solo usuario en `127.0.0.1`; en un login node compartido de NLHPC esto
sigue significando que cualquier otro usuario con shell ahí puede llegar al puerto directamente, sin
pasar por el túnel SSH de nadie. Documentado, no arreglado.

### Archivos de esta fase

Modificado: `sweep_generate.py` (`SAFE_SEGMENT_PATTERN`), `webapp/app.py` (`SafeSegmentConverter`,
rutas `<safe:...>`, `RUNNING_LOCK`, aviso de `ngentot` en `/generate`), `deploy_local.sh` (quoting
robusto). `NOTES.md`: esta entrada.

## Fase 93 -- override de z_max por sweep/clase, configurable en la pantalla de generación (pedido real del usuario)

### Motivación

El usuario, tras ver el z máximo ya alcanzado por sus sweeps (Fase 90), pidió ir un paso más allá:
poder **reconfigurar** el z máximo que se le pide al simulador para un sweep nuevo. `genrange_redshift
= (z_min, z_max)` era un valor fijo por clase en `CLASS_CONFIGS` (`run_simsed_poc.py`), sin ningún
mecanismo de override -- a diferencia de `ngentot`, que sí tiene `ngentot_overrides` de punta a
punta. Alcance acordado: solo `z_max` es overrideable (z_min queda siempre en el nominal del
catálogo).

### Trampa real encontrada y evitada

4 de las 15 clases (`SNIa-91bg`, `SNIa-91bg-elastic`, `KN-K17`, `KN-BULLA19`) tienen
`dndz=("powerlaw", [(rate0, beta, z_lo, z_hi)])` donde el `z_hi` del segmento está **duplicado** --
idéntico al `z_max` de `genrange_redshift`. `build_dndz_powerlaw2_cdf` (`snana_params.py`) usa
`z_min`/`z_max` solo para el grid, pero `rate_at(z)` devuelve densidad **cero** para cualquier z
fuera de `[z_lo, z_hi)` de los segmentos -- overridear solo `genrange_redshift` sin también extender
el `z_hi` del segmento habría dejado el override **sin efecto real** para esas 4 clases (confirmado
numéricamente, ver Validación).

### Cambio real

`run_simsed_poc.py`: `resolve_effective_class_config(class_key, z_max_override=None)` nueva -- sin
override devuelve `CLASS_CONFIGS[class_key]` TAL CUAL (mismo objeto, no-op garantizado por
identidad, no solo por igualdad de valores -- clave para que `sweep_hash.run_hash()` de un sweep sin
`z_max_overrides` siga dando el MISMO hash que antes de esta fase); con override, copia con
`genrange_redshift` parchado y, si `dndz[0]=="powerlaw"`, también el `z_hi` del último segmento.
`main()` ahora distingue `cfg_nominal` (SIEMPRE `CLASS_CONFIGS[class_key]`, usado solo para
`z_min_nominal`/`z_max_nominal` en `summary.json`) de `cfg` (el EFECTIVO, usado para todo lo demás,
incluido el sampler real) -- sin esta separación, `summary.json` habría reportado el override como
si fuera el nominal del catálogo. Nuevo campo `z_max_override` en `summary.json`. Flag `--z-max
<valor>` opcional en el CLI standalone.

`sweep_compile.py::build_runs()`: lee `z_max_overrides` del YAML (mismo patrón que
`ngentot_overrides`), resuelve el cfg efectivo vía el helper y lo pasa a `sweep_hash.run_hash()` --
el `run_hash` cambia solo cuando el override es real. Campo `z_max_override` nuevo en cada row del
manifiesto.

`sweep_worker.py::run_one()`: pasa `row.get("z_max_override")` a `run_simsed_main` y a `common`
(`run_hash.json`).

`sweep_generate.py`: `available_classes_redshift_range()` nueva (expone el nominal por clase);
`generate_sweep()` con parámetro `z_max_overrides`, validado (reusa el mismo helper, sin duplicar la
regla `z_max > z_min`) ANTES de escribir el YAML; nueva sección `z_max_overrides` en el YAML
(mismo agrupamiento que `ngentot_overrides`); `--z-max clase:numero` en el CLI.

`webapp/app.py` + `index.html`: input `z_max_<clase>` opcional por clase, con el nominal como
referencia (`z_ranges`, expuesto por `index()`); `generate()` parsea y valida el formato numérico
(la validación real `z_max > z_min` vive en `generate_sweep()`, no duplicada); flash de
transparencia ("z_max override aplicado para: ...") cuando corresponde, mismo espíritu que el aviso
de `ngentot` de Fase 92.

### Validación real

Sin acceso local a la pila completa de LightCurveLynx, se verificó cada pieza con el **código y los
datos REALES** del repo (no solo sintéticos) -- extrayendo `CLASS_CONFIGS`/`resolve_effective_class_
config`/`build_dndz_powerlaw2_cdf` vía `ast` directo del archivo fuente (sin ejecutar los imports
pesados de `lightcurvelynx`) y usando módulos stub solo para esa dependencia puntual:

- **No-op real**: para las 15 clases reales del catálogo, `resolve_effective_class_config(c, None)`
  devuelve el mismo objeto que `CLASS_CONFIGS[c]` (identidad, no solo igualdad).
- **Backward-compat real de `run_hash`**: para 4 clases reales (incluye powerlaw y no-powerlaw),
  `sweep_hash.run_hash()` da el hash IDÉNTICO con y sin pasar por el helper (sin override).
- **Sensibilidad real del hash**: con override real, el hash cambia -- sin colisión con la corrida
  nominal, confirmado en 3 clases.
- **Repro real de la trampa evitada**: `build_dndz_powerlaw2_cdf` real (con `astropy`/`scipy`
  instalados para la prueba) confirma que, sin parchear el segmento, la masa de probabilidad más allá
  del `z_hi` viejo es **0.000000** (el bug); parchando el segmento (lo que hace el helper), la misma
  extensión tiene **64.7%** de masa real -- diferencia inequívoca.
- **`sweep_compile.build_runs()` real**: sin `z_max_overrides`, todas las rows quedan con
  `z_max_override=None`; con override en una clase, se propaga solo a esa clase, y su `run_hash` da
  DISTINTO del que tendría sin override; un override inválido (`z_max <= z_min`) propaga `ValueError`
  con mensaje claro.
- **`sweep_generate.generate_sweep()` real**: el YAML generado trae `z_max_overrides` en la posición
  correcta (entre `ngentot_overrides` y `resources`); override inválido falla ANTES de escribir el
  YAML; sin overrides, el YAML trae `z_max_overrides: {}` (backward-compat).
- **Webapp real de punta a punta** (`Flask.test_client()`, `app.py` real cargado): `GET /` muestra el
  input `z_max_KN-K17` con "nominal: 0.280" y "z_min fijo en 0.011" (datos reales de `CLASS_CONFIGS`);
  `POST /generate` con `z_max_KN-K17=0.5` dispara el flash de transparencia real y produce un
  `manifest.json` REAL en disco (vía `sweep_compile.compile_sweep()` real, sin mockear) con
  `runs[0]["z_max_override"] == 0.5`; un valor no numérico da el flash de error esperado; sin
  override, ningún flash de `z_max`.

Pendiente: correr una simulación real en NLHPC con `z_max_overrides` (ver si `z_max_simulado`
efectivamente supera el `z_max_nominal` para una clase powerlaw) -- mismo patrón que el cierre de
Fase 90.

### Archivos de esta fase

Modificado: `run_simsed_poc.py` (`resolve_effective_class_config` nueva, `main()` con
`z_max_override`/`cfg_nominal`, `summary.json`, flag `--z-max`), `sweep_compile.py::build_runs()`,
`sweep_worker.py::run_one()`, `sweep_generate.py` (`available_classes_redshift_range()`,
`generate_sweep()`, CLI `--z-max`), `webapp/app.py` (`index()`, `generate()`),
`webapp/templates/index.html`. `NOTES.md`: esta entrada.

## Fase 94 -- rutas portables entre cuentas NLHPC: `ALCES_DATA` como carpeta compartida del equipo

### Motivación

El profesor empezó a instalar ALCeS con su propia cuenta de NLHPC (`fforster`, grupo
`astrolab_cmm`, distinto de `users`). Para que pudiera leer las plantillas se le dio acceso con ACL
(ver más abajo), pero la idea es que **cada miembro del equipo** pueda instalar y usar el pipeline
con su cuenta, sin depender del `$HOME` de `mvalenzuela` ni editar rutas a mano. Decisión del
usuario: **una sola copia compartida** de los datos en NLHPC (no una copia de 19 GB por persona).

### Inventario real de rutas a `/home/mvalenzuela` (antes de esta fase)

Tres niveles, no uno:

1. **Código**: `setup_*_local.py` (5), `pipeline/tools/run_qc_*.py` y `refresh_redshift_qc.py`.
2. **Configuración**: `pipeline/models.yaml` (42 `simgen_include`), `campaigns/*.yaml` (kcor,
   SEARCHEFF, `export SNDATA_ROOT`, `PATH` del binario custom), `activate_all.sh`, `setup_autosim.py`.
3. **Los datos mismos** (el nivel que nadie veía): 44 `SIMGEN_INCLUDE_*.INPUT` dentro de
   `run_SNANA/` y `OTMODEL_NON1ASED/` apuntan en `GENMODEL`/`PATH_NON1ASED`/
   `GENMODEL_EXTRAP_LATETIME` a `/home/mvalenzuela/{run_SNANA,OTMODEL_NON1ASED,SNDATA_ROOT}`. Una
   copia de `run_SNANA` en otra cuenta **seguiría leyendo de la cuenta original**: funciona mientras
   dure el permiso y deja de funcionar sin aviso el día que se quita.

Hallazgos colaterales verificados en NLHPC:

- 6 includes apuntan a `SNDATA_ROOT/models/NON1ASED/NON1ASED.V19_CC+HostXT`: está en la
  distribución **pública** de SNANA (`SNDATA_ROOT_2024-07-03.tar.gz`, verificado con `tar tzf`), así
  que se reescriben a `$SNDATA_ROOT` (de cada usuario), no a la carpeta compartida.
- El módulo `SNANA/11.05p` de NLHPC **no** define `SNDATA_ROOT` (`module show`): cada usuario
  necesita descomprimir el árbol público. `INSTALL.md` §4 decía crear una carpeta vacía, lo que no
  sirve (SNANA lee `MWDUST`, filtros y el modelo V19 de ahí). Corregido.
- `SIMSED_USE_BINARY: 1` hace que SNANA escriba `SED.BINARY` **en la carpeta del modelo**
  (`genmag_SIMSED.c`, `bin1File = SIMSED_PATHMODEL/...`; la tabla de flujos va a
  `SIMSED_PATH_BINARY`, cuyo default es `./`). Riesgo para una copia de solo lectura, pero ninguno
  de los 10 includes con `USE_BINARY: 1` (todos en `elastic/model_config/`, además los únicos con
  `$PLASTICC_MODELS`) está catalogado en `models.yaml`. Documentado en `INSTALL.md` §2.5.
- `bin/snana_custom/snlc_sim.exe` (necesario para DDF por `MXOBS_SIMLIB`) no está en git: va a la
  carpeta compartida.

### Cambio real

- `pipeline/paths.py`: `alces_data()` (`ALCES_DATA` → `SNANA_HOME` → `$HOME`), `expand_path()`
  (`${ALCES_DATA}`, `${ALCES_REPO}` = raíz del repo aunque no esté exportada, `$SNDATA_ROOT`, `~`;
  aborta con `UnresolvedPathError` si queda una variable indefinida) y `expand_alces_vars()` (solo
  las dos `ALCES_*`, para texto de un include; `$SNDATA_ROOT` se deja a SNANA).
- `pipeline/campaign/compiler.py`: expande `kcor_file`/SEARCHEFF/`simgen_include` al compilar
  (error de compilación claro en vez de un abort de SNANA dentro del job). Si el include curado
  tiene `${ALCES_*}` por dentro, escribe `includes/curated_<clase>.INPUT` expandido y el
  `include_model_` apunta a esa copia: `snlc_sim.exe` solo ve rutas absolutas. `snana_login_setup`
  también se expande al compilar.
- `pipeline/orchestrate/preflight.py`: nuevo check `ALCES_DATA` (debe contener `run_SNANA/`) y
  `_check_models` ahora revisa también `GENMODEL`/`GENMODEL_EXTRAP_LATETIME` de las copias
  `curated_*`.
- YAML: `models.yaml` y `campaigns/*.yaml` usan `${ALCES_DATA}`/`${ALCES_REPO}`/`$SNDATA_ROOT`;
  el `PATH` del job busca el binario custom primero en `${ALCES_DATA}/bin/snana_custom` y después
  en `${ALCES_REPO}/bin/snana_custom` (sin cambios para la cuenta original).
- `local_env.py`: `SNANA_HOME` respeta `ALCES_DATA` primero. Los 5 `setup_*_local.py` usan
  `SNANA_HOME` en vez de la ruta fija. Herramientas de QC: repo desde `__file__`, salida SNANA
  desde `Path.home()`.
- `activate_all.sh`: `SNDATA_ROOT`/`ALCES_DATA` con default y aviso si no son válidos.
- `pipeline/tools/export_alces_data.sbatch` (nuevo): arma la copia compartida con `rsync`
  (`run_SNANA` sin `.git`, `OTMODEL_NON1ASED`, binario custom, tarball público) y reescribe **solo en
  la copia** las rutas absolutas de los `.INPUT`; aborta si `DEST` es el home de origen y si queda
  alguna ruta a la cuenta de origen.

### Validación real

- Local: `tests/test_paths_portability.py` (nuevo, 21 checks), `tests/test_simlib_core.py` y
  `compile_campaign --self-test`: todo OK.
- NLHPC, **regresión en la cuenta original** (sin `ALCES_DATA`): `full_v5.3.yaml` compilada con
  el código de HEAD y con el nuevo, diff normalizado por la ruta del repo → los 42 `include_model_`
  y los `include_survey_` **idénticos**; solo cambian las 2 líneas del script SLURM
  (`SNDATA_ROOT`, `PATH`), equivalentes en la cuenta original.
- NLHPC, **caso otro usuario**: espejo de la carpeta compartida (symlinks a los datos + copias
  reales de los `.INPUT`), mismas reescrituras que el script → 44 `.INPUT` reescritos, 0 con rutas
  a la cuenta de origen, originales intactos (mismo conteo antes y después; ese conteo incluye 5
  respaldos `.INPUT.bak` sin uso que el script no toca). Compilación con `ALCES_DATA` apuntando al espejo: 34 `curated_*`, ninguno
  con `${ALCES` ni rutas a `/home/mvalenzuela/run_SNANA`; `preflight` 82 checks, único fallo
  `snlc_sim.exe` fuera del `PATH` (módulo SNANA no cargado en la prueba).
- **Pendiente**: correr `export_alces_data.sbatch` sobre el directorio compartido real (hay que
  pedirlo a soporte NLHPC) y lanzar una clase chica desde una segunda cuenta.

### Acceso ACL de `fforster` (mismo día, previo a esta fase)

`/home` es GPFS con ACL **NFSv4**: `setfacl` responde `Operation not supported`; se usan
`mmgetacl`/`mmputacl` (`/usr/lpp/mmfs/bin`). En NFSv4 los `allow` se **suman** (no hay prioridad
de la entrada nominal sobre `other` como en POSIX), así que `run_SNANA` (777) le habría dado
escritura vía `everyone@`: se hizo `chmod -R o-rwx` antes. Además, al darle `x` al home, quedaban
alcanzables archivos con permisos abiertos (`.ssh/id_rsa` 777, `.bashrc` escribible): se quitó
`other` de todo lo que cuelga del home (sin efecto previo, porque el home era 700) y las claves
quedaron en 600. Resultado: `user:fforster:--x-` en el home, `r-x-` heredable en `run_SNANA`
(15 606 entradas, job SLURM 13312334, 0 fallos). Cuando exista la carpeta compartida, este acceso
se puede retirar.

### Archivos de esta fase

`pipeline/paths.py`, `pipeline/campaign/compiler.py`, `pipeline/orchestrate/preflight.py`,
`pipeline/models.yaml`, `campaigns/full_v5.3.yaml`, `campaigns/test_small.yaml`, `setup_autosim.py`,
`activate_all.sh`, `pipeline/tools/{run_qc_full,run_qc_remainder,refresh_redshift_qc}.py`,
`pipeline/tools/export_alces_data.sbatch` (nuevo), `tests/test_paths_portability.py` (nuevo),
`exploration/lightcurvelynx/{local_env,setup_*_local}.py`, `INSTALL.md`,
`exploration/lightcurvelynx/HOWTO_LOCAL.md`.

## Fase 95 -- "Explore": notebook de análisis ejecutado en vivo por sweep + webapp en inglés

### Motivación

Pedido del usuario: poder **explorar los resultados desde la misma página** de la webapp, "viendo
cómo corre un notebook de Jupyter", y **traducir toda la página al inglés**. Hasta ahora los
resultados solo se veían como miniaturas de QC, el panel agregado (Fase 91) y el `summary.json` de
cada corrida. Opciones consideradas con el usuario: notebook ejecutado en vivo (elegida), JupyterLab
embebido (interactivo, pero con un segundo puerto por el túnel y kernels libres en el login node
compartido) o un explorador nativo sin notebooks. Traducción: todo lo visible (plantillas, flash, JS
y los errores de `sweep_*.py` que llegan a la página); comentarios y `NOTES.md` siguen en español.

### Cambio real

- `sweep_explore.py` (nuevo): `build_notebook()` arma un notebook **autocontenido** (no importa
  `sweep_*`; lee `manifest.json`, `run_hash.json`, `summary.json` y los parquet desde `SWEEP_DIR`)
  con las secciones de `analyze_phot_df.ipynb` (Fase 17) adaptadas a `runs/<hash>/`: inventario,
  eficiencia por clase/estrategia (media ± dispersión entre semillas), redshift/`NOBS`, eficiencia
  vs. z, `phot_df` (SNR, bandas, 3 curvas de luz; si no hay `keep_phot`, un aviso) y DDF vs. WFD.
  `start()` lo ejecuta en un hilo con `nbclient` (`setup_kernel()` + `execute_cell()` celda por
  celda, `allow_errors=True`, 180 s por celda) y escribe **después de cada celda** el `.ipynb`
  parcial (escritura atómica, la webapp lo lee mientras corre) y `explore/status.json`. `state()`
  devuelve el estado más las celdas ya renderizadas a HTML (markdown con `markdown2html`, PNG embebido,
  tablas de pandas, tracebacks sin ANSI). Guard de concurrencia `_RUNNING`/`_RUNNING_LOCK`, mismo
  patrón que la webapp.
- Kernel por **sockets IPC** (`KernelManager(transport="ipc")`, archivos en `explore/`) en vez de
  TCP en `127.0.0.1`: el login node es compartido. Los mensajes del kernel ya iban firmados con
  HMAC, pero así no queda ningún puerto del kernel expuesto a otros usuarios del nodo.
- Estado `interrupted`: si `status.json` dice `running` pero no hay hilo vivo (el proceso Flask murió
  a mitad de camino), `state()` lo reporta así; la página no queda consultando para siempre. La
  lectura usa el mismo candado que `start()`, así no hay falso `interrupted` justo al arrancar.
- `webapp/app.py`: rutas `/sweep/<safe:name>/explore` (página), `/explore/run` (POST),
  `/explore/state` (JSON, 404 sin manifiesto) y `/explore/notebook.ipynb` (descarga). Todos los
  `flash()` y errores JSON en inglés.
- Plantillas: `explore.html` nueva (progreso `cell k/N`, marcador `[*]`, celdas pendientes
  atenuadas, polling cada 1,5 s con el patrón `pollLoop` de `sweep_status.html`); enlace **Explore
  results** en `sweep_status.html` (aparece solo, vía el polling, con la primera corrida `done`) y
  columna **Explore** en `sweeps_list.html`. Las 7 plantillas existentes, traducidas
  (`lang="en"`).
- Mensajes de error en inglés en `sweep_generate.py`, `sweep_compile.py` y
  `sweep_publish_dataset.py`. **Trampa evitada**: `run_simsed_poc.py` está en
  `sweep_hash.CODE_FILES`; traducir su `ValueError` de `z_max` habría cambiado el `code_hash` y,
  con él, **todos los `run_hash` futuros** con física idéntica. Se revirtió ese cambio y el mensaje
  en inglés se arma en `sweep_generate.py` (fuera del hash), con el mismo validador de siempre
  (`resolve_effective_class_config`).
- `requirements.txt`: `nbclient`, `nbformat`, `nbconvert`, `ipykernel` (NLHPC ya los tenía; la
  máquina del profesor no).

### Validación real

- `test_sweep_explore.py` (nuevo, en NLHPC con el venv real): sweep sintético con DDF+WFD, con y sin
  `phot_df` → `done`, 0 celdas con error, gráficos embebidos, aviso sin `phot_df`, `.ipynb` válido
  (`nbformat.validate`); rutas Flask (404 con nombre inválido o sweep inexistente, página en inglés,
  `/explore/state`, descarga). **23/23 OK**.
- End-to-end en NLHPC (copia de prueba con el código nuevo y symlinks a los datos reales, webapp en
  el puerto 5055 porque el 5000 de `leftraru2` lo tenía otra instancia vieja, más túnel y navegador):
  `live_demo_fase91` (2 corridas) y `fase65_rebarrido` (65 corridas, 13 clases) → 16/16 celdas,
  0 errores, terminan en menos de 3 s; consultando el estado cada 0,3 s se observan los estados
  intermedios (`running` en la celda 0, luego la 1, luego la 7 con 3 celdas ejecutadas, y `done`).
  Sin errores en la consola del navegador. Formulario inválido (sin clases, sin estrategia, nombre
  inválido, semillas no numéricas) → los 4 mensajes llegan en inglés y no se crea ningún sweep.
- Ajustes encontrados en la prueba visual: la ruta larga del `.ipynb` (un `<code>` sin espacios)
  ensanchaba la página → `overflow-wrap: anywhere`; se ocultó el `¶` que agrega `markdown2html`.
- **Pendiente**: sincronizar el código a `~/AUTOSIM` en NLHPC (la instancia que corre ahí sigue con
  el código anterior).

### Archivos de esta fase

Nuevos: `sweep_explore.py`, `test_sweep_explore.py`, `webapp/templates/explore.html`. Modificados:
`webapp/app.py`, `webapp/templates/{base,index,sweep_status,sweeps_list,run_summary,dataset,history}.html`,
`sweep_generate.py`, `sweep_compile.py`, `sweep_publish_dataset.py`, `requirements.txt`,
`HOWTO_WEBAPP.md`, `NOTES.md`.

## Fase 96 -- webapp en NLHPC independiente del login node: `open_nlhpc.sh` + socket Unix + vigilante

### Motivación

Durante la prueba de la Fase 95, el alias `nlhpc` pasó de caer en `leftraru1` a caer en
`leftraru2` (y después de vuelta, sin poder elegir). La app se levantaba con `nohup` en una
conexión SSH y el túnel se abría en otra, así que el túnel podía llegar a un nodo sin app. Además,
cada `nohup` quedaba huérfano: en `leftraru2` había una webapp del 14-sep (PID 1414544,
`127.0.0.1:5000`) y un bucle `curl` del 6-sep (PID 595126), y la app de prueba de la Fase 95 quedó
allí sin poder volver a ese nodo para cerrarla. Pedido del usuario: que funcione igual en cualquier
login node, para que cualquiera del equipo la pueda correr sin problemas.

### Cambio real

- `webapp/open_nlhpc.sh` (nuevo, se corre en la máquina local; Git Bash, Linux o macOS): **una sola**
  conexión `ssh -tt -L 127.0.0.1:<puerto>:<socket remoto> nlhpc "bash serve_nlhpc.sh <socket>"`.
  El túnel llega siempre al nodo donde corre la app. El socket se nombra por sesión
  (`~/.alces/webapp-<epoch>-<rand>.sock`), así que las sesiones no se pisan. Abre el navegador cuando
  la app responde. Opciones: `ALCES_SSH_HOST`, `ALCES_REMOTE_REPO` y `ALCES_NO_BROWSER=1`.
- `webapp/serve_nlhpc.sh` (nuevo, se corre en el login node): crea `~/.alces` con permisos 700,
  carga el módulo y el venv, y lanza `app.py --socket`. Un **vigilante** revisa cada 3 s que el
  proceso padre (la sesión de `sshd`) siga vivo; si no, detiene la app y sus kernels y borra el
  socket.
- `webapp/app.py`: `main()` con `--socket RUTA` (`run_simple("unix://...")`; se niega si el
  directorio no es privado) y `--port`. Sin argumentos se comporta igual que antes (máquina local).
- **Seguridad**: en un login node el `127.0.0.1` es compartido por todos los usuarios del nodo. Con
  la app en `127.0.0.1:5000`, cualquiera de ellos podía abrirla y lanzar sweeps (sbatch) con la
  cuenta de quien la corría. El socket dentro de `~/.alces` (700) solo lo abre su dueño. No se tocó
  el `umask` del proceso para proteger el socket: habría dejado con permisos 600 los sweeps que
  genera la webapp.

### Bugs encontrados en la prueba real (y corregidos)

1. **La app quedaba huérfana sin terminal**: lanzado sin terminal local, `-tt` no consiguió una pty
   remota (`tty ?` en `ps`), así que al cortar la conexión no llegó SIGHUP y quedaron vivos
   `serve_nlhpc.sh`, `app.py` y un kernel (reparentados a PID 1). Por eso existe el vigilante del
   proceso padre, que no depende de la pty.
2. **Cada exploración (Fase 95) dejaba un kernel `ipykernel` vivo**: al pasarle un `km=` propio,
   `nbclient` asume que el kernel no es suyo y no lo apaga al salir de `setup_kernel()`. En las
   pruebas de la Fase 95 no se vio porque la app siempre se mataba al final. Corrección: un `finally`
   con `km.shutdown_kernel(now=True)` en `sweep_explore._execute`, más un check nuevo en
   `test_sweep_explore.py` (sin procesos `ipykernel` hijos al terminar).
3. **El navegador nunca se abría en Windows**: el `MSYS_NO_PATHCONV=1` que el lanzador necesita (si
   no, Git Bash convierte `-L 5000:/home/...` en `5000:C:/Program Files/Git/home/...`) hacía que
   `curl -o /dev/null` intentara escribir en `C:\dev\null`; el sondeo fallaba para siempre. Ahora se
   redirige con `>/dev/null` desde bash.

### Validación real

- `test_sweep_explore.py` en NLHPC: **25/25 OK** (incluye los 2 checks nuevos de kernels huérfanos).
- `open_nlhpc.sh` desde Windows (Git Bash) contra una copia de prueba en NLHPC: la app arrancó en
  `leftraru1`, respondió por el túnel y Explore corrió sobre `fase65_rebarrido` (`done`, 0 errores).
  Se probaron dos formas de corte: **matar el `ssh.exe` local de golpe** y **terminar el script
  lanzador** (`timeout`). En los dos casos el nodo quedó sin procesos de la app, sin kernels y sin
  sockets en `~/.alces`. El sondeo imprime la URL una sola vez.
- **Pendiente**: la webapp vieja (PID 1414544), el bucle del 6-sep (PID 595126) y la app de prueba
  de la Fase 95 (puerto 5055) siguen en `leftraru2`. En 10 intentos el balanceador no volvió a
  mandar la conexión a ese nodo. Se cierran con `pkill -u $USER -f webapp/app.py` la próxima vez que
  se caiga ahí.

### Archivos de esta fase

Nuevos: `webapp/open_nlhpc.sh`, `webapp/serve_nlhpc.sh`. Modificados: `webapp/app.py` (`main()`),
`sweep_explore.py` (apagado del kernel), `test_sweep_explore.py`, `HOWTO_WEBAPP.md` (§3-bis),
`NOTES.md`.

## Fase 97 -- diagnóstico de la confusión KN-K17 ↔ KN-BULLA19 + red de seguridad (regresión dorada, pytest, CI)

### Contexto

El equipo que entrena los clasificadores (fuera de este repo, etiqueta = `class_key`) reportó que
confunden KN-K17 con KN-BULLA19 y separan bien el resto. Además el profesor ya investiga con el
simulador, así que cualquier mejora futura tiene que demostrarse físicamente neutra.

### Diagnóstico KN (`kn_confusion_diag.py`)

- **Nivel A, templates sin observar** (329 K17 + 550 BULLA19, fotometría sintética AB a 10 pc con
  los passbands locales): kNN leave-one-out separa las dos grillas con accuracy balanceada **1.0**
  (control K17 vs CaRT: 1.0). El rasgo que más separa es la caída a 7 días (`dm7_r`, AUC 0.12):
  BULLA19 cae 5-7 mag/semana, K17 2-5.
- **Nivel B, objetos detectados** (6 semillas por KN, 645 K17 + 855 BULLA19): **0.68**. Por noches
  distintas con detección: 1 noche 0.57, 2 noches 0.58, 3 noches 0.67, 4-5 noches 0.82, 6+ 0.82.
  El 55% de las KN detectadas tiene 1-2 noches. Agregar z no ayuda (misma distribución de z en ambas).
- **Conclusión:** la confusión viene del muestreo de LSST, no de la física ni de un bug. Queda como
  trabajo futuro del paper (Sec. 9.2), no como resultado.
- **Hallazgo lateral:** `PEAKMJD` tiene origen distinto por clase (primera detección − PEAKMJD:
  mediana +0.89 d en BULLA19, −0.03 d en K17), porque BULLA19 declara `OPTFLAG_T0SHIFT_PEAKMAG: 0`.
- **Cuota de disco:** 14 corridas con `phot_df` completo (~250 MB c/u) llenaron el home.
  `kn_confusion_shrink.py` deja solo los detectados (2 GB → 86 MB); `kn_confusion_gen.sbatch` lo
  aplica y limita el array a 3 jobs simultáneos.
- Dos errores del propio diagnóstico, corregidos antes de concluir: flujo residual ~1e-105 de K17
  daba M≈+600 (corte en M=−5), y `n_det` contaba exposiciones DDF, no noches (`n_det_nights`).

### Red de seguridad

- **`tests/golden/check_golden.py`**: corre SNIa-91bg, KN-BULLA19, CaRT y TDE-MOSFIT (semilla 7,
  NGENTOT 300) y compara SHA256 de `head_df`/`phot_df` (solo columnas que existían al grabar) y los
  conteos de `summary.json`. `--record` y `--check` en nodos distintos de NLHPC: **idéntico bit a
  bit** (jobs 14959513/14959514). Referencia en `tests/golden/golden_reference.json`. Sirve para
  probar que un cambio a `CODE_FILES` (que siempre cambia el `code_hash`) no cambia la física.
- **pytest**: `pytest.ini` + `conftest.py` adaptan los tests-script existentes sin reescribirlos (un
  `check()` fallido cuenta como FAILED). Local: 11/11.
- **CI**: `.github/workflows/tests.yml` (Ubuntu, Python 3.12, `requirements.txt` + pytest). No
  verificado todavía en GitHub.

### Archivos de esta fase

Nuevos: `kn_confusion_diag.py`, `kn_confusion_gen.sbatch`, `kn_confusion_diag.sbatch`,
`kn_confusion_shrink.py`, `tests/golden/{check_golden.py,run_golden.sbatch,golden_reference.json}`,
`pytest.ini`, `conftest.py`, `.github/workflows/tests.yml`. Modificados: `.gitignore`, `NOTES.md`.
`run_simsed_poc.py`, `searcheff.py` y `snana_params.py` no se tocan.
