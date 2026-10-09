"""
Pruebas de la Fase 98 (head_metadata.py y class_labels.py). head_metadata se
prueba con datos sinteticos con la forma real de lc["params"] (struct de
pyarrow); class_labels necesita importar los runners (lightcurvelynx) y se
omite donde no esta instalado.
    python3 test_head_metadata.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from head_metadata import extract_head_metadata, read_template_params, t0_convention  # noqa: E402

_fail = 0
def check(cond, msg):
    global _fail
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond: _fail += 1


SED_INFO = """# comentario
FLUX_SCALE:  1
NPAR: 4
PARNAMES: KN_INDEX    COSTHETA     MEJ    PHI
SED: a.txt 1   0.0 0.010 15
SED: b.txt 2   0.5 0.020 30   # comentario al final
SED: c.txt 3   1.0 0.030 45
"""


def fake_valid(with_host: bool, with_field: bool) -> pd.DataFrame:
    """Misma forma que lc[valid_mask]: columna params = struct de pyarrow con
    los nombres reales que devuelve simulate_lightcurves (sonda en NLHPC)."""
    data = {
        "SIMSEDModel_0.selected_template": [2, 0, 1],
        "SIMSEDModel_0.ebv": [0.01, 0.02, 0.03],
        "SIMSEDModel_0.t0": [60000.0, 60001.0, 60002.0],
        "redshift.function_node_result": [0.1, 0.2, 0.3],
    }
    if with_host:
        data["SIMSEDModel_0.host_ebv"] = [0.1, 0.0, 0.2]
        data["host_av.function_node_result"] = [0.31, 0.0, 0.62]
    if with_field:
        data["ObsTableRADECSampler:_non_func_1.field"] = ["cosmos", "xmm_lss", "cosmos"]
    arr = pa.StructArray.from_arrays([pa.array(v) for v in data.values()], names=list(data))
    # indice no contiguo a proposito: lc[valid_mask] conserva el indice de lc
    idx = [5, 7, 9]
    return pd.DataFrame({"id": idx, "params": pd.Series(arr, dtype=pd.ArrowDtype(arr.type), index=idx)},
                        index=idx)


def test_read_template_params():
    print("test_read_template_params")
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "SED.INFO").write_text(SED_INFO)
        names, table = read_template_params(t)
    check(names == ["COSTHETA", "MEJ", "PHI"], f"PARNAMES sin el indice ({names})")
    check(table.shape == (3, 3), f"una fila por linea SED: ({table.shape})")
    check(np.allclose(table[1], [0.5, 0.02, 30]), "comentario al final de la linea ignorado")
    # SNIa-91bg real: PARNAMES sin columna de indice
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "SED.INFO").write_text("PARNAMES:  stretch    color\nSED: a.SED 0.6 0.25\nSED: b.SED 1.1 0.75\n")
        names, table = read_template_params(t)
    check(names == ["stretch", "color"], f"sin *_INDEX no se descarta nada ({names})")
    check(np.allclose(table, [[0.6, 0.25], [1.1, 0.75]]), "valores de stretch y color")


def test_extract_full():
    print("test_extract_full")
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "SED.INFO").write_text(SED_INFO)
        valid = fake_valid(with_host=True, with_field=True)
        meta = extract_head_metadata(valid, t, "KN-BULLA19", "bolometric_peak")
    check(list(meta.index) == [5, 7, 9], "mismo indice y orden que valid")
    check(meta["TEMPLATE_INDEX"].tolist() == [2, 0, 1], "TEMPLATE_INDEX")
    check(meta["PAR_MEJ"].tolist() == [0.03, 0.01, 0.02], "PAR_MEJ del template correcto")
    check(meta["PAR_PHI"].tolist() == [45, 15, 30], "PAR_PHI del template correcto")
    check(np.allclose(meta["MWEBV"], [0.01, 0.02, 0.03]), "MWEBV")
    check(np.allclose(meta["HOST_AV"], [0.31, 0.0, 0.62]), "HOST_AV")
    check(meta["FIELD"].tolist() == ["cosmos", "xmm_lss", "cosmos"], "FIELD")
    check((meta["T0_CONVENTION"] == "native_phase0").all(), "KN-BULLA19 -> native_phase0")
    check(not meta.isna().any().any(), "sin nulos")


def test_extract_minimal():
    print("test_extract_minimal")
    meta = extract_head_metadata(fake_valid(with_host=False, with_field=False), None,
                                 "SNIa-91bg", "bolometric_peak")
    check("HOST_AV" not in meta and "FIELD" not in meta,
          "columnas ausentes no se inventan (sin host AV, WFD sin campo)")
    check(not any(c.startswith("PAR_") for c in meta), "sin simsed_dir no hay PAR_*")
    check((meta["T0_CONVENTION"] == "bolometric_peak").all(), "SNIa-91bg -> bolometric_peak")


def test_t0_convention():
    print("test_t0_convention")
    check(t0_convention("KN-K17", "bolometric_peak") == "bolometric_peak", "K17 shift al pico")
    check(t0_convention("PISN-STELLA-HECORE", "bolometric_peak") == "native_phase0", "PISN-STELLA sin shift")
    check(t0_convention("KN-K17", "raw") == "native_phase0", "modo raw -> fase nativa")


def test_class_labels():
    print("test_class_labels")
    try:
        import lightcurvelynx  # noqa: F401
    except ImportError:
        print("  - omitido: lightcurvelynx no instalado")
        return
    from class_labels import KNOWN_SHARED_SNTYPES, build_label_table, shared_sntypes
    table = build_label_table()
    check(len(table) == table[["engine", "class_key"]].drop_duplicates().shape[0], "sin filas repetidas")
    shared = shared_sntypes(table)
    check(shared == KNOWN_SHARED_SNTYPES,
          f"solo los SNTYPE compartidos ya documentados (nuevos: "
          f"{ {k: v for k, v in shared.items() if KNOWN_SHARED_SNTYPES.get(k) != v} })")


if __name__ == "__main__":
    test_read_template_params()
    test_extract_full()
    test_extract_minimal()
    test_t0_convention()
    test_class_labels()
    print(f"\n{'OK' if not _fail else f'{_fail} FALLOS'}")
    sys.exit(1 if _fail else 0)
