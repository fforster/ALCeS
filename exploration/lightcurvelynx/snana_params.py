"""
Samplers custom que replican dos piezas de SNIa-SALT2.INPUT (SNANA) que
LightCurveLynx no trae nativo (ver Fase 0 NOTES.md):

1. DNDZ: POWERLAW2 -- tasa volumetrica de SNIa vs redshift (no uniforme).
2. Gaussianas bifurcadas para SALT2 x1/c (sigma distinto a cada lado del pico).

Se envuelven en lightcurvelynx.base_models.FunctionNode (la clase base que
usa NumpyRandomFunc internamente -- confirmado leyendo
math_nodes/np_random.py: NumpyRandomFunc.__init__ hace
`super().__init__(func, **kwargs)` con `func = getattr(rng, func_name)`, o
sea que FunctionNode acepta cualquier callable, no solo funciones de
numpy.random). Cada sampler de aqui expone la firma `func(size=None, **kw)`
para calzar con como FunctionNode invoca a su `func`.
"""
from __future__ import annotations

import numpy as np
from scipy.integrate import quad
from scipy.stats import truncnorm
from astropy.cosmology import FlatLambdaCDM

from lightcurvelynx.base_models import FunctionNode
from lightcurvelynx.effects.extinction import ExtinctionEffect


class ClippedExtinctionEffect(ExtinctionEffect):
    """ExtinctionEffect que clampea las longitudes de onda al rango valido
    del modelo dust_extinction subyacente en vez de lanzar ValueError.

    Necesario para clases con GENRANGE_REDSHIFT alto (p.ej. TDE-MOSFIT,
    z hasta 2.9, host extinction en frame='rest'): a z~2.9 el borde azul
    de LSST-u (~3200 A observado) cae en rest-frame a ~820 A
    (obs_to_rest_times_waves divide por 1+z), por debajo del limite fisico
    real de 1000 A (x=10 1/micron) al que estan calibradas las leyes de
    extincion parametricas estandar (CCM89/O94/F99/...) -- no es un bug de
    LightCurveLynx ni nuestro, es el limite real de la calibracion
    empirica. Igual que la extrapolacion (ZeroPadding/LinearDecay) que
    LightCurveLynx ya usa para el SED fuera de RESTLAMBDA_RANGE, se
    clampea el input en vez de inventar una extrapolacion nueva -- la
    extincion se mantiene constante (igual al valor de borde) mas alla del
    rango calibrado, en vez de fallar toda la simulacion por un punado de
    objetos en la cola de mayor z.

    Fase 51: `ebv_param_name` -- BasePhysicalModel.add_effect() (physical_model.py)
    fusiona los parametros de todos los efectos de un modelo en un solo dict por
    NOMBRE, y el primero que se registra gana en silencio si dos efectos declaran
    el mismo nombre (sin error, sin warning). ExtinctionEffect.__init__ siempre
    registra su parametro como "ebv" -- con MW extinction agregada primero
    (build_source_model, run_simsed_poc.py) y host extinction despues, el efecto
    de host nunca registraba su propio setter: quedaba recibiendo en silencio el
    E(B-V) de MW (~0.006-0.025) en vez del propio (host_av/R_V, hasta ~1.0),
    reduciendo su extincion real a ~2-8% de la nominal en las 12 clases con
    `host_av` en CLASS_CONFIGS. Confirmado con un smoke test real contra el
    ModelNode real (no simulado): "host effect requested ebv=0.4 -> model
    delivers 0.02". Ver NOTES.md Fase 51 -- reportado tambien como bug real de
    la libreria (add_effect() no deberia fusionar por nombre en silencio).
    """

    def __init__(self, *, ebv_param_name="ebv", **kwargs):
        super().__init__(**kwargs)
        self._ebv_param_name = ebv_param_name
        if ebv_param_name != "ebv":
            self.parameters[ebv_param_name] = self.parameters.pop("ebv")

    def apply(self, flux_density, times=None, wavelengths=None, ebv=None, **kwargs):
        # `ebv` (la clave original) puede traer el valor de OTRO efecto con el
        # mismo nombre (ver docstring) -- el valor real de este efecto llega
        # bajo self._ebv_param_name, y pisa lo que haya llegado como `ebv`.
        ebv = kwargs.pop(self._ebv_param_name, ebv)
        x_min, x_max = self._extinction_wrapper.ext_obj.x_range  # 1/micron
        lam_min_aa, lam_max_aa = 1e4 / x_max, 1e4 / x_min
        clipped = np.clip(wavelengths, lam_min_aa, lam_max_aa)
        return ExtinctionEffect.apply(self, flux_density, times=times, wavelengths=clipped, ebv=ebv, **kwargs)


class SizeAwareFunctionNode(FunctionNode):
    """FunctionNode que SI pasa `size=graph_state.num_samples` a la funcion
    envuelta -- la base FunctionNode.compute() llama `self.func(**args)` sin
    `size` en absoluto (confirmado leyendo base_models.py), asi que una
    funcion con firma `func(size=None, **kw)` recibe siempre size=None y
    devuelve UN solo valor que el grafo termina difundiendo (broadcast) a
    los N samples -- bug real encontrado en la Fase 1: los primeros PoC
    tenian TODOS los objetos con el mismo z/x1/c (un solo valor repetido).
    Mismo patron que usa NumpyRandomFunc.compute() internamente, aplicado a
    un callable arbitrario en vez de una funcion de numpy.random."""

    def compute(self, graph_state, rng_info=None, **kwargs):
        args = self._build_inputs(graph_state, **kwargs)
        results = self.func(size=graph_state.num_samples, **args)
        self._save_results(results, graph_state)
        return results


# ------------------------------------------------------------------ DNDZ
def _comoving_volume_element(z: float, cosmo: FlatLambdaCDM) -> float:
    """dV_c/dz (Mpc^3) -- shell de volumen comovil por unidad de z."""
    return cosmo.differential_comoving_volume(z).value  # Mpc^3/sr, luego *4pi si hiciera falta


