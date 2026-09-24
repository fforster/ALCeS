"""
Fase 74 -- portabilidad de rutas: reemplaza el hardcode real a
`/home/mvalenzuela` (21 archivos, confirmado por grep) que asumía que este
proyecto solo corre en la cuenta real de NLHPC del usuario. Sin este módulo,
instalar el proyecto en otra máquina (el pedido real del profesor: correr la
generación de simulaciones en su propio computador) requeriría editar cada
archivo a mano.

Uso real: cada script que antes tenía

    SNANA_HOME = Path("/home/mvalenzuela")
    ...
    sys.path.insert(0, "/home/mvalenzuela/AUTOSIM")

pasa a

    from local_env import SNANA_HOME, REPO_ROOT
    sys.path.insert(0, str(REPO_ROOT))

En NLHPC esto resuelve exactamente igual que antes sin tocar nada (el `home`
real del usuario ya es `/home/mvalenzuela`) -- no requiere exportar ninguna
variable de entorno ahí. En una instalación nueva (el caso real que motiva
este archivo), `SNANA_HOME` se puede apuntar a cualquier carpeta que tenga
`run_SNANA/` (y, si se necesita, `DATASIM_LSST_1/`) vía la variable de
entorno `SNANA_HOME` -- sin ella, cae al home real del usuario que corre el
script, que es lo más razonable para una instalación de un solo usuario.
"""
from __future__ import annotations

import os
from pathlib import Path

# Raíz que contiene `run_SNANA/` (config/plantillas reales de SNANA) y,
# opcionalmente, `DATASIM_LSST_1/` (solo lo necesitan los scripts de
# comparación contra SNANA, no los 3 scripts de producción). Por defecto el
# home real del usuario -- en NLHPC eso ya es `/home/mvalenzuela`, cero
# cambio de comportamiento. Override real vía variable de entorno para
# cualquier otra estructura de carpetas.
#
# Fase 94: el nombre canónico es ALCES_DATA (la carpeta compartida del
# equipo en NLHPC, la misma que usa pipeline/paths.py::alces_data());
# SNANA_HOME se sigue aceptando como alias.
SNANA_HOME = Path(os.environ.get("ALCES_DATA")
                  or os.environ.get("SNANA_HOME")
                  or str(Path.home()))

# Raíz real del repo (antes hardcodeada a "/home/mvalenzuela/AUTOSIM" en 15+
# archivos) -- se calcula desde la ubicación real de este archivo
# (exploration/lightcurvelynx/local_env.py, dos niveles bajo la raíz),
# funciona sin importar el nombre o ubicación real de la carpeta donde se
# clonó el repo.
REPO_ROOT = Path(__file__).resolve().parents[2]
