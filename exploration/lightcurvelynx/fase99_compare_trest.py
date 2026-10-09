"""
Fase 99: compara la eficiencia de deteccion LCL con la ventana historica
(-30, 100) contra el GENRANGE_TREST real (--real-trest), para SNIa y las 5
NON1ASED, mismas semillas 0-4, y el ratio de cada una contra SNANA.

- ventana historica: los summary.json de las corridas de Fase 70 que siguen en
  disco (poc_output_non1ased_<clase>[_seedN], poc_output[_seedN] para SNIa)
- GENRANGE_TREST real: fase99_trest/<clase>_seed<N>/summary.json
- SNANA%: misma referencia que la tabla de Fase 70 (NOTES.md L8596-8604)

Uso (NLHPC):  python3 fase99_compare_trest.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SEEDS = range(5)
# deteccion SNANA real usada en la tabla de Fase 70 (NOTES.md L8596-8604)
SNANA_PCT = {"SNIa": 29.85, "SNIa-91bg": 7.35, "SNIax": 1.49, "TDE": 23.11,
             "SLSN-I": 55.02, "KN-BULLA-BNS-M2COMP": 1.395}


def historical_dir(cls: str, seed: int) -> Path:
    suffix = f"_seed{seed}" if seed else ""
    if cls == "SNIa":
        return HERE / f"poc_output{suffix}"
    return HERE / f"poc_output_non1ased_{cls.lower().replace('-', '')}{suffix}"


def eff(path: Path) -> float | None:
    f = path / "summary.json"
    return json.loads(f.read_text())["detection_efficiency_pct"] if f.exists() else None


def main() -> None:
    print("| clase | det. ventana (-30,100) | det. GENRANGE_TREST real | ratio SNANA antes | ratio SNANA despues |")
    print("|---|---:|---:|---:|---:|")
    for cls, snana in SNANA_PCT.items():
        old = [eff(historical_dir(cls, s)) for s in SEEDS]
        new = [eff(HERE / "fase99_trest" / f"{cls}_seed{s}") for s in SEEDS]
        if None in old or None in new:
            print(f"| {cls} | faltan corridas: historicas {old}, nuevas {new} | | | |")
            continue
        o, n = np.array(old), np.array(new)
        print(f"| {cls} | {o.mean():.2f}% ± {o.std(ddof=1):.2f} | {n.mean():.2f}% ± {n.std(ddof=1):.2f} | "
              f"{o.mean() / snana:.3f} | {n.mean() / snana:.3f} |")


if __name__ == "__main__":
    main()
