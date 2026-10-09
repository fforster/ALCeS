"""
Regresion dorada del motor LightCurveLynx: demuestra que un cambio de codigo
NO altera la fisica. Corre un set fijo de clases/semillas chicas y compara
head_df/phot_df/summary.json contra una huella grabada antes del cambio.

Por que existe: sweep_hash.CODE_FILES hace que CUALQUIER edicion a
run_simsed_poc.py/searcheff.py/snana_params.py cambie el code_hash (y todos
los run_hash). Eso es correcto como procedencia, pero no dice si la fisica
cambio. Esta prueba si lo dice: solo se comparan las columnas que existian al
grabar, asi que agregar columnas nuevas (metadatos) no la rompe, y cambiar un
solo bit de un flujo si.

Uso (en NLHPC, dentro de SLURM -- ver run_golden.sbatch):
    python3 tests/golden/check_golden.py --record   # graba golden_reference.json
    python3 tests/golden/check_golden.py --check    # compara contra lo grabado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
LCL_DIR = REPO_ROOT / "exploration" / "lightcurvelynx"
REFERENCE = Path(__file__).resolve().parent / "golden_reference.json"

# Clases de carga rapida y comportamiento variado (peso REDCOR, peso uniforme,
# dndz powerlaw/md14/tde, extincion de host WV07 y exponencial, t0 shift y no
# shift). KN-K17 se excluye a proposito: sus templates tardan ~33 min en cargar.
CASES = [
    {"engine": "simsed", "class_key": "SNIa-91bg", "seed_index": 7, "ngentot": 300},
    {"engine": "simsed", "class_key": "KN-BULLA19", "seed_index": 7, "ngentot": 300},
    {"engine": "simsed", "class_key": "CaRT", "seed_index": 7, "ngentot": 300},
    {"engine": "simsed", "class_key": "TDE-MOSFIT", "seed_index": 7, "ngentot": 300},
    # Fase 99: los otros dos runners (NON1ASED y SALT2). Semilla 97: sus
    # main() historicos escriben a poc_output_*_seed<N> fijo, y 97 no pisa
    # ninguna realizacion existente (0-4).
    {"engine": "non1ased", "class_key": "TDE", "seed_index": 97, "ngentot": 300},
    {"engine": "non1ased", "class_key": "KN-BULLA-BNS-M2COMP", "seed_index": 97, "ngentot": 300},
    {"engine": "snia", "class_key": "SNIa", "seed_index": 97, "ngentot": 300},
]
SORT_KEYS = {"head_df": ["SNID"], "phot_df": ["SNID", "MJD", "FLT"]}
SUMMARY_KEYS = ["n_with_obs", "n_detected", "n_total_dump", "snr_median", "snr_p90"]


def frame_fingerprint(df: pd.DataFrame, columns: list[str], sort_keys: list[str]) -> dict:
    """SHA256 exacto de las columnas pedidas (filas ordenadas, sin indice) y
    una suma por columna numerica para diagnosticar CUAL cambio si el hash
    no coincide."""
    df = df[columns].sort_values(sort_keys, kind="stable").reset_index(drop=True)
    digest = hashlib.sha256(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()).hexdigest()
    sums = {c: float(np.nansum(df[c].to_numpy(dtype=float)))
            for c in columns if pd.api.types.is_numeric_dtype(df[c])}
    return {"rows": len(df), "sha256": digest, "column_sums": sums}


def run_case(case: dict, work: Path) -> Path:
    out = work / f"{case['class_key']}_seed{case['seed_index']}"
    sys.path.insert(0, str(LCL_DIR))
    cls, seed, n = case["class_key"], case["seed_index"], case["ngentot"]
    if case["engine"] == "simsed":
        from run_simsed_poc import main
        main(cls, ngentot_override=n, seed_index=seed, out_dir_override=out)
        return out
    if case["engine"] == "non1ased":
        import run_non1ased_poc as runner
        default = LCL_DIR / f"poc_output_non1ased_{cls.lower().replace('-', '')}_seed{seed}"
        run = lambda: runner.main(cls, ngentot_override=n, seed_index=seed)  # noqa: E731
    elif case["engine"] == "snia":
        import run_snia_ddf_poc as runner
        runner.NGENTOT_LC = n  # main() lo lee del modulo en tiempo de ejecucion
        default = LCL_DIR / f"poc_output_seed{seed}"
        run = lambda: runner.main(seed_index=seed)  # noqa: E731
    else:
        raise ValueError(f"engine desconocido: {case['engine']}")
    # Estos main() no aceptan (o no aceptaban) out_dir: se usa su ruta por
    # defecto y se mueve. Si ya existe, no es nuestra -- no se toca.
    if default.exists():
        raise FileExistsError(f"{default} ya existe; borrarlo a mano si es de una corrida dorada anterior")
    try:
        run()
        shutil.move(str(default), str(out))
    finally:
        shutil.rmtree(default, ignore_errors=True)
    return out


def fingerprint_case(out: Path, columns: dict[str, list[str]] | None) -> dict:
    result = {}
    for name in ("head_df", "phot_df"):
        df = pd.read_parquet(out / f"{name}.parquet")
        cols = columns[name] if columns else sorted(df.columns)
        missing = set(cols) - set(df.columns)
        if missing:
            raise AssertionError(f"{name}: faltan columnas que existian al grabar: {sorted(missing)}")
        result[name] = {"columns": cols, **frame_fingerprint(df, cols, SORT_KEYS[name])}
    summary = json.loads((out / "summary.json").read_text())
    result["summary"] = {k: summary.get(k) for k in SUMMARY_KEYS}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--record-new", action="store_true",
                      help="grabar solo los casos sin referencia (casos nuevos, codigo sin tocar)")
    ap.add_argument("--keep-work", action="store_true", help="no borrar las corridas temporales")
    args = ap.parse_args()

    reference = json.loads(REFERENCE.read_text()) if (args.check or args.record_new) else {}
    work = Path(tempfile.mkdtemp(prefix="alces_golden_", dir=LCL_DIR))
    results, failures = {}, []
    try:
        for case in CASES:
            key = f"{case['class_key']}|seed{case['seed_index']}|n{case['ngentot']}"
            if case["engine"] != "simsed":
                key = f"{case['engine']}:{key}"
            ref = reference.get(key)
            if args.record_new and ref is not None:
                continue
            if args.check and ref is None:
                failures.append(f"{key}: no hay referencia grabada")
                continue
            cols = {n: ref[n]["columns"] for n in ("head_df", "phot_df")} if (ref and args.check) else None
            got = fingerprint_case(run_case(case, work), cols)
            results[key] = got
            if args.check:
                for part in ("head_df", "phot_df"):
                    if got[part]["sha256"] != ref[part]["sha256"]:
                        diff = {c: (ref[part]["column_sums"].get(c), v)
                                for c, v in got[part]["column_sums"].items()
                                if ref[part]["column_sums"].get(c) != v}
                        failures.append(f"{key} {part}: hash distinto (filas {ref[part]['rows']} -> "
                                        f"{got[part]['rows']}); columnas que cambian: {diff}")
                if got["summary"] != ref["summary"]:
                    failures.append(f"{key} summary: {ref['summary']} -> {got['summary']}")
            print(f"[golden] {key}: head={got['head_df']['rows']} phot={got['phot_df']['rows']} "
                  f"detectados={got['summary']['n_detected']}", flush=True)
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)

    if args.record or args.record_new:
        if args.record_new:
            results = {**reference, **results}
        REFERENCE.write_text(json.dumps(results, indent=2, sort_keys=True))
        print(f"[golden] referencia grabada en {REFERENCE}")
        return 0
    if failures:
        print("[golden] FALLA -- la fisica cambio:")
        for f in failures:
            print("  - " + f)
        return 1
    print("[golden] OK -- identico bit a bit en todas las columnas previas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
