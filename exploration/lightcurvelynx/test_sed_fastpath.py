"""
Prueba de la Fase 98: three_column_to_matrix_vectorized() (run_simsed_poc.py)
tiene que dar EXACTAMENTE lo mismo que SEDTemplate._three_column_to_matrix de
LightCurveLynx, incluidos los casos raros: filas desordenadas, pares (fase,
lambda) faltantes (quedan en 0.0) y pares repetidos (gana la ultima fila).
Necesita lightcurvelynx (venv de NLHPC o CI); donde no esta, se omite.
    python3 test_sed_fastpath.py
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_fail = 0
def check(cond, msg):
    global _fail
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond: _fail += 1


def _cases():
    rng = np.random.default_rng(0)
    phases = np.round(np.arange(-2.0, 25.0, 0.1), 4)
    waves = np.arange(1000.0, 30000.0, 37.0)
    grid = np.array([(p, w) for p in phases for w in waves])
    full = np.column_stack([grid, rng.lognormal(size=len(grid))])
    yield "grilla completa ordenada (forma real de un .SED)", full
    yield "filas desordenadas", full[rng.permutation(len(full))]
    yield "pares faltantes", full[rng.random(len(full)) > 0.3]
    dup = full[rng.integers(0, len(full), 500)].copy()
    dup[:, 2] = rng.lognormal(size=len(dup))
    yield "pares repetidos con flujo distinto", np.vstack([full, dup])[rng.permutation(len(full) + 500)]
    yield "flujos negativos y cero", np.column_stack([grid, rng.normal(size=len(grid)) * (rng.random(len(grid)) > 0.5)])


def test_identical_to_library():
    print("test_identical_to_library")
    try:
        from run_simsed_poc import three_column_to_matrix_vectorized
        from lightcurvelynx.models.sed_template_model import SEDTemplate
    except ImportError:
        print("  - omitido: lightcurvelynx no instalado")
        return
    original = SEDTemplate._three_column_to_matrix
    for name, data in _cases():
        a = original(data)
        b = three_column_to_matrix_vectorized(data)
        same = all(x.shape == y.shape and x.dtype == y.dtype and np.array_equal(x.view(np.uint64), y.view(np.uint64))
                   for x, y in zip(a, b))
        check(same, f"identico bit a bit: {name}")


def test_patch_is_scoped():
    print("test_patch_is_scoped")
    try:
        import run_simsed_poc as r
        from lightcurvelynx.models.sed_template_model import SEDTemplate
    except ImportError:
        print("  - omitido: lightcurvelynx no instalado")
        return
    before = SEDTemplate.__dict__["_three_column_to_matrix"]
    try:
        with r._fast_three_column_to_matrix():
            check(SEDTemplate._three_column_to_matrix is r.three_column_to_matrix_vectorized,
                  "dentro del bloque se usa la version vectorizada")
            raise RuntimeError("forzar salida por excepcion")
    except RuntimeError:
        pass
    check(SEDTemplate.__dict__["_three_column_to_matrix"] is before,
          "al salir (incluso por excepcion) vuelve el original de la libreria")


if __name__ == "__main__":
    test_identical_to_library()
    test_patch_is_scoped()
    print(f"\n{'OK' if not _fail else f'{_fail} FALLOS'}")
    sys.exit(1 if _fail else 0)
