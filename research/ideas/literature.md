# Revisión bibliográfica: inferencia de parámetros de KN y detección de anomalías

Primera pasada: 2026-10-20. Las referencias están en `refs.bib`, que tiene 17 entradas
bajadas de `arxiv.org/bibtex` con título y autores verificados.

**Numeración.** En el documento "ALCeS: cinco líneas de investigación de frontera", estas son
la **idea 1** (inferencia de parámetros) y la **idea 4** (anomalías con clases retenidas). En
el orden recomendado son la 1 y la 2.

**Método y límites:**
- Se hicieron 10 búsquedas con buscador web y se leyeron los abstracts en arXiv u OUP.
- Todavía no se repitieron en NASA ADS.
- Nada se leyó en texto completo, así que todas las cifras salen de los abstracts.

---

## Idea 1: inferencia de parámetros físicos de KN con pocas noches de LSST

### Registro de búsquedas
| # | Cadena | Hallazgos |
|---|---|---|
| 1 | kilonova parameter estimation SBI normalizing flows LSST | Desai+25, Brown+26, Ragosta+24 |
| 2 | NPE transient light curves sparse Rubin amortized | Solo reconstrucción y clasificación (NightLANP, NAPTIME); nada de NPE de parámetros físicos |
| 3 | sistemáticas de modelo de KN, Bulla vs Kasen | Hussenot-Desenonges+25, Jhawar+25, Darc+24 |
| 4 | SBI con efectos de selección, trigger, LSST, KN | FlowSN (Boyd+26), Andrade+25, Redback |

