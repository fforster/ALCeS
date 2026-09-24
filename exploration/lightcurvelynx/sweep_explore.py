"""
Fase 95: "Explore" en vivo por sweep -- genera un notebook de analisis
para un sweep ya corrido, lo ejecuta en el servidor celda por celda
(nbclient) y deja en disco el estado parcial despues de CADA celda, para
que la webapp (webapp/app.py, /sweep/<name>/explore) muestre en vivo como
va corriendo: codigo, graficos y tablas.

El notebook es AUTOCONTENIDO (no importa sweep_*.py): lee manifest.json,
run_hash.json, summary.json y los parquet directo desde SWEEP_DIR, asi que
el .ipynb descargado se puede seguir usando en JupyterLab tal cual. Las
secciones de analisis se adaptaron de analyze_phot_df.ipynb (Fase 17) a la
estructura de un sweep (runs/<hash>/ en vez de poc_output_*/).

Estado en disco (fuente de verdad, igual que run_hash.json para las
corridas): sweep_runs/<name>/explore/{explore_<name>.ipynb, status.json}.
El dict en memoria (_RUNNING) es solo un guard para no ejecutar el mismo
sweep dos veces en paralelo, mismo patron que RUNNING/RUNNING_LOCK de la
webapp.

Uso standalone (sin webapp):
    python3 sweep_explore.py <sweep_name>
"""
from __future__ import annotations

import base64
import html
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

import sweep_hash
from sweep_compile import SWEEP_RUNS_DIR

# Limites para no cargar el login node de NLHPC: el notebook corre en el
# mismo proceso/nodo que la webapp. head_df pesa poco (~100 KB por corrida),
# phot_df puede ser grande -- se leen como maximo MAX_PHOT_RUNS corridas.
MAX_PHOT_RUNS = 6
CELL_TIMEOUT_S = 180

_RUNNING: dict[str, threading.Thread] = {}
_RUNNING_LOCK = threading.Lock()


def explore_dir(sweep_name: str, runs_dir: Path | None = None) -> Path:
    return (runs_dir or SWEEP_RUNS_DIR) / sweep_name / "explore"


def notebook_path(sweep_name: str, runs_dir: Path | None = None) -> Path:
    return explore_dir(sweep_name, runs_dir) / f"explore_{sweep_name}.ipynb"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ notebook
