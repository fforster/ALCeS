# Revisión bibliográfica: curvas de luz como imágenes para clasificar transientes

Primera pasada: 2026-10-20. Es la Parte 1 del plan "Opción A". Las referencias están en
`refs.bib`.

## Estado de esta revisión (léase primero)
- **Herramientas:** la búsqueda se hizo con un buscador web general más la lectura de los
  abstracts y HTML de arXiv. **Todavía no se hizo en NASA ADS**, porque no tengo acceso a su
  API. Falta repetir las cadenas en ADS y anotar cuántos resultados da cada una.
- **Origen de las BibTeX:** las 28 entradas de `refs.bib` se bajaron de `arxiv.org/bibtex/<id>`
  y no se escribieron a mano. Son entradas `@misc` de arXiv. Antes de citar en un paper hay que
  reemplazarlas por la versión con revista desde ADS. Por ejemplo, para ATAT las fuentes dan
  dos referencias distintas: A&A 689, A289 y A&A 691, A163.
- **Un ID descartado:** la búsqueda asoció 2305.13745 a un estudio de codificaciones GAF y
  *recurrence plots* con curvas de Kepler, pero ese ID corresponde a otro paper (LightCurve MoE).
  Lo saqué de `refs.bib` y el estudio de Kepler queda **sin verificar**.
- **Fichas:** salen de abstracts y resúmenes. Solo Moreno-Cartagena et al. (2025a) se leyó en
  texto completo. Las cifras se tienen que confirmar en el PDF antes de usarlas.

## Registro de búsquedas (2026-10-20)
| # | Cadena (buscador web) | Hallazgos relevantes |
|---|---|---|
| 1 | SCONE supernova CNN Gaussian process heatmaps | SCONE (2106.04370), SCONE temprano (2111.05539) |
| 2 | light curve image representation CNN transient LSST sparse early | Mahabal+17 (dm-dt), NEEDLE, embeddings multibanda |
| 3 | kilonova photometric classification ML LSST | TLW, El-CID, revisiones generales |
| 4 | Gramian angular field / recurrence plot astronomical CNN | Wang & Oates 2015, Hatami+17, estudio de Kepler (sin verificar) |
| 5 | ATAT ALeRCE transformer | ATAT (2405.03078), ATCAT (2511.00614, sin revisión por pares) |
| 6 | ELAsTiCC classification results brokers | Fink benchmarks, AMPEL, MALLORN, clasificador de TDE |
| 7 | 2D heatmap CNN vs RNN/transformer pocas observaciones | Brunel+19 (CNN 1D vs LSTM), modelos de atención |
| 8 | Mahabal 2017 dm-dt | 1709.06257 |
| 9 | KN Kasen vs Bulla sistemáticas del clasificador | El-CID, WFST (2312.12169), 7DT |
| 10 | stamp classifier y LC classifier de ALeRCE | 2008.03309, 2008.03311, extensión TDE 2503.19698 |
| 11 | RAPID, SuperNNova, ParSNIP, Avocado | 1904.00014, 1901.06384, 2109.13999, 1907.04690 |
| 12 | fuga de información por templates en train/test | **nada encontrado** |
| 13 | vision transformer preentrenado y curvas de luz como imagen | **Moreno-Cartagena+25 (2502.20479, 2507.11711)** |
| 14 | Fink kilonova | Biswas+23 (2210.17433) |
| 15 | PLAsTiCC modelos y resultados | Kessler+19, Hložek+23 |
| 16 | efecto de la cadencia de LSST en la clasificación | Alves+22, Alves+23 |

