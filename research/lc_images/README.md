# Información de clase bajo muestreo escaso de LSST

Línea de investigación aparte del paper de ALCeS. Usa las salidas del simulador y **no lo
modifica**: nada aquí toca `CODE_FILES`, `run_hash` ni la regresión dorada.

- **Pregunta:** ¿cuánta información de clase sobrevive al muestreo escaso de LSST, y depende
  de la representación (imagen, secuencia o features)? Se evalúa según el número de noches con
  detección y con particiones agrupadas por template.
- **Estado (2026-10-20):** propuesta enviada al profesor. Ningún experimento ha corrido.
- **Revisión bibliográfica:** `literature.md` y `refs.bib`.

## Experimentos
| ID | Pregunta | Comparación | Hardware |
|---|---|---|---|
| E1 | ¿Infla la exactitud repetir templates entre train y test? | Partición aleatoria vs agrupada por `TEMPLATE_INDEX` | CPU |
| E2 | ¿Importa la representación con pocas noches? | Imagen GP, gráfico + SwinV2, secuencia (ATAT/GRU), features + GBDT | GPU `v100` |
| E3 | ¿Cuánto del modelo físico de KN sobrevive al muestreo? | K17 vs BULLA19 con las representaciones de E2 | GPU |
| E4 | ¿Cambia la conclusión con otra versión de OpSim? | Entrenar con v5.0.0, probar con v5.3.1 | GPU |

## Contrato de datos
- **Fuente:** `head_df.parquet` y `phot_df.parquet` generados con el código actual (Fase 98 o
  posterior).
  - Las salidas anteriores (`poc_output_*`, `kn_confusion_diag/`) **no traen
    `TEMPLATE_INDEX`** y no sirven para E1.
  - La física es idéntica entre versiones (regresión dorada bit a bit), así que basta con
    regenerar.
- **Etiqueta:** `class_key`. Nunca `SNTYPE`, que se comparte entre clases (por ejemplo, 51 =
  KN-K17, TDE-MOSFIT y TDE de NON1ASED).
- **Universo:** solo objetos detectados por el trigger SNANA.
  - Reducir con la lógica de `exploration/lightcurvelynx/kn_confusion_shrink.py`.
  - La cuota del home en el NLHPC no admite la fotometría completa.
- **Noches con detección:** `n_det_nights`, calculado como en
  `exploration/lightcurvelynx/kn_confusion_diag.py`. Los bins son 1, 2, 3, 4-5 y 6+.
- **Grupo para particionar:** `TEMPLATE_INDEX` en clases SIMSED.
  - Para clases sin template (SALT2, NON1ASED) la partición es aleatoria.
  - Esto se reporta aparte.

## Protocolo común
- 5 semillas por configuración, reportando media ± desviación.
- Métricas: exactitud balanceada y F1 macro, más una matriz de confusión por bin de noches.
- Cada corrida guarda su configuración y el SHA256 de los archivos de entrada.
- Controles:
  - con etiquetas barajadas debe dar nivel de azar;
  - con 6 o más noches debe igualar o superar el kNN del diagnóstico KN (0.82).

## Entorno
- **Simulación y E1:** el venv existente del simulador
  (`exploration/lightcurvelynx/venv`, Python 3.12). No tiene sklearn: para E1 hay que crear un
  venv aparte con sklearn/lightgbm, y no instalarlos en el del simulador.
- **GPU:**
  - venv propio `research/lc_images/venv` con PyTorch para CUDA 12.x. NLHPC no tiene módulo de
    PyTorch, pero sí `CUDA/12.1.1` y `cuDNN/8.9.2.26-CUDA-12.1.1`.
  - Revisar el espacio antes de instalar, porque PyTorch ocupa varios GB.
- **Particiones:** `v100` (2 nodos × 2 V100). Las AMD (`mi100`, `mi210`) solo si hace falta,
  porque requieren ROCm 5.1.

## Estructura prevista
```
research/lc_images/
  README.md, literature.md, refs.bib
  data/          # regeneración: sbatch que llama a run_simsed_poc.main(...) y reduce a detectados
  reps/          # phot_df -> .npz: imagen GP, gráfico, secuencia, features
  models/        # gbdt.py, cnn.py, swin.py, seq.py
  experiments/   # e1_leakage.py ... e4_cadence.py: cada uno escribe results/<exp>/<run>/
  slurm/         # sbatch por experimento
  results/       # ignorado por git; solo tablas y figuras finales se versionan
```

## Etapas y decisiones
1. **Cerrar la revisión bibliográfica:** ADS, citas hacia adelante y lectura completa.
   - *Decisión:* quitar del diseño los huecos que ya estén cubiertos.
2. **Regenerar datos:** KN-K17, KN-BULLA19 y SNIa, con 5 semillas, guardando solo detectados.
3. **E1 en CPU.**
   - *Decisión:* si la fuga es grande, se prioriza como resultado propio.
4. **Entorno GPU y piloto de E2/E3** con 3 clases.
   - *Decisión:* escalar solo si el piloto pasa los controles.
5. **Escalar a las 19 clases y correr E4.**
