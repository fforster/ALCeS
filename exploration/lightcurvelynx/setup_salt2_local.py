"""
Prepara exploration/lightcurvelynx/salt2_h17_local/ -- una copia LEGIBLE por
sncosmo.SALT2Source del modelo SALT2.WFIRST-H17 real que usa SNANA
(run_SNANA/plasticc_models/SALT2.WFIRST-H17), en vez de depender del mirror
remoto de sncosmo (`get_source("salt2-h17")` -> sncosmo.github.io/data ->
404 confirmado, caido al 2026-08-12).

Dos ajustes sobre los archivos de SNANA, no un modelo distinto:
  1. Descomprime los .dat.gz de SNANA (sncosmo.read_griddata_ascii abre en
     texto plano, no gzip).
  2. Reescribe salt2_color_correction.dat en el formato que espera
     sncosmo (`<ncoeffs>\\n<coefs>\\nSalt2ExtinctionLaw.version 1\\n...`) --
     el archivo de SNANA con ese mismo nombre es una tabla de dispersion
     distinta (4.9MB, no los ~4 coeficientes de un polinomio); los
     coeficientes reales del color law H17 estan en SALT2.INFO ->
     COLORCOR_PARAMS y son los que se usan aqui, no un valor inventado.

Uso (una sola vez, en NLHPC):
    python3 setup_salt2_local.py
"""
import gzip
import shutil
from pathlib import Path

# Fase 94: ALCES_DATA (carpeta compartida) o $HOME, ver local_env.py.
from local_env import SNANA_HOME

SNANA_SALT2_DIR = SNANA_HOME / "run_SNANA/plasticc_models/SALT2.WFIRST-H17"
OUT_DIR = Path(__file__).resolve().parent / "salt2_h17_local"

# de SALT2.INFO -> COLORCOR_PARAMS: <min_lambda> <max_lambda> <ncoeffs> <coef1> ... <coefN>
COLORCOR_MIN_LAMBDA = 2800
COLORCOR_MAX_LAMBDA = 9500
COLORCOR_COEFFS = [-1.33154627, 0.61225710, -0.12117791, 0.00840832]


def main():
    OUT_DIR.mkdir(exist_ok=True)
    for gz_file in SNANA_SALT2_DIR.glob("*.dat.gz"):
        out_path = OUT_DIR / gz_file.stem  # quita el .gz
        with gzip.open(gz_file, "rb") as f_in, open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        print(f"  descomprimido: {out_path.name}")

    info_src = SNANA_SALT2_DIR / "SALT2.INFO"
    if info_src.exists():
        shutil.copy(info_src, OUT_DIR / "SALT2.INFO")

    clfile = OUT_DIR / "salt2_color_correction.dat"
    lines = [str(len(COLORCOR_COEFFS))]
    lines.append(" ".join(f"{c:.8f}" for c in COLORCOR_COEFFS))
    lines.append("Salt2ExtinctionLaw.version 1")
    lines.append(f"Salt2ExtinctionLaw.min_lambda {COLORCOR_MIN_LAMBDA}")
    lines.append(f"Salt2ExtinctionLaw.max_lambda {COLORCOR_MAX_LAMBDA}")
    clfile.write_text("\n".join(lines) + "\n")
    print(f"  reescrito (formato sncosmo, coefs reales de SALT2.INFO): {clfile.name}")

    print(f"listo: {OUT_DIR}")


if __name__ == "__main__":
    main()
