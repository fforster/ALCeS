"""Add a normal-SN Ia class, "SNIa-SALT2", to the ALCeS sweep system (run on Leftraru, in exploration/lightcurvelynx/).

LSST_sim_lcs, 2026-09-30 -- see docs/SNIa_SALT2.md. Until now SNIa/SALT2 lived only in run_snia_ddf_poc.py (outside the
sweep system, Fase 73). This patch makes it a CLASS_CONFIGS class that goes through the same code path as every SIMSED
class (OpSim noise, FOV-uniform positions, MW extinction F99, RESTLAMBDA gate, SEARCHEFF trigger, outputs), with the
SALT2 physics of run_snia_ddf_poc.py / SIMGEN_INCLUDE_SNIa-SALT2.INPUT:

  * SALT2.WFIRST-H17 (salt2_h17_local, from setup_salt2_local.py), x1/c bifurcated Gaussians, alpha 0.14, beta 3.1,
    M = -19.365 + MAG_OFFSET (0.27, SALT2.INFO), coherent SIGMA_INT 0.090 (G10 approximation, as in the PoC),
    H0 70, Om 0.315; DNDZ POWERLAW2 (Dilday 2008 + high-z), z 0.011-1.2, GENRANGE_TREST -100/300;
  * RESTLAMBDA_RANGE 2000-23000 A (SALT2.INFO) through the existing gate;
  * GENMODEL_EXTRAP_LATETIME (SNIa_Extrap_LateTime_2expon.TEXT, K. Mandel): after 45 rest-frame days
    F(t, lam) = F(45, lam) g(t)/g(45), g(t) = exp(-t/tau1) + rho exp(-t/tau2), (tau1, tau2, rho) interpolated linearly
    in rest wavelength (clamped at the table ends). Before the SALT2 phase range (-20 d): zero flux.

All code goes into run_simsed_poc.py (it is part of sweep_hash.CODE_FILES, so it enters the run hash); sweep_generate.py
learns that a SALT2 class is available when its salt2_dir exists. Backups: *.bak_snia_salt2_20260930.

    python3 patch_alces_snia_salt2.py
"""
import shutil
from pathlib import Path

HERE = Path.cwd()
TAG = "bak_snia_salt2_20260930"


def patch(path, pairs):
    p = HERE / path
    s = p.read_text()
    if "SNIa-SALT2" in s:
        print(f"{path}: already patched")
        return
    for a, b in pairs:
        assert s.count(a) == 1, (path, a[:80], s.count(a))
        s = s.replace(a, b)
    bak = p.with_suffix(p.suffix + "." + TAG)
    if not bak.exists():
        shutil.copy2(p, bak)
    p.write_text(s)
    print(f"{path}: patched (backup {bak.name})")


SALT2_CODE = '''

# --- SNIa-SALT2 (LSST_sim_lcs 2026-09-30, docs/SNIa_SALT2.md): SALT2 inside the sweep system ------------------------
# GENMODEL_EXTRAP_LATETIME of SIMGEN_INCLUDE_SNIa-SALT2.INPUT (SNIa_Extrap_LateTime_2expon.TEXT, K. Mandel 2018):
# columns rest wavelength [A], TAU1 [d], TAU2 [d], EXPRATIO; applied after EXTRAP_DAYMIN rest-frame days.
SALT2_LATE_DAYMIN = 45.0
SALT2_LATE_TABLE = np.array([[3590, 33.0, 59.9, 1.01], [4380, 57.1, 91.7, 0.30], [5490, 31.0, 84.0, 0.31],
                             [6520, 28.6, 56.2, 0.35], [8030, 20.6, 84.0, 0.25], [11000, 18.3, 147.0, 0.06],
                             [12500, 16.9, 100.0, 0.14]])


def _salt2_latetime_class():
    from lightcurvelynx.models.sncosmo_models import SncosmoWrapperModel

    class SALT2LateTimeModel(SncosmoWrapperModel):
        """SALT2 (sncosmo source) + SNANA's two-exponential late-time extrapolation after 45 rest-frame days:
        F(t, lam) = F(45, lam) g(t)/g(45), g(t) = exp(-t/tau1) + rho exp(-t/tau2), parameters linear in rest lam.
        maxphase() is None so the generic time extrapolation of PhysicalModel is not used after the model range."""

        def maxphase(self, **kwargs):
            return None

        def compute_sed(self, times, wavelengths, graph_state=None, **kwargs):
            params = self.get_local_params(graph_state)
            times = np.asarray(times, dtype=float)
            phase = times - params["t0"]
            late = phase > SALT2_LATE_DAYMIN
            flux = np.zeros((len(times), len(wavelengths)))
            if (~late).any():
                flux[~late] = super().compute_sed(times[~late], wavelengths, graph_state, **kwargs)
            if late.any():
                f45 = super().compute_sed(np.array([params["t0"] + SALT2_LATE_DAYMIN]), wavelengths, graph_state,
                                          **kwargs)[0]
                tab = SALT2_LATE_TABLE
                tau1, tau2, rho = (np.interp(wavelengths, tab[:, 0], tab[:, k]) for k in (1, 2, 3))
                g = lambda t: np.exp(-t / tau1) + rho * np.exp(-t / tau2)
                flux[late] = f45[None, :] * g(phase[late][:, None]) / g(SALT2_LATE_DAYMIN)[None, :]
            return flux

    return SALT2LateTimeModel


def build_salt2_model(cfg, seed_base, redshift_func, radec_sampler, t0_func, t_start):
    """SALT2 source model for a CLASS_CONFIGS entry with model="salt2" (same physics as run_snia_ddf_poc.py)."""
    import sncosmo
    from lightcurvelynx.astro_utils.snia_utils import DistModFromRedshift, X0FromDistMod
    from snana_params import make_bifurcated_normal_sampler, read_salt2_info

    salt2_dir = Path(cfg["salt2_dir"])
    src = sncosmo.SALT2Source(modeldir=str(salt2_dir), name="salt2-h17-local")
    c_func = SizeAwareFunctionNode(make_bifurcated_normal_sampler(**cfg["salt2c"], seed=seed_base + 13), node_label="c")
    x1_func = SizeAwareFunctionNode(make_bifurcated_normal_sampler(**cfg["salt2x1"], seed=seed_base + 14),
                                    node_label="x1")
    distmod_func = DistModFromRedshift(redshift_func, H0=70.0, Omega_m=0.315)
    mag_offset = read_salt2_info(salt2_dir)["MAG_OFFSET"]
    m_abs_func = NumpyRandomFunc("normal", loc=-19.365 + mag_offset, scale=cfg["sigma_int"], seed=seed_base + 15)
    x0_func = X0FromDistMod(distmod=distmod_func, x1=x1_func, c=c_func, alpha=cfg["alpha"], beta=cfg["beta"],
                            m_abs=m_abs_func)
    model = _salt2_latetime_class()(
        src, t0=t0_func, x0=x0_func, x1=x1_func, c=c_func,
        ra=radec_sampler.ra, dec=radec_sampler.dec, redshift=redshift_func,
        node_label="source", time_extrapolation=ZeroPadding(), wave_extrapolation=ZeroPadding(),
    )
    print(f"[{time.time()-t_start:.1f}s] SALT2 (H17 local, MAG_OFFSET {mag_offset}) + late-time 2-exponential "
          f"extrapolation after {SALT2_LATE_DAYMIN:g} d")
    return model


# --- config por clase, parametros reales de cada SIMGEN_INCLUDE_*.INPUT ---
CLASS_CONFIGS = {'''

