"""
Fase 66: compilador de barridos (sweeps) -- YAML declarativo ->
manifest.json + un script sbatch de job array por tier de recursos.

Reemplaza el flujo real de escribir `.sh` a mano cada ronda de
investigacion (confirmado en NOTES.md: un bug real recurrio por eso --
`$([ N -ne 0 ] && echo _seedN)` bajo `set -e` rompia silenciosamente la
semilla 0). Con esto, un unico script de array por tier cubre TODA la
matriz clase x semilla x modo del sweep.

Requiere el venv de LightCurveLynx activado (importa CLASS_CONFIGS real
de run_simsed_poc.py para validar los nombres de clase del YAML) --
no se puede compilar "en frio" desde la maquina local del usuario.

Uso:
    module load python/3.12.3-legacy-skylake && source venv/bin/activate
    python3 sweep_compile.py sweeps/<archivo>.yaml [--force]
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import sweep_hash
from sweep_history import record_event
from run_simsed_poc import CLASS_CONFIGS, HERE, NGENTOT_LC, resolve_effective_class_config

SWEEP_RUNS_DIR = HERE / "sweep_runs"
# Fase 66, riesgo #5 del plan: un YAML mal editado puede disparar N jobs
# pesados de una sola vez ("un click amplifica el radio de daño"). Ningun
# ngentot historico de este proyecto se acerco a esto (2000 tipico, 20000
# solo para PISN-STELLA-HYDROGENIC) -- una advertencia fuerte, no un error
# duro, porque puede ser intencional en una fase futura.
NGENTOT_WARN_THRESHOLD = 5000


def load_sweep_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def resolve_tier(class_key: str, resources: dict) -> str:
    """tier == class_key si esa clase tiene un override de recursos propio,
    "default" si no. Evitar un tier generico "heavy" compartido evita el
    problema real de mezclar 2 clases con perfiles de recursos DISTINTOS
    bajo el mismo array (cada clase con override propio -> su propio
    array, sin ambiguedad posible)."""
    overrides = resources.get("overrides", {})
    return class_key if class_key in overrides else "default"


def build_runs(sweep_cfg: dict, code_hash_value: str) -> list[dict]:
    classes = sweep_cfg["classes"]
    seeds = sweep_cfg["seeds"]
    modes = sweep_cfg.get("modes") or [{"wfd": False, "simsed_t0_mode": "bolometric_peak"}]
    ngentot_overrides = sweep_cfg.get("ngentot_overrides") or {}
    # Fase 93: mapa plano class_key -> z_max (float), mismo patron que
    # ngentot_overrides -- clase sin entrada = sin override, usa el
    # genrange_redshift nominal de CLASS_CONFIGS sin cambios.
    z_max_overrides = sweep_cfg.get("z_max_overrides") or {}
    resources = sweep_cfg.get("resources") or {"default": {"mem": "16G", "time": "02:00:00", "cpus": 4}}

    unknown = [c for c in classes if c not in CLASS_CONFIGS]
    if unknown:
        raise ValueError(
            f"Unknown classes (not in CLASS_CONFIGS of run_simsed_poc.py): {unknown}"
        )

    rows = []
    for class_key in classes:
        z_max_override = z_max_overrides.get(class_key)
        # Fase 93: cfg EFECTIVO (con z_max parchado si hay override, ver
        # resolve_effective_class_config) -- es lo que se pasa a
        # sweep_hash.run_hash() mas abajo, asi el run_hash cambia solo
        # cuando el override es real (sin override, es el mismo objeto
        # CLASS_CONFIGS[class_key] de siempre -- mismo hash que antes de
        # esta fase). Puede levantar ValueError (override invalido, p.ej.
        # z_max <= z_min nominal) -- se deja propagar, mismo criterio que
        # el chequeo de "clases desconocidas" de arriba.
        cfg = resolve_effective_class_config(class_key, z_max_override)
        tier = resolve_tier(class_key, resources)
        ngentot = ngentot_overrides.get(class_key, cfg.get("ngentot_lc", NGENTOT_LC))
        if ngentot > NGENTOT_WARN_THRESHOLD:
            print(f"  ! ADVERTENCIA: {class_key} ngentot={ngentot} supera el umbral historico de "
                  f"este proyecto ({NGENTOT_WARN_THRESHOLD}) -- confirmar que es intencional antes de lanzar.")
        for mode in modes:
            wfd = bool(mode.get("wfd", False))
            simsed_t0_mode = mode.get("simsed_t0_mode", "bolometric_peak")
            for seed_index in seeds:
                full, short = sweep_hash.run_hash(
                    class_key=class_key, class_config=cfg, seed_index=seed_index,
                    wfd=wfd, simsed_t0_mode=simsed_t0_mode, ngentot=ngentot,
                    code_hash_value=code_hash_value,
                )
                rows.append(dict(
                    run_hash=short, run_hash_full=full, class_key=class_key,
                    seed_index=seed_index, wfd=wfd, simsed_t0_mode=simsed_t0_mode,
                    ngentot=ngentot, tier=tier, z_max_override=z_max_override,
                ))

    # agrupar por tier ANTES de asignar indice -- asi cada tier obtiene un
    # rango de array CONTIGUO (0-N, N+1-M, ...), sin sintaxis de array
    # dispersa (--array=0,3,7,...), mas fragil de generar y de leer.
    rows.sort(key=lambda r: (r["tier"] != "default", r["tier"], r["class_key"], r["seed_index"]))
    seen_hashes: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r["run_hash"] in seen_hashes:
            other = rows[seen_hashes[r["run_hash"]]]
            raise ValueError(
                f"run_hash collision between two rows of the sweep: "
                f"{other['class_key']}/seed{other['seed_index']} and {r['class_key']}/seed{r['seed_index']} "
                f"-- this should never happen unless the hash scheme has a bug; not compiling."
            )
        seen_hashes[r["run_hash"]] = i
        r["index"] = i
        r["output_dir"] = f"runs/{r['run_hash']}"
        r["status"] = "pending"
        r["slurm_job_id"] = None
    return rows


def tier_ranges(rows: list[dict]) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    for r in rows:
        t = r["tier"]
        lo, hi = ranges.get(t, (r["index"], r["index"]))
        ranges[t] = (min(lo, r["index"]), max(hi, r["index"]))
    return ranges


SBATCH_TEMPLATE = """#!/bin/bash
#SBATCH -J sweep_{sweep_name}_{tier}
#SBATCH -p {partition}
#SBATCH -n 1
#SBATCH -c {cpus}
#SBATCH --mem={mem}
#SBATCH -t {time}
#SBATCH --array={lo}-{hi}%{max_concurrent}
#SBATCH -o exploration/lightcurvelynx/sweep_runs/{sweep_name}/logs/%A_%a.out
#SBATCH -e exploration/lightcurvelynx/sweep_runs/{sweep_name}/logs/%A_%a.err

