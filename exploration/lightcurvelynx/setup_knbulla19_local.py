"""
Fase 2B ronda 4 -- SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP tiene un
problema de dato real distinto a los ya vistos (typo de un caracter en
SNIa-91bg, linea suelta invalida en TDE-MOSFIT): los 550 archivos
`*.txt.gz` que declara `SED.INFO` **no son gzip** -- son archivos ZIP
(firma real `PK\x03\x04`, confirmado con `file`/`xxd` en NLHPC), cada uno
con un solo miembro interno (`<mismo_nombre>.txt`). `SIMSEDModel.
_read_simsed_data_file()` usa `np.loadtxt(path, comments="#")`, que
autodetecta gzip por extension/magic bytes y falla con
`gzip.BadGzipFile: Not a gzipped file (b'PK')` -- no es un bug nuestro ni
de LightCurveLynx, es un problema real de empaquetado en el dato de
referencia (probablemente un paso de compresion equivocado al publicar
esta libreria SIMSED). El parser de SNANA (snlc_sim.exe) probablemente
usa una utilidad de sistema mas tolerante; el nuestro no.

No se modifica el archivo real de SNANA -- se genera una copia local
(mismo patron que setup_simsed_91bg_local.py/setup_simsed_local.py, no
versionada) donde cada archivo se descomprime del ZIP y se re-comprime
como gzip real, con el mismo nombre de archivo (SED.INFO no necesita
tocarse, ya parsea limpio).

Uso:
    python3 setup_knbulla19_local.py
    (corre en NLHPC, liviano -- solo I/O, no computo pesado)
"""
from __future__ import annotations

import gzip
import zipfile
from pathlib import Path

# Fase 94: ALCES_DATA (carpeta compartida) o $HOME, ver local_env.py.
from local_env import SNANA_HOME

SRC = SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.KN-BULLA19/SIMSED.BULLA-BNS-M2-2COMP"
DST = Path(__file__).resolve().parent / "simsed_knbulla19_local"


def main():
    DST.mkdir(exist_ok=True)

    info_src = SRC / "SED.INFO"
    (DST / "SED.INFO").write_bytes(info_src.read_bytes())
    print("SED.INFO copiado (ya parsea limpio, sin cambios)")

    n_fixed = 0
    n_skipped = 0
    for f in SRC.glob("*.txt.gz"):
        dst_f = DST / f.name
        if dst_f.exists():
            n_skipped += 1
            continue
        with zipfile.ZipFile(f) as zf:
            names = zf.namelist()
            if len(names) != 1:
                raise ValueError(f"{f.name}: esperaba 1 miembro interno, encontre {names}")
            raw = zf.read(names[0])
        with gzip.open(dst_f, "wb") as gz:
            gz.write(raw)
        n_fixed += 1

    print(f"{n_fixed} archivo(s) descomprimidos de ZIP y re-comprimidos como gzip real")
    if n_skipped:
        print(f"{n_skipped} archivo(s) ya existian, sin tocar")


if __name__ == "__main__":
    main()