## Fichas
| Trabajo | Representación | Modelo | Datos | ¿KN? | ¿Pocas épocas? | Resultado clave | Qué deja abierto |
|---|---|---|---|---|---|---|---|
| **SCONE**, Qu+21 | Imagen: GP 2D (tiempo × λ), canales de flujo e incertidumbre | CNN | PLAsTiCC | No (solo SN) | No | 98.2% en 6 tipos de SN | Rendimiento fuera de distribución menor |
| **SCONE temprano**, Qu & Sako 22 | Igual a SCONE, truncado a 0-50 días del trigger | CNN | LSST simulado | No | **Sí**, por días | ~75% en el trigger, ~89% a 50 días (con z) | Sin KN; corta por días, no por número de noches detectadas |
| **Moreno-Cartagena+25a** (ALeRCE / U. de Concepción) | Imagen: gráfico matplotlib 256×256 (grilla o superpuesto) | SwinV2 preentrenado | ELAsTiCC (20 clases), MACHO | No se mencionan | **No** | F1 macro 65.5 en ELAsTiCC (ATAT 64.2 sin metadatos) | Subclases de SN difíciles; sin metadatos; sin evaluación temprana; no agrupa por template |
| Moreno-Cartagena+25b | Imagen, ViT en dos ramas | SwinV2 | ZTF + ATLAS reales | — | No | Combinar surveys mejora | Taller ICML-ML4Astro |
| Mahabal+17 | Imagen dm-dt | CNN | CRTS (periódicas) | No | — | Las curvas escasas quedan sin clasificar | Ya identifica la escasez como modo de falla |
| **ATAT**, Cabrera-Vives+24 | Secuencia + tabular | Transformer | ELAsTiCC (20 clases) | ELAsTiCC sí incluye KN | — | F1 macro 82.9 con metadatos | Es la línea base natural de ALeRCE |
| **RAPID**, Muthukrishna+19 | Secuencia | GRU | PLAsTiCC/ZTF simulado | Sí | **Sí**, clasifica en cada época | — | No compara con imágenes |
| SuperNNova, Möller+20 | Secuencia | RNN bayesiana | SNANA | Adaptable | Parcial | — | — |
| Avocado, Boone 19 | Features + aumentación con GP | GBDT | PLAsTiCC | Sí | — | Ganó PLAsTiCC | — |
| ParSNIP, Boone 21 | Latente físico | VAE + clasificador | PLAsTiCC, PS1 | Sí | — | 2-2.3x menos contaminación de SN Ia | — |
| Brunel+19 | CNN 1D vs LSTM | — | SN simuladas | No | — | — | Única comparación directa CNN vs RNN encontrada |
| **Biswas+23** (KN en Fink) | PCA + random forest | RF | Simulaciones tipo ZTF | **Sí** | **Sí** | ~69% de precisión y recall | Usa features, no imágenes |
| **Liang+23** (WFST) | — | — | Bulla + MOSFiT, contra SN Ia | **Sí** | Sí, 3 días | >98% KN vs resto | Clasificación binaria; no separa modelos de KN |
| **El-CID**, Chatterjee+21 | — | — | Bulla + Kasen | **Sí** | Sí | Verifica que no aprende la cadencia | Modelos de KN aún inmaduros |
| **Alves+22, Alves+23** | Features (snmachine) | — | PLAsTiCC con varias cadencias | No | — | Rolling +25%; 3 visitas por noche empeora | Un solo clasificador; no evalúa imágenes |
| Hložek+23, Kessler+19 | Desafío PLAsTiCC | — | — | Sí | — | Los mejores clasifican bien SN Ia y KN | — |
| Carrasco-Davis+21 | Stamps de píxeles | CNN | ZTF real | — | 1ª detección | ~94% (5 clases amplias) | Es la opción B, fuera de alcance |
| Sánchez-Sáez+21, Pavez-Herrera+25 | Features | BHRF | ZTF real | No | — | Clasificador LC de ALeRCE (+TDE) | — |
| Fraga+24 (Fink), MALLORN 25, NEEDLE 23, ATCAT 25 | Varias | — | ELAsTiCC / real | Varía | — | Contexto de brokers | ATCAT sin revisión por pares |
| Wang & Oates 15, Hatami+17 | GAF, *recurrence plot* | CNN | Series genéricas | — | — | Origen de las codificaciones como imagen | — |

