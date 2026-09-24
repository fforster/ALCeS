"""
Pruebas de la Fase 94 (rutas portables entre cuentas NLHPC).
Se pueden correr con:  python tests/test_paths_portability.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from pipeline import paths
from pipeline.campaign import compile_campaign
from pipeline.campaign.compiler import CampaignError
from pipeline.orchestrate.preflight import _check_alces_data, _check_models

REPO = Path(__file__).resolve().parent.parent

_fail = 0
def check(cond, msg):
    global _fail
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond: _fail += 1


class env:
    """Fija/borra variables de entorno durante un bloque."""
    def __init__(self, **kv):
        self.kv, self.old = kv, {}
    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


# --------- resolucion de ALCES_DATA ---------
def test_alces_data():
    print("test_alces_data")
    with env(ALCES_DATA="/shared/alces", SNANA_HOME="/viejo"):
        check(paths.alces_data() == Path("/shared/alces"), "ALCES_DATA tiene prioridad")
    with env(ALCES_DATA=None, SNANA_HOME="/viejo"):
        check(paths.alces_data() == Path("/viejo"), "SNANA_HOME sigue aceptado como alias")
    with env(ALCES_DATA=None, SNANA_HOME=None):
        check(paths.alces_data() == Path.home(), "sin variables cae a $HOME (cuenta original)")


def test_expand_path():
    print("test_expand_path")
    with env(ALCES_DATA="/shared/alces", SNDATA_ROOT="/u/sndata"):
        got = paths.expand_path("${ALCES_DATA}/run_SNANA/X.DAT")
        check(got == f"{Path('/shared/alces')}/run_SNANA/X.DAT", f"${{ALCES_DATA}} expandida: {got}")
        got = paths.expand_path("$SNDATA_ROOT/models/Y")
        check(got == "/u/sndata/models/Y", f"$SNDATA_ROOT expandida: {got}")
        got = paths.expand_path("${ALCES_REPO}/pipeline/kcor/kcor_LSST.fits")
        check(got == f"{paths.repo_root()}/pipeline/kcor/kcor_LSST.fits",
              "${ALCES_REPO} = raiz del repo aunque no este exportada")
    with env(NO_EXISTE_X=None):
        try:
            paths.expand_path("$NO_EXISTE_X/a")
            check(False, "variable indefinida deberia abortar")
        except paths.UnresolvedPathError:
            check(True, "variable indefinida aborta con UnresolvedPathError")


def test_expand_alces_vars():
    print("test_expand_alces_vars")
    with env(ALCES_DATA="/shared/alces"):
        txt = "GENMODEL: ${ALCES_DATA}/run_SNANA/m\nPATH_NON1ASED: $SNDATA_ROOT/models/n\n"
        got = paths.expand_alces_vars(txt)
        check(f"{Path('/shared/alces')}/run_SNANA/m" in got, "expande ${ALCES_DATA} en el texto")
        check("$SNDATA_ROOT/models/n" in got, "deja $SNDATA_ROOT para SNANA")


# --------- compilador con un SIMGEN_INCLUDE de la copia compartida ---------
def _mini_campaign(tmp: Path, data: Path) -> Path:
    inc = data / "run_SNANA" / "model_config" / "SIMGEN_INCLUDE_Test.INPUT"
    inc.parent.mkdir(parents=True)
    inc.write_text("GENMODEL: ${ALCES_DATA}/run_SNANA/plasticc_models/SIMSED.Test\n"
                   "GENMODEL_EXTRAP_LATETIME: ${ALCES_DATA}/run_SNANA/late.TEXT\n"
                   "PATH_NON1ASED: $SNDATA_ROOT/models/NON1ASED/V19\n", encoding="utf-8")
    (data / "run_SNANA" / "plasticc_models" / "SIMSED.Test").mkdir(parents=True)
    models = {"Test": {"simgen_include":
                       "${ALCES_DATA}/run_SNANA/model_config/SIMGEN_INCLUDE_Test.INPUT"}}
    (tmp / "models.yaml").write_text(yaml.safe_dump(models), encoding="utf-8")
    camp = {
        "name": "fase94", "models_catalog": str(tmp / "models.yaml"),
        "runs": [{"run": "baseline_v5.3.1_10yrs", "strategies": ["WFD"]}],
        "classes": [{"model": "Test"}],
        "defaults": {
            "kcor_file": "${ALCES_REPO}/pipeline/kcor/kcor_LSST.fits",
            "searcheff_pipeline_file": "${ALCES_DATA}/run_SNANA/LSST_SEARCHEFF_PIPELINE.DAT",
            "searcheff_pipeline_logic_file": "${ALCES_DATA}/run_SNANA/LSST_PIPELINE_LOGIC.DAT",
        },
        "batch": {"snana_login_setup":
                  "export PATH=${ALCES_DATA}/bin/snana_custom:${ALCES_REPO}/bin/snana_custom:$PATH"},
    }
    p = tmp / "camp.yaml"
    p.write_text(yaml.safe_dump(camp, sort_keys=False), encoding="utf-8")
    return p


def test_compile_materializes():
    print("test_compile_materializes")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); data = tmp / "alces_data"
        camp = _mini_campaign(tmp, data)
        with env(ALCES_DATA=str(data), SNDATA_ROOT=str(tmp)):
            plan = compile_campaign(camp, out_dir=tmp / "build")
        inc_dir = plan.out_dir / "includes"
        curated = inc_dir / "curated_Test.INPUT"
        check(curated.is_file(), "copia expandida curated_Test.INPUT escrita")
        ctext = curated.read_text(encoding="utf-8")
        check("${ALCES_DATA}" not in ctext and str(data) in ctext,
              "la copia ya no tiene ${ALCES_DATA}")
        check("$SNDATA_ROOT/models/NON1ASED/V19" in ctext, "la copia conserva $SNDATA_ROOT")
        mtext = (inc_dir / "include_model_Test.INPUT").read_text(encoding="utf-8")
        check(str(curated.resolve()) in mtext, "include_model apunta a la copia expandida")
        stext = next(inc_dir.glob("include_survey_*.INPUT")).read_text(encoding="utf-8")
        check(f"SEARCHEFF_PIPELINE_FILE: {data}" in stext, "SEARCHEFF expandido en el survey include")
        check(f"KCOR_FILE: {paths.repo_root()}" in stext, "KCOR expandido a la raiz del repo")
        sh = next((plan.out_dir / "slurm").glob("*.sh")).read_text(encoding="utf-8")
        check(f"{data}/bin/snana_custom" in sh and "${ALCES" not in sh,
              "PATH del job SLURM fijado al compilar")

        # preflight: detecta el GENMODEL que falta (late.TEXT no existe)
        res = _check_models(plan.out_dir)
        bad = [r for r in res if not r.ok and "late.TEXT" in r.message]
        good = [r for r in res if r.ok and "SIMSED.Test" in r.message]
        check(bool(bad), "preflight marca GENMODEL_EXTRAP_LATETIME inexistente")
        check(bool(good), "preflight acepta GENMODEL existente en la copia")
        with env(ALCES_DATA=str(data)):
            check(_check_alces_data().ok, "preflight ALCES_DATA OK con run_SNANA/")
        with env(ALCES_DATA=str(tmp / "no_existe")):
            check(not _check_alces_data().ok, "preflight ALCES_DATA falla sin run_SNANA/")


def test_compile_unresolved_var_aborts():
    print("test_compile_unresolved_var_aborts")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); data = tmp / "alces_data"
        camp = _mini_campaign(tmp, data)
        with env(ALCES_DATA=str(data), SNDATA_ROOT=None):
            c = yaml.safe_load(camp.read_text())
            c["defaults"]["kcor_file"] = "$SNDATA_ROOT/kcor.fits"
            camp.write_text(yaml.safe_dump(c, sort_keys=False))
            try:
                compile_campaign(camp, out_dir=tmp / "build")
                check(False, "deberia abortar con $SNDATA_ROOT indefinida")
            except CampaignError as e:
                check("SNDATA_ROOT" in str(e), "aborta al compilar, no dentro del job SLURM")


# --------- regresion: la config del repo ya no apunta a una cuenta ---------
def test_repo_config_portable():
    print("test_repo_config_portable")
    for rel in ("pipeline/models.yaml", "campaigns/full_v5.3.yaml", "campaigns/test_small.yaml"):
        data = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
        blob = yaml.safe_dump(data)   # solo valores: los comentarios historicos no cuentan
        check("/home/mvalenzuela" not in blob, f"{rel}: sin rutas a /home/mvalenzuela")


if __name__ == "__main__":
    test_alces_data()
    test_expand_path()
    test_expand_alces_vars()
    test_compile_materializes()
    test_compile_unresolved_var_aborts()
    test_repo_config_portable()
    print(f"\n{'OK' if not _fail else f'{_fail} FALLOS'}")
    sys.exit(1 if _fail else 0)
