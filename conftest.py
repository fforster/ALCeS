"""Adapta los tests-script del repo a pytest sin reescribirlos.

Cada archivo de tests define `check(cond, msg)`, que imprime y suma fallas a
un contador global `_fail` del modulo en vez de lanzar AssertionError (asi
el modo script reporta TODOS los checks fallidos, no solo el primero). Aqui:
- un fixture autouse falla el test si `_fail` crecio durante el;
- `keep_phot` (parametro de test_sweep_explore.test_execute) se parametriza;
- se excluyen scripts que no son tests y necesitan datos reales.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# test_opsim_load.py es un script de inspeccion que corre al importarse y
# necesita la OpSim real (data/opsim/*.db) -- no es un test de pytest.
# tests/golden/ corre simulaciones reales en NLHPC (ver run_golden.sbatch).
collect_ignore = [
    "exploration/lightcurvelynx/test_opsim_load.py",
    "tests/golden",
]

# test_sweep_explore.py importa run_simsed_poc via sweep_compile, y con el
# lightcurvelynx (que trae sncosmo, sin wheel en algunas plataformas). Donde
# no este instalado se omite en vez de romper toda la coleccion.
try:
    import lightcurvelynx  # noqa: F401
except ImportError:
    collect_ignore.append("exploration/lightcurvelynx/test_sweep_explore.py")


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    # Dentro de la llamada del test (no en un fixture teardown) para que un
    # check fallido cuente como FAILED y no como ERROR.
    module = pyfuncitem.module
    before = getattr(module, "_fail", None)
    outcome = yield
    if before is not None and outcome.excinfo is None:
        failed = module._fail - before
        if failed:
            outcome.force_exception(AssertionError(
                f"{failed} check(s) fallaron -- ver la salida capturada"))


def pytest_generate_tests(metafunc):
    if "keep_phot" in metafunc.fixturenames:
        metafunc.parametrize("keep_phot", [True, False])
