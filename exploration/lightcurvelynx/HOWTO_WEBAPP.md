# Cómo usar "el botón" — la interfaz web de generación de sweeps

Instructivo práctico para la app web local (Flask) que reemplaza la línea de comandos para generar,
lanzar y publicar sweeps de LightCurveLynx. Documento hermano de `HOWTO.md` (flujo real de NLHPC) y
`HOWTO_LOCAL.md` (instalación en una máquina sin NLHPC) — este cubre solo la interfaz, construida
sobre esos dos.

## 1. Qué es esto, y qué NO es

Es una app web que corre **en tu propia máquina** (o en el login node de NLHPC para una prueba
rápida) y te deja generar/lanzar/monitorear/publicar sweeps desde el navegador en vez de la
terminal. Todo lo que hace, ya lo hacían los scripts `sweep_*.py` (Fases 66/76/79-82) — esta app
solo les pone un formulario y botones encima; no agrega ninguna capacidad nueva de simulación.

**No es**: un servicio multiusuario ni algo para desplegar en un servidor compartido — corre en
`127.0.0.1` únicamente, pensada para que una sola persona la abra en su propio navegador mientras el
proceso Flask corre en la misma máquina (o vía un túnel SSH si se corre en NLHPC). No entrena ni
despliega ningún modelo — llega hasta producir el dataset (parquet por clase).

## 2. Requisitos

Completar primero `HOWTO_LOCAL.md` (venv con `requirements.txt` instalado -- incluye `flask` desde
la Fase 83 --, datos vendorizados, `.db` de OpSim). Sin eso, la app arranca pero el formulario no
tendrá ninguna clase disponible para elegir.

## 3. Levantar la app

```bash
cd exploration/lightcurvelynx
source venv/bin/activate            # o el equivalente de tu instalación local
python3 webapp/app.py
```

Abre `http://127.0.0.1:5000/` en el navegador.

### 3-bis. Usarla en NLHPC (un comando, desde tu máquina — Fase 96)

Para usar la app con tus datos de NLHPC, **no la levantes a mano en el login node**. Desde tu
máquina (Git Bash en Windows, o una terminal en Linux/macOS), con el repo clonado ahí también:

```bash
cd exploration/lightcurvelynx/webapp
./open_nlhpc.sh            # o: ./open_nlhpc.sh 5001 si tu puerto 5000 local está ocupado
```

Levanta la app en el login node al que te mande el balanceador (`leftraru1`, `leftraru2`, … da
igual), abre el túnel **en la misma conexión** SSH y abre el navegador en
`http://127.0.0.1:5000/` cuando la app ya responde. Para cerrarla: **Ctrl+C o cerrar la ventana**.
La app se detiene sola en el nodo (también si se corta la red) y no deja procesos ni sockets.

Requisitos: el alias `nlhpc` en `~/.ssh/config` con clave (sin contraseña interactiva) y el repo
clonado en NLHPC en `~/AUTOSIM`, con su venv. Si tu alias o tu clon son otros:
`ALCES_SSH_HOST=<alias> ALCES_REMOTE_REPO=<ruta del clon> ./open_nlhpc.sh`.

Por qué así (antes se hacía `nohup python3 webapp/app.py` en una conexión y `ssh -L
5000:127.0.0.1:5000 nlhpc` en otra):

- **El nodo no importa.** Con dos conexiones, el balanceador podía mandar cada una a un login node
  distinto y el túnel llegaba a un nodo sin app. Ahora app y túnel viajan juntos.
- **No quedan procesos huérfanos.** `serve_nlhpc.sh` vigila la conexión SSH que lo lanzó y detiene
  la app (y sus kernels de Explore) cuando se cierra. Antes cada `nohup` quedaba corriendo en el
  nodo (se encontraron instancias de hacía semanas).
- **Solo tú puedes abrirla.** La app escucha en un socket Unix dentro de `~/.alces/` (permisos 700),
  no en `127.0.0.1:5000`. En un login node compartido, el `127.0.0.1` es de todos los usuarios del
  nodo: antes cualquiera de ellos podía abrir tu app y lanzar sweeps con tu cuenta. Tampoco hay
  choques de puerto con otros usuarios.

## 4. Generar y correr un sweep

1. **Generate** (`/`): nombre del sweep, clases (solo aparecen las que ya tienen datos
   vendorizados en esta máquina — ver `HOWTO_LOCAL.md` sección 8 para agregar una clase nueva),
   `ngentot` por clase (vacío = default del catálogo), semillas, WFD/DDF, y si quieres preservar la
   fotometría cruda (`keep_phot` — necesario si vas a publicar un dataset con parquet por clase para
   el equipo de ML, ver sección 6). La sección "Avanzado" deja ajustar memoria/tiempo/CPUs/
   paralelismo si los defaults no alcanzan.
2. Al enviar el formulario, la app genera el YAML real (`sweep_generate.py`, Fase 79) y lo compila
   (`sweep_compile.py`) automáticamente, y te lleva a la página de estado del sweep.
