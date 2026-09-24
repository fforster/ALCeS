"""
Fase 2 parte B -- reproduce una copia local de SIMSED.SNIa-91bg (35
templates) con un fix de un solo caracter en SED.INFO: la linea

    $ template to all 91bg at low-z as from Gonzalez-Gaitan+14.

trae un '$' donde debería ir '#' (typo real en el archivo de referencia de
SNANA -- confirmado con `cat -A` en NLHPC, no es un problema nuestro). El
parser de SNANA (snlc_sim.exe) tolera esto porque no usa un parser YAML
estricto, pero `lightcurvelynx.models.sed_template_model.SIMSEDModel.
_read_simsed_info_file()` sí hace `yaml.safe_load()` sobre el archivo
completo, y ese caracter rompe el parseo. No se toca el archivo real de
SNANA en NLHPC -- se copia localmente (mismo patrón que
`setup_salt2_local.py` en Fase 1, no versionado, se regenera desde los
archivos de SNANA ya en NLHPC).

Uso:
    python3 setup_simsed_91bg_local.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

# Fase 94: ALCES_DATA (carpeta compartida) o $HOME, ver local_env.py.
from local_env import SNANA_HOME

SRC = SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIa-91bg"
DST = Path(__file__).resolve().parent / "simsed_91bg_local"


def main():
    DST.mkdir(exist_ok=True)

    info_text = (SRC / "SED.INFO").read_text()
    n_fixed = info_text.count("\n$ ")
    info_text = info_text.replace("\n$ ", "\n# ")
    (DST / "SED.INFO").write_text(info_text)
    print(f"SED.INFO copiado, {n_fixed} linea(s) con '$' corregida(s) a '#'")

    n_copied = 0
    for f in SRC.glob("*.SED*"):
        shutil.copy2(f, DST / f.name)
        n_copied += 1
    print(f"{n_copied} archivos de template copiados a {DST}")


if __name__ == "__main__":
    main()
