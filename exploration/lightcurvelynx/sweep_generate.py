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

from run_simsed_poc import CLASS_CONFIGS, HERE
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


def validate_classes(classes: list[str]) -> list[str]:
    """Devuelve una lista de mensajes de error (vacia si todo esta OK).
    Dos causas raiz reales distintas, dos mensajes distintos -- no un
    "clase invalida" generico que oculte cual de las dos paso."""
    errors = []
    avail = set(available_classes())
    for c in classes:
        if c not in CLASS_CONFIGS:
            errors.append(
                f"'{c}': no es una clase real del catalogo (no esta en CLASS_CONFIGS de "
                f"run_simsed_poc.py). Clases reales: {sorted(CLASS_CONFIGS)}"
            )
        elif c not in avail:
            errors.append(
                f"'{c}': es una clase real del catalogo pero sin datos vendorizados "
                f"localmente (su simsed_dir no existe o esta vacio en esta maquina) -- "
                f"correr 'python3 vendor_snana_class.py {c}' en NLHPC primero, empaquetar "
                f"el resultado, y extraerlo aqui (ver HOWTO_LOCAL.md)."
            )
    return errors


def generate_sweep(
    *,
    sweep_name: str,
    classes: list[str],
    seeds: list[int],
    ngentot_overrides: dict[str, int] | None = None,
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
            f"sweep_name '{sweep_name}' invalido -- debe matchear {SWEEP_NAME_RE.pattern} "
            f"(letras/digitos/guion/guion-bajo, 1-64 caracteres). Esto evita nombres que "
            f"rompan la ruta real sweep_runs/<sweep_name>/ (p.ej. '/', '..', espacios)."
        )
    if not classes:
        raise ValueError("classes no puede estar vacio -- ninguna clase que simular")
    if not seeds:
        raise ValueError("seeds no puede estar vacio -- ninguna semilla que correr")

    errors = validate_classes(classes)
    if errors:
        raise ValueError("clases invalidas:\n  - " + "\n  - ".join(errors))

    out_path = SWEEPS_DIR / f"{sweep_name}.yaml"
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} ya existe -- pasa force=True para sobreescribir. "
            f"Cuidado: si ya fue compilado (sweep_runs/{sweep_name}/manifest.json), "
            f"sobreescribir el YAML sin recompilar deja el manifiesto desactualizado."
        )

    ngentot_overrides = dict(ngentot_overrides or {})
    for class_key, ngentot in ngentot_overrides.items():
        if ngentot > NGENTOT_WARN_THRESHOLD:
            print(f"  ! ADVERTENCIA: {class_key} ngentot={ngentot} supera el umbral historico "
                  f"de este proyecto ({NGENTOT_WARN_THRESHOLD}) -- confirmar que es intencional.")
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
        keep_phot=bool(keep_phot),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", dest="sweep_name")
    parser.add_argument("--classes", nargs="+")
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--ngentot", nargs="*", default=[], help="pares clase:numero, p.ej. SNIa-91bg:500")
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
        modes=[{"wfd": args.wfd, "simsed_t0_mode": "bolometric_peak"}],
        keep_phot=args.keep_phot, description=args.description, force=args.force,
    )
