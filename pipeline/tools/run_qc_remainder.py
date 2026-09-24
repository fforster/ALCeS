"""
Corre Capa 4 (QC) para las 2 GENVERSION que quedaron fuera del batch
principal (job 11337320) porque sus simulaciones llegaron despues:
SNIa_WFD y SNII_WFD, ya confirmadas en DATASIM_LSST_1/WFD/SIMWv8/.

Fusiona el resultado en el postprocess_manifest.json existente (no lo
pisa) para dejar la campana full_v5.3_10yrs con las 75 GENVERSION que
si tienen datos.

Uso (dentro de un job sbatch, nunca en el login node):
    python3 -m pipeline.tools.run_qc_remainder
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # raiz del repo (Fase 94)
from pipeline.postprocess import process_genversion  # noqa: E402

DATASIM = Path.home() / "DATASIM_LSST_1"  # salida SNANA del usuario (Fase 94)
WFD_ROOT = DATASIM / "WFD" / "SIMWv8"
BUILD = Path(__file__).resolve().parents[2] / "build" / "full_v5.3_10yrs"
OUT_BASE = BUILD / "postproc"

TARGETS = [
    ("SNIa_WFD_baseline_v5.3.1_10yrs", "WFD"),
    ("SNII_WFD_baseline_v5.3.1_10yrs", "WFD"),
]


def main():
    results = []
    for gv, strat in TARGETS:
        gv_dir = WFD_ROOT / gv
        if not gv_dir.is_dir():
            print(f"  ! no encontrado: {gv} en {gv_dir}")
            results.append({"genversion": gv, "error": "directorio no encontrado"})
            continue
        try:
            r = process_genversion(gv_dir, OUT_BASE / gv, skip_qc=False)
            r.pop("head_df", None)
            r.pop("phot_df", None)
            results.append(r)
            print(f"  ok: {gv}")
        except Exception as exc:
            print(f"  X {gv}: {exc}")
            results.append({"genversion": gv, "error": str(exc)})

    n_ok = len([r for r in results if "error" not in r])
    n_err = len([r for r in results if "error" in r])
    print(f"\nOK={n_ok} ERR={n_err}")

    manifest_path = OUT_BASE / "postprocess_manifest.json"
    if manifest_path.exists():
        pp_manifest = json.loads(manifest_path.read_text())
    else:
        pp_manifest = {"campaign": "full_v5.3_10yrs", "results": [], "skipped": []}

    existing_gvs = {r.get("genversion") for r in pp_manifest.get("results", [])}
    for r in results:
        gv = r.get("genversion")
        if gv in existing_gvs:
            pp_manifest["results"] = [
                x for x in pp_manifest["results"] if x.get("genversion") != gv
            ]
        pp_manifest["results"].append(r)

    pp_manifest["skipped"] = [
        g for g in pp_manifest.get("skipped", []) if g not in {t[0] for t in TARGETS}
    ]
    pp_manifest["n_processed"] = len(
        [r for r in pp_manifest["results"] if "error" not in r]
    )
    pp_manifest["n_errors"] = len([r for r in pp_manifest["results"] if "error" in r])
    pp_manifest["n_skipped"] = len(pp_manifest["skipped"])

    manifest_path.write_text(json.dumps(pp_manifest, indent=2, default=str))
    print("manifiesto actualizado.")


if __name__ == "__main__":
    main()
