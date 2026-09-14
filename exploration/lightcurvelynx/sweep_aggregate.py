"""
Fase 66: agrega los resultados de un sweep -- reemplaza el proceso manual
de leer `summary.json` de cada corrida a mano, fase a fase, que se ha
usado en toda esta investigacion (NOTES.md, tablas de Fase 59/60/62/64).

Para cada corrida del manifiesto: lee runs/<hash>/summary.json (si existe)
y runs/<hash>/run_hash.json (si existe), arma una fila con el run_hash
como columna real (no solo el nombre de directorio), y escribe una tabla
consolidada -- lista para seguir el analisis de la fase que corresponda,
o como insumo de sweep_publish_dataset.py.

Uso:
    python3 sweep_aggregate.py <sweep_name>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import sweep_hash
from sweep_compile import SWEEP_RUNS_DIR


def aggregate_sweep(sweep_name: str) -> Path:
    sweep_dir = SWEEP_RUNS_DIR / sweep_name
    manifest_path = sweep_dir / "manifest.json"
    manifest = sweep_hash.read_json(manifest_path)

    rows = []
    for r in manifest["runs"]:
        output_dir = sweep_dir / r["output_dir"]
        summary_path = output_dir / "summary.json"
        run_hash_path = output_dir / "run_hash.json"

        row = dict(
            run_hash=r["run_hash"], run_hash_full=r["run_hash_full"],
            class_key=r["class_key"], seed_index=r["seed_index"], wfd=r["wfd"],
            simsed_t0_mode=r["simsed_t0_mode"], ngentot=r["ngentot"], tier=r["tier"],
        )

        status = "no_run_hash_json"
        if run_hash_path.exists():
            try:
                info = sweep_hash.read_json(run_hash_path)
                status = info.get("status", "unknown")
                row["node"] = info.get("node")
                row["slurm_job_id"] = info.get("slurm_job_id")
                row["started_at"] = info.get("started_at")
                row["finished_at"] = info.get("finished_at")
            except Exception:  # noqa: BLE001 -- archivo corrupto no debe tumbar el agregado completo
                status = "run_hash_json_ilegible"
        row["status"] = status

        if summary_path.exists():
            try:
                summary = sweep_hash.read_json(summary_path)
                # todos los campos reales de summary.json (ver run_simsed_poc.py::main):
                # class_key/strategy/seed_index/ngentot_lc/n_with_obs/n_detected/
                # n_total_dump/sim_wall_time_s/detection_efficiency_pct/snr_median/snr_p90
                for k, v in summary.items():
                    row.setdefault(f"summary_{k}", v)
            except Exception:  # noqa: BLE001 -- idem, no tumbar el resto del agregado
                row["summary_read_error"] = True

        rows.append(row)

    df = pd.DataFrame(rows)
    out_path = sweep_dir / "aggregated_summary.parquet"
    sweep_hash.write_dataframe_atomic(out_path, df)
    print(f"  agregado: {out_path} ({len(df)} filas)")
    print(df[["run_hash", "class_key", "seed_index", "status"]].to_string(index=False))
    return out_path


def sweep_zmax(sweep_name: str) -> dict:
    """Fase 90: z maximo REAL alcanzado por el sweep completo -- el maximo
    de `summary.json::z_max_simulado` entre las corridas ya 'done'. Lee
    summary.json directo (no aggregated_summary.parquet, que puede estar
    desactualizado si no se aprieto "Agregar" despues de la ultima corrida
    en terminar) -- mismo patron de iteracion que aggregate_sweep().

    Devuelve {} si el sweep no existe, no tiene corridas 'done' todavia, o
    ninguna corrida 'done' trae el campo (summary.json de antes de esta
    fase)."""
    sweep_dir = SWEEP_RUNS_DIR / sweep_name
    manifest_path = sweep_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = sweep_hash.read_json(manifest_path)

    best: dict = {}
    for r in manifest["runs"]:
        output_dir = sweep_dir / r["output_dir"]
        run_hash_path = output_dir / "run_hash.json"
        summary_path = output_dir / "summary.json"
        if not run_hash_path.exists() or not summary_path.exists():
            continue
        try:
            if sweep_hash.read_json(run_hash_path).get("status") != "done":
                continue
            summary = sweep_hash.read_json(summary_path)
        except Exception:  # noqa: BLE001 -- archivo corrupto no debe tumbar el calculo del resto
            continue
        z = summary.get("z_max_simulado")
        if z is None:
            continue
        if not best or z > best["z_max_simulado"]:
            best = dict(
                z_max_simulado=z, z_max_detectado=summary.get("z_max_detectado"),
                class_key=r["class_key"], run_hash=r["run_hash"],
            )
    return best


def build_live_panel(sweep_name: str) -> dict:
    """Fase 91: panel agregado en vivo, SOLO de corridas 'done' -- sin
    matplotlib (liviano, pensado para recalcularse cada vez que cambia el
    conteo de 'done', no cada 3s de polling, ver webapp/app.py::sweep_panel_json
    y el JS de sweep_status.html). Reusa los 3 patrones ya probados en
    analyze_phot_df.ipynb (eficiencia por clase/estrategia, histogramas de
    REDSHIFT_HELIO/NOBS, pivot WFD vs DDF) pero como tablas, no graficos.

    Devuelve {} si el sweep no existe. Sin corridas 'done' todavia, devuelve
    listas/histogramas vacios (no {} -- a diferencia de sweep_zmax, aca el
    llamador siempre espera las 4 claves)."""
    sweep_dir = SWEEP_RUNS_DIR / sweep_name
    manifest_path = sweep_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = sweep_hash.read_json(manifest_path)

    efficiency_rows = []
    z_values: list[float] = []
    nobs_values: list[float] = []
    pivot_acc: dict[tuple[str, str], dict] = {}

    for r in manifest["runs"]:
        output_dir = sweep_dir / r["output_dir"]
        run_hash_path = output_dir / "run_hash.json"
        summary_path = output_dir / "summary.json"
        if not run_hash_path.exists() or not summary_path.exists():
            continue
        try:
            if sweep_hash.read_json(run_hash_path).get("status") != "done":
                continue
            summary = sweep_hash.read_json(summary_path)
        except Exception:  # noqa: BLE001 -- archivo corrupto no debe tumbar el resto del panel
            continue

        strategy = summary.get("strategy", "WFD" if r.get("wfd") else "DDF")
        class_key = summary.get("class_key", r["class_key"])
        eff = summary.get("detection_efficiency_pct")
        snr_median = summary.get("snr_median")
        snr_p90 = summary.get("snr_p90")
        efficiency_rows.append(dict(class_key=class_key, strategy=strategy,
                                     detection_efficiency_pct=eff, snr_median=snr_median))

        acc = pivot_acc.setdefault((class_key, strategy), dict(eff=[], snr_median=[], snr_p90=[]))
        if eff is not None:
            acc["eff"].append(eff)
        if snr_median is not None:
            acc["snr_median"].append(snr_median)
        if snr_p90 is not None:
            acc["snr_p90"].append(snr_p90)

        head_path = output_dir / "head_df.parquet"
        if head_path.exists():
            try:
                cols = pd.read_parquet(head_path, columns=["REDSHIFT_HELIO", "NOBS"])
                z_values.extend(cols["REDSHIFT_HELIO"].dropna().tolist())
                nobs_values.extend(cols["NOBS"].dropna().tolist())
            except Exception:  # noqa: BLE001 -- parquet corrupto/columna ausente no tumba el resto
                pass

    efficiency_rows.sort(key=lambda row: (row["class_key"], row["strategy"]))

    def _hist(values: list[float], bins: int = 10) -> dict:
        if not values:
            return {}
        counts, edges = np.histogram(values, bins=bins)
        return dict(bin_edges=edges.tolist(), counts=counts.tolist())

    def _mean(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    pivot_rows = [
        dict(class_key=ck, strategy=st, detection_efficiency_pct=_mean(acc["eff"]),
             snr_median=_mean(acc["snr_median"]), snr_p90=_mean(acc["snr_p90"]))
        for (ck, st), acc in sorted(pivot_acc.items())
    ]

    return dict(
        efficiency_rows=efficiency_rows,
        z_hist=_hist(z_values),
        nobs_hist=_hist(nobs_values),
        pivot_ddf_wfd=pivot_rows,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("uso: python3 sweep_aggregate.py <sweep_name>")
        sys.exit(1)
    aggregate_sweep(sys.argv[1])
