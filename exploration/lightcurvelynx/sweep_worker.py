"""
Fase 66: entry point de CADA tarea de un job array de sweep -- resuelve su
propia fila del manifiesto via SLURM_ARRAY_TASK_ID (o --index en pruebas
interactivas), corre la simulacion real, y deja evidencia de que paso.

Regla de concurrencia (ver NOTES.md Fase 66): `manifest.json` es de SOLO
LECTURA para este script -- nunca lo reabre para escribir. Cada tarea del
array escribe EXCLUSIVAMENTE su propio `runs/<hash>/run_hash.json` --
archivos distintos entre tareas concurrentes, sin colision posible. Esto
es deliberado: dos tareas del mismo array terminando en la misma fraccion
de segundo NUNCA compiten por el mismo archivo.

Uso (normalmente invocado por el .sbatch generado por sweep_compile.py):
    python3 sweep_worker.py --manifest sweep_runs/<sweep>/manifest.json --index <N>
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import sweep_hash
from run_simsed_poc import HERE, main as run_simsed_main


def resolve_run(manifest: dict, index: int) -> dict:
    for r in manifest["runs"]:
        if r["index"] == index:
            return r
    raise IndexError(f"indice {index} no existe en el manifiesto ({manifest['n_runs']} corridas, "
                      f"indices 0-{manifest['n_runs']-1})")


def cleanup_phot_df(output_dir: Path) -> bool:
    """Borra phot_df.parquet si existe -- best-effort, nunca relanza (un
    fallo al borrar no debe tapar el resultado real de la simulacion, ver
    NOTES.md Fase 8/59/65: gestion de cuota de disco por corrida)."""
    phot_path = output_dir / "phot_df.parquet"
    if not phot_path.exists():
        return False
    try:
        phot_path.unlink()
        return True
    except OSError:
        return False


def run_one(manifest_path: Path, index: int) -> int:
    manifest = sweep_hash.read_json(manifest_path)
    sweep_name = manifest["sweep_name"]
    # Fase 81: opt-in de nivel-sweep leido del manifiesto completo (no de
    # `row`) -- evita que se cuele por error en el payload de run_hash(),
    # es politica de almacenamiento, no un parametro fisico de la corrida.
    keep_phot = manifest.get("keep_phot", False)
    sweep_dir = manifest_path.parent
    row = resolve_run(manifest, index)

    output_dir = sweep_dir / row["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    run_hash_path = output_dir / "run_hash.json"

    common = dict(
        run_hash=row["run_hash"], run_hash_full=row["run_hash_full"],
        class_key=row["class_key"], seed_index=row["seed_index"], wfd=row["wfd"],
        simsed_t0_mode=row["simsed_t0_mode"], ngentot=row["ngentot"], tier=row["tier"],
        sweep_name=sweep_name, code_hash=manifest["code_hash"],
        node=socket.gethostname(),
        slurm_job_id=os.environ.get("SLURM_JOB_ID"),
        slurm_array_job_id=os.environ.get("SLURM_ARRAY_JOB_ID"),
        slurm_array_task_id=os.environ.get("SLURM_ARRAY_TASK_ID"),
        # Fase 93: .get(), no row[...] -- un manifest compilado antes de
        # esta fase no tiene esta clave, no debe romper un worker nuevo.
        z_max_override=row.get("z_max_override"),
    )

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sweep_hash.write_json_atomic(run_hash_path, {
        **common, "status": "running", "started_at": started_at, "finished_at": None, "error": None,
    })
    print(f"[{started_at}] index={index} run_hash={row['run_hash']} "
          f"class={row['class_key']} seed={row['seed_index']} -> {output_dir}")

    status = "done"
    error = None
    try:
        run_simsed_main(
            row["class_key"],
            ngentot_override=row["ngentot"],
            seed_index=row["seed_index"],
            wfd=row["wfd"],
            simsed_t0_mode=row["simsed_t0_mode"],
            out_dir_override=output_dir,
            z_max_override=row.get("z_max_override"),
        )
    except OSError as e:
        # errno 122 = EDQUOT (disk quota exceeded) -- incidente real
        # recurrente de este proyecto (Fase 8/59/65). Distinguirlo
        # explicitamente deja que sweep_monitor.py separe "bug real" de
        # "cupo agotado" de un vistazo, sin tener que leer un traceback.
        if getattr(e, "errno", None) == 122:
            status = "failed"
            error = f"DISK_QUOTA_EXCEEDED: {e}"
        else:
            status = "failed"
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    except Exception as e:  # noqa: BLE001 -- se quiere capturar cualquier fallo real de main()
        status = "failed"
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    finally:
        # Fase 81: si el sweep pidio keep_phot=true, no se borra -- el
        # export por clase (Fase 82) necesita la fotometria cruda real.
        cleaned = False if keep_phot else cleanup_phot_df(output_dir)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sweep_hash.write_json_atomic(run_hash_path, {
        **common, "status": status, "started_at": started_at, "finished_at": finished_at,
        "error": error, "phot_df_cleaned": cleaned, "phot_df_kept": keep_phot,
    })
    print(f"[{finished_at}] index={index} run_hash={row['run_hash']} status={status}"
          + (f" ({error.splitlines()[0]})" if error else ""))
    return 0 if status == "done" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args()
    sys.exit(run_one(args.manifest, args.index))
