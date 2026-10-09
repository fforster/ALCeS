"""
Fase 66: punto de enganche para un futuro entrenamiento de clasificador.
Fase 82: conector real implementado -- el profesor especifico el formato
(parquet, por clase), reemplazando el `ingestion_format: null` deliberado
que este modulo mantuvo desde la Fase 66/73 mientras el formato real no
estaba definido.

Junta el `aggregated_summary.parquet` de uno o mas sweeps ya corridos
(solo corridas con status="done") en un directorio de dataset versionado
por su propio hash (`datasets/<hash>/`), con un manifiesto propio,
`consolidated.parquet` (tabla agregada POR CORRIDA -- metricas, no
fotometria) y, si alguna corrida de origen tenia `keep_phot=true` (Fase
81), `by_class/<clase>.parquet` real (ver `sweep_export_by_class.py`) con
`ingestion_format: "parquet_by_class_v1"` en el manifiesto. Si ninguna
corrida preservo fotometria, `ingestion_format` queda `null` con un
`ingestion_format_pending_reason` explicito -- publicar sigue funcionando,
solo sin el export por clase.

Uso:
    python3 sweep_publish_dataset.py --sweeps <sweep1> [<sweep2> ...]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import sweep_hash
from run_simsed_poc import HERE
from sweep_compile import SWEEP_RUNS_DIR
from sweep_history import record_event

DATASETS_DIR = HERE / "datasets"
DATASET_SCHEMA_VERSION = 1


def load_sweep_done_rows(sweep_name: str) -> tuple[pd.DataFrame, str]:
    """Corre (o reusa, si ya existe) el aggregated_summary.parquet de un
    sweep, y devuelve (filas con status=done, code_hash del sweep)."""
    sweep_dir = SWEEP_RUNS_DIR / sweep_name
    manifest = sweep_hash.read_json(sweep_dir / "manifest.json")
    agg_path = sweep_dir / "aggregated_summary.parquet"
    if not agg_path.exists():
        from sweep_aggregate import aggregate_sweep
        aggregate_sweep(sweep_name)
    df = pd.read_parquet(agg_path)
    df_done = df[df["status"] == "done"].copy()
    df_done["source_sweep"] = sweep_name
    return df_done, manifest["code_hash"]


def publish_dataset(sweep_names: list[str], triggered_by: str = "cli") -> Path:
    frames = []
    code_hash_by_sweep: dict[str, str] = {}
    for sweep_name in sweep_names:
        df_done, code_hash_value = load_sweep_done_rows(sweep_name)
        print(f"  {sweep_name}: {len(df_done)} corridas con status=done (de {sweep_name})")
        frames.append(df_done)
        code_hash_by_sweep[sweep_name] = code_hash_value

    if not frames or all(f.empty for f in frames):
        raise ValueError("No run with status=done in the given sweeps -- nothing to publish.")

    consolidated = pd.concat(frames, ignore_index=True)
    run_hashes_full = sorted(consolidated["run_hash_full"].tolist())

    # dataset_hash: determinista dado el mismo conjunto de corridas + el
    # code_hash de cada sweep que las produjo -- publicar dos veces el
    # mismo conjunto de resultados da el MISMO dataset_hash (idempotente).
    payload = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "source_sweeps": sorted(sweep_names),
        "run_hashes_full": run_hashes_full,
        "code_hash_by_sweep": code_hash_by_sweep,
    }
    dataset_hash_full = sweep_hash.sha256_hex(
        sweep_hash.canonical_json(payload).encode("utf-8")
    )
    dataset_hash = dataset_hash_full[:12]

    out_dir = DATASETS_DIR / dataset_hash
    table_path = out_dir / "consolidated.parquet"
    manifest_path = out_dir / "manifest.json"
    readme_path = out_dir / "README.md"

    sweep_hash.write_dataframe_atomic(table_path, consolidated)

    # Fase 82: conector real de ML -- parquet por clase, a partir de la
    # fotometria cruda real de las corridas que la preservaron
    # (keep_phot=true, Fase 81). Import local para evitar un ciclo real de
    # importacion (sweep_export_by_class importa load_sweep_done_rows de
    # este mismo modulo) -- mismo patron que ya usa load_sweep_done_rows()
    # con sweep_aggregate mas arriba.
    from sweep_export_by_class import export_by_class
    by_class_paths = export_by_class(sweep_names, out_dir)

    if by_class_paths:
        ingestion_format = "parquet_by_class_v1"
        ingestion_format_pending_reason = None
    else:
        ingestion_format = None
        ingestion_format_pending_reason = (
            "ninguna corrida de origen tenia keep_phot=true -- sin fotometria cruda que exportar"
        )

    manifest = dict(
        dataset_hash=dataset_hash,
        dataset_hash_full=dataset_hash_full,
        schema_version=DATASET_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_sweeps=sorted(sweep_names),
        code_hash_by_sweep=code_hash_by_sweep,
        n_runs=len(consolidated),
        table_file="consolidated.parquet",
        # Fase 82: version explicita en el nombre a proposito -- si el
        # formato real de ALeRCE termina siendo distinto, esto cambia a
        # "parquet_by_class_v2" (o lo que corresponda) sin ambiguedad sobre
        # que datasets ya publicados usan cual version.
        ingestion_format=ingestion_format,
        ingestion_format_pending_reason=ingestion_format_pending_reason,
        by_class_schema_version=1 if by_class_paths else None,
        by_class_files={k: f"by_class/{k}.parquet" for k in by_class_paths} if by_class_paths else {},
        # Fase 98: el SNTYPE numerico NO identifica la clase de forma unica
        # (KN-K17 y TDE-MOSFIT comparten 51, las variantes -elastic comparten
        # el de su clase base) -- ver class_labels.py.
        label_column="class_key",
        label_note=("Use class_key as the class label. SNTYPE is kept for traceability to the "
                    "SNANA inputs but is not unique across classes. PEAKMJD has a class-dependent "
                    "origin; see T0_CONVENTION where present."),
    )
    sweep_hash.write_json_atomic(manifest_path, manifest)

    if by_class_paths:
        by_class_note = (
            "**Fotometria cruda real disponible, organizada por clase** en `by_class/"
            "<clase>.parquet` (`ingestion_format: \"parquet_by_class_v1\"`) -- una fila por "
            "observacion real (mismas columnas que `phot_df.parquet`: `SNID`/`MJD`/`FLT`/"
            "`FLUXCAL`/`FLUXCALERR`/`FLUXTRUE`/`MAG`/`PHOTFLAG`) mas contexto de `head_df.parquet` "
            "(`REDSHIFT_HELIO`/`SNTYPE`/`DETECTED`) y procedencia (`class_key`/`run_hash`/"
            "`source_sweep`/`seed_index`/`wfd`). Solo incluye corridas de sweeps con "
            "`keep_phot=true` (Fase 81) -- ver `manifest.json[\"by_class_files\"]` para la lista "
            "real de clases exportadas.\n\n"
            "**Etiqueta de clase: usar `class_key`, no `SNTYPE`** -- el `SNTYPE` numerico se "
            "repite entre clases (p.ej. KN-K17 y TDE-MOSFIT = 51). `PEAKMJD` tiene un origen "
            "distinto segun la clase (ver `T0_CONVENTION` en corridas desde la Fase 98).\n"
        )
    else:
        by_class_note = (
            "**El formato de ingesta por clase (parquet, Fase 82) todavia no aplica a este "
            f"dataset**: {ingestion_format_pending_reason}. Relanzar el/los sweep(s) de origen "
            "con `keep_phot: true` y volver a publicar para obtener `by_class/`.\n"
        )

    readme_path.write_text(
        "# Dataset publicado (Fase 66, conector de Fase 82)\n\n"
        f"`dataset_hash`: `{dataset_hash}` (`{dataset_hash_full}`)\n\n"
        f"Sweeps de origen: {', '.join(sorted(sweep_names))}\n\n"
        f"{len(consolidated)} corridas (solo status=done).\n\n"
        f"{by_class_note}\n"
        "`consolidated.parquet` es la tabla agregada POR CORRIDA (metricas de `summary.json` + "
        "`run_hash`) -- util para comparar corridas entre si, no reemplaza la fotometria de "
        "`by_class/`. Este directorio es el punto de enganche real -- un conversor externo debe "
        "leer desde aca, sin tocar `sweep_runs/` ni el resto del sistema de automatizacion.\n",
        encoding="utf-8",
    )

    print(f"\n  dataset publicado: {out_dir} ({len(consolidated)} corridas, hash={dataset_hash}, "
          f"ingestion_format={ingestion_format})")

    record_event(
        "publish_dataset", triggered_by=triggered_by, source_sweeps=sorted(sweep_names),
        dataset_hash=dataset_hash, ingestion_format=manifest["ingestion_format"],
    )
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweeps", nargs="+", required=True)
    args = parser.parse_args()
    publish_dataset(args.sweeps)