### Fichas
| Trabajo | Qué hace | Survey / cadencia | ¿Selección del trigger? | ¿Cruza modelos de KN? |
|---|---|---|---|---|
| [Desai+25](https://arxiv.org/abs/2408.06947) (MNRAS 541, 2619) | *Embedding* + flujo normalizante para masa, velocidad y fracción de lantánidos; invariante a tiempo y distancia; integrado en NMMA | Tipo ZTF, hasta 200 Mpc | No | Versión de congreso con varios modelos (sin verificar) |
| [Brown+26](https://arxiv.org/abs/2605.13983) (con M. Bulla) | SBI con emulador GP de ~1300 corridas de POSSIS; MCMC con verosimilitud gaussiana sale sesgado; muestras en segundos | AT2017gfo, sin cadencia de survey | No | No: corrige la mala especificación de la *verosimilitud*, no del modelo físico |
| [Ragosta+24](https://arxiv.org/abs/2403.14016) | Qué parámetros de KN restringe LSST según la estrategia | LSST (estrategias de visita) | No informado | No informado |
| [Darc+24](https://arxiv.org/abs/2311.09471) | NPE amortizada sobre *espectros* de KN | AT2017gfo | — | — |
| [Hussenot-Desenonges+25](https://arxiv.org/abs/2505.21392) | Incertezas de modelado; con cadencia diaria, sesgo leve a menor masa | Simulada, diaria | No | Discute Bulla19, Kasen17 y Bulla23 |
| [Jhawar+25](https://arxiv.org/abs/2410.21978) (PRD 111, 043046) | Sistemáticas dependientes del tiempo y del filtro; menores a 1 mag entre 1 y 5 días | — | No | Un resumen de búsqueda dice que recupera inyecciones Bu2019lm con Ka2017 con desajuste; **no aparece en el abstract, falta verificar** |
| [FlowSN, Boyd+26](https://arxiv.org/abs/2603.11165) (MNRAS 2026, con R. Kessler) | Flujo que aprende la verosimilitud *seleccionada* desde simulaciones; un orden de magnitud menos sesgo | **SNANA tipo LSST**, SN Ia | **Sí** | — (cosmología con SN Ia) |
| [Andrade+25](https://arxiv.org/abs/2502.14124) | Detectabilidad de KN según la cadencia de Rubin | LSST | Detectabilidad, no inferencia | — |
| [Nunes+26](https://arxiv.org/abs/2610.02088) (1-oct-2026) | Simulador multimodal de KN (fotometría, espectros, imágenes) para entrenar IA | ZTF | — | — |
| [Redback](https://arxiv.org/abs/2308.12806) | Inferencia bayesiana de transientes, con herramientas de simulación y selección | Varios | Parcial | — |

### Hueco y veredicto
- **Ya hecho:**
  - SBI y NPE para KN existen y son rápidos (Desai+25, Brown+26), pero sobre ZTF o AT2017gfo
    y **sin función de selección**.
  - La inferencia con selección del survey existe para SN Ia en simulaciones SNANA tipo LSST
    (FlowSN), pero no para KN.
- **Abierto,** sin encontrar en esta pasada:
  - NPE para KN con la cadencia WFD real de LSST y el trigger SNANA dentro del modelo directo;
  - estratificada por número de noches con detección;
  - con una prueba cruzada K17 ↔ BULLA19 en el **marco amortizado**.
  - ALCeS tiene justo esa pieza: ruido, SEARCHEFF y `SNR_CALC` de SNANA, más OpSim.
- **Pregunta ajustada:** *¿Qué parámetros de una KN detectada por casualidad en el WFD de
  LSST se pueden inferir de forma calibrada con 1-3 noches, una vez que el posterior se
  condiciona a haber pasado el trigger? ¿Cuánto sesgo introduce entrenar con el modelo
  equivocado?*
- **Veredicto: viable, con novedad moderada-alta.**
  - Riesgo principal: es un campo muy activo (Coughlin, Bulla y NMMA). Antes de empezar hay
    que revisar si NMMA ya ofrece SBI con cadencia LSST.
  - Una colaboración con ese grupo es una opción realista.

---

## Idea 2: detección de anomalías con clases retenidas (*leave-class-out*)

### Registro de búsquedas
| # | Cadena | Hallazgos |
|---|---|---|
| 5 | anomaly detection transients leave-one-class-out LSST | Gupta+24 (MCIF), Crispim Romão+25 |
| 6 | Muthukrishna / Villar real-time anomaly detection | Muthukrishna+22, Muthukrishna+21, Villar+21, Aleo+24 |
| 7 | OOD novelty transient early epochs ELAsTiCC | Gupta+24, AppleCiDEr; nada específico de ELAsTiCC |
| 8 | seguimiento de MCIF con LSST o ELAsTiCC, 2025-2026 | Gupta+24b (series de tiempo, OOD); ninguna versión LSST encontrada |

### Fichas
| Trabajo | Método | Datos | Clases anómalas | ¿Rota la clase retenida? | Resultado |
|---|---|---|---|---|---|
| [Gupta+24](https://arxiv.org/abs/2403.14742) (RASTI, con Muthukrishna y Lochner) | Latente de un clasificador RNN + un *isolation forest* por clase (MCIF) | **Simulaciones ZTF** | KN, PISN, ILOT (fijas) | No informado | 41 ± 3 de 54 anomalías en el 15% mejor rankeado; detecta poco después del trigger |
| [Gupta+24b](https://arxiv.org/abs/2408.08888) | MCIF aplicado a series de tiempo y OOD | Varios | — | — | Mejor que un *isolation forest* único |
| [Muthukrishna+22](https://arxiv.org/abs/2111.00036) | Modelos autorregresivos por clase; el error de predicción es el puntaje | SNANA con logs de ZTF | Clases raras de PLAsTiCC | — | Detección en tiempo real |
| [Muthukrishna+21](https://arxiv.org/abs/2112.08415) | Extensión multivariada | 10 000 transientes, g y r | 8 clases raras | — | — |
| [Villar+21](https://arxiv.org/abs/2103.12102) | Autoencoder variacional recurrente, anomalía activa | **PLAsTiCC** (LSST, 6 bandas) | Extragalácticas raras | — | — |
| [Aleo+24](https://arxiv.org/abs/2404.01235) (LAISS) | Features + contexto de la galaxia anfitriona, en el broker ANTARES | ZTF real | — | — | 1-5 candidatos por noche |
| Crispim Romão+25 (MNRAS 543, 351; [DOI](https://doi.org/10.1093/mnras/staf1477)) | *Isolation forest* de una clase | **LSST** baseline v2.0, solo banda i | Microlentes, RR Lyrae | No | Necesita unas 30 visitas para marcar transientes; la cadencia escasa degrada la separación |
| [AppleCiDEr](https://arxiv.org/abs/2507.16088) | Transformer multimodal temprano | ZTF | — | — | Contexto |

### Hueco y veredicto
- **Ya hecho:**
  - La detección de anomalías en transientes basada en un clasificador está bien establecida.
  - Gupta+24 trata justamente KN, PISN e ILOT como anomalías, pero sobre ZTF y con un conjunto
    fijo de clases anómalas.
- **Abierto,** sin encontrar en esta pasada:
  - hacerlo con la cadencia **LSST** real y transientes extragalácticos;
  - **rotar sistemáticamente** la clase retenida entre muchas clases (ALCeS tiene 42);
  - estratificar por **noches con detección**;
  - **particionar por template** para no sobrestimar.
- **Pregunta ajustada:** *¿Qué clases de transientes se pueden descubrir como anomalías con
  la cadencia LSST, y con cuántas noches? Es un mapa de descubribilidad por clase, con MCIF
  (Gupta+24) como método base y clases retenidas por rotación.*
- **Veredicto: viable, con novedad moderada.**
  - El aporte es de protocolo y de escala (LSST, 42 clases, rotación, noches), no de método.
  - Es rápido, porque reutiliza la base de `research/lc_images`.
  - Riesgo: que el grupo de Muthukrishna y Lochner publique la versión LSST primero. Conviene
    usar MCIF tal cual y citarlo, en vez de competir en el método.

---

## Pendientes de esta revisión
1. Repetir en ADS y hacer *snowballing* de citas hacia adelante de Desai+25, Brown+26,
   FlowSN y Gupta+24.
2. Leer en texto completo:
   - Jhawar+25, para confirmar o descartar la prueba cruzada Bu2019lm ↔ Ka2017;
   - Ragosta+24, para ver el método y si usa el WFD;
   - Gupta+24, para ver la rotación de clases y el código.
3. Revisar la documentación de NMMA (SBI y LSST) y si existe un código público de MCIF.
4. Buscar el arXiv de Crispim Romão+25 y el paper de ELAsTiCC con resultados de anomalías,
   si existe.
