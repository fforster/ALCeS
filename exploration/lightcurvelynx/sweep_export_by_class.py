"""
Fase 82: conector real de ML -- parquet organizado por clase. Reemplaza el
`ingestion_format: null` deliberado de `sweep_publish_dataset.py` (Fase
66/73: el formato real de entrega a ALeRCE nunca habia sido definido por
el profesor/equipo -- ahora si esta definido: "parquet, por clase").

`consolidated.parquet` (Fase 66) es la tabla agregada POR CORRIDA
(metricas de summary.json) -- nunca tuvo fotometria cruda, porque
`sweep_worker.py::cleanup_phot_df()` la borraba de cada corrida por
diseno (cuota de disco). Este modulo lee la fotometria cruda real de las
corridas que SI la preservaron (`keep_phot=true`, Fase 81) y arma un
parquet por clase, uniendo columnas de contexto de `head_df.parquet`.

Corridas de sweeps sin `keep_phot=true` no tienen `phot_df.parquet` en
disco -- se omiten con una advertencia contada, no es un error duro: un
export parcial (algunas clases con fotometria, otras sin) sigue siendo
util.

Uso:
    python3 sweep_export_by_class.py --sweeps <sweep1> [<sweep2> ...] --out-dir <dir>
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import sweep_hash
from sweep_compile import SWEEP_RUNS_DIR
from sweep_publish_dataset import load_sweep_done_rows

# Columnas de contexto reales de head_df.parquet (ver run_simsed_poc.py::main,
# HOWTO.md seccion 6) -- no todo head_df, solo lo util para un consumidor
# externo que ya tiene la fotometria en phot_df.
HEAD_CONTEXT_COLS = ["SNID", "REDSHIFT_HELIO", "SNTYPE", "DETECTED"]
# Fase 98: metadatos por objeto que run_simsed_poc.py agrega desde esa fase.
# Corridas anteriores no los tienen -- se exportan solo si existen (PAR_* son
# los parametros del template, distintos por clase).
OPTIONAL_HEAD_COLS = ["PEAKMJD", "TEMPLATE_INDEX", "MWEBV", "HOST_AV", "FIELD", "T0_CONVENTION"]


def export_by_class(sweep_names: list[str], out_dir: Path) -> dict[str, Path]:
    frames_by_class: dict[str, list[pd.DataFrame]] = {}
    n_total = 0
    n_with_phot = 0

    for sweep_name in sweep_names:
        df_done, _code_hash = load_sweep_done_rows(sweep_name)
        sweep_dir = SWEEP_RUNS_DIR / sweep_name
        n_total += len(df_done)

        for _, r in df_done.iterrows():
            run_dir = sweep_dir / "runs" / r["run_hash"]
            phot_path = run_dir / "phot_df.parquet"
            head_path = run_dir / "head_df.parquet"
            if not phot_path.exists():
                continue
            n_with_phot += 1

            phot = pd.read_parquet(phot_path)
            head = pd.read_parquet(head_path)
            extra = [c for c in head.columns if c in OPTIONAL_HEAD_COLS or c.startswith("PAR_")]
            head = head[HEAD_CONTEXT_COLS + extra]
            merged = phot.merge(head, on="SNID", how="left")
            merged["class_key"] = r["class_key"]
            merged["run_hash"] = r["run_hash"]
            merged["run_hash_full"] = r["run_hash_full"]
            merged["source_sweep"] = sweep_name
            merged["seed_index"] = r["seed_index"]
            merged["wfd"] = r["wfd"]
            frames_by_class.setdefault(r["class_key"], []).append(merged)

    if n_total and n_with_phot < n_total:
        print(f"  ! {n_total - n_with_phot}/{n_total} corridas sin phot_df.parquet "
              f"(keep_phot no estaba activo) -- se omiten del export por clase")

    by_class_dir = out_dir / "by_class"
    result: dict[str, Path] = {}
    for class_key, frames in frames_by_class.items():
        df = pd.concat(frames, ignore_index=True)
        path = by_class_dir / f"{class_key}.parquet"
        sweep_hash.write_dataframe_atomic(path, df)
        print(f"  {class_key}: {len(df)} filas de fotometria -> {path}")
        result[class_key] = path

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweeps", nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    export_by_class(args.sweeps, args.out_dir)
