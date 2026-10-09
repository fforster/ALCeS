"""
Fase 98: metadatos por objeto para head_df -- SOLO lectura de lo que la
simulacion ya muestreo, nunca un muestreo nuevo (no toca el RNG ni la fisica;
la regresion dorada de tests/golden/ lo verifica bit a bit).

Origen de cada columna nueva:
  TEMPLATE_INDEX  <modelo>.selected_template (indice en el orden de las
                  lineas SED: del SED.INFO real, el mismo que indexa
                  MultiSEDTemplateModel)
  PAR_<NOMBRE>    parametros fisicos de ese template, leidos de la misma
                  linea SED: (PARNAMES del SED.INFO, sin el indice KN_INDEX/
                  similar que es la primera columna)
  MWEBV           <modelo>.ebv  (E(B-V) de la Via Lactea, con su scatter)
  HOST_AV         host_av.function_node_result (solo clases con extincion
                  de host declarada en el .INPUT real)
  HOST_EBV        <modelo>.host_ebv
  FIELD           campo DDF del sampler de RA/DEC (no existe en WFD)
  T0_CONVENTION   que significa PEAKMJD para esta clase (PEAKMJD NO cambia;
                  esto solo lo documenta -- ver t0_convention())

Las columnas que una clase no tiene (p.ej. HOST_AV en SNIa-91bg, FIELD en
WFD) simplemente no se agregan: nunca se rellenan con un valor inventado.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Clases SIMSED cuyo SED.INFO real declara OPTFLAG_T0SHIFT_PEAKMAG: 0 -- su
# PEAKMJD es la fase 0 nativa del template (fusion/explosion), no el pico
# bolometrico (NOTES.md Fase 62, confirmado barriendo las 13 clases).
NATIVE_PHASE0_CLASSES = {"KN-BULLA19", "PISN-STELLA-HECORE", "PISN-STELLA-HYDROGENIC"}

_MODEL_SUFFIXES = {"selected_template": "TEMPLATE_INDEX", "ebv": "MWEBV", "host_ebv": "HOST_EBV"}


def t0_convention(class_key: str, simsed_t0_mode: str) -> str:
    """Significado de PEAKMJD para una clase SIMSED corrida con este modo."""
    if simsed_t0_mode != "bolometric_peak" or class_key in NATIVE_PHASE0_CLASSES:
        return "native_phase0"
    return "bolometric_peak"


def _model_prefix(fields: list[str]) -> str | None:
    """Nombre del nodo del modelo fuente (p.ej. 'SIMSEDModel_0'): el que tiene
    t0 y selected_template. Los sufijos numericos de LCL no son estables entre
    versiones, por eso se busca en vez de fijarlo."""
    for f in fields:
        if f.endswith(".selected_template"):
            return f.rsplit(".", 1)[0]
    return None


def read_template_params(simsed_dir: Path | str) -> tuple[list[str], np.ndarray]:
    """(nombres, matriz n_templates x n_par) desde las lineas SED: del SED.INFO
    real, en el mismo orden de lineas que usa SIMSEDModel._read_simsed_info_file.
    Se omiten las columnas *_INDEX (KN_INDEX, Iax_INDEX... indice de template,
    no fisica). No todas las clases la tienen: SNIa-91bg declara solo
    `stretch color` (revisado en los 13 SED.INFO reales)."""
    parnames: list[str] = []
    rows: list[list[float]] = []
    for line in (Path(simsed_dir) / "SED.INFO").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("PARNAMES:"):
            parnames = line.split()[1:]
        elif line.startswith("SED:"):
            tok = line.split()
            rows.append([float(x) for x in tok[2:2 + len(parnames)]])
    if not parnames or not rows:
        return [], np.empty((0, 0))
    keep = [j for j, name in enumerate(parnames) if not name.upper().endswith("_INDEX")]
    return [parnames[j] for j in keep], np.array(rows)[:, keep]


def extract_head_metadata(valid: pd.DataFrame, simsed_dir: Path | str | None,
                          class_key: str, simsed_t0_mode: str) -> pd.DataFrame:
    """Una fila por fila de `valid` (mismo orden), con las columnas nuevas."""
    params = valid["params"]
    fields = [f.name for f in params.dtype.pyarrow_dtype]
    out: dict[str, np.ndarray] = {}

    prefix = _model_prefix(fields)
    if prefix is not None:
        for suffix, col in _MODEL_SUFFIXES.items():
            name = f"{prefix}.{suffix}"
            if name in fields:
                out[col] = params.struct.field(name).to_numpy()
    if "host_av.function_node_result" in fields:
        out["HOST_AV"] = params.struct.field("host_av.function_node_result").to_numpy()
    field_cols = [f for f in fields if f.endswith(".field") and f.startswith("ObsTableRADECSampler")]
    if field_cols:
        out["FIELD"] = params.struct.field(field_cols[0]).astype(str).to_numpy()

    meta = pd.DataFrame(out, index=valid.index)
    if "TEMPLATE_INDEX" in meta and simsed_dir is not None:
        meta["TEMPLATE_INDEX"] = meta["TEMPLATE_INDEX"].astype(int)
        names, table = read_template_params(simsed_dir)
        if names and len(table) > meta["TEMPLATE_INDEX"].max():
            for j, name in enumerate(names):
                meta[f"PAR_{name.upper()}"] = table[meta["TEMPLATE_INDEX"].to_numpy(), j]
    meta["T0_CONVENTION"] = t0_convention(class_key, simsed_t0_mode)
    return meta