## Hueco identificado

**1. La idea de "curva de luz como imagen + CNN o ViT" ya está publicada.** Existe con
imágenes GP (SCONE) y con gráficos y SwinV2 preentrenado (Moreno-Cartagena+25a). Este segundo
trabajo es del **mismo entorno ALeRCE** (Cabrera-Vives, U. de Concepción). Por eso, plantear
la pregunta original como "¿sirven las imágenes?" **no es nuevo**. Antes de seguir, el
profesor tiene que saberlo y conviene coordinarse o colaborar con ese grupo.

**2. Lo que no encontré.** Esto es ausencia en una primera pasada, no prueba de que no exista.
Hay que confirmarlo en ADS.
- **(a) Imagen vs secuencia en el régimen de pocas noches.** No hay comparación controlada
  estratificada por **número de noches con detección**. SCONE trunca por días y
  Moreno-Cartagena+25a no evalúa curvas tempranas.
- **(b) Fuga de información por template.** No encontré ningún trabajo que agrupe la
  partición train/test por template SIMSED. Con la grilla de KN, el mismo template puede
  aparecer en train y test, lo que inflaría la exactitud.
- **(c) Distinguir entre *modelos* de KN** (K17 vs BULLA19), no solo KN vs resto. Los trabajos
  de KN usan varios modelos (El-CID, WFST), pero clasifican KN contra contaminantes. Cuánta
  información sobre el modelo físico sobrevive al muestreo de LSST parece no estar
  estudiado. Nuestro diagnóstico ya tiene una primera respuesta: 1.0 en templates y 0.57 con
  1 noche.
- **(d) Efecto de la versión de OpSim** (v5.0 vs v5.3) en clasificadores basados en imagen.
  Alves+22 y Alves+23 lo estudian solo con features.

**3. Pregunta reformulada (propuesta para el profesor):**
> ¿Cuánta información de clase sobrevive al muestreo escaso de LSST, y depende de la
> representación? Se comparan imagen (GP 2D y gráfico estilo SwinV2), secuencia y features
> según el número de noches detectadas, con particiones agrupadas por template para evitar
> fuga. El caso límite son dos modelos de KN, K17 y BULLA19.

Lo que aportaría:
- un protocolo de evaluación (estratificado por noches y agrupado por template), aplicable a
  cualquier clasificador, incluidos los de ALeRCE;
- un resultado sobre separabilidad de modelos de KN;
- simulaciones ALCeS validadas contra SNANA (motor LCL).

El "uso de GPU" deja de ser la pregunta y pasa a ser el medio.

**4. Implicaciones para el experimento (Parte 2 del plan):**
- Agregar la representación de Moreno-Cartagena+25a (gráfico + SwinV2 preentrenado) como
  segunda variante de imagen. El SwinV2 preentrenado cabe en una V100.
- Usar ATAT como línea base de secuencia en vez de una GRU propia, si su código
  (`alercebroker/ATAT`) corre sobre nuestros datos.
- Medir (b) primero, porque es barato: el mismo modelo con partición aleatoria vs agrupada
  por `TEMPLATE_INDEX`. Si la diferencia es grande, ese resultado vale por sí solo.

## Pendientes de esta revisión
1. Repetir las 16 cadenas en ADS y registrar el número de resultados.
2. Hacer *snowballing* de citas hacia adelante de SCONE, Moreno-Cartagena+25a y Biswas+23.
   Es lo más probable para encontrar trabajo de 2025-2026 sobre (a) y (c).
3. Leer en texto completo SCONE temprano, Biswas+23, El-CID, Liang+23 y Alves+23.
4. Verificar o encontrar el estudio de codificaciones de Kepler y el clasificador de TDE para
   Rubin (A&A 2025, ELAsTiCC2).
5. Buscar si hay un paper oficial de resultados de ELAsTiCC.
6. Reemplazar las entradas `@misc` por las de revista desde ADS.
