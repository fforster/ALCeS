"""
Fase 66: esquema de hash de identificacion por corrida + escritura atomica
compartida por el resto de sweep_*.py (compile/worker/launch/monitor/
aggregate/publish_dataset).

Sin dependencia de `lightcurvelynx` a proposito -- solo hashlib/json/
pathlib de la libreria estandar, para poder validarse localmente (sin venv
de NLHPC) antes de tocar nada en el cluster real.

Que se hashea por corrida (`run_hash`): class_key, la config real de esa
clase en CLASS_CONFIGS (canonicalizada), seed_index, wfd, simsed_t0_mode,
ngentot resuelto, y un `code_hash` (SHA256 combinado de los .py que
determinan el resultado fisico de la simulacion). El code_hash es lo que
`pipeline/provenance/tagger.py` (produccion, no se toca) NO cubre hoy: ese
depende de que el YAML de config este congelado/commiteado; aca se hashea
el CONTENIDO real de los .py, asi que editar `searcheff.py` sin commitear
ya cambia el hash de cualquier corrida nueva.

`CLASS_CONFIGS` real (`run_simsed_poc.py`) no es JSON-limpio: `simsed_dir`
es un `pathlib.Path`, varios campos son tuplas, y `redcor_params["redcor"]`
usa CLAVES de dict que son tuplas (`{("stretch","color"): -0.656}`) -- eso
rompe `json.dumps` directo (`TypeError: keys must be str...`). Por eso
`canonicalize()` existe: recursivamente convierte todo a algo JSON-limpio
y deterministico ANTES de hashear.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA_VERSION = 1

# Los .py reales que determinan el resultado fisico de una corrida -- orden
# fijo (no alfabetico) porque el orden de concatenacion es parte del hash;
# cambiarlo a proposito cambiaria todos los code_hash existentes, lo cual
# es correcto (bump manual de SCHEMA_VERSION si eso llega a pasar).
CODE_FILES = ["run_simsed_poc.py", "searcheff.py", "snana_params.py"]


def normalize_keep_phot(value) -> bool | str:
    """Politica de almacenamiento de phot_df (no entra al run_hash): False (borrar), True (conservar todo) o
    "detected" (Fase 90: conservar solo las filas de objetos detectados)."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "detected":
            return "detected"
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0", ""):
            return False
        raise ValueError(f"keep_phot invalido: {value!r} (opciones: true, false, detected)")
    return bool(value)


def canonicalize(obj):
    """Convierte cualquier valor real de CLASS_CONFIGS a algo JSON-limpio y
    deterministico. Recursivo. Casos reales que maneja:
    - pathlib.Path -> str
    - dict con claves no-string (p.ej. tuplas de redcor_params) -> las
      claves se convierten a "a|b" antes de recursar
    - tuple/list -> lista canonicalizada recursivamente (una tupla y una
      lista con el mismo contenido deben hashear IGUAL -- ambas terminan
      como lista JSON)
    - todo lo demas (str/int/float/bool/None) -> se deja tal cual
    """
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, tuple):
                key = "|".join(str(x) for x in k)
            elif isinstance(k, str):
                key = k
            else:
                key = str(k)
            out[key] = canonicalize(v)
        return out
    if isinstance(obj, (tuple, list)):
        return [canonicalize(x) for x in obj]
    return obj