3. **Launch**: el botón "Launch" corre el sweep en segundo plano (sin bloquear la página) vía el
   mismo runner local sin SLURM de la Fase 76. El estado de cada corrida se actualiza solo, cada
   pocos segundos, sin recargar la página — cuando termina, aparecen enlaces reales a sus 4 gráficos
   de control (QC).
4. Cuando todas las corridas terminan, aparecen los botones **Aggregate** (consolida las métricas del
   sweep) y **Publish** (crea un dataset versionado por hash en `datasets/<hash>/`).

La interfaz está en inglés desde la Fase 95 (los botones y mensajes que se nombran en este documento
usan su texto en inglés: **Generate**, **Launch**, **Aggregate**, **Publish**, **History**,
*Keep raw photometry*).

## 4-bis. Explorar los resultados (**Explore**, Fase 95)

En cuanto un sweep tiene al menos una corrida `done`, su página muestra **Explore results →** (y la
lista de sweeps, una columna **Explore**). Esa página ejecuta en el servidor un notebook de análisis
del sweep y lo muestra **celda por celda mientras corre**: código, gráficos y tablas.

1. **Run exploration** genera `sweep_runs/<sweep>/explore/explore_<sweep>.ipynb` (`sweep_explore.py`)
   y lo ejecuta con `nbclient` en el kernel `python3` del mismo venv. La barra de progreso y el
   marcador `[*]` indican la celda en ejecución; la página consulta el estado cada 1,5 s.
2. Secciones: inventario de corridas terminadas, eficiencia de detección por clase/estrategia
   (promedio y dispersión entre semillas), distribuciones de redshift y `NOBS` (`head_df`), eficiencia
   vs. redshift, fotometría cruda (SNR, cobertura por banda y 3 curvas de luz de ejemplo — solo si el
   sweep se generó con *Keep raw photometry*; si no, un aviso) y la comparación DDF vs. WFD.
3. **Download .ipynb** descarga el notebook ya ejecutado. Es autocontenido (lee `manifest.json` y
   los parquet directo desde la carpeta del sweep), así que se puede seguir editando en JupyterLab
   en la misma máquina donde están los datos.
4. **Re-run exploration** lo vuelve a generar desde cero (útil cuando terminan más corridas).

El notebook corre en la máquina de la app (en NLHPC, el login node): lee a lo más 6 `phot_df` y
cada celda tiene un límite de 180 s. En los sweeps reales probados (hasta 65 corridas) termina en
pocos segundos. El kernel se comunica por sockets IPC dentro de tu home (no abre puertos TCP),
porque el login node es compartido. Si el servidor se reinicia a mitad de una ejecución, la página
lo indica como *interrupted* y basta con volver a ejecutarla.

## 5. Historial

La pestaña **History** muestra `generation_history.jsonl` (Fase 80) — cada sweep generado,
compilado, corrido o publicado, más reciente primero, con quién/qué lo disparó. Es la traza
reproducible real: cualquiera que abra esta página ve exactamente qué se generó, cuándo y con qué
parámetros, sin tener que leer `NOTES.md`.

## 6. El dataset publicado (conector de ML)

La página de un dataset (`/datasets/<hash>`) muestra su `ingestion_format`:

- **`parquet_by_class_v1`**: al menos una corrida de origen tenía `keep_phot=true` — hay archivos
  reales en `datasets/<hash>/by_class/<clase>.parquet` (fotometría completa + contexto +
  procedencia), listos para entregar al equipo de ML tal cual (Fase 82).
- **`null`**: ninguna corrida de origen preservó fotometría cruda — la página explica por qué.
  Solución: generar un sweep nuevo marcando *Keep raw photometry* y volver a publicar.

## 7. Qué NO hace esta interfaz

- No entrena ni despliega ningún modelo — el punto de entrega es el `parquet` por clase.
- No agrega soporte para `SNIa`/SALT2 ni las clases NON1ASED al sistema de sweeps (decisión ya
  tomada en Fase 73) — el formulario solo lista clases de `CLASS_CONFIGS` (`run_simsed_poc.py`).
- No reemplaza `sweep_launch.py`/`sbatch` para barridos grandes reales en NLHPC con SLURM — usa el
  runner local (Fase 76), pensado para máquinas sin cluster. Para un barrido grande en NLHPC con
  cientos de corridas, seguir usando `sweep_launch.py` desde la terminal (`HOWTO.md` sección 5-bis).

## 8. Para profundizar

- `HOWTO.md` / `HOWTO_LOCAL.md` — los flujos de NLHPC y de instalación local que esta interfaz
  envuelve.
- `NOTES.md`, Fases 79-85 — el detalle real de cada pieza (el generador, el historial,
  `keep_phot`, el conector por clase, el backend Flask, el frontend, y esta fase de cierre). Fase 95:
  **Explore** y la traducción al inglés.
- `docs/index.html`, pestaña "06 LightCurveLynx" — el resumen curado de todas las fases.
