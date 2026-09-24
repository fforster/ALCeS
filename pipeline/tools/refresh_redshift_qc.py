"""
Reprocesa SOLO el QC de redshift (qc_redshift.png) para todas las GENVERSION
ya procesadas por Capa 4, sin tocar magnitudes/detecciones/curvas de luz
(sin cambios desde la ultima pasada completa) -- mucho mas rapido que
correr run_qc_full.py --force de nuevo.

Uso (dentro de un job sbatch, nunca en el login node):
    python3 pipeline/tools/refresh_redshift_qc.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # raiz del repo (Fase 94)
from pipeline.postproc import converter, qc  # noqa: E402

BUILD = Path(__file__).resolve().parents[2] / "build" / "full_v5.3_10yrs"
OUT_BASE = BUILD / "postproc"
DATASIM = Path.home() / "DATASIM_LSST_1"  # salida SNANA del usuario (Fase 94)
SIM_ROOTS = {"WFD": DATASIM / "WFD" / "SIMWv8", "DDF": DATASIM / "DDF" / "SIMDv8"}


def main():
    manifest_path = OUT_BASE / "postprocess_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    ok_results = [r for r in manifest["results"] if "error" not in r]
    print(f"reprocesando redshift QC para {len(ok_results)} GENVERSION ok")

    n_done = n_err = 0
    for r in ok_results:
        gv = r["genversion"]
        strategy = r.get("strategy", "")
        sim_root = SIM_ROOTS.get(strategy)
        gv_dir = sim_root / gv if sim_root else None
        if not gv_dir or not gv_dir.is_dir():
            print(f"  ! no encontrado: {gv}")
            n_err += 1
            continue
        try:
            head_df = converter.read_head(next(gv_dir.glob("*HEAD.FITS*")))
            dump_files = sorted(gv_dir.glob("*.DUMP"))
            dump_df = converter.read_dump(dump_files[0]) if dump_files else None
            out_path = OUT_BASE / gv / "qc" / f"{gv}_qc_redshift.png"
            qc.redshift_distribution(head_df, out_path, dump_df=dump_df)
            print(f"  ok: {gv}")
            n_done += 1
        except Exception as exc:
            print(f"  X {gv}: {exc}")
            n_err += 1

    print(f"\nOK={n_done} ERR={n_err}")


if __name__ == "__main__":
    main()
