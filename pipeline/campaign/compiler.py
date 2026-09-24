"""
compiler.py — Compilador de campanha: expande campaign.yaml a archivos .INPUT
y a un script SLURM por GENVERSION.

REDISEÑO: en vez de generar un unico master_submit.INPUT para
submit_batch_jobs.sh (herramienta que el usuario nunca uso en la practica),
se genera UN SCRIPT SBATCH POR GENVERSION que invoca snlc_sim.exe
directamente — replicando EXACTO el patron probado y ya usado con exito en
NLHPC (DATASIM_LSST/DDF/input_files_v6/<CLASE>/run_<CLASE>_<fecha>.sh):

    ml SNANA/<version>
    export SNDATA_ROOT=<ruta>
    snlc_sim.exe sim_<GENVERSION>.INPUT

Esto es mas simple, no requiere un archivo de plantilla SLURM adicional, y
usa exactamente la invocacion que ya esta validada en la cuenta del usuario.

Genera:

    out_dir/
    ├── includes/
    │   ├── include_survey_WFD_baseline_v5.3.1_10yrs.INPUT
    │   ├── include_survey_DDF_baseline_v5.3.1_10yrs.INPUT
    │   ├── include_model_SNIa.INPUT
    │   ├── include_model_SNII.INPUT
    │   └── ...
    ├── sim_SNIa_WFD_baseline_v5.3.1_10yrs.INPUT
    ├── sim_SNII_WFD_baseline_v5.3.1_10yrs.INPUT
    ├── ...
    ├── slurm/
    │   ├── run_SNIa_WFD_baseline_v5.3.1_10yrs.sh
    │   ├── run_SNII_WFD_baseline_v5.3.1_10yrs.sh
    │   └── ...
    ├── submit_all.sh                 ← lanza los N sbatch en secuencia (Capa 3)
    └── campaign_manifest.json        ← inventario de todo lo generado
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import templates as tpl
from ..paths import UnresolvedPathError, expand_alces_vars, expand_path


class CampaignError(RuntimeError):
    pass


def _expand(path_str: str, dry_run: bool) -> str:
    """Rutas de models.yaml/campaign.yaml con ${ALCES_DATA} etc. (Fase 94)."""
    if not path_str:
        return path_str
    try:
        return expand_path(path_str)
    except UnresolvedPathError as exc:
        if dry_run:
            return path_str
        raise CampaignError(str(exc)) from exc


@dataclasses.dataclass
class CampaignPlan:
    """Resultado de la compilacion: todas las rutas generadas."""
    out_dir: Path
    survey_includes: list[Path]
    model_includes: list[Path]
    root_inputs: list[Path]
    slurm_scripts: list[Path]
    submit_all: Path | None
    manifest: dict


# ------------------------------------------------------------------ loader
def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_models(catalog_path: Path) -> dict[str, dict]:
    raw = _load_yaml(catalog_path)
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _simlib_path_for(run: str, strategy: str, data_dir: str | None = None) -> str:
    """Ruta ABSOLUTA al SIMLIB generado por la Capa 1.

    snlc_sim.exe corre con cwd=out_dir (via el script sbatch), asi que una
    ruta relativa tipo 'data/simlib/...' resolveria mal. Se resuelve siempre
    a absoluta respecto del cwd actual de compilacion.
    """
    base = Path(data_dir or "data/simlib").resolve()
    return str(base / run / f"{strategy}_{run}.SIMLIB")


def _mjd_range_from_coverage(run: str, strategy: str, data_dir: str | None = None,
                             peakmjd_pad: int = 50) -> tuple[float, float, float, float]:
    """Lee mjd_min/max del .coverage.json de la Capa 1 (fallback si no existe).

    Devuelve (mjd_min, mjd_max, peakmjd_min, peakmjd_max). GENRANGE_MJD usa la
    ventana real de observacion; GENRANGE_PEAKMJD se ensancha hacia afuera por
    peakmjd_pad dias (para capturar objetos con pico justo antes/despues del
    survey) — igual que en el .input real de referencia del usuario.
    """
    base = data_dir or "data/simlib"
    cov_file = Path(base) / run / f"{strategy}_{run}.coverage.json"
    if cov_file.exists():
        cov = json.loads(cov_file.read_text())
        mjd_lo, mjd_hi = cov["mjd_min"], cov["mjd_max"]
    else:
        mjd_lo, mjd_hi = 61208.0, 62500.0  # fallback tipico v5.3.1
    return mjd_lo, mjd_hi, mjd_lo - peakmjd_pad, mjd_hi + peakmjd_pad


# ------------------------------------------------------------------ compilador
def compile_campaign(
    campaign_path: str | Path,
    out_dir: str | Path | None = None,
    simlib_data_dir: str | None = None,
    dry_run: bool = False,
) -> CampaignPlan:
    """Lee campaign.yaml + models.yaml y genera todo el arbol de .INPUT + SLURM."""
    campaign_path = Path(campaign_path)
    camp = _load_yaml(campaign_path)
    name = camp.get("name", "unnamed")

    catalog_rel = camp.get("models_catalog", "pipeline/models.yaml")
    catalog_path = (campaign_path.parent / catalog_rel)
    if not catalog_path.exists():
        catalog_path = Path(catalog_rel)
    if not catalog_path.exists():
        raise CampaignError(f"catalogo de modelos no encontrado: {catalog_rel}")
    all_models = _load_models(catalog_path)

    defs = camp.get("defaults", {}) or {}
    runs = camp.get("runs", [])
    classes = camp.get("classes", [])
    batch = camp.get("batch", {}) or {}

    out = Path(out_dir or f"build/{name}")
    inc_dir = out / "includes"
    slurm_dir = out / "slurm"
    if not dry_run:
        inc_dir.mkdir(parents=True, exist_ok=True)
        slurm_dir.mkdir(parents=True, exist_ok=True)

    survey_includes: list[Path] = []
    model_includes: list[Path] = []
    root_inputs: list[Path] = []
    slurm_scripts: list[Path] = []
    combos: list[dict] = []

    required_defaults = ("kcor_file", "searcheff_pipeline_file", "searcheff_pipeline_logic_file")
    missing_defs = [k for k in required_defaults if not defs.get(k)]
    if missing_defs and not dry_run:
        raise CampaignError(
            f"faltan claves obligatorias en 'defaults' de {campaign_path.name}: {missing_defs}"
        )

    # --- survey includes (uno por run × strategy) ---
    for rspec in runs:
        run = rspec["run"]
        for strat in rspec.get("strategies", ["WFD"]):
            simlib = _simlib_path_for(run, strat, simlib_data_dir)
            mjd_lo, mjd_hi, pk_lo, pk_hi = _mjd_range_from_coverage(
                run, strat, simlib_data_dir, defs.get("peakmjd_pad", 50))
            ctx = tpl.SurveyContext(
                run=run, strategy=strat, simlib_path=simlib,
                mjd_min=mjd_lo, mjd_max=mjd_hi,
                peakmjd_min=pk_lo, peakmjd_max=pk_hi,
                kcor_file=_expand(defs.get("kcor_file", ""), dry_run),
                searcheff_pipeline_file=_expand(defs.get("searcheff_pipeline_file", ""), dry_run),
                searcheff_pipeline_logic_file=_expand(
                    defs.get("searcheff_pipeline_logic_file", ""), dry_run),
                genfilters=defs.get("genfilters", "ugrizY"),
                solid_angle=defs.get("solid_angle", 0.0),
                simlib_maxranstart=defs.get("simlib_maxranstart", 1000),
                simlib_mskopt=defs.get("simlib_mskopt", 128),
                gensigma_search_peakmjd=defs.get("gensigma_search_peakmjd", 1.0),
                opt_mwebv=defs.get("opt_mwebv", 1),
                opt_mwcolorlaw=defs.get("opt_mwcolorlaw", 99),
                smearflag_flux=defs.get("smearflag_flux", 1),
                smearflag_zeropt=defs.get("smearflag_zeropt", 1),
                format_mask=defs.get("format_mask", 32),
                dump_all=defs.get("simgen_dumpall", True),
            )
            fname = f"include_survey_{strat}_{run}.INPUT"
            path = inc_dir / fname
            if not dry_run:
                path.write_text(tpl.render_survey_include(ctx), encoding="utf-8")
            survey_includes.append(path)

    # --- model includes (uno por clase, reutilizado entre runs) ---
    seen_models: set[str] = set()
    for cspec in classes:
        mkey = cspec["model"]
        if mkey in seen_models:
            continue
        seen_models.add(mkey)
        if mkey not in all_models:
            raise CampaignError(f"clase '{mkey}' no existe en {catalog_path}")
        raw = all_models[mkey]
        ngen = cspec.get("ngen", raw.get("ngen", 10000))

        opt_mwebv_default = defs.get("opt_mwebv", 1)
        opt_mwcolorlaw_default = defs.get("opt_mwcolorlaw", 99)

        if raw.get("simgen_include"):
            # Si el archivo curado ya define OPT_MWEBV/OPT_MWCOLORLAW (comun en
            # modelos LCLIB cuyo template ya trae la extincion MW aplicada), NO
            # inyectar el default — SNANA aborta con clave duplicada si se repite.
            curated_text = ""
            simgen_include = _expand(raw["simgen_include"], dry_run)
            curated_path = Path(simgen_include)
            if curated_path.is_file():
                curated_text = curated_path.read_text(encoding="utf-8", errors="replace")
            # Fase 94: en la copia compartida los SIMGEN_INCLUDE usan
            # ${ALCES_DATA} en GENMODEL/PATH_NON1ASED. Se escribe una copia
            # expandida junto a los includes generados, asi snlc_sim.exe solo
            # ve rutas absolutas (no depende del entorno del job SLURM).
            expanded_text = expand_alces_vars(curated_text)
            if expanded_text != curated_text:
                curated_copy = inc_dir / f"curated_{mkey}.INPUT"
                if not dry_run:
                    curated_copy.write_text(
                        f"# Copia expandida (Fase 94) de: {curated_path}\n" + expanded_text,
                        encoding="utf-8")
                simgen_include = str(curated_copy.resolve())
                curated_text = expanded_text
            has_mwebv = bool(re.search(r"(?im)^\s*OPT_MWEBV\s*:", curated_text))
            has_mwcolorlaw = bool(re.search(r"(?im)^\s*OPT_MWCOLORLAW\s*:", curated_text))
            spec = tpl.ModelSpec(
                key=mkey, simgen_include=simgen_include, ngen=ngen,
                opt_mwebv=None if has_mwebv else opt_mwebv_default,
                opt_mwcolorlaw=None if has_mwcolorlaw else opt_mwcolorlaw_default,
            )
        else:
            missing = [k for k in ("genmodel", "gentype", "dndz", "zrange", "trest") if k not in raw]
            if missing:
                raise CampaignError(
                    f"clase '{mkey}': sin 'simgen_include' y faltan campos SCRATCH {missing}"
                )
            spec = tpl.ModelSpec(
                key=mkey, genmodel=raw["genmodel"],
                genmodel_path=expand_alces_vars(raw.get("genmodel_path", "")),
                gentype=raw["gentype"], dndz=raw["dndz"],
                zrange=tuple(raw["zrange"]), trest=tuple(raw["trest"]),
                minslope_extrap_late=raw.get("minslope_extrap_late"),
                ngen=ngen,
                opt_mwebv=opt_mwebv_default, opt_mwcolorlaw=opt_mwcolorlaw_default,
            )
        fname = f"include_model_{mkey}.INPUT"
        path = inc_dir / fname
        if not dry_run:
            path.write_text(tpl.render_model_include(spec), encoding="utf-8")
        model_includes.append(path)

    # --- root .INPUT + script SLURM (uno por run × strategy × class) ---
    for rspec in runs:
        run = rspec["run"]
        for strat in rspec.get("strategies", ["WFD"]):
            survey_inc = str((inc_dir / f"include_survey_{strat}_{run}.INPUT").resolve()) \
                if not dry_run else f"includes/include_survey_{strat}_{run}.INPUT"
            for cspec in classes:
                mkey = cspec["model"]
                raw = all_models[mkey]
                # Prioridad: override explicito en campaign.yaml (aplica a
                # cualquier estrategia) > NGENTOT_LC real por estrategia
                # (ngen_wfd/ngen_ddf en models.yaml, calibrado contra
                # DATASIM_LSST) > fallback generico 'ngen' (clases sin dato
                # real todavia, ver notas en models.yaml).
                strat_key = f"ngen_{strat.lower()}"
                ngen = cspec.get("ngen", raw.get(strat_key, raw.get("ngen", 10000)))
                genversion = f"{mkey}_{strat}_{run}"
                model_inc = str((inc_dir / f"include_model_{mkey}.INPUT").resolve()) \
                    if not dry_run else f"includes/include_model_{mkey}.INPUT"
                content = tpl.render_root_input(
                    genversion=genversion,
                    survey_include=survey_inc,
                    model_include=model_inc,
                    ngen=ngen,
                    ranseed=defs.get("ranseed", 12945),
                )
                fname = f"sim_{genversion}.INPUT"
                path = out / fname
                if not dry_run:
                    path.write_text(content, encoding="utf-8")
                root_inputs.append(path)

                sh_name = f"run_{genversion}.sh"
                sh_path = slurm_dir / sh_name
                if not dry_run:
                    sh_path.write_text(_render_slurm_script(genversion, fname, batch), encoding="utf-8")
                    sh_path.chmod(0o755)
                slurm_scripts.append(sh_path)

                combos.append({"genversion": genversion, "run": run, "strategy": strat,
                               "model": mkey, "ngen": ngen, "file": fname,
                               "slurm_script": f"slurm/{sh_name}"})

    # --- submit_all.sh: lanza todos los sbatch (Capa 3) ---
    submit_all = None
    if not dry_run:
        submit_all = out / "submit_all.sh"
        submit_all.write_text(_render_submit_all(name, combos), encoding="utf-8")
        submit_all.chmod(0o755)

    # --- manifest ---
    manifest = {
        "campaign": name,
        "description": camp.get("description", ""),
        "compiled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_survey_includes": len(survey_includes),
        "n_model_includes": len(model_includes),
        "n_root_inputs": len(root_inputs),
        "combos": combos,
    }
    if not dry_run:
        (out / "campaign_manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )

    return CampaignPlan(
        out_dir=out,
        survey_includes=survey_includes,
        model_includes=model_includes,
        root_inputs=root_inputs,
        slurm_scripts=slurm_scripts,
        submit_all=submit_all,
        manifest=manifest,
    )


# ------------------------------------------------------------------ SLURM
def _render_slurm_script(genversion: str, input_fname: str, batch: dict) -> str:
    """Script sbatch por GENVERSION — replica EXACTO el patron probado del
    usuario (run_<CLASE>_<fecha>.sh): ml SNANA + export SNDATA_ROOT +
    snlc_sim.exe <input>. Corre con cwd = out_dir (el .INPUT esta ahi mismo)."""
    partition = batch.get("partition", "general")
    mem_per_cpu = batch.get("mem_per_cpu", 2000)
    walltime = batch.get("walltime", "04:00:00")
    mail_user = batch.get("mail_user", "")
    # ${ALCES_DATA}/${ALCES_REPO} se fijan al compilar (Fase 94): el job no
    # depende de que el usuario los tenga exportados al hacer sbatch.
    setup = expand_alces_vars(batch.get("snana_login_setup", "module load SNANA/11.05p").strip())

    lines = [
        "#!/bin/bash",
        "#---------------Script SBATCH - NLHPC ----------------",
        f"#SBATCH -J run_{genversion}",
        f"#SBATCH -p {partition}",
        "#SBATCH -n 1",
        "#SBATCH -c 1",
        f"#SBATCH --mem-per-cpu={mem_per_cpu}",
        f"#SBATCH --time={walltime}",
    ]
    if mail_user:
        lines += [f"#SBATCH --mail-user={mail_user}", "#SBATCH --mail-type=END,FAIL"]
    lines += [
        f"#SBATCH -o run_{genversion}_%j.out",
        f"#SBATCH -e run_{genversion}_%j.err",
        "",
        "#-----------------Toolchain---------------------------",
        "# ----------------Modulos----------------------------",
        setup,
        "# ----------------Comando--------------------------",
        "",
        f"snlc_sim.exe {input_fname}",
        "",
    ]
    return "\n".join(lines) + "\n"


def _render_submit_all(name: str, combos: list[dict]) -> str:
    """Script que lanza todos los sbatch de la campanha (uso: bash submit_all.sh)."""
    lines = [
        "#!/bin/bash",
        f"# submit_all.sh — lanza los {len(combos)} jobs de la campanha '{name}'",
        "# Generado por compile_campaign.py — correr desde este mismo directorio.",
        "set -e",
        "",
    ]
    for c in combos:
        lines.append(f'sbatch "{c["slurm_script"]}"')
    lines.append("")
    return "\n".join(lines) + "\n"