def build_notebook(sweep_name: str, runs_dir: Path | None = None) -> nbformat.NotebookNode:
    sweep_dir = ((runs_dir or SWEEP_RUNS_DIR) / sweep_name).resolve()
    cells = [
        new_markdown_cell(
            f"# Exploring sweep `{sweep_name}`\n\n"
            "Generated and executed by the LightCurveLynx webapp (**Explore** button). "
            "The notebook is self-contained: it reads `manifest.json`, each run's "
            "`run_hash.json`/`summary.json` and the `head_df`/`phot_df` parquet files "
            "directly from the sweep directory, so you can download it and keep working "
            "in JupyterLab.\n\n"
            "Only runs with `status == \"done\"` are included."
        ),
        new_code_cell(
            "import json\n"
            "from pathlib import Path\n\n"
            "import matplotlib\n"
            "import matplotlib.pyplot as plt\n"
            "import numpy as np\n"
            "import pandas as pd\n\n"
            "%matplotlib inline\n"
            "pd.set_option('display.max_rows', 60)\n\n"
            f"SWEEP_DIR = Path({str(sweep_dir)!r})\n"
            f"MAX_PHOT_RUNS = {MAX_PHOT_RUNS}   # phot_df can be large: cap how many runs are loaded\n"
            "manifest = json.loads((SWEEP_DIR / 'manifest.json').read_text())\n"
            "print(f\"sweep: {manifest['sweep_name']} -- {manifest['n_runs']} runs, \"\n"
            "      f\"keep_phot={manifest.get('keep_phot', False)}, compiled {manifest.get('compiled_at', '?')}\")"
        ),
        new_markdown_cell(
            "## 1. Run inventory\n\n"
            "One row per finished run, with the metrics from its `summary.json` and which "
            "raw tables are still on disk (`phot_df.parquet` only exists when the sweep was "
            "generated with *Keep raw photometry*)."
        ),
        new_code_cell(
            "rows = []\n"
            "for r in manifest['runs']:\n"
            "    run_dir = SWEEP_DIR / r['output_dir']\n"
            "    rh_path, sm_path = run_dir / 'run_hash.json', run_dir / 'summary.json'\n"
            "    if not rh_path.exists() or json.loads(rh_path.read_text()).get('status') != 'done':\n"
            "        continue\n"
            "    summary = json.loads(sm_path.read_text()) if sm_path.exists() else {}\n"
            "    rows.append({\n"
            "        'run_hash': r['run_hash'], 'class_key': r['class_key'],\n"
            "        'strategy': 'WFD' if r.get('wfd') else 'DDF', 'seed_index': r.get('seed_index', 0),\n"
            "        'ngentot': summary.get('ngentot_lc', r.get('ngentot')),\n"
            "        'n_detected': summary.get('n_detected'),\n"
            "        'detection_efficiency_pct': summary.get('detection_efficiency_pct'),\n"
            "        'snr_median': summary.get('snr_median'), 'snr_p90': summary.get('snr_p90'),\n"
            "        'z_max_simulated': summary.get('z_max_simulado'),\n"
            "        'z_max_detected': summary.get('z_max_detectado'),\n"
            "        'has_head_df': (run_dir / 'head_df.parquet').exists(),\n"
            "        'has_phot_df': (run_dir / 'phot_df.parquet').exists(),\n"
            "        'run_dir': run_dir,\n"
            "    })\n"
            "inventory = pd.DataFrame(rows)\n"
            "if inventory.empty:\n"
            "    print('No finished runs yet -- launch the sweep and come back when at least one run is done.')\n"
            "else:\n"
            "    print(f\"{len(inventory)} finished runs, {inventory['class_key'].nunique()} classes\")\n"
            "inventory.drop(columns=['run_dir'], errors='ignore')"
        ),
        new_markdown_cell(
            "## 2. Detection efficiency by class and strategy\n\n"
            "`detection_efficiency_pct = n_detected / ngentot` (SEARCHEFF), averaged over seeds."
        ),
        new_code_cell(
            "if inventory.empty:\n"
            "    print('nothing to plot yet')\n"
            "else:\n"
            "    eff = (inventory.groupby(['class_key', 'strategy'])['detection_efficiency_pct']\n"
            "           .agg(['mean', 'std', 'count']).reset_index().sort_values('mean'))\n"
            "    labels = eff['class_key'] + ' (' + eff['strategy'] + ')'\n"
            "    colors = eff['strategy'].map({'DDF': 'tab:blue', 'WFD': 'tab:orange'})\n"
            "    fig, ax = plt.subplots(figsize=(9, max(3, 0.35 * len(eff))))\n"
            "    ax.barh(labels, eff['mean'], xerr=eff['std'].fillna(0), color=colors)\n"
            "    ax.set_xlabel('detection efficiency (%)')\n"
            "    ax.set_title('Detection efficiency (mean over seeds)')\n"
            "    plt.tight_layout(); plt.show()\n"
            "    display(eff.rename(columns={'mean': 'eff_mean_pct', 'std': 'eff_std_pct', 'count': 'n_seeds'}))"
        ),
        new_markdown_cell(
            "## 3. `head_df`: redshift and number of observations\n\n"
            "One row per simulated object with observations (`SNID, REDSHIFT_HELIO, PEAKMJD, NOBS, DETECTED`)."
        ),
        new_code_cell(
            "HEAD_COLS = ['SNID', 'REDSHIFT_HELIO', 'PEAKMJD', 'NOBS', 'DETECTED']\n"
            "frames = []\n"
            "head_runs = inventory[inventory['has_head_df']] if not inventory.empty else inventory\n"
            "for _, row in head_runs.iterrows():\n"
            "    h = pd.read_parquet(row['run_dir'] / 'head_df.parquet')\n"
            "    h = h[[c for c in HEAD_COLS if c in h.columns]]\n"
            "    h['class_key'], h['strategy'], h['seed_index'] = row['class_key'], row['strategy'], row['seed_index']\n"
            "    frames.append(h)\n"
            "head_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()\n"
            "if head_all.empty:\n"
            "    print('no head_df.parquet available in the finished runs')\n"
            "else:\n"
            "    print(f\"{len(head_all):,} objects with observations, {head_all['class_key'].nunique()} classes\")\n"
            "    classes = sorted(head_all['class_key'].unique())\n"
            "    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))\n"
            "    for c in classes:\n"
            "        sub = head_all[head_all['class_key'] == c]\n"
            "        axes[0].hist(sub['REDSHIFT_HELIO'], bins=30, histtype='step', label=c)\n"
            "        axes[1].hist(sub['NOBS'], bins=30, histtype='step', label=c)\n"
            "    axes[0].set_xlabel('REDSHIFT_HELIO'); axes[0].set_ylabel('objects'); axes[0].set_title('Simulated redshift')\n"
            "    axes[1].set_xlabel('NOBS'); axes[1].set_title('Observations per object')\n"
            "    axes[0].legend(fontsize=7)\n"
            "    plt.tight_layout(); plt.show()"
        ),
        new_markdown_cell(
            "## 4. Detection efficiency vs. redshift\n\n"
            "Fraction of objects with `DETECTED == True` in each redshift bin."
        ),
        new_code_cell(
            "if head_all.empty or 'DETECTED' not in head_all:\n"
            "    print('needs head_df.parquet with a DETECTED column')\n"
            "else:\n"
            "    z_bins = np.linspace(0, head_all['REDSHIFT_HELIO'].quantile(0.99), 16)\n"
            "    fig, ax = plt.subplots(figsize=(9, 4.5))\n"
            "    for (c, s), sub in head_all.groupby(['class_key', 'strategy']):\n"
            "        binned = sub.assign(z_bin=pd.cut(sub['REDSHIFT_HELIO'], z_bins))\n"
            "        eff = binned.groupby('z_bin', observed=True)['DETECTED'].mean() * 100\n"
            "        ax.plot([iv.mid for iv in eff.index], eff.to_numpy(), marker='o', ms=3, label=f'{c} ({s})')\n"
            "    ax.set_xlabel('REDSHIFT_HELIO (bin centre)'); ax.set_ylabel('detection efficiency (%)')\n"
            "    ax.set_title('Detection efficiency vs. redshift'); ax.legend(fontsize=7)\n"
            "    plt.tight_layout(); plt.show()"
        ),
        new_markdown_cell(
            "## 5. `phot_df`: SNR, band coverage and example light curves\n\n"
            "Needs the raw photometry (`phot_df.parquet`), which only exists when the sweep was "
            f"generated with *Keep raw photometry*. At most `MAX_PHOT_RUNS` = {MAX_PHOT_RUNS} runs "
            "are loaded."
        ),
        new_code_cell(
            "phot_runs = inventory[inventory['has_phot_df']].head(MAX_PHOT_RUNS) if not inventory.empty else inventory\n"
            "if phot_runs.empty:\n"
            "    print('No run in this sweep kept phot_df.parquet -- generate a new sweep with '\n"
            "          '\"Keep raw photometry\" checked to explore observation-level data.')\n"
            "else:\n"
            "    stats = []\n"
            "    for _, row in phot_runs.iterrows():\n"
            "        p = pd.read_parquet(row['run_dir'] / 'phot_df.parquet')\n"
            "        snr = (p['FLUXCAL'] / p['FLUXCALERR']).abs()\n"
            "        stats.append({'class_key': row['class_key'], 'strategy': row['strategy'],\n"
            "                      'seed_index': row['seed_index'], 'n_obs': len(p),\n"
            "                      'snr_median': snr.median(), 'snr_p90': snr.quantile(0.9),\n"
            "                      **{f'n_{b}': int(n) for b, n in p['FLT'].value_counts().sort_index().items()}})\n"
            "    display(pd.DataFrame(stats))"
        ),
        new_code_cell(
            "if not phot_runs.empty:\n"
            "    row = phot_runs.iloc[0]\n"
            "    p = pd.read_parquet(row['run_dir'] / 'phot_df.parquet')\n"
            "    ids = p['SNID'].unique()\n"
            "    if row['has_head_df']:\n"
            "        h = pd.read_parquet(row['run_dir'] / 'head_df.parquet')\n"
            "        if 'DETECTED' in h and h['DETECTED'].any():\n"
            "            ids = h.loc[h['DETECTED'], 'SNID']\n"
            "    # brightest objects (highest median SNR), same criterion as the QC light-curve panel\n"
            "    best = (p[p['SNID'].isin(ids)].assign(snr=lambda d: (d['FLUXCAL'] / d['FLUXCALERR']).abs())\n"
            "            .groupby('SNID')['snr'].median().sort_values(ascending=False).head(3).index)\n"
            "    fig, axes = plt.subplots(1, len(best), figsize=(5 * len(best), 4), squeeze=False)\n"
            "    for ax, snid in zip(axes[0], best):\n"
            "        lc = p[p['SNID'] == snid]\n"
            "        for band, g in lc.groupby('FLT'):\n"
            "            ax.errorbar(g['MJD'], g['FLUXCAL'], yerr=g['FLUXCALERR'], fmt='o', ms=3, label=band)\n"
            "        ax.set_title(f\"{row['class_key']} ({row['strategy']}) -- SNID {snid}\")\n"
            "        ax.set_xlabel('MJD'); ax.set_ylabel('FLUXCAL'); ax.legend(fontsize=7)\n"
            "    plt.tight_layout(); plt.show()"
        ),
        new_markdown_cell(
            "## 6. DDF vs. WFD\n\n"
            "Side-by-side metrics for every class that has runs in both strategies."
        ),
        new_code_cell(
            "if inventory.empty or inventory['strategy'].nunique() < 2:\n"
            "    print('this sweep has a single strategy -- generate it with both DDF and WFD checked to compare them')\n"
            "else:\n"
            "    pivot = inventory.pivot_table(index='class_key', columns='strategy',\n"
            "                                  values=['detection_efficiency_pct', 'snr_median', 'snr_p90'])\n"
            "    display(pivot.dropna().round(2))"
        ),
        new_markdown_cell(
            "## Next steps\n\n"
            "Download this notebook (**Download .ipynb** on the Explore page) and open it in "
            "JupyterLab to keep exploring: every table above (`inventory`, `head_all`, the "
            "`phot_df` of any run in `inventory['run_dir']`) is a regular pandas DataFrame."
        ),
    ]
    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    return nb


