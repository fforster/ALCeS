"""Deja en phot_df.parquet solo los objetos DETECTED de head_df (lo unico que
usa kn_confusion_diag.py observed) -- la corrida completa pesa ~250 MB y la
cuota del home de NLHPC no alcanza para 14. Uso: python3 kn_confusion_shrink.py <run_dir>..."""
import sys
from pathlib import Path

import pandas as pd

for run in map(Path, sys.argv[1:]):
    phot_path, head_path = run / "phot_df.parquet", run / "head_df.parquet"
    if not phot_path.exists() or not head_path.exists():
        continue
    head = pd.read_parquet(head_path)
    phot = pd.read_parquet(phot_path)
    keep = phot[phot["SNID"].isin(head.loc[head["DETECTED"], "SNID"])]
    tmp = phot_path.with_suffix(".tmp.parquet")
    keep.to_parquet(tmp, index=False)
    tmp.replace(phot_path)
    print(f"{run.name}: {len(phot)} -> {len(keep)} filas")
