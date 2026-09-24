"""
Fase 79: backend generador de sweeps -- reemplaza la autoria 100% manual
de `sweeps/*.yaml` (confirmado: cero `yaml.dump` en todo el repo antes de
esta fase, `HOWTO.md` decia literalmente "copiar un YAML existente como
plantilla"). Es el pedido real del profesor: "backend que genere scripts".

No compila ni lanza nada -- solo escribe un `sweeps/<nombre>.yaml` real,
con EXACTAMENTE el esquema que `sweep_compile.py::build_runs()` ya espera
(mismo orden de claves que `sweeps/_smoke_local.yaml`, no una forma nueva).
Compilar (`sweep_compile.compile_sweep`) sigue siendo un paso separado y
explicito -- mismo criterio que ya sigue `sweep_launch.py` ("nunca
recompila algo que ya existe" sin `--force`).

Sin dependencia de Flask a proposito -- importable desde CLI (este
`__main__`) y desde `webapp/app.py` (Fase 83) por igual, mismo patron que
el resto de `sweep_*.py`.

Uso:
    python3 sweep_generate.py --name <nombre> --classes SNIa-91bg --seeds 0 1 \
        --ngentot SNIa-91bg:500 --wfd
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from run_simsed_poc import CLASS_CONFIGS, HERE, resolve_effective_class_config
from sweep_compile import NGENTOT_WARN_THRESHOLD
from sweep_history import record_event

SWEEPS_DIR = HERE / "sweeps"
# Fase 92: patron reusado tal cual por webapp/app.py (SafeSegmentConverter)
# para validar CUALQUIER segmento de URL que se use para construir un Path
# (sweep name, run_hash, dataset_hash) -- una sola fuente de verdad en vez
# de repetir el regex en cada lado. No cambia el comportamiento de
# SWEEP_NAME_RE, que ya usaba este mismo patron antes de esta fase.
SAFE_SEGMENT_PATTERN = r"[A-Za-z0-9_-]{1,64}"
SWEEP_NAME_RE = re.compile(f"^{SAFE_SEGMENT_PATTERN}$")

# SNIa/SALT2 vive en run_snia_ddf_poc.py, fuera del sistema de sweeps por
# decision ya tomada en Fase 73 (no se generaliza el sweep a esa clase ni
# a las 5 NON1ASED de run_non1ased_poc.py) -- sweep_generate.py solo cubre
# lo que CLASS_CONFIGS de run_simsed_poc.py ya cubre.


def available_classes() -> list[str]:
    """Clases reales usables HOY en esta maquina: estan en CLASS_CONFIGS
    (el catalogo completo, 15 claves SIMSED) Y su `simsed_dir` existe en
    disco y no esta vacio. No es una lista hardcodeada -- se auto-actualiza
    a medida que `vendor_snana_class.py` empaquete mas clases (Fase 75)."""
    out = []
    for class_key, cfg in CLASS_CONFIGS.items():
        simsed_dir = Path(cfg["simsed_dir"])
        if simsed_dir.is_dir() and any(simsed_dir.iterdir()):
            out.append(class_key)
    return sorted(out)


def available_classes_redshift_range() -> dict[str, tuple[float, float]]:
    """Fase 93: (z_min, z_max) NOMINAL de GENRANGE_REDSHIFT por cada clase
    de available_classes() -- para que index.html muestre el z_max nominal
    como referencia junto al input de override, sin duplicar CLASS_CONFIGS
    del lado de la webapp (una sola fuente de verdad: run_simsed_poc.py)."""
    return {c: CLASS_CONFIGS[c]["genrange_redshift"] for c in available_classes()}


def validate_classes(classes: list[str]) -> list[str]:
    """Devuelve una lista de mensajes de error (vacia si todo esta OK).
    Dos causas raiz reales distintas, dos mensajes distintos -- no un
    "clase invalida" generico que oculte cual de las dos paso."""
    errors = []
    avail = set(available_classes())
    for c in classes:
        if c not in CLASS_CONFIGS:
            errors.append(
                f"'{c}': not a class of the catalog (not in CLASS_CONFIGS of "
                f"run_simsed_poc.py). Available classes: {sorted(CLASS_CONFIGS)}"
            )
        elif c not in avail:
            errors.append(
                f"'{c}': a catalog class without vendored data on this machine (its "
                f"simsed_dir is missing or empty) -- run 'python3 vendor_snana_class.py {c}' "
                f"on NLHPC first, package the result and extract it here (see HOWTO_LOCAL.md)."
            )
    return errors


def generate_sweep(
    *,
    sweep_name: str,
    classes: list[str],
    seeds: list[int],
    ngentot_overrides: dict[str, int] | None = None,
    z_max_overrides: dict[str, float] | None = None,
    modes: list[dict] | None = None,
    resources: dict | None = None,
    max_concurrent: dict | None = None,
    partition: str = "general",
    keep_phot: bool = False,
    description: str = "",
    force: bool = False,
    triggered_by: str = "cli",
) -> Path:
    if not SWEEP_NAME_RE.match(sweep_name):
        raise ValueError(
            f"Invalid sweep name '{sweep_name}' -- it must match {SWEEP_NAME_RE.pattern} "
            f"(letters/digits/hyphen/underscore, 1-64 characters), so it cannot break the "
            f"sweep_runs/<sweep_name>/ path (e.g. '/', '..', spaces)."
        )
    if not classes:
        raise ValueError("No classes selected -- choose at least one class to simulate.")
    if not seeds:
        raise ValueError("No seeds given -- enter at least one seed (e.g. '0').")

    errors = validate_classes(classes)
    if errors:
        raise ValueError("Invalid classes:\n  - " + "\n  - ".join(errors))

    out_path = SWEEPS_DIR / f"{sweep_name}.yaml"
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists -- choose another sweep name (or pass force=True to "
            f"overwrite). Careful: if it was already compiled (sweep_runs/{sweep_name}/manifest.json), "
            f"overwriting the YAML without recompiling leaves the manifest out of date."
        )

    ngentot_overrides = dict(ngentot_overrides or {})
    for class_key, ngentot in ngentot_overrides.items():
        if ngentot > NGENTOT_WARN_THRESHOLD:
            print(f"  ! ADVERTENCIA: {class_key} ngentot={ngentot} supera el umbral historico "
                  f"de este proyecto ({NGENTOT_WARN_THRESHOLD}) -- confirmar que es intencional.")

    # Fase 93: validar los overrides de z_max ANTES de escribir el YAML
    # (falla rapido, mismo criterio que validate_classes() arriba) --
    # reusa resolve_effective_class_config() como unico validador real
    # (z_max > z_min nominal), sin duplicar esa regla aca.
    z_max_overrides = dict(z_max_overrides or {})
    z_max_errors = []
    for class_key, z_max in z_max_overrides.items():
        # Fase 95: el mensaje se arma aca, en ingles (se muestra en la webapp),
        # y no en run_simsed_poc.py: ese archivo es parte de CODE_FILES y
        # cambiar su texto cambiaria el code_hash (y todos los run_hash).
        try:
            resolve_effective_class_config(class_key, z_max)
        except KeyError:
            z_max_errors.append(f"'{class_key}': not a class of the catalog")
        except ValueError:
            z_min = CLASS_CONFIGS[class_key]["genrange_redshift"][0]
            z_max_errors.append(f"'{class_key}': z_max={z_max} must be greater than the nominal "
                                f"z_min ({z_min}), which cannot be overridden")
    if z_max_errors:
        raise ValueError("Invalid z_max overrides:\n  - " + "\n  - ".join(z_max_errors))

    if keep_phot:
        print("  ! ADVERTENCIA: keep_phot=true preserva phot_df.parquet de cada corrida (no se "
              "borra por cuota de disco, ver NOTES.md Fase 8/59/65/81) -- verificar headroom real "
              "de disco antes de lanzar un barrido grande con esta opcion activa.")

    # Mismo orden de claves que sweeps/_smoke_local.yaml (Fase 76) -- no una
    # forma nueva, para que sea indistinguible de un YAML escrito a mano.
    sweep_cfg: dict = {
        "sweep_name": sweep_name,
        "description": description or f"Generado por sweep_generate.py (Fase 79).",
        "seeds": list(seeds),
        "modes": modes or [{"wfd": False, "simsed_t0_mode": "bolometric_peak"}],
        "classes": list(classes),
        "ngentot_overrides": ngentot_overrides,
        "z_max_overrides": z_max_overrides,
        "resources": resources or {"default": {"mem": "8G", "time": "00:15:00", "cpus": 2}, "overrides": {}},
        "max_concurrent": max_concurrent or {"default": 2},
        "partition": partition,
        # Fase 81: opt-in de nivel-sweep, siempre explicito en el archivo
        # generado (no omitido por default) para que quede visible en el
        # propio YAML que se pidio (o no se pidio) preservar fotometria.
        "keep_phot": bool(keep_phot),
    }

    SWEEPS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "# Generado por sweep_generate.py (Fase 79) -- no escrito a mano.\n"
        + yaml.safe_dump(sweep_cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"  generado {out_path} ({len(classes)} clase(s) x {len(seeds)} semilla(s))")

    record_event(
        "generate_sweep", triggered_by=triggered_by, sweep_name=sweep_name,
        classes=list(classes), seeds=list(seeds), ngentot_overrides=ngentot_overrides,
        z_max_overrides=z_max_overrides, keep_phot=bool(keep_phot),
    )
    return out_path


def _parse_ngentot(pairs: list[str]) -> dict[str, int]:
    out = {}
    for p in pairs:
        class_key, _, value = p.partition(":")
        if not value:
            raise argparse.ArgumentTypeError(f"--ngentot espera 'clase:numero', recibido '{p}'")
        out[class_key] = int(value)
    return out


def _parse_z_max(pairs: list[str]) -> dict[str, float]:
    """Fase 93: mismo formato/patron que _parse_ngentot(), 'clase:numero',
    pero float en vez de int (z_max no es un conteo entero)."""
    out = {}
    for p in pairs:
        class_key, _, value = p.partition(":")
        if not value:
            raise argparse.ArgumentTypeError(f"--z-max espera 'clase:numero', recibido '{p}'")
        out[class_key] = float(value)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", dest="sweep_name")
    parser.add_argument("--classes", nargs="+")
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--ngentot", nargs="*", default=[], help="pares clase:numero, p.ej. SNIa-91bg:500")
    parser.add_argument("--z-max", nargs="*", default=[], dest="z_max",
                         help="pares clase:numero (override de z_max, z_min queda fijo), p.ej. KN-K17:0.5")
    parser.add_argument("--wfd", action="store_true")
    parser.add_argument("--keep-phot", action="store_true", dest="keep_phot")
    parser.add_argument("--description", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--list-classes", action="store_true", help="lista las clases disponibles y termina")
    args = parser.parse_args()

    if args.list_classes:
        for c in available_classes():
            print(c)
        raise SystemExit(0)

    if not (args.sweep_name and args.classes and args.seeds):
        parser.error("--name, --classes y --seeds son requeridos (salvo con --list-classes)")

    generate_sweep(
        sweep_name=args.sweep_name, classes=args.classes, seeds=args.seeds,
        ngentot_overrides=_parse_ngentot(args.ngentot),
        z_max_overrides=_parse_z_max(args.z_max),
        modes=[{"wfd": args.wfd, "simsed_t0_mode": "bolometric_peak"}],
        keep_phot=args.keep_phot, description=args.description, force=args.force,
    )