# ------------------------------------------------------------------ ejecucion
def _write_notebook(nb, path: Path) -> None:
    """Escritura atomica: la webapp lee el .ipynb mientras se ejecuta."""
    tmp = path.with_suffix(".ipynb.tmp")
    nbformat.write(nb, tmp)
    tmp.replace(path)


def _write_status(sweep_name: str, runs_dir: Path | None, **fields) -> None:
    path = explore_dir(sweep_name, runs_dir) / "status.json"
    status = sweep_hash.read_json(path) if path.exists() else {}
    status.update(fields)
    sweep_hash.write_json_atomic(path, status)


def _execute(sweep_name: str, runs_dir: Path | None) -> None:
    """Ejecuta el notebook celda por celda, persistiendo despues de cada una."""
    from jupyter_client import KernelManager
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    out_dir = explore_dir(sweep_name, runs_dir)
    nb_path = notebook_path(sweep_name, runs_dir)
    nb = build_notebook(sweep_name, runs_dir)
    _write_notebook(nb, nb_path)
    _write_status(sweep_name, runs_dir, state="running", current_cell=0, n_cells=len(nb.cells),
                  started_at=_now(), finished_at=None, error=None)

    # Kernel por sockets IPC (archivos en out_dir, protegidos por los permisos
    # del home) en vez de TCP en 127.0.0.1: el login node de NLHPC es
    # compartido y asi no queda ningun puerto del kernel expuesto a otros
    # usuarios del mismo nodo.
    km = KernelManager(kernel_name="python3", transport="ipc", ip=str(out_dir / "kernel-ipc"))
    client = NotebookClient(nb, km=km, timeout=CELL_TIMEOUT_S, kernel_name="python3",
                            allow_errors=True, resources={"metadata": {"path": str(out_dir)}})
    try:
        with client.setup_kernel():
            for i, cell in enumerate(nb.cells):
                _write_status(sweep_name, runs_dir, current_cell=i)
                if cell.cell_type == "code":
                    try:
                        client.execute_cell(cell, i)
                    except CellExecutionError:
                        pass  # allow_errors: el traceback ya quedo en la salida de la celda
                _write_notebook(nb, nb_path)
        _write_status(sweep_name, runs_dir, state="done", current_cell=len(nb.cells),
                      finished_at=_now())
    except Exception as e:  # kernel que no arranca, timeout, etc.
        _write_notebook(nb, nb_path)
        _write_status(sweep_name, runs_dir, state="failed", finished_at=_now(),
                      error=f"{type(e).__name__}: {e}")
    finally:
        # Fase 96: con km= propio, nbclient asume que el kernel no es suyo y
        # NO lo apaga al salir de setup_kernel() -- cada exploracion dejaba un
        # proceso ipykernel vivo en el login node (encontrado en la prueba real).
        if km.has_kernel:
            km.shutdown_kernel(now=True)


