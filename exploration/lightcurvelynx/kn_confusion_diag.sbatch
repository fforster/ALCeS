#!/bin/bash
# ============================================================================
# kn_confusion_diag.sbatch -- analisis de kn_confusion_diag.py (niveles A y B)
# ----------------------------------------------------------------------------
# Uso (despues de que termine kn_confusion_gen.sbatch, o con
# --dependency=afterok:<jobid>):
#     cd ~/AUTOSIM
#     sbatch exploration/lightcurvelynx/kn_confusion_diag.sbatch [--limit N]
# --limit N: solo N templates por clase en el nivel A (prueba rapida).
# ============================================================================
#SBATCH -J kn_conf_diag
#SBATCH -p general
#SBATCH -n 1
#SBATCH -c 8
#SBATCH --mem=24G
#SBATCH -t 02:00:00
#SBATCH -o logs/kn_conf_diag_%j.out
#SBATCH -e logs/kn_conf_diag_%j.err

set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
module load python/3.12.3-legacy-skylake
source exploration/lightcurvelynx/venv/bin/activate
cd exploration/lightcurvelynx

OUT=kn_confusion_diag
date
python3 kn_confusion_diag.py templates --out-dir "$OUT" --workers 8 "$@"
if ls -d "$OUT"/runs/*_seed* >/dev/null 2>&1; then
  python3 kn_confusion_diag.py observed --runs-dir "$OUT/runs" --out-dir "$OUT"
fi
python3 kn_confusion_diag.py report --out-dir "$OUT"
date
