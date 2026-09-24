"""
Fase 7 -- NON1ASED.TDE-BBFIT/2019qiz.sed.gz tiene un problema de dato real
distinto a los ya vistos: la segunda linea del archivo,

    phase wavelength flux

es la fila de encabezado de columnas, pero le falta el prefijo "#" (la
primera linea, "# phase: ...", SI esta comentada correctamente). Confirmado
comparando linea por linea contra el archivo hermano
NON1ASED.SLSN-I-BBFIT/2016apd.sed.gz, que tiene la misma estructura de
encabezado de 2 lineas pero con "#" en ambas -- este es un typo real de un
solo caracter en el archivo de referencia de TDE-BBFIT especificamente, no
un problema nuestro ni de LightCurveLynx. `np.loadtxt(path, comments="#")`
(usado por SIMSEDModel._read_simsed_data_file(), reusado por
non1ased.load_non1ased_model()) intenta parsear esa linea como datos y
falla con `ValueError: could not convert string 'phase' to float64`.

No se modifica el archivo real de SNANA -- se genera una copia local (mismo
patron que setup_simsed_91bg_local.py/setup_knbulla19_local.py, no
versionada) con esa linea comentada.

Uso:
    python3 setup_tdebbfit_local.py
    (corre en NLHPC, liviano -- solo I/O, no computo pesado)
"""
from __future__ import annotations

import gzip
import shutil
from pathlib import Path

# Fase 94: ALCES_DATA (carpeta compartida) o $HOME, ver local_env.py.
from local_env import SNANA_HOME

SRC = SNANA_HOME / "run_SNANA/elastic/model_libs_updates/NON1ASED.TDE-BBFIT"
DST = Path(__file__).resolve().parent / "tdebbfit_local"


def main():
    DST.mkdir(exist_ok=True)

    shutil.copy2(SRC / "NON1A.LIST", DST / "NON1A.LIST")
    print("NON1A.LIST copiado (ya parsea limpio, sin cambios)")

    with gzip.open(SRC / "2019qiz.sed.gz", "rt", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    n_fixed = 0
    for i, line in enumerate(lines):
        if line.strip() == "phase wavelength flux":
            lines[i] = "# " + line
            n_fixed += 1

    with gzip.open(DST / "2019qiz.sed.gz", "wt", encoding="utf-8") as fh:
        fh.writelines(lines)

    print(f"2019qiz.sed.gz copiado, {n_fixed} linea(s) de encabezado sin '#' corregida(s)")


if __name__ == "__main__":
    main()