def start(sweep_name: str, runs_dir: Path | None = None, *, background: bool = True) -> bool:
    """Lanza la exploracion. Devuelve False si ya hay una corriendo para este sweep."""
    sweep_dir = (runs_dir or SWEEP_RUNS_DIR) / sweep_name
    if not (sweep_dir / "manifest.json").exists():
        raise FileNotFoundError(f"sweep '{sweep_name}' has no compiled manifest")
    explore_dir(sweep_name, runs_dir).mkdir(parents=True, exist_ok=True)
    with _RUNNING_LOCK:
        existing = _RUNNING.get(sweep_name)
        if existing is not None and existing.is_alive():
            return False
        thread = threading.Thread(target=_execute, args=(sweep_name, runs_dir), daemon=True)
        _RUNNING[sweep_name] = thread
        # "running" antes de soltar el lock: el primer poll del front ya lo ve
        _write_status(sweep_name, runs_dir, state="running", current_cell=0, started_at=_now(),
                      finished_at=None, error=None)
        thread.start()
    if not background:
        thread.join()
    return True


def is_running(sweep_name: str) -> bool:
    t = _RUNNING.get(sweep_name)
    return t is not None and t.is_alive()


# ------------------------------------------------------------------ render
def _output_html(out: dict) -> str:
    kind = out.get("output_type")
    if kind == "stream":
        return f'<pre class="out-stream">{html.escape(out.get("text", ""))}</pre>'
    if kind == "error":
        from nbconvert.filters import strip_ansi
        tb = strip_ansi("\n".join(out.get("traceback", [])))
        return f'<pre class="out-error">{html.escape(tb)}</pre>'
    data = out.get("data", {})
    if "image/png" in data:
        png = data["image/png"]
        png = png if isinstance(png, str) else base64.b64encode(png).decode()
        return f'<img class="out-img" src="data:image/png;base64,{png.strip()}">'
    if "text/html" in data:
        # tablas de pandas producidas por el codigo de este mismo notebook
        return f'<div class="out-html">{data["text/html"]}</div>'
    if "text/plain" in data:
        return f'<pre class="out-text">{html.escape(data["text/plain"])}</pre>'
    return ""


