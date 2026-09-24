"""
Pruebas de la Fase 95 (sweep_explore.py + rutas /explore de la webapp).
Necesita el venv del proyecto (nbclient, ipykernel, pandas, pyarrow, flask):
    python3 test_sweep_explore.py
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import nbformat

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sweep_explore

_fail = 0
def check(cond, msg):
    global _fail
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond: _fail += 1


def make_sweep(runs_dir: Path, name: str, keep_phot: bool) -> None:
    """Sweep sintetico con la misma estructura que escribe sweep_worker.py."""
    rng = np.random.default_rng(0)
    runs = []
    for i, (cls, wfd) in enumerate([("SNIa-91bg", False), ("SNIa-91bg", True)]):
        h = f"{i:012x}"
        run_dir = runs_dir / name / "runs" / h
        run_dir.mkdir(parents=True)
        n = 200
        head = pd.DataFrame({
            "SNID": np.arange(n), "SNTYPE": 1, "RA": 0.0, "DEC": 0.0,
            "REDSHIFT_HELIO": rng.uniform(0.01, 1.0, n), "PEAKMJD": 61000.0,
            "NOBS": rng.integers(1, 60, n), "DETECTED": rng.random(n) < 0.4,
        })
        head.to_parquet(run_dir / "head_df.parquet")
        if keep_phot and i == 0:
            m = 2000
            pd.DataFrame({
                "SNID": rng.integers(0, n, m), "MJD": rng.uniform(61000, 61100, m),
                "FLT": rng.choice(list("ugrizY"), m), "FLUXCAL": rng.normal(50, 20, m),
                "FLUXCALERR": rng.uniform(1, 10, m), "FLUXTRUE": 50.0,
            }).to_parquet(run_dir / "phot_df.parquet")
        (run_dir / "run_hash.json").write_text(json.dumps({"status": "done", "run_hash": h}))
        (run_dir / "summary.json").write_text(json.dumps({
            "class_key": cls, "strategy": "WFD" if wfd else "DDF", "ngentot_lc": n,
            "n_detected": int(head["DETECTED"].sum()),
            "detection_efficiency_pct": 100 * head["DETECTED"].mean(),
            "snr_median": 3.2, "snr_p90": 9.1, "z_max_simulado": 0.99, "z_max_detectado": 0.9,
        }))
        runs.append({"class_key": cls, "index": i, "ngentot": n, "output_dir": f"runs/{h}",
                     "run_hash": h, "seed_index": 0, "wfd": wfd})
    (runs_dir / name / "manifest.json").write_text(json.dumps({
        "sweep_name": name, "n_runs": len(runs), "keep_phot": keep_phot,
        "compiled_at": "2026-09-24T00:00:00+00:00", "runs": runs,
    }))


def test_execute(keep_phot: bool):
    print(f"test_execute(keep_phot={keep_phot})")
    with tempfile.TemporaryDirectory() as t:
        runs_dir = Path(t)
        make_sweep(runs_dir, "synthetic", keep_phot)
        check(sweep_explore.state("synthetic", runs_dir)["state"] == "never_run",
              "state=never_run antes de ejecutar")
        check(sweep_explore.start("synthetic", runs_dir, background=False), "start() ejecuta")
        st = sweep_explore.state("synthetic", runs_dir)
        check(st["state"] == "done", f"state=done (fue {st['state']}, error={st.get('error')})")
        code = [c for c in st["cells"] if c["type"] == "code"]
        errs = [c for c in code if c["has_error"]]
        check(not errs, f"0 celdas con error ({len(errs)}: "
                        f"{[c['outputs_html'][-300:] for c in errs][:1]})")
        check(all(c["execution_count"] for c in code), "todas las celdas de codigo ejecutadas")
        n_img = sum(c["outputs_html"].count("<img") for c in code)
        check(n_img >= 3, f"graficos embebidos en las salidas ({n_img} <img>)")
        allout = "".join(c["outputs_html"] for c in code)
        if keep_phot:
            check("n_obs" in allout and "snr_p90" in allout, "seccion phot_df con tabla de SNR/bandas")
        else:
            check("Keep raw photometry" in allout, "sin phot_df: aviso en vez de fallar")
        check("<table" in allout, "tablas de pandas renderizadas como HTML")
        nb = nbformat.read(sweep_explore.notebook_path("synthetic", runs_dir), as_version=4)
        nbformat.validate(nb)
        check(True, ".ipynb ejecutado valido (nbformat.validate)")
        # Fase 96: el kernel no debe quedar vivo al terminar (antes quedaba uno por exploracion)
        import os, subprocess
        if os.name == "posix":
            import time; time.sleep(1)
            kids = subprocess.run(["pgrep", "-P", str(os.getpid()), "-f", "ipykernel"],
                                  capture_output=True, text=True).stdout.split()
            check(not kids, f"sin kernels huerfanos tras la ejecucion ({kids})")


def test_webapp_routes():
    print("test_webapp_routes")
    sys.path.insert(0, str(HERE / "webapp"))
    import app as webapp
    with tempfile.TemporaryDirectory() as t:
        runs_dir = Path(t)
        make_sweep(runs_dir, "synthetic", keep_phot=False)
        old = webapp.SWEEP_RUNS_DIR
        webapp.SWEEP_RUNS_DIR = runs_dir
        try:
            c = webapp.app.test_client()
            check(c.get("/sweep/..%2Fetc/explore").status_code == 404, "nombre invalido -> 404")
            check(c.get("/sweep/no_such_sweep/explore/state").status_code == 404,
                  "sweep inexistente -> 404 JSON")
            r = c.get("/sweep/synthetic/explore")
            check(r.status_code == 200 and b"Run exploration" in r.data, "pagina /explore en ingles")
            sweep_explore.start("synthetic", runs_dir, background=False)
            r = c.get("/sweep/synthetic/explore/state")
            check(r.status_code == 200 and r.get_json()["state"] == "done", "/explore/state JSON done")
            r = c.get("/sweep/synthetic/explore/notebook.ipynb")
            check(r.status_code == 200 and b'"cells"' in r.data, "descarga del .ipynb")
        finally:
            webapp.SWEEP_RUNS_DIR = old


if __name__ == "__main__":
    test_execute(keep_phot=True)
    test_execute(keep_phot=False)
    test_webapp_routes()
    print(f"\n{'OK' if not _fail else f'{_fail} FALLOS'}")
    sys.exit(1 if _fail else 0)
