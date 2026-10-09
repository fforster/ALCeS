#!/bin/bash
# ============================================================================
# run_golden.sbatch -- regresion dorada del motor LightCurveLynx
# ----------------------------------------------------------------------------
# Uso:
#     cd ~/AUTOSIM
#     sbatch tests/golden/run_golden.sbatch --record   # antes de un cambio
#     sbatch tests/golden/run_golden.sbatch --check    # despues del cambio
# ============================================================================
#SBATCH -J alces_golden
#SBATCH -p general
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH -o logs/alces_golden_%j.out
#SBATCH -e logs/alces_golden_%j.err

set -euo pipefail
MODE="${1:?uso: sbatch tests/golden/run_golden.sbatch --record|--check}"
cd "$SLURM_SUBMIT_DIR"
module load python/3.12.3-legacy-skylake
source exploration/lightcurvelynx/venv/bin/activate
python3 tests/golden/check_golden.py "$MODE"
