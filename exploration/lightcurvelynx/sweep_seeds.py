"""
Semillas efectivas por clase y estrategia para los sweeps (seed_scheme "per_class").

Problema (encontrado 2026-11-05): `run_simsed_poc.main()` deriva TODAS las semillas de una corrida de
`seed_base = SEED_BASE + seed_index * 1_000_000`, sin la clase. Los sweeps nativos de produccion usaban los
mismos seed_index para todas las clases (DDF 100..119, WFD 200..239), asi que el objeto k de la corrida con
seed_index s tenia la MISMA posicion (RA, Dec), el mismo t0 y el mismo cuantil de redshift en todas las clases:
p.ej. ~5,200 de 5,937 posiciones de SNIa WFD detectadas coincidian exactamente con SLSN-I, con t0 identico. Cada
clase seguia siendo una muestra valida por si sola, pero las clases no eran realizaciones independientes.

Solucion: el compilador de sweeps traduce cada semilla del YAML a una semilla efectiva propia de (clase,
estrategia), sin tocar `main()`:

    seed_index_efectivo = NATIVE_SEED_FLOOR + SEED_BLOCK * slot(clase, estrategia) + semilla_yaml
    slot = sha256("<clase>|<WFD|DDF>") mod N_SLOTS

- 0 <= semilla_yaml < SEED_BLOCK (los YAML de produccion usan 100..239).
- Rango resultante [1e8, ~9.1e9]: muy por encima de los rangos de los modos de entrenamiento (< ~2.2e7:
  tools/logz/plan_wave.py, train_sample.py, tools/nt/nt_common.py), asi que tampoco se repiten objetos entre
  corridas nativas y de entrenamiento. seed_base queda < 1e16 (cabe en int64).
- `check_unique_slots()` verifica que ninguna pareja (clase, estrategia) de CLASS_CONFIGS comparta slot; una clase
  nueva que colisionara detiene la compilacion en vez de repetir sorteos en silencio.
- La semilla efectiva va al run_hash, al manifiesto y a run_hash.json (seed_index), asi que reanudar un sweep y
  reconstruir corridas (tools/dense_model_curves.py lee seed_index de run_hash.json) siguen funcionando.
- seed_scheme "legacy" reproduce el comportamiento anterior (semilla_yaml tal cual) para recompilar sweeps viejos.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

NATIVE_SEED_FLOOR = 100_000_000
SEED_BLOCK = 10_000
N_SLOTS = 900_000
SCHEMES = ("per_class", "legacy")
DEFAULT_SCHEME = "per_class"


def strategy_name(wfd: bool) -> str:
    return "WFD" if wfd else "DDF"


def slot(class_key: str, wfd: bool) -> int:
    digest = hashlib.sha256(f"{class_key}|{strategy_name(wfd)}".encode("utf-8")).hexdigest()
    return int(digest, 16) % N_SLOTS


def effective_seed(class_key: str, wfd: bool, seed: int, scheme: str = DEFAULT_SCHEME) -> int:
    """Semilla que recibe main(): propia de (clase, estrategia) en el esquema per_class."""
    if scheme not in SCHEMES:
        raise ValueError(f"seed_scheme desconocido: {scheme!r} (opciones: {SCHEMES})")
    seed = int(seed)
    if scheme == "legacy":
        return seed
    if not 0 <= seed < SEED_BLOCK:
        raise ValueError(f"con seed_scheme 'per_class' las semillas del YAML deben estar en [0, {SEED_BLOCK}): {seed}")
    return NATIVE_SEED_FLOOR + SEED_BLOCK * slot(class_key, wfd) + seed


def check_unique_slots(class_keys: Iterable[str]) -> None:
    """Falla si dos parejas (clase, estrategia) comparten bloque de semillas."""
    seen: dict[int, str] = {}
    for c in class_keys:
        for wfd in (False, True):
            s = slot(c, wfd)
            label = f"{c}|{strategy_name(wfd)}"
            if s in seen:
                raise ValueError(f"colision de bloque de semillas entre {seen[s]} y {label} (slot {s}): "
                                 f"cambiar el nombre de clase o extender sweep_seeds.py con una sal explicita")
            seen[s] = label
