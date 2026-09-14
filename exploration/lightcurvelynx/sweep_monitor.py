"""
Fase 66: estado de todas las corridas de un sweep -- reemplaza el
`sacct -o State -X -n` a mano, corrida por corrida, que se ha usado toda
esta investigacion. Mismo patron real de `pipeline/orchestrate/monitor.py`
(solo lectura de ese archivo como referencia).

Fuente de verdad por corrida, en este orden:
    1. runs/<hash>/run_hash.json si existe -- status ahi es AUTORITATIVO
       (lo escribe el propio worker al terminar, "done" o "failed").
    2. si no existe pero runs/<hash>/phot_df.parquet SI existe -> la
       corrida murio a mitad de camino (worker nunca llego al `finally`
       que limpia phot_df.parquet ni al `write_json_atomic` final) -- se
       reporta como INTERRUPTED, distinto de FAILED (que si alcanzo a
       escribir el traceback). Mismo patron real ya visto en Fase 65:
       3 nodos distintos con ExitCode 120:0, phot_df.parquet grande sin
       borrar y sin ningun archivo de estado.
    3. si ninguno de los dos existe -- consultar sacct real por el
       slurm_job_id del manifiesto (PENDING/RUNNING/...).

Uso:
    python3 sweep_monitor.py <sweep_name>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import sweep_hash
from run_simsed_poc import HERE
from sweep_compile import SWEEP_RUNS_DIR


def sacct_states(job_ids: list[str]) -> dict[str, str]:
    """Consulta sacct UNA sola vez para todos los job_ids reales
    (formato "<array_job_id>_<index>"), no una llamada por corrida."""
    ids = sorted(set(j for j in job_ids if j))
    if not ids:
        return {}
    try:
        proc = subprocess.run(
            ["sacct", "-j", ",".join(ids), "-o", "JobID,State", "-X", "-n", "-P"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            out[parts[0].strip()] = parts[1].strip()
    return out


def run_status(sweep_dir: Path, row: dict, sacct: dict[str, str]) -> dict:
    output_dir = sweep_dir / row["output_dir"]
    run_hash_path = output_dir / "run_hash.json"
    phot_path = output_dir / "phot_df.parquet"

    if run_hash_path.exists():
        try:
            info = sweep_hash.read_json(run_hash_path)
            return dict(status=info.get("status", "unknown"), detail=info.get("error") or "", source="run_hash.json")
        except Exception as e:  # noqa: BLE001 -- archivo corrupto es informacion real, no un crash del monitor
            return dict(status="unknown", detail=f"run_hash.json ilegible: {e}", source="run_hash.json")

    if phot_path.exists():
        return dict(status="INTERRUPTED", detail="phot_df.parquet existe, run_hash.json no", source="filesystem")

    slurm_id = row.get("slurm_job_id")
    state = sacct.get(slurm_id, "") if slurm_id else ""
    if state:
        return dict(status=state, detail="", source="sacct")
    if row.get("status") == "pending":
        return dict(status="NOT_SUBMITTED", detail="", source="manifest")
    return dict(status="UNKNOWN", detail=f"slurm_job_id={slurm_id!r} sin match en sacct", source="none")


def monitor_sweep(sweep_name: str) -> list[dict]:
    sweep_dir = SWEEP_RUNS_DIR / sweep_name
    manifest_path = sweep_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"sweep '{sweep_name}' no tiene manifest.json compilado "
            f"(esperado en {manifest_path}) -- correr sweep_compile.py primero"
        )
    manifest = sweep_hash.read_json(manifest_path)

    job_ids = [r.get("slurm_job_id") for r in manifest["runs"]]
    sacct = sacct_states(job_ids)

    rows = []
    for r in manifest["runs"]:
        st = run_status(sweep_dir, r, sacct)
        rows.append(dict(
            index=r["index"], run_hash=r["run_hash"], class_key=r["class_key"],
            seed_index=r["seed_index"], tier=r["tier"], wfd=r.get("wfd", False), **st,
        ))
    return rows


def format_status(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    lines = []
    lines.append(f"{'IDX':>4}  {'RUN_HASH':<14}{'CLASE':<26}{'SEED':>5}  {'TIER':<26}{'STATUS':<16}DETALLE")
    for r in sorted(rows, key=lambda x: x["index"]):
        detail = (r["detail"] or "").splitlines()[0][:60] if r["detail"] else ""
        lines.append(
            f"{r['index']:>4}  {r['run_hash']:<14}{r['class_key']:<26}{r['seed_index']:>5}  "
            f"{r['tier']:<26}{r['status']:<16}{detail}"
        )
    lines.append("")
    lines.append("resumen: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("uso: python3 sweep_monitor.py <sweep_name>")
        sys.exit(1)
    try:
        rows = monitor_sweep(sys.argv[1])
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    print(format_status(rows))