def _md14_sfr(z: np.ndarray) -> np.ndarray:
    """Madau & Dickinson 2014 (ApJ, arXiv:1403.0007) cosmic star-formation-
    rate density, Msun/yr/Mpc^3 -- formula estandar y ampliamente citada,
    usada por SNANA como `DNDZ: MD14 <rate0>` (rate0 = tasa en z=0, la
    forma se normaliza a SFR_MD14(0))."""
    return 0.015 * (1.0 + z) ** 2.7 / (1.0 + ((1.0 + z) / 2.9) ** 5.6)


def build_dndz_md14_cdf(
    rate0: float,
    z_min: float,
    z_max: float,
    *,
    H0: float = 70.0,
    Om0: float = 0.3,
    n_grid: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """Como build_dndz_powerlaw2_cdf pero con `DNDZ: MD14 <rate0>` de SNANA
    -- tasa proporcional a la forma de Madau&Dickinson 2014 en vez de una
    ley de potencia simple, normalizada para que rate(0) = rate0."""
    cosmo = FlatLambdaCDM(H0=H0, Om0=Om0)
    z_grid = np.linspace(z_min, z_max, n_grid)
    sfr0 = _md14_sfr(np.array([0.0]))[0]
    rate_z = rate0 * _md14_sfr(z_grid) / sfr0

    dn_dz = np.array([
        rate_z[i] * _comoving_volume_element(z_grid[i], cosmo) / (1.0 + z_grid[i])
        for i in range(n_grid)
    ])
    cdf = np.cumsum(dn_dz)
    cdf -= cdf[0]
    if cdf[-1] <= 0:
        raise ValueError("CDF de DNDZ MD14 degenerada -- revisar rate0/z_min/z_max.")
    cdf /= cdf[-1]
    return z_grid, cdf


def build_dndz_powerlaw2_cdf(
    segments: list[tuple[float, float, float, float]],
    z_min: float,
    z_max: float,
    *,
    H0: float = 70.0,  # SNANA default (ver Fase 2 parte A) -- antes 73.0 sin
    Om0: float = 0.3,  # verificar, mismo placeholder que ya se corrigio en
    n_grid: int = 2000,  # el calculo de distancia/flujo.
) -> tuple[np.ndarray, np.ndarray]:
    """Construye la CDF de dN/dz = DNDZ(z) * dVc/dz / (1+z) para redshift.

    `segments`: lista de (rate0, beta, z_lo, z_hi) -- exactamente el formato
    de las lineas `DNDZ: POWERLAW2 <rate0> <beta> <z_lo> <z_hi>` de SNANA,
    donde la tasa en ese tramo es `rate0 * (1+z)**beta`. El .INPUT real de
    SNIa tiene 2 tramos (ver SIMGEN_INCLUDE_SNIa-SALT2.INPUT):
        POWERLAW2 2.5E-5  1.5  0.0 1.0
        POWERLAW2 9.7E-5 -0.5  1.0 3.0
    El factor `/(1+z)` es dilucion temporal cosmologica (SNANA la aplica
    tambien -- tasa observada vs tasa en el marco de reposo del evento).

    Devuelve (z_grid, cdf) listos para sampleo por inversion.
    """
    cosmo = FlatLambdaCDM(H0=H0, Om0=Om0)
    z_grid = np.linspace(z_min, z_max, n_grid)

    def rate_at(z):
        for rate0, beta, z_lo, z_hi in segments:
            if z_lo <= z < z_hi or (z == z_max and z_hi == z_max):
                return rate0 * (1.0 + z) ** beta
        return 0.0

    dn_dz = np.array([
        rate_at(z) * _comoving_volume_element(z, cosmo) / (1.0 + z) for z in z_grid
    ])
    cdf = np.cumsum(dn_dz)
    cdf -= cdf[0]
    if cdf[-1] <= 0:
        raise ValueError("CDF de DNDZ degenerada -- revisar segments/z_min/z_max.")
    cdf /= cdf[-1]
    return z_grid, cdf


def build_dndz_ccs15_cdf(
    scale: float,
    z_min: float,
    z_max: float,
    *,
    H0: float = 70.0,
    Om0: float = 0.3,
    n_grid: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """`DNDZ: CC_S15` de SNANA (tasa de core-collapse, Strolger 2015) --
    misma forma funcional que MD14 pero con los parametros A,B,C,D
    ajustados a R_CC(z) (Fig 6, Ec 9 de Strolger 2015), NO los de la
    tasa de formacion estelar general. Formula y constantes leidas
    directo del codigo fuente real de SNANA
    (~/github/SNANA_src/src/snlc_sim.c, bloque
    `INDEX_RATEMODEL_CCS15`) -- no una aproximacion:

        rate(z) = k * h^2 * SFR_MD14(z; A=0.015,B=1.50,C=5.00,D=6.10)
                  * DNDZ_ALLSCALE
        k = 0.0091, h = H0/100

    `scale` = DNDZ_ALLSCALE del .INPUT real de cada clase. La
    normalizacion absoluta no importa para el sampleo por CDF (se
    cancela), pero se mantiene por fidelidad con la fuente."""
    cosmo = FlatLambdaCDM(H0=H0, Om0=Om0)
    z_grid = np.linspace(z_min, z_max, n_grid)
    h = H0 / 100.0
    k = 0.0091
    A, B, C, D = 0.015, 1.50, 5.00, 6.10
    sfr = A * (1.0 + z_grid) ** C / (1.0 + ((1.0 + z_grid) / B) ** D)
    rate_z = k * (h ** 2) * sfr * scale

    dn_dz = np.array([
        rate_z[i] * _comoving_volume_element(z_grid[i], cosmo) / (1.0 + z_grid[i])
        for i in range(n_grid)
    ])
    cdf = np.cumsum(dn_dz)
    cdf -= cdf[0]
    if cdf[-1] <= 0:
        raise ValueError("CDF de DNDZ CC_S15 degenerada -- revisar scale/z_min/z_max.")
    cdf /= cdf[-1]
    return z_grid, cdf


def build_dndz_tde_cdf(
    rate0: float,
    z_min: float,
    z_max: float,
    *,
    H0: float = 70.0,
    Om0: float = 0.3,
    n_grid: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """`DNDZ: TDE` de SNANA -- decaimiento exponencial simple en z, leido
    directo de snlc_sim.c (bloque `INDEX_RATEMODEL_TDE`):
        rate(z) = rate0 * 10^(-0.5*z/0.6)
    """
    cosmo = FlatLambdaCDM(H0=H0, Om0=Om0)
    z_grid = np.linspace(z_min, z_max, n_grid)
    rate_z = rate0 * 10.0 ** (-0.5 * z_grid / 0.6)

    dn_dz = np.array([
        rate_z[i] * _comoving_volume_element(z_grid[i], cosmo) / (1.0 + z_grid[i])
        for i in range(n_grid)
    ])
    cdf = np.cumsum(dn_dz)
    cdf -= cdf[0]
    if cdf[-1] <= 0:
        raise ValueError("CDF de DNDZ TDE degenerada -- revisar rate0/z_min/z_max.")
    cdf /= cdf[-1]
    return z_grid, cdf


def build_dndz_pisn_cdf(
    z_min: float,
    z_max: float,
    *,
    scale: float = 1.0,
    H0: float = 70.0,
    Om0: float = 0.3,
    n_grid: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """`DNDZ: PISN_PLK12` de SNANA -- polinomio de grado 5 ajustado a
    arxiv.org/pdf/1111.3648.pdf Fig 2, leido directo de snlc_sim.c (bloque
    `INDEX_RATEMODEL_PISN`, no una aproximacion ni un nombre sin formula
    como se penso en Fase 2B ronda 1/2):

        rate(z) = 1.98 + 6.38z + 6.558z^2 - 4.42z^3 + 0.8312z^4 - 0.0508z^5
                  [/yr/Gpc^3], convertido a /yr/Mpc^3 (/1e9)

    Sin dependencia de H0/h^2 en la forma funcional (a diferencia de
    MD14/CC_S15) -- H0 solo entra via el elemento de volumen comovil.
    `scale` = factor multiplicador opcional del `.INPUT` real (PISN-MOSFIT
    no declara ninguno, scale=1.0 por defecto)."""
    cosmo = FlatLambdaCDM(H0=H0, Om0=Om0)
    z_grid = np.linspace(z_min, z_max, n_grid)
    z2, z3, z4, z5 = z_grid ** 2, z_grid ** 3, z_grid ** 4, z_grid ** 5
    rate_z = (1.98 + 6.38 * z_grid + 6.558 * z2 - 4.42 * z3 + 0.8312 * z4 - 0.0508 * z5)
    rate_z = (rate_z / 1.0e9) * scale

    dn_dz = np.array([
        rate_z[i] * _comoving_volume_element(z_grid[i], cosmo) / (1.0 + z_grid[i])
        for i in range(n_grid)
    ])
    cdf = np.cumsum(dn_dz)
    cdf -= cdf[0]
    if cdf[-1] <= 0:
        raise ValueError("CDF de DNDZ PISN degenerada -- revisar z_min/z_max.")
    cdf /= cdf[-1]
    return z_grid, cdf


def make_dndz_sampler(z_grid: np.ndarray, cdf: np.ndarray, *, seed: int | None = None):
    """Devuelve una funcion `sampler(size=None)` que samplea redshift por
    inversion de la CDF precomputada (interpolacion lineal)."""
    rng = np.random.default_rng(seed)

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else (size if np.isscalar(size) else size[0])
        u = rng.uniform(0.0, 1.0, size=n)
        z = np.interp(u, cdf, z_grid)
        return z if size is not None else float(z[0])

    sampler.__name__ = "dndz_redshift_sampler"
    return sampler


# ------------------------------------------------------------------ bifurcated gaussian
def make_bifurcated_normal_sampler(
    peak: float, sigma_lo: float, sigma_hi: float, lo: float, hi: float, *, seed: int | None = None
):
    """Gaussiana con sigma distinto a cada lado del pico (bifurcada), con
    corte duro en [lo, hi] via rechazo -- replica el patron
    GENPEAK/GENSIGMA (dos valores)/GENRANGE de SNANA para SALT2c y SALT2x1.

    Fase 32: la probabilidad de elegir cada lado NO es 50/50 -- SNANA la
    pesa proporcional a cada sigma (getRan_GaussAsym(), sntools.c real:
    p_lado_bajo = siglo/(siglo+sighi), BIGAUSSNORMCON se cancela en el
    cociente) para que la densidad sea continua en el pico. Un split fijo
    50/50 sub-muestrea el lado ancho y sobre-muestrea el lado angosto --
    bug real, corregido aca. Ver NOTES.md Fase 32."""
    rng = np.random.default_rng(seed)
    p_side_lo = 0.5 if (sigma_lo == 0.0 and sigma_hi == 0.0) else sigma_lo / (sigma_lo + sigma_hi)

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else (size if np.isscalar(size) else size[0])
        out = np.empty(n)
        filled = 0
        while filled < n:
            batch = max(n - filled, 16)
            side = rng.uniform(size=batch) < p_side_lo
            sigma = np.where(side, sigma_lo, sigma_hi)
            # sigma_lo va del lado izquierdo del pico (draw < peak), sigma_hi
            # del lado derecho -- misma convencion que GENSIGMA de SNANA.
            magnitude = np.abs(rng.standard_normal(batch)) * sigma
            draw = np.where(side, peak - magnitude, peak + magnitude)
            valid = draw[(draw >= lo) & (draw <= hi)]
            take = min(len(valid), n - filled)
            out[filled:filled + take] = valid[:take]
            filled += take
        return out if size is not None else float(out[0])

    sampler.__name__ = "bifurcated_normal_sampler"
    return sampler


# ------------------------------------------------------------------ AV exponencial (host)
def make_exp_av_sampler(tau: float, av_max: float, *, seed: int | None = None):
    """Extincion de galaxia anfitriona `dN/dAV = exp(-AV/tau)` truncada en
    [0, av_max] -- el caso "solo componente exponencial, sin nucleo
    Gaussiano" que declara TDE-MOSFIT (`GENTAU_AV: 0.4`, comentario real en
    el .INPUT: "expon component only, no Gauss core") en vez del modelo
    WV07 mixto (que sí se omitio, ver NOTES.md Fase 2 parte B -- ese es el
    flag `GENAV_WV07`, con un historial de bugs documentado en el codigo
    real de SNANA que hizo preferible no reimplementarlo de memoria).

    Nota (Fase 2B ronda 3): SNIax se trato inicialmente como este mismo
    caso puro, pero su .INPUT real SI declara `GENSIG_AV`/`GENRATIO_AV0`
    ademas de `GENTAU_AV` -- es la mezcla exponencial+semi-Gaussiana de
    `make_exp_halfgauss_av_sampler()`, no este caso. Ver esa funcion para
    el caso mixto (distinto del WV07 bugueado -- confirmado leyendo
    snlc_sim.c::gen_AV(), que llama a getRan_GEN_EXP_HALFGAUSS() para
    GENTAU_AV/GENSIG_AV/GENRATIO_AV0 y solo usa GENAV_WV07() si el flag
    `GENAV_WV07`/`WV07_REWGT_EXPAV` esta presente -- SNIax no lo declara).

    Esta version pura exponencial es la formula estandar de inversion de
    CDF truncada -- CDF(AV) = (1-exp(-AV/tau)) / (1-exp(-av_max/tau))."""
    rng = np.random.default_rng(seed)
    norm = 1.0 - np.exp(-av_max / tau)

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else (size if np.isscalar(size) else size[0])
        u = rng.uniform(0.0, 1.0, size=n)
        av = -tau * np.log(1.0 - u * norm)
        return av if size is not None else float(av[0])

    sampler.__name__ = "exp_av_sampler"
    return sampler


def make_exp_halfgauss_av_sampler(
    tau: float, sig: float, ratio: float, av_range: tuple[float, float],
    peak: float = 0.0, *, seed: int | None = None,
):
    """Replica exacta de `getRan_GEN_EXP_HALFGAUSS()`
    (~/github/SNANA_src/src/sntools_genExpHalfGauss.c, refactor de Mar 2020
    por D.Brout/R.Kessler, bug de peso EXPON/GAUSS corregido en Dic 2023) --
    mezcla exponencial truncada + semi-Gaussiana con seleccion de rama por
    peso relativo real, **no** el flag legacy `GENAV_WV07` (esa es una
    funcion completamente autonoma y distinta -- ver
    `make_wv07_av_sampler()` -- que nunca llama a esta, confirmado leyendo
    `snlc_sim.c::GENAV_WV07()` linea por linea en Fase 3). Usada por
    SNIax (`GENTAU_AV: 1.7`, `GENSIG_AV: 0.6`, `GENRATIO_AV0: 4.0`,
    `GENRANGE_AV: 0.001 3.0`, sin `GENAV_WV07` en su .INPUT real).

    Algoritmo (identico al C real, no una aproximacion):
        WGT_EXPON = tau * (exp(-r0/tau) - exp(-r1/tau))
        WGT_GAUSS = 0.5 * ratio * sqrt(2*pi*sig^2)
        con prob. WGT_EXPON/(WGT_EXPON+WGT_GAUSS): exponencial truncada en
        [r0,r1] (inversion de CDF); si no, semi-Gaussiana (`peak=0` ->
        solo lado positivo, `|Gauss|*sig`) por rechazo hasta caer en
        [r0,r1]."""
    rng = np.random.default_rng(seed)
    r0, r1 = av_range
    wgt_expon = tau * (np.exp(-r0 / tau) - np.exp(-r1 / tau))
    wgt_gauss = 0.5 * ratio * np.sqrt(2.0 * np.pi * sig ** 2)
    p_expon = wgt_expon / (wgt_expon + wgt_gauss)
    expmin, expmax = np.exp(-r0 / tau), np.exp(-r1 / tau)
    expdif = expmin - expmax

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else (size if np.isscalar(size) else size[0])
        branch_expon = rng.uniform(0.0, 1.0, size=n) < p_expon
        out = np.empty(n)

        n_exp = int(branch_expon.sum())
        if n_exp > 0:
            u = rng.uniform(0.0, 1.0, size=n_exp)
            out[branch_expon] = -tau * np.log(expmin - expdif * u)

        gauss_idx = np.where(~branch_expon)[0]
        n_gauss = len(gauss_idx)
        if n_gauss > 0:
            vals = np.full(n_gauss, np.nan)
            pending = np.arange(n_gauss)
            while len(pending) > 0:
                g = rng.standard_normal(size=len(pending))
                cand = sig * g + peak if peak > 0.0001 else sig * np.abs(g)
                ok = (cand >= r0) & (cand <= r1)
                vals[pending[ok]] = cand[ok]
                pending = pending[~ok]
            out[gauss_idx] = vals

        return out if size is not None else float(out[0])

    sampler.__name__ = "exp_halfgauss_av_sampler"
    return sampler


def make_wv07_av_sampler(
    av_range: tuple[float, float], rewgt_expav: float | None = None, *, seed: int | None = None,
):
    """Replica exacta de `GENAV_WV07()`
    (~/github/SNANA_src/src/snlc_sim.c, funcion real del modelo de
    extincion de host ESSENCE-WV07, Wood-Vasey et al. 2007 -- comentario
    real en el codigo: "return AV from distribution used by ESSENCE-WV07").

    Fase 3 (esta ronda): investigada a fondo por primera vez -- funcion
    completamente autonoma, NO llama a `getRan_GEN_EXP_HALFGAUSS()` (esa
    es la funcion con el bug de peso corregido en Dic 2023 que motivo
    omitir WV07 en las rondas 1-2 de Fase 2B, por prudencia, sin haber
    leido esta funcion linea por linea todavia). El unico bug historico
    real de `GENAV_WV07()` (Mar 2022: "fix bug that has resulted in all
    AV=0", una variable obsoleta) ya esta corregido en la version del
    codigo fuente leida esta ronda -- se implementa la version ya
    corregida, no la bugueada.

    Constantes FIJAS en el codigo real (no configurables por .INPUT,
    iguales para las 9 clases que declaran este modelo):
        tau = 0.4, sqsigma = 0.01  (sigma del nucleo Gaussiano = 0.1)
        AEXP = 1/tau, BEXP = 1/sqrt(sqsigma*2*pi)

    Si el .INPUT declara `WV07_REWGT_EXPAV` (`rewgt_expav`, KN-K17 y
    KN-BULLA19 usan 0.5 -- las demas 7 clases no lo declaran, AEXP sin
    modificar), reescala AEXP (`AEXP *= rewgt_expav`) -- confirmado leyendo
    `snlc_sim.c` linea ~7887: cualquier valor real de `WV07_REWGT_EXPAV`
    activa el mismo `WV07_GENAV_FLAG` que `GENAV_WV07: 1` directo, mismo
    camino de codigo.

    Algoritmo (identico al C real, muestreo por rechazo, no inversion de
    CDF):
        W0 = AEXP + BEXP  (peso en AV=0)
        por cada intento: AV ~ Uniform(r0, r1)
        W(AV) = AEXP*exp(-AV/tau) + BEXP*exp(-0.5*AV^2/sqsigma)
        aceptar si Uniform(0,1) < W(AV)/W0, si no reintentar."""
    rng = np.random.default_rng(seed)
    r0, r1 = av_range
    tau, sqsigma = 0.4, 0.01
    aexp = 1.0 / tau
    if rewgt_expav is not None:
        aexp *= rewgt_expav
    bexp = 1.0 / np.sqrt(sqsigma * 2.0 * np.pi)
    w0 = aexp + bexp

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else (size if np.isscalar(size) else size[0])
        out = np.full(n, np.nan)
        pending = np.arange(n)
        while len(pending) > 0:
            av = rng.uniform(r0, r1, size=len(pending))
            w = (aexp * np.exp(-av / tau) + bexp * np.exp(-0.5 * av * av / sqsigma)) / w0
            u = rng.uniform(0.0, 1.0, size=len(pending))
            accept = u < w
            out[pending[accept]] = av[accept]
            pending = pending[~accept]
        return out if size is not None else float(out[0])

    sampler.__name__ = "wv07_av_sampler"
    return sampler


# ------------------------------------------------------------------ N-dim correlated normal
def make_correlated_normal_weights(
    values: dict[str, np.ndarray],
    peaks: dict[str, float],
    sigmas: dict[str, float],
    redcor: dict[tuple[str, str], float],
    genrange: dict[str, tuple[float, float]] | None = None,
    cdf_seed: int = 20260813,
    cdf_eps: float = 1e-7,
) -> np.ndarray:
    """Generaliza el peso de `SIMSED_REDCOR` a N parametros (no solo los 2
    de SALT2 c/x1).

    Fase 44: la version anterior evaluaba la PDF Gaussiana exactamente en
    el punto discreto de cada template ("peso = altura de la campana ahi"),
    asumiendo que eso aproxima bien la probabilidad de que ese template sea
    el elegido. Fase 41 encontro, comparando 200k draws contra los
    stretch/color reales de 2000 objetos SNIa-91bg, que esto NO reproduce
    la distribucion real (KS p=1.2e-77 en stretch, p=2.7e-133 en color) --
    leyendo el algoritmo real de SNANA (`prep_user_SIMSED()`/
    `nearest_gridval_SIMSED()`, `~/github/SNANA_src/src/genmag_SEDtools.c`
    linea real 2427) se confirmo que SNANA arma la descomposicion de
    Cholesky de la covarianza real, samplea un valor CONTINUO correlacionado,
    y recien despues snapea cada parametro POR SEPARADO (no conjunto) al
    valor de grilla mas cercano en ESE eje (`frac=(lumipar-parval0)/
    (parval1-parval0); if frac<0.5: usa parval0 else parval1` -- redondeo de
    vecino mas cercano en 1D, un eje a la vez).

    Verificado que el SED.INFO real de SNIa-91bg (`simsed_91bg_local/
    SED.INFO`) es una grilla Cartesiana genuina (stretch: 7 valores
    {0.65..1.25} x color: 5 valores {0.0..1.0} = 35 templates) -- el
    redondeo independiente por eje sobre una grilla Cartesiana es
    exactamente el redondeo a la celda de Voronoi RECTANGULAR de cada
    template (bordes en los puntos medios entre valores de grilla
    adyacentes en cada eje). La probabilidad real de que un draw continuo
    caiga en la celda de un template dado es entonces la masa exacta de la
    normal multivariada correlacionada dentro de ese rectangulo (o
    hiper-rectangulo en N dimensiones) -- no aproximada por Monte Carlo,
    calculada exacta via inclusion-exclusion sobre los `scipy.stats.
    multivariate_normal.cdf()` de las 2^N esquinas de la caja.

    Fase 45: SNANA real no samplea de una Gaussiana sin mas cuando hay
    parametros correlacionados -- `snlc_sim.c` linea real ~14038 (bloque
    `if (NROW_COV > 0)`) hace reject-and-retry real (`goto PICK_RANCOV`,
    hasta 100 intentos): descarta cualquier draw continuo que caiga fuera
    de `GENRANGE_<param>` ANTES de snapear a la grilla. La version de
    Fase 44 extendia los bordes exteriores de la grilla a `+-50 sigma`
    (soporte casi infinito) en vez de cortar en el `GENRANGE` real -- para
    SNIa-91bg, `GENRANGE_stretch: 0.65 1.25`/`GENRANGE_color: 0.0 1.0`
    coinciden EXACTO con los extremos de la grilla (confirmado contra el
    `.INPUT` real), asi que el corte real esta a solo ~3.2-3.4 sigma del
    pico, no en el infinito. Verificado (Fase 45): la masa total fuera de
    esa caja es ~0.85% (chica) -- la hipotesis de que esto explicara el
    desajuste KS fuerte de Fase 44 pierde fuerza antes de medir, pero se
    implementa y verifica empiricamente de todas formas (nunca se asume
    sin medir). `genrange` (opcional, default `None` = mismo comportamiento
    de Fase 44, bordes a `+-50 sigma`): {nombre_param: (GENRANGE_min,
    GENRANGE_max)} real -- si se pasa, los bordes exteriores de cada eje
    se recortan ahi en vez de a `+-50 sigma`, y el resultado queda
    automaticamente normalizado a la masa real dentro de la caja completa
    al dividir por la suma (equivalente exacto al reject-and-retry real en
    el limite de infinitos intentos).

    `values`: {nombre_param: array de valores por template}.
    `peaks`/`sigmas`: {nombre_param: GENPEAK/GENSIGMA (simetrica)}.
    `redcor`: {(param_i, param_j): SIMSED_REDCOR(param_i,param_j)} -- solo
    los pares declarados, el resto se asume no correlacionado (0).

    Fix determinismo (2026-09-24): `scipy.stats.multivariate_normal.cdf` en
    N>=2 dimensiones integra con quasi-Monte Carlo ALEATORIZADO (Genz) y
    precision por defecto ~1e-5 -- sin semilla, cada proceso obtenia pesos
    distintos (ruido ~1e-5 absoluto, varios % relativo en templates chicos).
    Como el template se samplea con el rng compartido de la simulacion, ~2%
    de los objetos elegian un template vecino distinto al re-construir la
    corrida (FLUXTRUE no reproducible). `cdf_seed` fija el QMC (pesos
    identicos bit a bit en cualquier proceso) y `cdf_eps` (abseps=releps)
    baja el error de ~3e-2 a ~5e-4 relativo por template (~2.5 min para
    los 384 templates de SNII-NMF)."""
    from itertools import product as _iproduct

    from scipy.stats import multivariate_normal as _mvn

    names = list(values.keys())
    n_par = len(names)
    n_tmpl = len(next(iter(values.values())))

    cov = np.zeros((n_par, n_par))
    for i, ni in enumerate(names):
        cov[i, i] = sigmas[ni] ** 2
    for (a, b), rc in redcor.items():
        i, j = names.index(a), names.index(b)
        cov[i, j] = cov[j, i] = rc * sigmas[a] * sigmas[b]

    mean = np.array([peaks[n] for n in names])
    dist = _mvn(mean=mean, cov=cov, seed=cdf_seed, abseps=cdf_eps, releps=cdf_eps)

    # celda de Voronoi rectangular por eje: bordes en los puntos medios
    # entre valores de grilla adyacentes (unicos, ordenados); extremos
    # abiertos hacia +-inf, aproximados por +-50 sigma (mas alla de eso la
    # masa Gaussiana es numericamente cero).
    lo = np.empty((n_tmpl, n_par))
    hi = np.empty((n_tmpl, n_par))
    for k, name in enumerate(names):
        grid = np.unique(values[name])
        mid = (grid[:-1] + grid[1:]) / 2.0
        if genrange is not None and name in genrange:
            lo_edge, hi_edge = genrange[name]
        else:
            lo_edge, hi_edge = mean[k] - 50 * sigmas[name], mean[k] + 50 * sigmas[name]
        edges = np.concatenate(([lo_edge], mid, [hi_edge]))
        idx = np.searchsorted(grid, values[name])  # posicion de cada template en la grilla ordenada
        lo[:, k] = edges[idx]
        hi[:, k] = edges[idx + 1]

    # masa exacta de la caja [lo,hi]^N via inclusion-exclusion sobre las
    # 2^N esquinas (formula estandar de probabilidad de rectangulo N-dim).
    weights = np.zeros(n_tmpl)
    corners = list(_iproduct([0, 1], repeat=n_par))
    for t in range(n_tmpl):
        box = np.stack([lo[t], hi[t]], axis=1)  # (n_par, 2)
        acc = 0.0
        for corner in corners:
            point = np.array([box[k, corner[k]] for k in range(n_par)])
            sign = (-1) ** (n_par - sum(corner))
            acc += sign * dist.cdf(point)
        weights[t] = max(acc, 0.0)  # errores numericos pueden dar -1e-16

    return weights


# ------------------------------------------------------------------ MWEBV scatter (Fase 10)
def make_mwebv_ratio_scatter(ratio: float, *, seed: int | None = None):
    """Replica GENSIGMA_MWEBV_RATIO de SNANA -- confirmado leyendo
    snlc_sim.c::gen_MWEBV() (github.com/RickKessler/SNANA, funcion real,
    lineas ~13526-13599):

        MWXT_GaussRan = getRan_GaussClip(1, -3.0, 3.0)   # Z~N(0,1), recorte 3-sigma
        MWEBV_ERR     = sqrt(MWEBV_SIG^2 + (MWEBV_SIGRATIO * MWEBV_nominal)^2)
        MWEBV_SMEAR   = (MWEBV_nominal + MWEBV_ERR * MWXT_GaussRan + MWEBV_SHIFT) * MWEBV_SCALE

    Esta campana solo fija GENSIGMA_MWEBV_RATIO=0.16 (MWEBV_SIG/SHIFT=0,
    SCALE=1 son los defaults de SNANA, no se tocan en templates.py), asi que
    la formula se reduce a:

        EBV_true = EBV_nominal * (1 + ratio * Z),  Z ~ N(0,1) recortado a +-3sigma

    Como ratio*|Z| <= 0.16*3 = 0.48 < 1, el resultado es siempre positivo sin
    necesidad de un piso en 0 (a diferencia del C real, que si lo necesita
    para el caso GENRANGE_MWEBV / EBV grande).

    Nota aparte (no replicada aqui): en la campana real, el EBV *nominal* que
    entra a esta formula no es un valor fijo por campo -- viene del mapa real
    SFD98 evaluado en el RA/DEC exacto de cada objeto (el SIMLIB real escribe
    MWEBV=0.00 en cada header LIBID, lo cual dispara el fallback de SNANA de
    OPT_MWEBV_FILE a OPT_MWEBV_SFD98 dentro de gen_MWEBV()). El diccionario
    DDF_FIELD_EBV de este proyecto usa un valor fijo por campo (promedio),
    sin la variacion espacial continua del mapa real. Ese es un hallazgo
    aparte, no probado aun -- ver NOTES.md Fase 10."""
    dist = truncnorm(-3.0, 3.0)
    rng = np.random.default_rng(seed)

    def scatter(nominal):
        nominal = np.asarray(nominal, dtype=float)
        z = dist.rvs(size=nominal.shape, random_state=rng)
        return nominal * (1.0 + ratio * z)

    scatter.__name__ = "mwebv_ratio_scatter"
    return scatter


def make_wfd_ebv_lookup(grid_csv_path, ratio: float, *, seed: int | None = None):
    """Fase 17 (WFD): equivalente de DDF_FIELD_EBV/_field_to_ebv para WFD, que
    no tiene campos fijos (ver build_wfd_mwebv_grid.py). En vez de un
    diccionario de 6 valores por nombre de campo, hace nearest-neighbor
    angular contra una grilla real de E(B-V) (SFD98 via IRSA Dust Extinction
    Service, misma fuente/columna que los 6 valores DDF) sobre el RA/DEC
    EXACTO de cada objeto simulado -- variacion espacial continua real, a
    diferencia del valor fijo por campo que usa DDF. Reusa
    make_mwebv_ratio_scatter() para el mismo GENSIGMA_MWEBV_RATIO real
    aplicado a DDF (misma formula, mismo gen_MWEBV() de SNANA).

    grid_csv_path: CSV con columnas ra,dec,ebv_sfd (build_wfd_mwebv_grid.py).
    """
    import pandas as pd

    grid = pd.read_csv(grid_csv_path)
    grid_ra = grid["ra"].to_numpy(dtype=float)
    grid_dec = grid["dec"].to_numpy(dtype=float)
    grid_ebv = grid["ebv_sfd"].to_numpy(dtype=float)
    _scatter = make_mwebv_ratio_scatter(ratio, seed=seed)

    def lookup(size=None, ra=None, dec=None, **_kwargs):
        ra_arr = np.atleast_1d(np.asarray(ra, dtype=float))
        dec_arr = np.atleast_1d(np.asarray(dec, dtype=float))
        # separacion angular aproximada (valida para el espaciado de 8 grados
        # de la grilla -- no hace falta la formula esferica exacta tipo
        # haversine para elegir el vecino mas cercano a esta resolucion),
        # con wrap de RA en el borde 0/360.
        dra = (ra_arr[:, None] - grid_ra[None, :] + 180.0) % 360.0 - 180.0
        dra *= np.cos(np.radians(dec_arr))[:, None]
        ddec = dec_arr[:, None] - grid_dec[None, :]
        d2 = dra ** 2 + ddec ** 2
        nearest_idx = np.argmin(d2, axis=1)
        nominal = grid_ebv[nearest_idx].reshape(np.asarray(ra).shape)
        return _scatter(nominal)

    lookup.__name__ = "wfd_ebv_lookup"
    return lookup


# ------------------------------------------------------------------ filtro de contaminacion DDF
def filter_ddf_field_contamination(df, opsim_db_path, max_sep_deg: float = 2.0):
    """Filtra objetos de un `.DUMP` real de SNANA que NO son miembros reales de
    ninguno de los 6 campos DDF -- hallazgo real de Fase 33 (NOTES.md), nunca
    aplicado a la comparacion principal de `PEAKMAG` hasta que Fase 36 lo
    verifico: ~15% del `.DUMP` de referencia usado desde Fase 16
    (`SNIa_DDF_baseline_v5.3.1_10yrs.DUMP`) mezcla objetos `GW_case_*`/
    `neutrino_*` del OpSim real (incluidos algunos sobre el centro galactico,
    `MWEBV` hasta 72.68) en el mismo archivo que los `SNIa` DDF reales.

    Como la contaminacion es sistematicamente MAS TENUE (extincion extrema),
    inflaba artificialmente el residuo LCL-vs-SNANA que persiguieron las
    Fases 16-35: Fase 36 midio, con la poblacion ya corregida (Fase 32+34),
    que filtrar reduce el nivel acromatico ~19% y prácticamente elimina el
    spread cromatico g-y (-0.076 -> +0.016 mag, cambia de signo) -- ver
    NOTES.md Fase 36 para el detalle completo. Usar esta funcion en cualquier
    comparacion futura contra el `.DUMP` de referencia real de SNIa.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame real leido de un `.DUMP` de SNANA, con columnas `RA`/`DEC`
        reales (grados).
    opsim_db_path : str o Path
        Ruta al sqlite real del OpSim (mismo que usan los scripts de
        produccion, `AUTOSIM/data/opsim/baseline_v5.3.1_10yrs.db`) -- se usa
        para extraer los centros reales de los 6 campos DDF
        (`target_name LIKE '%ddf_%'`, promedio de `fieldRA`/`fieldDec`).
    max_sep_deg : float
        Separacion angular maxima (grados) para considerar un objeto
        miembro real de un campo DDF. Default 2.0 -- el mismo umbral que
        uso Fase 33 (distribucion real bimodal: mediana 1.47 grados para
        objetos reales, ~77 grados para los contaminantes).

    Returns
    -------
    pandas.DataFrame
        Subconjunto de `df` con separacion angular real < `max_sep_deg` al
        campo DDF real mas cercano, con columnas nuevas `field_assigned`/
        `field_sep_deg`.
    """
    import sqlite3

    import pandas as pd

    con = sqlite3.connect(str(opsim_db_path))
    opsim = pd.read_sql_query("SELECT * FROM observations", con)
    con.close()
    opsim_ddf = opsim[opsim["target_name"].str.contains("ddf_", na=False)].reset_index(drop=True)
    opsim_ddf["field"] = opsim_ddf["target_name"].str.extract(r"ddf_(\w+)")
    centers = opsim_ddf.groupby("field")[["fieldRA", "fieldDec"]].mean()
    centers.columns = ["ra", "dec"]

    def _angsep_deg(ra1, dec1, ra2, dec2):
        ra1, dec1, ra2, dec2 = map(np.radians, (ra1, dec1, ra2, dec2))
        cos_sep = np.sin(dec1) * np.sin(dec2) + np.cos(dec1) * np.cos(dec2) * np.cos(ra1 - ra2)
        return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))

    best_sep = np.full(len(df), np.inf)
    best_field = np.array([""] * len(df), dtype=object)
    for field, row in centers.iterrows():
        sep = _angsep_deg(df["RA"].to_numpy(dtype=float), df["DEC"].to_numpy(dtype=float),
                           row["ra"], row["dec"])
        better = sep < best_sep
        best_sep[better] = sep[better]
        best_field[better] = field

    out = df.copy()
    out["field_assigned"] = best_field
    out["field_sep_deg"] = best_sep
    return out[out["field_sep_deg"] < max_sep_deg].reset_index(drop=True)


# ------------------------------------------------------------------ SALT2.INFO
def read_salt2_info(model_dir):
    """Parsea el `SALT2.INFO` real del directorio del modelo SALT2.

    Fase 37: `sncosmo.SALT2Source` **NO lee `SALT2.INFO` en absoluto** --
    solo `salt2_template_0/1.dat`, `salt2_color_correction.dat`,
    `salt2_color_dispersion.dat` y los mapas de error (confirmado leyendo la
    firma real de `SALT2Source.__init__` en `sncosmo==2.13.0`, y grepeando su
    fuente: ni `SALT2.INFO` ni `MAG_OFFSET` aparecen). SNANA si lo lee, y
    aplica dos claves que este proyecto ignoraba sin saberlo:

      MAG_OFFSET: 0.27   -> `genmag_SALT2.c:2257` real:
                            `magobs = ZP - 2.5*log10(flux) + MAG_OFFSET;`
                            (leido en `genmag_SALT2.c:1275-1276`). Es un
                            offset ADITIVO de magnitud, acromatico, aplicado
                            a TODA magnitud del modelo -- incluido
                            `peakmag_obs` y por lo tanto `PEAKMAG_<filt>` del
                            `.DUMP` y `SIM_PEAKMAG_<filt>` del `_HEAD.FITS`.
      SIGMA_INT: 0.090   -> la dispersion intrinseca coherente que el
                            proyecto ya usaba (queda confirmada aca como
                            valor real del modelo, no un supuesto).

    El `SALT2.INFO` real de `SALT2.WFIRST-H17` (el modelo de produccion de
    esta campana) declara `MAG_OFFSET: 0.27` -- y la comparacion PAREADA
    objeto-a-objeto contra el `_HEAD.FITS` real de produccion (Fase 37,
    alimentando a LightCurveLynx los `SIM_SALT2x0/x1/c/z/MWEBV` exactos de
    SNANA) midio un residuo acromatico de **-0.2722 mag**, plano en banda y
    en `z` -- el valor declarado, a 0.002 mag. Ver NOTES.md Fase 37.

    Parameters
    ----------
    model_dir : str o Path
        Directorio del modelo SALT2 (el mismo que se le pasa a
        `sncosmo.SALT2Source(modeldir=...)`). Debe contener `SALT2.INFO`.

    Returns
    -------
    dict
        Claves numericas reales del archivo. Siempre trae al menos
        `MAG_OFFSET` (0.0 si no esta declarada -- mismo default que
        `INPUT_SALT2_INFO.MAG_OFFSET = 0.0` en `genmag_SALT2.c:1205`).
    """
    from pathlib import Path

    info_path = Path(model_dir) / "SALT2.INFO"
    out = {"MAG_OFFSET": 0.0}
    if not info_path.exists():
        return out
    for line in info_path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        parts = val.split()
        if len(parts) != 1:
            continue
        try:
            out[key.strip()] = float(parts[0])
        except ValueError:
            continue
    return out


if __name__ == "__main__":
    # sanity check standalone (sin LightCurveLynx) -- corridas rapidas para
    # confirmar que las formas son razonables antes de conectarlas al grafo.
    z_grid, cdf = build_dndz_powerlaw2_cdf(
        segments=[(2.5e-5, 1.5, 0.0, 1.0), (9.7e-5, -0.5, 1.0, 3.0)],
        z_min=0.011, z_max=1.2,
    )
    print("CDF sample (every 200th grid point, should climb smoothly 0->1, not "
          "sit near 0 then jump at the end):")
    print("  ", np.round(cdf[::200], 4))

    z_sampler = make_dndz_sampler(z_grid, cdf, seed=42)
    zs = z_sampler(size=5000)
    pct = np.percentile(zs, [10, 25, 50, 75, 90])
    print(f"z: min={zs.min():.3f} max={zs.max():.3f} mean={zs.mean():.3f} "
          f"p10={pct[0]:.3f} p25={pct[1]:.3f} p50={pct[2]:.3f} p75={pct[3]:.3f} p90={pct[4]:.3f}")
    hist, edges = np.histogram(zs, bins=10, range=(0.011, 1.2))
    print("  histograma (10 bins, 0.011-1.2):", hist.tolist())

    c_sampler = make_bifurcated_normal_sampler(-0.054, 0.043, 0.101, -0.3, 0.5, seed=1)
    cs = c_sampler(size=5000)
    print(f"c: min={cs.min():.3f} max={cs.max():.3f} mean={cs.mean():.3f}")

    x1_sampler = make_bifurcated_normal_sampler(0.973, 1.472, 0.222, -3.0, 2.0, seed=2)
    x1s = x1_sampler(size=5000)
    print(f"x1: min={x1s.min():.3f} max={x1s.max():.3f} mean={x1s.mean():.3f}")
