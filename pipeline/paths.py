"""
paths.py — Resolucion de rutas del pipeline.

Objetivo: que cualquier script (o capa) sepa donde esta la raiz del repo y
donde viven las bases OpSim descargadas, sin rutas absolutas hardcodeadas.

Orden de resolucion del directorio de datos:
    1. variable de entorno  RUBIN_OPSIM_DIR  (util en NLHPC / SLURM)
    2. clave  defaults.data_dir  en opsims.yaml
    3. por defecto:  <repo_root>/data/opsim
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Marcadores que identifican la raiz del repositorio al subir por el arbol.
_ROOT_MARKERS = ("pipeline/opsims.yaml", ".git", "pyproject.toml")


class LoginNodeError(SystemExit):
    """Se lanza cuando un paso pesado intenta correr fuera de un job SLURM."""


def require_slurm(step: str, sbatch_hint: str, *, allow_flag: bool = False) -> None:
    """Aborta si el paso pesado se esta corriendo fuera de un job SLURM.

    NLHPC banea/reta a quien corre computo pesado en el login node (ya paso
    una vez con este proyecto). La deteccion es simple: dentro de un job
    lanzado por `sbatch`/`srun`, SLURM siempre exporta `SLURM_JOB_ID`; en el
    login node esa variable no existe.

    `allow_flag=True` es el escape manual (`--allow-login`) para los casos
    que el propio README documenta como aceptables en login (p.ej. una
    campanha de prueba con 2-3 clases) — igual imprime una advertencia
    visible para que quede claro que fue una decision explicita.
    """
    if os.environ.get("SLURM_JOB_ID"):
        return  # corriendo dentro de un job SLURM real: OK

    if allow_flag or os.environ.get("ALCES_ALLOW_LOGIN") == "1":
        print(
            f"  ⚠ ADVERTENCIA: corriendo «{step}» en el login node por override explicito "
            f"(--allow-login). Solo para pruebas chicas — NLHPC puede advertir/banear el uso "
            f"de computo pesado en login.",
            file=sys.stderr,
        )
        return

    print(
        "\n"
        "  ✗ ✗ ✗  BLOQUEADO: este paso NO se puede correr en el login node.  ✗ ✗ ✗\n"
        f"\n"
        f"  «{step}» es computo pesado. NLHPC ya advirtio por esto una vez —\n"
        f"  correrlo interactivo en el login afecta a todos los usuarios del cluster.\n"
        f"\n"
        f"  Correcto (via SLURM):\n"
        f"      {sbatch_hint}\n"
        f"\n"
        f"  Si de verdad sabes que este caso es chico y aceptable en login\n"
        f"  (ver README, seccion 'Flujo completo de ejecucion'), puedes forzarlo con:\n"
        f"      --allow-login\n"
        f"  o exportando ALCES_ALLOW_LOGIN=1 — pero es la excepcion, no la regla.\n",
        file=sys.stderr,
    )
    raise LoginNodeError(3)


def repo_root(start: Path | str | None = None) -> Path:
    """Devuelve la raiz del repo buscando hacia arriba desde `start`.

    Si no encuentra ningun marcador, cae al directorio padre de este archivo
    (asumiendo la disposicion  <repo>/pipeline/paths.py).
    """
    here = Path(start or __file__).resolve()
    for parent in [here, *here.parents]:
        for marker in _ROOT_MARKERS:
            if (parent / marker).exists():
                return parent
    # Fallback: <repo>/pipeline/paths.py  ->  <repo>
    return Path(__file__).resolve().parent.parent


def alces_data() -> Path:
    """Carpeta con los datos SNANA curados del proyecto (Fase 94).

    Contiene `run_SNANA/` (plantillas, SEARCHEFF, SIMGEN_INCLUDE) y
    `OTMODEL_NON1ASED/`. Pensada para ser UNA copia compartida de solo
    lectura para todo el equipo en NLHPC. Orden de resolucion:
        1. variable de entorno  ALCES_DATA
        2. variable de entorno  SNANA_HOME  (nombre heredado de la Fase 74)
        3. el $HOME del usuario (cuenta original: /home/mvalenzuela)
    """
    val = os.environ.get("ALCES_DATA") or os.environ.get("SNANA_HOME")
    return Path(val).expanduser() if val else Path.home()


class UnresolvedPathError(ValueError):
    """Una ruta del catalogo/campanha usa una variable que no esta definida."""


def expand_path(path_str: str) -> str:
    """Expande las variables de ruta portables usadas en models.yaml,
    campaigns/*.yaml y los SIMGEN_INCLUDE de la copia compartida:

        ${ALCES_DATA}   -> alces_data()   (aunque no este exportada)
        ${ALCES_REPO}   -> raiz del repo  (aunque no este exportada)
        $SNDATA_ROOT    -> la del usuario (debe estar exportada)
        ~               -> $HOME

    Aborta si queda alguna variable sin resolver: SNANA la dejaria tal cual
    y fallaria dentro del job SLURM, lejos de la causa real.
    """
    env = dict(os.environ)
    env["ALCES_DATA"] = str(alces_data())
    env["ALCES_REPO"] = str(repo_root())
    expanded = os.path.expanduser(path_str)
    for var in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", expanded):
        if var not in env:
            raise UnresolvedPathError(
                f"variable ${var} no definida en la ruta {path_str!r} "
                f"(¿falta 'source activate_all.sh'?)")
    return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env[m.group(1)], expanded)


def expand_alces_vars(text: str) -> str:
    """Expande SOLO ${ALCES_DATA}/${ALCES_REPO} dentro del texto de un
    SIMGEN_INCLUDE. $SNDATA_ROOT y el resto se dejan tal cual: SNANA ya los
    expande solo, y el job SLURM exporta SNDATA_ROOT."""
    subs = {"ALCES_DATA": str(alces_data()), "ALCES_REPO": str(repo_root())}
    return re.sub(r"\$\{?(ALCES_DATA|ALCES_REPO)\}?", lambda m: subs[m.group(1)], text)


def data_dir(default_from_yaml: str | None = None) -> Path:
    """Directorio local donde se guardan los .db de OpSim.

    Crea el directorio si no existe. Ver orden de resolucion en el modulo.
    """
    env = os.environ.get("RUBIN_OPSIM_DIR")
    if env:
        d = Path(env).expanduser()
    elif default_from_yaml:
        d = (repo_root() / default_from_yaml).resolve()
    else:
        d = repo_root() / "data" / "opsim"
    d.mkdir(parents=True, exist_ok=True)
    return d


def curated_registry_path() -> Path:
    """Ruta al registro curado (versionado en git)."""
    return repo_root() / "pipeline" / "opsims.yaml"


def local_registry_path() -> Path:
    """Ruta al registro local auto-gestionado (checksums, altas locales; NO en git)."""
    return repo_root() / "pipeline" / "opsims.local.yaml"