# Nota real (Fase 66): #SBATCH -o/-e se resuelven por SLURM relativos al
# directorio desde donde se corrio `sbatch` ($SLURM_SUBMIT_DIR), ANTES de
# que corra cualquier `cd` de este script -- por eso van con el path
# completo `exploration/lightcurvelynx/...` arriba. La convencion real de
# este proyecto es correr `sbatch` desde ~/AUTOSIM (confirmado en todas
# las rondas anteriores de investigacion), asi que este script asume lo
# mismo y hace su propio `cd` al subdirectorio real del venv/codigo.
cd "$SLURM_SUBMIT_DIR/exploration/lightcurvelynx"
module load python/3.12.3-legacy-skylake
source venv/bin/activate
# Fase 65/66: el font cache de matplotlib puede fallar por si solo cuando
# el cupo de disco esta ajustado, y enmascara el error real (visto
# literalmente en Fase 65). Aislar el cache por tarea del array evita esa
# confusion sin depender de que ~/.cache tenga espacio libre.
export MPLCONFIGDIR="${{TMPDIR:-/tmp}}/mplcache_${{SLURM_JOB_ID}}_${{SLURM_ARRAY_TASK_ID}}"
python3 sweep_worker.py --manifest sweep_runs/{sweep_name}/manifest.json --index "$SLURM_ARRAY_TASK_ID"
"""


def compile_sweep(yaml_path: Path, force: bool = False, triggered_by: str = "cli") -> Path:
    yaml_path = Path(yaml_path)
    sweep_cfg = load_sweep_yaml(yaml_path)
    sweep_name = sweep_cfg["sweep_name"]
    out_dir = SWEEP_RUNS_DIR / sweep_name
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists() and not force:
        raise FileExistsError(
            f"{manifest_path} already exists -- pass --force to recompile. "
            f"Careful: recompiling changes the run_hash values if CLASS_CONFIGS or the code changed; "
            f"runs launched under the old manifest become orphaned (their results in "
            f"runs/<old-hash>/ remain valid, the new manifest just does not list them)."
        )

    code_hash_value = sweep_hash.code_hash(HERE)
    print(f"code_hash: {code_hash_value}")
    rows = build_runs(sweep_cfg, code_hash_value)

    resources = sweep_cfg.get("resources") or {"default": {"mem": "16G", "time": "02:00:00", "cpus": 4}}
    max_concurrent = sweep_cfg.get("max_concurrent") or {"default": 8}
    partition = sweep_cfg.get("partition", "general")

    ranges = tier_ranges(rows)
    array_scripts = []
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)
    for tier, (lo, hi) in sorted(ranges.items()):
        if tier == "default":
            res = dict(resources.get("default", {}))
            mc = max_concurrent.get("default", 8)
        else:
            res = {**resources.get("default", {}), **resources.get("overrides", {}).get(tier, {})}
            mc = max_concurrent.get("override", max_concurrent.get("default", 8))
        script_name = f"array_{tier}.sbatch"
        script_text = SBATCH_TEMPLATE.format(
            sweep_name=sweep_name, tier=tier, partition=partition,
            cpus=res.get("cpus", 4), mem=res.get("mem", "16G"), time=res.get("time", "02:00:00"),
            lo=lo, hi=hi, max_concurrent=mc,
        )
        script_path = out_dir / script_name
        script_path.write_text(script_text, encoding="utf-8")
        array_scripts.append(dict(
            tier=tier, script=script_name, array_range=f"{lo}-{hi}",
            max_concurrent=mc, slurm_array_job_id=None,
        ))
        print(f"  generado {script_path} (array {lo}-{hi}%{mc}, mem={res.get('mem', '16G')})")

    manifest = dict(
        sweep_name=sweep_name,
        sweep_yaml=str(yaml_path),
        sweep_yaml_sha256=sweep_hash.sha256_hex(yaml_path.read_bytes()),
        compiled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        code_hash=code_hash_value,
        code_files=sweep_hash.CODE_FILES,
        hash_schema_version=sweep_hash.SCHEMA_VERSION,
        n_runs=len(rows),
        resource_tiers=resources,
        max_concurrent=max_concurrent,
        array_scripts=array_scripts,
        runs=rows,
        # Fase 81: politica de almacenamiento de nivel-sweep, NO entra en
        # sweep_hash.run_hash() -- cambiar esto no debe cambiar la
        # identidad de una corrida ya existente, es sobre que se conserva
        # en disco despues, no sobre el resultado fisico de la simulacion.
        keep_phot=bool(sweep_cfg.get("keep_phot", False)),
    )
    sweep_hash.write_json_atomic(manifest_path, manifest)
    print(f"\n  manifest: {manifest_path} ({len(rows)} corridas, {len(array_scripts)} tier(s))")

    record_event(
        "compile_sweep", triggered_by=triggered_by, sweep_name=sweep_name,
        code_hash=code_hash_value, n_runs=len(rows),
        manifest_sha256=sweep_hash.sha256_hex(manifest_path.read_bytes()),
    )
    return manifest_path


if __name__ == "__main__":
    _args = [a for a in sys.argv[1:] if a != "--force"]
    if len(_args) != 1:
        print("uso: python3 sweep_compile.py sweeps/<archivo>.yaml [--force]")
        sys.exit(1)
    compile_sweep(Path(_args[0]), force="--force" in sys.argv)