def canonical_json(obj) -> str:
    """JSON deterministico: claves ordenadas, sin espacios extra."""
    return json.dumps(canonicalize(obj), sort_keys=True, separators=(",", ":"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_files(paths: list[Path]) -> str:
    """SHA256 combinado de varios archivos, concatenados en el ORDEN dado
    (no reordenado -- el orden es parte de la identidad del hash)."""
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def code_hash(base_dir: Path | str) -> str:
    """SHA256 combinado de CODE_FILES, relativos a base_dir (normalmente
    HERE de run_simsed_poc.py -- exploration/lightcurvelynx/)."""
    base_dir = Path(base_dir)
    return hash_files([base_dir / f for f in CODE_FILES])


def run_hash(
    *,
    class_key: str,
    class_config: dict,
    seed_index: int,
    wfd: bool,
    simsed_t0_mode: str,
    ngentot: int,
    code_hash_value: str,
) -> tuple[str, str]:
    """Devuelve (hash_completo_64_hex, hash_corto_12_hex). Deterministico:
    mismo input -> mismo hash, sin timestamps ni PIDs adentro."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "class_key": class_key,
        "class_config": canonicalize(class_config),
        "seed_index": seed_index,
        "wfd": wfd,
        "simsed_t0_mode": simsed_t0_mode,
        "ngentot": ngentot,
        "code_hash": code_hash_value,
    }
    full = sha256_hex(canonical_json(payload).encode("utf-8"))
    return full, full[:12]


def write_json_atomic(path: Path | str, data) -> Path:
    """Escribe JSON de forma atomica: archivo temporal + fsync + os.replace().

    Nunca deja un archivo truncado o a medio escribir si el proceso muere a
    mitad de camino (disco lleno, OOM kill, nodo caido) -- responde directo
    a 3 incidentes reales de corrupcion por escritura fallida en esta misma
    investigacion (Fase 65: un notebook quedo en 0 bytes, 5 archivos
    _PHOT.FITS reales quedaron truncados, todos por escribir directo sobre
    el path final con `open(path, "w")`/`open(path, "wb")` en vez de este
    patron). `os.replace()` es atomico dentro del mismo filesystem POSIX.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    text = json.dumps(data, indent=2, default=str, sort_keys=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    return path


def read_json(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_jsonl(path: Path | str, record: dict) -> None:
    """Agrega UNA linea a un archivo JSON Lines -- distinto de
    write_json_atomic() a proposito (Fase 80): ahi se REEMPLAZA el archivo
    entero (un manifiesto/snapshot fresco cada vez); aca se AGREGA, nunca
    se reescriben lineas ya escritas -- es el mecanismo real detras de
    generation_history.jsonl, el historial reproducible que acumula a
    traves de multiples sweeps/publicaciones a lo largo del tiempo (algo
    que ningun manifest.json/run_hash.json hace, cada uno es un snapshot
    autocontenido de su propio evento).

    flush()+fsync() por la misma razon que write_json_atomic(): no dejar
    una linea a medio escribir si el proceso muere a mitad de camino."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, sort_keys=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_dataframe_atomic(path: Path | str, df) -> Path:
    """Escribe un DataFrame a parquet de forma atomica (mismo patron que
    write_json_atomic): to_parquet() al archivo temporal, luego
    os.replace(). Usado por sweep_aggregate.py/sweep_publish_dataset.py --
    no depende de pandas a nivel de modulo (import local) para que
    sweep_hash.py siga siendo importable sin pandas instalado."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, path)
    return path


if __name__ == "__main__":
    # Fase 66, paso 1: validacion local pura, sin lightcurvelynx ni NLHPC.
    import tempfile

    print("=== sweep_hash.py: self-test local ===")

    # caso real: SNIa-91bg tal como aparece en CLASS_CONFIGS (redcor_params
    # con clave tupla en "redcor", simsed_dir como Path).
    cfg_91bg = dict(
        simsed_dir=Path("simsed_91bg_local"),
        genrange_redshift=(0.011, 0.6),
        dndz=("powerlaw", [(3.0e-6, 1.5, 0.011, 0.6)]),
        sntype=13,
        redcor_params=dict(
            peaks=dict(stretch=0.975, color=0.557),
            sigmas=dict(stretch=0.096, color=0.175),
            redcor={("stretch", "color"): -0.656},
        ),
        trest_range=(-100.0, 400.0),
    )

    fake_code_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b85"

    h1_full, h1_short = run_hash(
        class_key="SNIa-91bg", class_config=cfg_91bg, seed_index=0, wfd=False,
        simsed_t0_mode="bolometric_peak", ngentot=2000, code_hash_value=fake_code_hash,
    )
    print(f"hash SNIa-91bg seed=0: {h1_short} ({h1_full})")
    assert len(h1_full) == 64 and len(h1_short) == 12

    # 1. determinismo: mismo input -> mismo hash (objeto NUEVO, no el mismo
    #    dict en memoria, para probar de verdad la canonicalizacion).
    cfg_91bg_copy = dict(
        simsed_dir=Path("simsed_91bg_local"),
        genrange_redshift=(0.011, 0.6),
        dndz=("powerlaw", [(3.0e-6, 1.5, 0.011, 0.6)]),
        sntype=13,
        redcor_params=dict(
            peaks=dict(stretch=0.975, color=0.557),
            sigmas=dict(stretch=0.096, color=0.175),
            redcor={("stretch", "color"): -0.656},
        ),
        trest_range=(-100.0, 400.0),
    )
    h1_repeat_full, _ = run_hash(
        class_key="SNIa-91bg", class_config=cfg_91bg_copy, seed_index=0, wfd=False,
        simsed_t0_mode="bolometric_peak", ngentot=2000, code_hash_value=fake_code_hash,
    )
    assert h1_repeat_full == h1_full, "FALLO: mismo input deberia dar el mismo hash"
    print("  OK: determinismo (mismo input -> mismo hash)")

    # 2. sensibilidad: cambiar seed_index -> hash distinto.
    h2_full, _ = run_hash(
        class_key="SNIa-91bg", class_config=cfg_91bg, seed_index=1, wfd=False,
        simsed_t0_mode="bolometric_peak", ngentot=2000, code_hash_value=fake_code_hash,
    )
    assert h2_full != h1_full, "FALLO: distinto seed_index deberia dar hash distinto"
    print("  OK: sensibilidad a seed_index")

    # 3. sensibilidad: cambiar un valor DENTRO de la clave tupla de redcor
    #    (el caso mas fragil -- si canonicalize() no maneja bien la clave
    #    tupla, esto podria fallar en json.dumps antes de llegar aca).
    cfg_91bg_redcor_distinto = dict(cfg_91bg)
    cfg_91bg_redcor_distinto["redcor_params"] = dict(
        peaks=dict(stretch=0.975, color=0.557),
        sigmas=dict(stretch=0.096, color=0.175),
        redcor={("stretch", "color"): -0.999},  # valor distinto
    )
    h3_full, _ = run_hash(
        class_key="SNIa-91bg", class_config=cfg_91bg_redcor_distinto, seed_index=0, wfd=False,
        simsed_t0_mode="bolometric_peak", ngentot=2000, code_hash_value=fake_code_hash,
    )
    assert h3_full != h1_full, "FALLO: cambiar el valor de redcor deberia dar hash distinto"
    print("  OK: sensibilidad al valor dentro de una clave-tupla de redcor_params")

    # 4. sensibilidad: cambiar code_hash (simula editar searcheff.py sin
    #    commitear) -> hash distinto aunque la config sea identica.
    h4_full, _ = run_hash(
        class_key="SNIa-91bg", class_config=cfg_91bg, seed_index=0, wfd=False,
        simsed_t0_mode="bolometric_peak", ngentot=2000,
        code_hash_value="0" * 64,
    )
    assert h4_full != h1_full, "FALLO: distinto code_hash deberia dar hash distinto"
    print("  OK: sensibilidad a code_hash (detecta cambios de codigo)")

    # 5. escritura atomica: write_json_atomic + read_json deben dar ida y
    #    vuelta identica, y no debe quedar ningun archivo .tmp.* huerfano.
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "sub" / "run_hash.json"
        payload = {"run_hash": h1_short, "status": "done", "class_key": "SNIa-91bg"}
        write_json_atomic(target, payload)
        assert target.exists(), "FALLO: write_json_atomic no creo el archivo"
        loaded = read_json(target)
        assert loaded == payload, "FALLO: ida y vuelta de write_json_atomic/read_json no coincide"
        leftover = list(target.parent.glob("*.tmp.*"))
        assert not leftover, f"FALLO: quedaron archivos temporales huerfanos: {leftover}"
    print("  OK: escritura atomica (write_json_atomic/read_json ida y vuelta, sin huerfanos)")

    print("\n=== todos los self-tests locales pasaron ===")
