"""
preflight.py — Validacion pre-vuelo antes de lanzar una campanha.

Verifica que todo lo necesario existe ANTES de gastar tiempo y cola SLURM.
Cada check devuelve (ok, mensaje). Si alguno falla, se aborta con un resumen
claro de que falta.

Checks:
    1. snlc_sim.exe  accesible en $PATH
    2. $SNDATA_ROOT  definido y existente
    3. SIMLIBs referenciados en los survey includes existen en disco
    4. Directorios de modelo / SIMGEN_INCLUDE existen en disco
    5. SLURM (sbatch/squeue) accesible (fatal: es como se lanza cada job)
    6. Un script slurm/run_<GENVERSION>.sh por cada GENVERSION declarada
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    fatal: bool = True     # False = warning


def preflight_check(build_dir: str | Path) -> list[CheckResult]:
    """Corre todos los checks y devuelve la lista de resultados."""
    build_dir = Path(build_dir)
    results: list[CheckResult] = []

    # 1. snlc_sim.exe
    results.append(_check_binary("snlc_sim.exe", "simulador SNANA"))

    # 2. $SNDATA_ROOT
    results.append(_check_sndata_root())

    # 2b. carpeta de datos compartida (Fase 94)
    results.append(_check_alces_data())

    # 3. SIMLIBs
    results.extend(_check_simlibs(build_dir))

    # 4. modelos
    results.extend(_check_models(build_dir))

    # 5. SLURM (fatal: es el mecanismo de lanzamiento en este diseño)
    results.append(_check_slurm())

    # 6. scripts SLURM por GENVERSION
    results.append(_check_slurm_scripts(build_dir))

    return results


def preflight_summary(results: list[CheckResult]) -> tuple[bool, str]:
    """Resumen legible + bool de si pasa."""
    lines = []
    all_ok = True
    for r in results:
        icon = "✓" if r.ok else ("⚠" if not r.fatal else "✗")
        lines.append(f"  {icon} {r.name}: {r.message}")
        if not r.ok and r.fatal:
            all_ok = False
    header = "pre-flight OK ✓" if all_ok else "pre-flight FALLÓ — corregir antes de lanzar"
    return all_ok, header + "\n" + "\n".join(lines)


# ------------------------------------------------------------------ checks
def _check_binary(name: str, desc: str) -> CheckResult:
    path = shutil.which(name)
    if path:
        return CheckResult(name, True, f"encontrado en {path}")
    return CheckResult(name, False, f"{desc} ({name}) no encontrado en $PATH")


def _check_sndata_root() -> CheckResult:
    val = os.environ.get("SNDATA_ROOT")
    if not val:
        return CheckResult("SNDATA_ROOT", False, "variable de entorno no definida")
    p = Path(val)
    if not p.is_dir():
        return CheckResult("SNDATA_ROOT", False, f"definido pero no existe: {val}")
    return CheckResult("SNDATA_ROOT", True, str(p))


def _check_alces_data() -> CheckResult:
    from ..paths import alces_data
    d = alces_data()
    origin = ("ALCES_DATA" if os.environ.get("ALCES_DATA")
              else "SNANA_HOME" if os.environ.get("SNANA_HOME") else "$HOME por defecto")
    if not (d / "run_SNANA").is_dir():
        return CheckResult("ALCES_DATA", False,
                           f"{d} ({origin}) no contiene run_SNANA/ — exportar ALCES_DATA "
                           f"apuntando a la copia compartida (ver INSTALL.md)")
    return CheckResult("ALCES_DATA", True, f"{d} ({origin})")


def _check_simlibs(build_dir: Path) -> list[CheckResult]:
    """Parsea los include_survey_*.INPUT buscando SIMLIB_FILE."""
    inc_dir = build_dir / "includes"
    results = []
    if not inc_dir.is_dir():
        results.append(CheckResult("SIMLIBs", False, f"no existe {inc_dir}"))
        return results
    for f in sorted(inc_dir.glob("include_survey_*.INPUT")):
        for line in f.read_text().splitlines():
            m = re.match(r"SIMLIB_FILE:\s*(.+)", line.strip())
            if m:
                simlib_path = _resolve_snana_path(m.group(1).strip())
                if simlib_path and simlib_path.exists():
                    results.append(CheckResult(
                        f"SIMLIB {f.stem}", True,
                        f"{simlib_path.name} ({simlib_path.stat().st_size / 1e6:.1f} MB)"))
                else:
                    results.append(CheckResult(
                        f"SIMLIB {f.stem}", False,
                        f"no encontrado: {m.group(1).strip()}"))
    return results or [CheckResult("SIMLIBs", True, "(ningún survey include encontrado — ¿dry-run?)")]


def _check_models(build_dir: Path) -> list[CheckResult]:
    """Parsea include_model_*.INPUT buscando PATH_NON1ASED/PATH_SIMSED e INPUT_INCLUDE_FILE."""
    inc_dir = build_dir / "includes"
    results = []
    if not inc_dir.is_dir():
        return results
    files = sorted(inc_dir.glob("include_model_*.INPUT")) + sorted(inc_dir.glob("curated_*.INPUT"))
    for f in files:
        model_name = f.stem.replace("include_model_", "").replace("curated_", "")
        for line in f.read_text().splitlines():
            line = line.split("#", 1)[0]
            for key in ("PATH_NON1ASED:", "PATH_SIMSED:", "INPUT_INCLUDE_FILE:",
                        "GENMODEL:", "GENMODEL_EXTRAP_LATETIME:"):
                if line.strip().startswith(key):
                    path_str = line.strip().split(key, 1)[1].strip()
                    # GENMODEL: "LCLIB <ruta> 1+2+3" / "<ruta>" / "SALT2" (sin ruta)
                    path_str = next((t for t in path_str.split() if "/" in t or "\\" in t), "")
                    if not path_str:
                        continue
                    resolved = _resolve_snana_path(path_str)
                    if resolved and resolved.exists():
                        results.append(CheckResult(
                            f"modelo {model_name}", True, f"{path_str} OK"))
                    elif resolved:
                        results.append(CheckResult(
                            f"modelo {model_name}", False,
                            f"no encontrado: {path_str}"))
                    else:
                        # no se pudo resolver (variable no definida): warning
                        results.append(CheckResult(
                            f"modelo {model_name}", True,
                            f"{path_str} (no se pudo resolver — verificar en NLHPC)",
                            fatal=False))
    return results


def _check_slurm() -> CheckResult:
    sbatch = shutil.which("sbatch")
    squeue = shutil.which("squeue")
    if sbatch and squeue:
        return CheckResult("SLURM", True, "sbatch + squeue disponibles")
    return CheckResult("SLURM", False,
                       "sbatch/squeue no encontrados en $PATH (necesarios para lanzar)")


def _check_slurm_scripts(build_dir: Path) -> CheckResult:
    manifest_path = build_dir / "campaign_manifest.json"
    if not manifest_path.exists():
        return CheckResult("scripts SLURM", False, f"no existe {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    combos = manifest.get("combos", [])
    if not combos:
        return CheckResult("scripts SLURM", False, "la campaña no tiene GENVERSION alguna")
    missing = [c["genversion"] for c in combos
               if not (build_dir / c["slurm_script"]).exists()]
    if missing:
        return CheckResult("scripts SLURM", False,
                           f"faltan {len(missing)}/{len(combos)}: {missing[:3]}…")
    return CheckResult("scripts SLURM", True, f"{len(combos)} script(s) run_<GENVERSION>.sh listos")


def _resolve_snana_path(path_str: str) -> Path | None:
    """Intenta resolver $SNDATA_ROOT/... a una ruta absoluta."""
    expanded = os.path.expandvars(path_str)
    if "$" in expanded:   # variable no resuelta
        return None
    return Path(expanded)