CLASS_ENTRY = '''
    # SNIa-SALT2 (LSST_sim_lcs 2026-09-30, docs/SNIa_SALT2.md): normal SNe Ia in the sweep system, parameters of
    # run_SNANA/model_config/SIMGEN_INCLUDE_SNIa-SALT2.INPUT (same as run_snia_ddf_poc.py), model built by
    # build_salt2_model(); RESTLAMBDA_RANGE from SALT2.WFIRST-H17/SALT2.INFO.
    "SNIa-SALT2": dict(
        model="salt2",
        salt2_dir=HERE / "salt2_h17_local",
        genrange_redshift=(0.011, 1.2),
        dndz=("powerlaw", [(2.5e-5, 1.5, 0.0, 1.0), (9.7e-5, -0.5, 1.0, 3.0)]),
        sntype=1,
        salt2c=dict(peak=-0.054, sigma_lo=0.043, sigma_hi=0.101, lo=-0.3, hi=0.5),
        salt2x1=dict(peak=0.973, sigma_lo=1.472, sigma_hi=0.222, lo=-3.0, hi=2.0),
        alpha=0.14,
        beta=3.1,
        sigma_int=0.090,
        trest_range=(-100.0, 300.0),
        restlambda_range=(2000.0, 23000.0),
    ),'''

patch("run_simsed_poc.py", [
    ("\n\n# --- config por clase, parametros reales de cada SIMGEN_INCLUDE_*.INPUT ---\nCLASS_CONFIGS = {",
     SALT2_CODE + CLASS_ENTRY),
    ('''    simsed_dir = cfg["simsed_dir"]
    file_names, _ = SIMSEDModel._read_simsed_info_file(simsed_dir)
    if "redcor_params" in cfg:''',
     '''    is_salt2 = cfg.get("model") == "salt2"          # SNIa-SALT2: no SIMSED templates (build_salt2_model)
    simsed_dir = cfg.get("simsed_dir")
    file_names = [] if is_salt2 else SIMSEDModel._read_simsed_info_file(simsed_dir)[0]
    if is_salt2:
        weights = None
    elif "redcor_params" in cfg:'''),
    ('''    if simsed_t0_mode == "bolometric_peak":
        templates, flux_scale = load_simsed_templates_bolometric(simsed_dir)''',
     '''    if is_salt2:
        source_model = build_salt2_model(cfg, seed_base, redshift_func, radec_sampler, t0_func, t_start)
    elif simsed_t0_mode == "bolometric_peak":
        templates, flux_scale = load_simsed_templates_bolometric(simsed_dir)'''),
    ('''    source_model._sampler_node.set_seed(seed_base + 9)
    source_model.add_effect(mw_extinction)''',
     '''    if not is_salt2:
        source_model._sampler_node.set_seed(seed_base + 9)
    source_model.add_effect(mw_extinction)'''),
    ('''    print(f"[{time.time()-t_start:.1f}s] SIMSEDModel cargado ({len(source_model)} templates)")''',
     '''    print(f"[{time.time()-t_start:.1f}s] " + ("SALT2 model cargado" if is_salt2 else
                                                f"SIMSEDModel cargado ({len(source_model)} templates)"))'''),
])

patch("sweep_generate.py", [
    ('''        simsed_dir = Path(cfg["simsed_dir"])
        if simsed_dir.is_dir() and any(simsed_dir.iterdir()):''',
     '''        simsed_dir = Path(cfg.get("simsed_dir") or cfg["salt2_dir"])   # SNIa-SALT2 (2026-09-30): SALT2 model dir
        if simsed_dir.is_dir() and any(simsed_dir.iterdir()):'''),
])
