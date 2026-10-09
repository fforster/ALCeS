#!/bin/bash
# ============================================================================
# fase99_trest_validation.sbatch -- GENRANGE_TREST real (--real-trest) en SNIa
# y las 5 NON1ASED, mismas 5 semillas (0-4) que los ratios de Fase 70.
# ----------------------------------------------------------------------------
# Solo se guarda summary.json + head_df.parquet: phot_df (~250 MB por corrida)
# se borra al terminar, la cuota del home no alcanza para 30 (ver Fase 97).
#
# Uso:
#     cd ~/AUTOSIM
#     sbatch exploration/lightcurvelynx/fase99_trest_validation.sbatch
# Resultado: exploration/lightcurvelynx/fase99_trest/<clase>_seed<N>/summary.json
# ============================================================================
#SBATCH -J f99_trest
#SBATCH -p general
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH --array=0-29%5
#SBATCH -o logs/f99_trest_%A_%a.out
#SBATCH -e logs/f99_trest_%A_%a.err

set -euo pipefail
CLASSES=(SNIa SNIa-91bg SNIax TDE SLSN-I KN-BULLA-BNS-M2COMP)
CLASS_KEY="${CLASSES[$((SLURM_ARRAY_TASK_ID / 5))]}"
SEED=$((SLURM_ARRAY_TASK_ID % 5))

cd "$SLURM_SUBMIT_DIR"
module load python/3.12.3-legacy-skylake
source exploration/lightcurvelynx/venv/bin/activate
cd exploration/lightcurvelynx

OUT="fase99_trest/${CLASS_KEY}_seed${SEED}"
echo "=== $CLASS_KEY seed=$SEED --real-trest -> $OUT · nodo=$(hostname) ==="
date
if [ "$CLASS_KEY" = "SNIa" ]; then
  python3 -c "from run_snia_ddf_poc import main; main(seed_index=$SEED, out_dir_override='$OUT', real_trest=True)"
else
  python3 -c "from run_non1ased_poc import main; main('$CLASS_KEY', seed_index=$SEED, out_dir_override='$OUT', real_trest=True)"
fi
rm -f "$OUT/phot_df.parquet"
date