def state(sweep_name: str, runs_dir: Path | None = None) -> dict:
    """Estado + celdas renderizadas a HTML, para el polling de la webapp."""
    from nbconvert.filters import markdown2html

    status_path = explore_dir(sweep_name, runs_dir) / "status.json"
    nb_path = notebook_path(sweep_name, runs_dir)
    # Bajo el mismo candado que start(): start() escribe state=running y
    # arranca el hilo sin soltarlo, asi que nunca se ve "running" sin hilo vivo
    # por una carrera -- solo cuando el proceso que ejecutaba murio.
    with _RUNNING_LOCK:
        status = sweep_hash.read_json(status_path) if status_path.exists() else {"state": "never_run"}
        alive = is_running(sweep_name)
    if status.get("state") == "running" and not alive:
        status["state"] = "interrupted"
    cells = []
    if nb_path.exists():
        try:
            nb = nbformat.read(nb_path, as_version=4)
        except Exception:  # escritura a medio camino: el proximo poll lo lee bien
            nb = None
        for i, cell in enumerate(nb.cells if nb else []):
            if cell.cell_type == "markdown":
                cells.append({"index": i, "type": "markdown", "html": markdown2html(cell.source)})
            else:
                cells.append({
                    "index": i, "type": "code", "source": cell.source,
                    "execution_count": cell.get("execution_count"),
                    "outputs_html": "".join(_output_html(o) for o in cell.get("outputs", [])),
                    "has_error": any(o.get("output_type") == "error" for o in cell.get("outputs", [])),
                })
    status["cells"] = cells
    return status


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 sweep_explore.py <sweep_name>")
    start(sys.argv[1], background=False)
    st = state(sys.argv[1])
    print(f"{st['state']}: {sum(c.get('has_error', False) for c in st['cells'])} cells with errors "
          f"-> {notebook_path(sys.argv[1])}")
