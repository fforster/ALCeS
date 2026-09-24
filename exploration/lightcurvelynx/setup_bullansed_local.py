"""
Fase 7 -- NON1ASED.BULLA-BNS-M2-2COMP tiene el mismo problema de dato real
ya visto en Fase 2B ronda 4 para SIMSED.KN-BULLA19 (ver
setup_knbulla19_local.py): 549 de los 550 archivos que declara NON1A.LIST
son ZIP mal etiquetados como `*.txt.gz` (firma real `PK`, confirmado con
`file` en NLHPC), cada uno con un solo miembro interno. Mismo problema,
dato distinto: la conversion NON1ASED reusa los mismos archivos fisicos
que el SIMSED original (mismo empaquetado incorrecto heredado).
`SIMSEDModel._read_simsed_data_file()` (via `np.loadtxt`) falla con
`gzip.BadGzipFile: Not a gzipped file (b'PK')`.

Segundo bug real encontrado en esta misma libreria (no visto en
KN-BULLA19/SIMSED): UN archivo especifico
(`sed_cos_theta_0.0_mej_0.010_phi_15.txt`, confirmado por listado real de
directorio) no tiene sufijo `.gz` en absoluto -- esta en texto plano, a
diferencia de sus 549 hermanos `*.txt.gz`. NON1A.LIST lo referencia igual
como `...phi_15.txt` (sin `.gz`), y el fallback automatico de
`_read_simsed_data_file()` (que agrega `.gz` si el archivo base no
existe) espera lo contrario -- un archivo base sin `.gz` que SI existe
comprimido, no uno que genuinamente no esta comprimido. Sin la copia
local, esto fallaba con `FileNotFoundError` al buscar
`...phi_15.txt.gz` (que nunca existio).

No se modifica el archivo real de SNANA -- se genera una copia local (mismo
patron que setup_knbulla19_local.py, no versionada) donde: los 549 ZIP mal
etiquetados se descomprimen y re-comprimen como gzip real; el archivo
plano se comprime a gzip real por primera vez. Los 550 terminan con el
mismo nombre `*.txt.gz` que espera NON1A.LIST.

Uso:
    python3 setup_bullansed_local.py
    (corre en NLHPC, liviano -- solo I/O, no computo pesado)
"""
from __future__ import annotations

import gzip
import shutil
import zipfile
from pathlib import Path

# Fase 94: ALCES_DATA (carpeta compartida) o $HOME, ver local_env.py.
from local_env import SNANA_HOME

SRC = SNANA_HOME / "run_SNANA/elastic/model_libs_updates/NON1ASED.BULLA-BNS-M2-2COMP"
DST = Path(__file__).resolve().parent / "bullansed_local"


def main():
    DST.mkdir(exist_ok=True)

    shutil.copy2(SRC / "NON1A.LIST", DST / "NON1A.LIST")
    print("NON1A.LIST copiado (ya parsea limpio, sin cambios)")

    n_fixed_zip = 0
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
        n_fixed_zip += 1

    # segundo bug: archivos .txt sin .gz que NON1A.LIST referencia como
    # .txt.gz -- comprimirlos por primera vez, con el nombre .gz que espera.
    n_fixed_plain = 0
    for f in SRC.glob("*.txt"):
        dst_f = DST / f"{f.name}.gz"
        if dst_f.exists():
            n_skipped += 1
            continue
        with gzip.open(dst_f, "wb") as gz:
            gz.write(f.read_bytes())
        n_fixed_plain += 1

    print(f"{n_fixed_zip} archivo(s) descomprimidos de ZIP y re-comprimidos como gzip real")
    print(f"{n_fixed_plain} archivo(s) planos (.txt, sin .gz) comprimidos por primera vez")
    if n_skipped:
        print(f"{n_skipped} archivo(s) ya existian, sin tocar")


if __name__ == "__main__":
    main()
