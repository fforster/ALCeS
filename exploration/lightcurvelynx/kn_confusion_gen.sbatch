#!/bin/bash
# ============================================================================
# kn_confusion_gen.sbatch -- corridas con phot_df para kn_confusion_diag.py
# ----------------------------------------------------------------------------
# Los sweeps borran phot_df.parquet (sin keep_phot) y ninguna corrida KN previa
# lo conserva, asi que el nivel B del diagnostico necesita corridas propias.
# 6 semillas por KN (~110-150 detectados c/u) + 2 de CaRT como control.
# Semillas 10+ para no pisar las realizaciones historicas (0-4).
# Para relanzar solo algunas: sbatch --array=0,2-5 kn_confusion_gen.sbatch
#
# Uso:
#     cd ~/AUTOSIM
#     sbatch exploration/lightcurvelynx/kn_confusion_gen.sbatch
# ============================================================================
#SBATCH -J kn_conf_gen
#SBATCH -p general
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH --array=0-13%3
#SBATCH -o logs/kn_conf_gen_%A_%a.out
#SBATCH -e logs/kn_conf_gen_%A_%a.err

set -euo pipefail
JOBS=(
  "KN-K17 10" "KN-K17 11" "KN-K17 12" "KN-K17 13" "KN-K17 14" "KN-K17 15"
  "KN-BULLA19 10" "KN-BULLA19 11" "KN-BULLA19 12" "KN-BULLA19 13" "KN-BULLA19 14" "KN-BULLA19 15"
  "CaRT 10" "CaRT 11"
)
read -r CLASS_KEY SEED <<< "${JOBS[$SLURM_ARRAY_TASK_ID]}"

cd "$SLURM_SUBMIT_DIR"
module load python/3.12.3-legacy-skylake
source exploration/lightcurvelynx/venv/bin/activate
cd exploration/lightcurvelynx

OUT="kn_confusion_diag/runs/${CLASS_KEY}_seed${SEED}"
echo "=== $CLASS_KEY seed=$SEED -> $OUT · job=$SLURM_JOB_ID · nodo=$(hostname) ==="
date
python3 -c "from run_simsed_poc import main; main('$CLASS_KEY', seed_index=$SEED, out_dir_override='$OUT')"
# solo detectados: la corrida completa pesa ~250 MB y no cabe en la cuota del home
python3 kn_confusion_shrink.py "$OUT"
date
