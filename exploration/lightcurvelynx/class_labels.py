"""
Fase 98: tabla unica de etiquetas de las clases del motor LightCurveLynx,
GENERADA desde el codigo (CLASS_CONFIGS de cada runner), no copiada a mano --
asi no puede desincronizarse de lo que realmente se escribe en head_df.

Documenta, sin cambiarlos, los SNTYPE que se repiten entre clases. Los SNTYPE
vienen de los .INPUT/NON1A_KEYS reales de SNANA y son parte de los
fundamentos (no se renumeran); la etiqueta correcta para entrenar es
`class_key` (ver el manifest de sweep_publish_dataset.py).

Uso:
    python3 class_labels.py            # imprime la tabla en Markdown
    python3 class_labels.py --csv out  # la escribe como CSV
"""
from __future__ import annotations

import argparse
from collections import defaultdict

import pandas as pd

from head_metadata import NATIVE_PHASE0_CLASSES

# SNIa/SALT2 no tiene CLASS_CONFIGS: su runner escribe SNTYPE=1 fijo
# (run_snia_ddf_poc.py, construccion de head_rows) y PEAKMJD = pico en B.
SNIA_SALT2_SNTYPE = 1

# SNTYPE compartidos que YA se conocen y estan documentados (NOTES.md Fase 97,
# paper Sec. 9.1). Un SNTYPE compartido nuevo hace fallar
# test_class_labels.py: hay que revisarlo y documentarlo a proposito.
KNOWN_SHARED_SNTYPES = {
    # variantes de la misma clase fisica (mismo SNTYPE real en su .INPUT)
    12: {"SIMSED:SNIax", "SIMSED:SNIax-elastic", "NON1ASED:SNIax"},
    13: {"SIMSED:SNIa-91bg", "SIMSED:SNIa-91bg-elastic", "NON1ASED:SNIa-91bg"},
    # choque real entre clases fisicas distintas: KN-K17 y TDE
    51: {"SIMSED:KN-K17", "SIMSED:TDE-MOSFIT", "NON1ASED:TDE"},
}


def build_label_table() -> pd.DataFrame:
    from run_simsed_poc import CLASS_CONFIGS as SIMSED
    from run_non1ased_poc import CLASS_CONFIGS as NON1ASED

    rows = []
    for key, cfg in SIMSED.items():
        rows.append(dict(
            engine="SIMSED", class_key=key, sntype=cfg["sntype"],
            z_min=cfg["genrange_redshift"][0], z_max=cfg["genrange_redshift"][1],
            t0_convention="native_phase0" if key in NATIVE_PHASE0_CLASSES else "bolometric_peak",
            runner="run_simsed_poc.py",
        ))
    for key, cfg in NON1ASED.items():
        rows.append(dict(
            engine="NON1ASED", class_key=key, sntype=cfg["sntype"],
            z_min=cfg["genrange_redshift"][0], z_max=cfg["genrange_redshift"][1],
            t0_convention="native_phase0", runner="run_non1ased_poc.py",
        ))
    rows.append(dict(engine="SALT2", class_key="SNIa", sntype=SNIA_SALT2_SNTYPE,
                     z_min=None, z_max=None, t0_convention="B_peak", runner="run_snia_ddf_poc.py"))
    df = pd.DataFrame(rows)
    groups = shared_sntypes(df)
    df["sntype_shared_with"] = [
        ", ".join(sorted(groups.get(s, set()) - {f"{e}:{k}"}))
        for e, k, s in zip(df["engine"], df["class_key"], df["sntype"])
    ]
    return df


def shared_sntypes(df: pd.DataFrame) -> dict[int, set[str]]:
    by_type: dict[int, set[str]] = defaultdict(set)
    for e, k, s in zip(df["engine"], df["class_key"], df["sntype"]):
        by_type[int(s)].add(f"{e}:{k}")
    return {s: members for s, members in by_type.items() if len(members) > 1}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="escribir la tabla a este CSV")
    args = ap.parse_args()
    table = build_label_table()
    if args.csv:
        table.to_csv(args.csv, index=False)
    print(table.to_markdown(index=False) if hasattr(table, "to_markdown") else table.to_string(index=False))
