"""
Corre Capa 4 (QC) para TODAS las GENVERSION de la campana full_v5.3_10yrs,
resolviendo la raiz de simulacion real por estrategia:

    WFD -> ~/DATASIM_LSST_1/WFD/SIMWv8/<genversion>
    DDF -> ~/DATASIM_LSST_1/DDF/SIMDv8/<genversion>

$SNDATA_ROOT/SIM (el default de pipeline.postprocess.process_campaign) quedo
vacio tras la limpieza de cuota de disco -- por eso el manifiesto anterior
marcaba ~58 GENVERSION como "no encontradas" cuando en realidad si existian,
solo que en otra raiz.

Reescribe por completo build/full_v5.3_10yrs/postproc/postprocess_manifest.json
(a diferencia de run_qc_remainder.py, que solo fusiona 2 GENVERSION puntuales).

Por defecto reusa el QC ya generado si los 4 PNG existen (rapido). Pasar
--force para reprocesar TODO sin importar lo que ya exista -- necesario
despues de un fix en converter.py/qc.py que invalida los PNG previos
(p.ej. el fix de link_phot_head/magnitude_histograms/redshift_distribution
del 2026-08-12: los 73 PNG generados antes de ese fix estaban mal, no
solo incompletos).

Uso (dentro de un job sbatch, nunca en el login node):
    python3 pipeline/tools/run_qc_full.py [--force]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # raiz del repo (Fase 94)
from pipeline.postprocess import process_genversion  # noqa: E402

DATASIM = Path.home() / "DATASIM_LSST_1"  # salida SNANA del usuario (Fase 94)
SIM_ROOTS = {
    "WFD": DATASIM / "WFD" / "SIMWv8",
    "DDF": DATASIM / "DDF" / "SIMDv8",
}
BUILD = Path(__file__).resolve().parents[2] / "build" / "full_v5.3_10yrs"
OUT_BASE = BUILD / "postproc"
QC_NAMES = ["redshift", "magnitudes", "detections", "lightcurves"]


def _existing_qc_ok(out_dir: Path, gv: str) -> bool:
    qc_dir = out_dir / "qc"
    if not qc_dir.is_dir():
        return False
    for name in QC_NAMES:
        p = qc_dir / f"{gv}_qc_{name}.png"
        if not p.is_file() or p.stat().st_size == 0:
            return False
    return True


def main():
    force = "--force" in sys.argv
    manifest_path = BUILD / "campaign_manifest.json"
    combos = json.loads(manifest_path.read_text()).get("combos", [])
    print(f"campana: {len(combos)} combos ({sum(1 for c in combos if c.get('strategy')=='WFD')} WFD, "
          f"{sum(1 for c in combos if c.get('strategy')=='DDF')} DDF)")

    results = []
    skipped = []

    for combo in combos:
        gv = combo["genversion"]
        strategy = combo.get("strategy", "")
        sim_root = SIM_ROOTS.get(strategy)
        if sim_root is None:
            print(f"  ! estrategia desconocida para {gv}: {strategy!r}")
            skipped.append(gv)
            continue

        gv_dir = sim_root / gv
        if not gv_dir.is_dir():
            skipped.append(gv)
            continue

        out_dir = OUT_BASE / gv
        already_ok = (not force) and _existing_qc_ok(out_dir, gv)

        try:
            r = process_genversion(gv_dir, out_dir, skip_qc=already_ok)
            r.pop("head_df", None)
            r.pop("phot_df", None)
            if already_ok:
                # ya habia QC valido -- no lo regeneramos, solo referenciamos
                r["qc"] = {
                    name: str(out_dir / "qc" / f"{gv}_qc_{name}.png") for name in QC_NAMES
                }
                print(f"  = {gv}: QC ya existia, solo se releyeron conteos")
            else:
                print(f"  ok: {gv}")
            r["strategy"] = strategy
            r["model"] = combo.get("model", "")
            r["run"] = combo.get("run", "")
            results.append(r)
        except Exception as exc:
            print(f"  X {gv}: {exc}")
            results.append({
                "genversion": gv, "strategy": strategy, "model": combo.get("model", ""),
                "run": combo.get("run", ""), "error": str(exc),
            })

    n_ok = len([r for r in results if "error" not in r])
    n_err = len([r for r in results if "error" in r])
    print(f"\nOK={n_ok} ERR={n_err} SKIPPED={len(skipped)}")

    by_strategy = {}
    for strat in ("WFD", "DDF"):
        strat_results = [r for r in results if r.get("strategy") == strat]
        strat_skipped = [
            gv for gv in skipped
            if next((c for c in combos if c["genversion"] == gv), {}).get("strategy") == strat
        ]
        by_strategy[strat] = {
            "processed": len([r for r in strat_results if "error" not in r]),
            "errors": len([r for r in strat_results if "error" in r]),
            "skipped": len(strat_skipped),
        }

    pp_manifest = {
        "campaign": "full_v5.3_10yrs",
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sim_roots": {k: str(v) for k, v in SIM_ROOTS.items()},
        "n_total_combos": len(combos),
        "n_processed": n_ok,
        "n_errors": n_err,
        "n_skipped": len(skipped),
        "by_strategy": by_strategy,
        "skipped": skipped,
        "results": results,
    }

    OUT_BASE.mkdir(parents=True, exist_ok=True)
    manifest_out = OUT_BASE / "postprocess_manifest.json"
    manifest_out.write_text(json.dumps(pp_manifest, indent=2, default=str))
    print(f"manifiesto escrito: {manifest_out}")


if __name__ == "__main__":
    main()
