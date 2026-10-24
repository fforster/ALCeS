"""SNII_NMF_tail (v5): the SNII-NMF SIMSED model with a parametrized radioactive (56Co) tail.

Deployed next to ALCeS's run_simsed_poc.py (Leftraru: ~/AUTOSIM/exploration/lightcurvelynx/snii_tail.py, with
./snii_tail/sn2012aw_nebular_template.npz and ./snii_tail/bessell_V.dat); source in LSST_sim_lcs/tools/snii_tail/.
Full description, numbers, validation and change log: LSST_sim_lcs/docs/SNII_NMF_tail.md.

Why: the SNII-NMF templates (SIMSED.SNII-NMF, 384 SEDs) stop at rest phase +150.5 d from peak, while the SNe are
still falling off the plateau; LightCurveLynx returns zero flux outside a template's phase range, so SNII-NMF objects
have no radioactive tail at all.

Model (per object; rest phase p = t - t0, time since explosion t = p - p_first, p_first = template's first phase):

  T(lambda, t)    = template flam; beyond its last phase, continued with its own last e-folding rate per wavelength
                    (capped at <= -1/30 d^-1)
  tail(lambda, t) = s(lambda, t) * L_dep(t; M_Ni, T0)
      L_dep(t; M, T0) = M [6.45e43 exp(-t/8.8) + 1.45e43 exp(-t/111.3)] [1 - exp(-T0^2/t^2)]  erg/s (t in days)
      s(lambda, t)    = SN 2012aw nebular flam at 10 pc per erg/s deposited: per wavelength,
                        ln s = a + b (t_eff - 350.5), fitted to the 250/332/369/451 d spectra divided by
                        L_dep(t; 0.056, 440); t_eff = 350.5 + 125 tanh((t - 350.5)/125)
  w(lambda, t)    = 1 / (1 + exp(-(t - t_on(lambda) + 2 w0) / w0)),  w0 = 5 d
      t_on(lambda) = first t >= 60 d with T <= 3 x tail at that wavelength, capped at the template's t_PT
      t_PT         = when the template's pseudo-bolometric flux (4000-9000 A) is 1 mag below its value at 60 d
  F(lambda, t)    = (T^4 + (s w tail)^4)^(1/4)        (smooth maximum; +0.19 mag at most where T = s w tail)
  s (v3)          = min(1, 0.9 x template / tail) over 4 broad rest windows (~g, r, i, z) at t_PT - 20 d:
                    a H-rich SN's tail cannot outshine its plateau (only 56Ni-rich tails on faint plateaus);
                    effective M_Ni = s M_Ni

  M_Ni v5 (class SNII_NMF_tail): the plateau-relation value (below) quantile-mapped onto the Rodriguez+21 distribution,
      log10 M_Ni = -1.50 + 0.35 (x - mu_src)/sig_src, x = relation + m_ni_dex, mu_src/sig_src = -1.6276/0.3136 (template-
      weighted), truncated 0.005-0.18 Msun; keeps the plateau correlation, marginal = Rodriguez+21. No cap (tail.cap False).
  M_Ni (default, "plateau_relation"): log10 M_Ni = -7.708 - 0.3755 M_V(50 d) + m_ni_dex  (Rodriguez+21 eq. 29),
      M_V(50 d) = the object's template, Bessell V (Vega) at 10 pc, 50 d after explosion; M_Ni bounded 0.001-0.3.
      Alternatively ("independent"): a sampled m_ni.

Per-object parameters: m_ni_dex (or m_ni) and t0_trap, sampled with seeded samplers (make_tail_sampler).
"""
from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np
from lightcurvelynx.models.sed_template_model import MultiSEDTemplateModel, SIMSEDModel
from lightcurvelynx.astro_utils.unit_utils import flam_to_fnu

M_NI_REF, T0_REF = 0.056, 440.0            # SN 2012aw: M_Ni from Dall'Ora et al. 2014; T0 fitted to its nebular L
MIN_EFOLD_RATE = 1.0 / 30.0                # template continuation fades by at least one e-fold per 30 d
W0_TRANSITION = 5.0                        # width [d] of the logistic plateau->tail switch (Olivares+10 median ~5 d)
TPT_DROP_MAG, TPT_REF_DAY = 1.0, 60.0      # t_PT: template pseudo-bolometric 1 mag below its level at 60 d post-expl
TPT_BAND = (4000.0, 9000.0)                # rest-frame range of the pseudo-bolometric flux used for t_PT
SWITCH_RATIO, SWITCH_MIN_DAY = 3.0, 60.0    # tail fully on when template pseudo-bol <= 3x tail (>= 60 d)
SOFTMAX_N = 4.0                            # template/tail combination F = (T^n + (w tail)^n)^(1/n)
CEIL_LEAD = 20.0                           # v3: t_ref = t_PT - 20 d (still on the plateau)
TAIL_MAX_FRAC = 0.9                        # v3: tail flux in each CAP_WINDOWS window <= 0.9 x the plateau's at t_ref
CAP_WINDOWS = ((4000.0, 5500.0), (5500.0, 7000.0), (7000.0, 8200.0), (8200.0, 9200.0))   # ~g, r, i, z (rest frame)
CAP_LEAD = (0.0, 0.0, 0.0, 30.0)           # v3.1: the z window is evaluated 30 d earlier than t_ref (~68 d), on the
                                           # plateau: the NMF templates' z band collapses from ~95 d (artefact)
SWITCH_WAVE = np.arange(1000.0, 11500.1, 100.0)   # coarse grid for the per-wavelength switch-on time
MNI_REL_A, MNI_REL_B = -7.708, -0.3755     # log10 M_Ni = A + B M_V(50 d)  (Rodriguez et al. 2021, eq. 29)
MNI_BOUNDS = (0.001, 0.3)                  # Msun, hard bounds on the derived 56Ni mass
VEGA_MINUS_AB_V = -0.02                    # V_Vega = V_AB - 0.02 (Blanton & Roweis 2007)
BESSELL_V_DEFAULT = Path(__file__).resolve().parent / "snii_tail" / "bessell_V.dat"
TAIL_TEMPLATE_DEFAULT = Path(__file__).resolve().parent / "snii_tail" / "sn2012aw_nebular_template.npz"


def deposition_luminosity(t_days, m_ni, t0_trap):
    """56Ni + 56Co decay energy deposited in the ejecta [erg/s] at t_days since explosion."""
    t = np.maximum(np.asarray(t_days, dtype=float), 1e-3)
    full = m_ni * (6.45e43 * np.exp(-t / 8.8) + 1.45e43 * np.exp(-t / 111.3))
    return full * (1.0 - np.exp(-(t0_trap ** 2) / t ** 2))


class NebularTailTemplate:
    """Nebular SED of SN 2012aw per unit deposited luminosity, smooth in time.

    Each epoch k (250/332/369/451 d) gives r_k(lambda) = ln[S_k(lambda) / L_dep(t_k; 0.056 Msun, 440 d)]
    (flam at 10 pc per erg/s). Per wavelength r is fitted by least squares as a(lambda) + b(lambda) (t_eff - T_MID),
    with t_eff = T_MID + H tanh((t - T_MID)/H) (smoothly levels off outside the data; T_MID = 350.5, H = 125 d).
    This removes the +-0.2 mag epoch-to-epoch calibration noise and the slope kinks of piecewise interpolation.
    flam(t, lambda) = exp[a + b (t_eff - T_MID)] * L_dep(t; m_ni, t0_trap)   [erg/s/cm^2/A at 10 pc]
    """

    T_MID, H = 350.5, 125.0

    def __init__(self, path=TAIL_TEMPLATE_DEFAULT):
        d = np.load(path)
        phase = np.asarray(d["phase_expl"], dtype=float)
        self.wave = np.asarray(d["wave"], dtype=float)
        flam = np.asarray(d["flam_10pc"], dtype=float)
        self.zero = (flam <= 0).any(axis=0)                            # outside the tapered range (< 2000 A)
        r = np.log(np.maximum(flam, 1e-300)) - np.log(deposition_luminosity(phase, M_NI_REF, T0_REF))[:, None]
        x = self._t_eff(phase) - self.T_MID
        X = np.column_stack([np.ones_like(x), x])
        coef, *_ = np.linalg.lstsq(X, r, rcond=None)                   # 2 x N_wave
        self.a, self.b = coef[0], coef[1]
        self.a[self.zero] = -np.inf

    def _t_eff(self, t):
        return self.T_MID + self.H * np.tanh((np.asarray(t, dtype=float) - self.T_MID) / self.H)

    def per_unit_luminosity(self, t_exp, wavelengths):
        """(T x W) flam at 10 pc per erg/s of deposited luminosity, at rest-frame times since explosion t_exp."""
        x = self._t_eff(np.atleast_1d(t_exp)) - self.T_MID
        f = np.exp(self.a[None, :] + self.b[None, :] * x[:, None])
        return np.array([np.interp(wavelengths, self.wave, row, left=0.0, right=0.0) for row in f])

    def flam(self, t_exp, wavelengths, m_ni=M_NI_REF, t0_trap=T0_REF):
        t = np.atleast_1d(np.asarray(t_exp, dtype=float))
        return self.per_unit_luminosity(t, wavelengths) * deposition_luminosity(t, m_ni, t0_trap)[:, None]


class SIMSEDTailModel(SIMSEDModel):
    """SIMSEDModel + smooth template continuation + parametrized 56Co tail (see module docstring).

    Extra parameters: m_ni (56Ni mass, Msun) and t0_trap (gamma-ray trapping timescale, days).
    """

    def __init__(self, templates, flux_scale=1.0, *, t0_trap, m_ni=None, m_ni_dex=None,
                 tail_template=TAIL_TEMPLATE_DEFAULT, bessell_v=BESSELL_V_DEFAULT, w0_transition=W0_TRANSITION,
                 tail_cap=True, m_ni_map=None, **kwargs):
        """Give exactly one of m_ni (56Ni mass, sampled independently) or m_ni_dex (scatter [dex] about the
        Rodriguez+21 relation log10 M_Ni = -7.708 - 0.3755 M_V(50 d), M_V of the object's template)."""
        if (m_ni is None) == (m_ni_dex is None):
            raise ValueError("give exactly one of m_ni or m_ni_dex")
        super().__init__(templates, flux_scale=flux_scale, **kwargs)
        self.tail = tail_template if isinstance(tail_template, NebularTailTemplate) else NebularTailTemplate(tail_template)
        self.w0_transition = float(w0_transition)
        self.tail_cap = bool(tail_cap)                      # v3 tail-brightness cap on/off (class config tail.cap)
        # v5 m_ni_map = dict(source=(mean, sigma), target=(mean, sigma), bounds=(lo, hi)): quantile-map the plateau-
        # relation log10 M_Ni (template-weighted source distribution) onto a target log-normal, e.g. Rodriguez+21
        self.m_ni_map = m_ni_map
        self._t_pt, self._pbol, self._mv50 = {}, {}, {}   # per-template caches
        self.m_ni_mode = "independent" if m_ni is not None else "plateau_relation"
        if m_ni is not None:
            self.add_parameter("m_ni", m_ni, description="56Ni mass powering the radioactive tail (Msun).")
        else:
            bv = np.loadtxt(bessell_v)
            self._bv_wave, self._bv_trans = bv[:, 0], bv[:, 1]
            self.add_parameter("m_ni_dex", m_ni_dex,
                               description="Scatter [dex] of log10 M_Ni about the M_V(50 d) relation (Rodriguez+21).")
        self.add_parameter("t0_trap", t0_trap, description="Gamma-ray trapping timescale T0 (days).")

    def template_mv50(self, index):
        """Absolute Vega V magnitude of template `index` 50 d after explosion (at 10 pc, x FLUX_SCALE)."""
        if index not in self._mv50:
            tmpl = self.templates[index]
            w = np.arange(self._bv_wave.min(), self._bv_wave.max() + 1, 5.0)
            flam = self.continued_template_sed(tmpl, np.array([float(tmpl.times[0]) + 50.0]), w)[0] * self.flux_scale
            t = np.interp(w, self._bv_wave, self._bv_trans, left=0, right=0)
            fnu = flam * w ** 2 / 2.998e18
            num = np.trapezoid(fnu * t / w, w)
            self._mv50[index] = (-2.5 * np.log10(num / np.trapezoid(t / w, w)) - 48.6 + VEGA_MINUS_AB_V
                                 if num > 0 else np.inf)
        return self._mv50[index]

    def tail_scale(self, index, m_ni, t0_trap):
        """v3 brightness cap s <= 1: in each broad rest-frame window of CAP_WINDOWS (~g, r, i, z) the tail flux at
        t_ref = t_PT - 20 d is at most TAIL_MAX_FRAC x the template's (a H-rich SN's tail cannot outshine its plateau;
        broad windows average over individual nebular lines). Effective 56Ni mass = s * M_Ni."""
        tmpl = self.templates[index]
        t_ref = self.t_pt(index) - CEIL_LEAD
        s = 1.0
        for (lo, hi), lead in zip(CAP_WINDOWS, CAP_LEAD):
            w = np.arange(lo, hi + 1, 20.0)
            t_c = t_ref - lead
            t_w = self.continued_template_sed(tmpl, np.array([float(tmpl.times[0]) + t_c]), w)[0].sum()
            tail_w = (self.tail.flam(np.array([t_c]), w, m_ni, t0_trap)[0] / self.flux_scale).sum()
            if tail_w > 0 and t_w > 0:
                s = min(s, TAIL_MAX_FRAC * t_w / tail_w)
        return float(s)

    def m_ni_effective(self, index, graph_state):
        """56Ni mass actually powering the tail after the v3 brightness cap (Msun)."""
        m_ni = self.m_ni_of(index, graph_state)
        if not self.tail_cap:
            return m_ni
        return m_ni * self.tail_scale(index, m_ni, self.get_param(graph_state, "t0_trap"))

    def m_ni_of(self, index, graph_state):
        """56Ni mass [Msun] of the object: its m_ni, or the plateau relation for its template plus m_ni_dex."""
        if self.m_ni_mode == "independent":
            return float(np.atleast_1d(self.get_param(graph_state, "m_ni"))[0])
        dex = float(np.atleast_1d(self.get_param(graph_state, "m_ni_dex"))[0])
        log_m = MNI_REL_A + MNI_REL_B * self.template_mv50(index) + dex
        if self.m_ni_map:
            (sm, ss), (tm, ts), bounds = self.m_ni_map["source"], self.m_ni_map["target"], self.m_ni_map["bounds"]
            return float(np.clip(10 ** (tm + ts * (log_m - sm) / ss), *bounds))
        return float(np.clip(10 ** log_m, *MNI_BOUNDS))

    @staticmethod
    def continued_template_sed(tmpl, phase, wavelengths):
        """Template flam at rest phases `phase`; beyond its last phase, its own last e-folding rate (<= -1/30 d)."""
        phase = np.asarray(phase, dtype=float)
        flam = tmpl.evaluate_sed(phase, wavelengths)                       # 0 outside the template range
        p_prev, p_last = float(tmpl.times[-2]), float(tmpl.times[-1])
        late = phase > p_last
        if late.any():
            f_edge = tmpl.evaluate_sed(np.array([p_prev, p_last]), wavelengths)
            with np.errstate(divide="ignore", invalid="ignore"):
                k = np.log(f_edge[1] / f_edge[0]) / (p_last - p_prev)
            k = np.where(np.isfinite(k), np.minimum(k, -MIN_EFOLD_RATE), -MIN_EFOLD_RATE)
            flam[late] = f_edge[1][None, :] * np.exp(k[None, :] * (phase[late] - p_last)[:, None])
        return flam

    def _pseudo_bol_curves(self, index):
        """Cached curves of template `index` on t_grid (days since explosion): pseudo-bolometric template flux over
        TPT_BAND, and per-wavelength (SWITCH_WAVE) template flam and tail flam per erg/s (both in template units)."""
        if index not in self._pbol:
            tmpl = self.templates[index]
            p_first = float(tmpl.times[0])
            t_grid = np.arange(1.0, 400.0, 0.5)
            wave = np.arange(TPT_BAND[0], TPT_BAND[1] + 1, 20.0)
            tmpl_pb = self.continued_template_sed(tmpl, p_first + t_grid, wave).sum(axis=1)
            tmpl_w = self.continued_template_sed(tmpl, p_first + t_grid, SWITCH_WAVE)
            tail_w = self.tail.per_unit_luminosity(t_grid, SWITCH_WAVE) / self.flux_scale
            self._pbol[index] = (t_grid, tmpl_pb, tmpl_w, tail_w)
        return self._pbol[index]

    def t_pt(self, index):
        """Plateau->tail transition of template `index` [d since explosion]: its (continued) pseudo-bolometric flux
        over TPT_BAND falls TPT_DROP_MAG below its value at TPT_REF_DAY."""
        if index not in self._t_pt:
            t_grid, tmpl_pb, _, _ = self._pseudo_bol_curves(index)
            ref = np.interp(TPT_REF_DAY, t_grid, tmpl_pb)
            below = np.where((t_grid >= TPT_REF_DAY) & (tmpl_pb <= ref * 10 ** (-0.4 * TPT_DROP_MAG)))[0]
            self._t_pt[index] = float(t_grid[below[0]]) if len(below) and ref > 0 else float(t_grid[-1])
        return self._t_pt[index]

    def t_switch(self, index, m_ni, t0_trap, wavelengths=None):
        """Per-wavelength switch-on time of the tail [d since explosion] (tail weight 0.88 there): the first time
        after SWITCH_MIN_DAY when the template flam at that wavelength is <= SWITCH_RATIO x the tail's, capped at
        t_PT. Bands in which the template collapses early (u, z, y in SNII-NMF) get their tail early, so they do not
        dip below it first. Returned on SWITCH_WAVE, or interpolated to `wavelengths`."""
        t_grid, _, tmpl_w, tail_w = self._pseudo_bol_curves(index)
        tail = tail_w * deposition_luminosity(t_grid, m_ni, t0_trap)[:, None]
        cond = (t_grid[:, None] >= SWITCH_MIN_DAY) & (tmpl_w <= SWITCH_RATIO * tail)
        first = np.where(cond.any(axis=0), t_grid[np.argmax(cond, axis=0)], np.inf)
        t_on = np.maximum(SWITCH_MIN_DAY, np.minimum(first, self.t_pt(index)))
        return t_on if wavelengths is None else np.interp(wavelengths, SWITCH_WAVE, t_on)

    def compute_sed(self, times, wavelengths, graph_state):
        index = self.get_param(graph_state, "selected_template")
        tmpl = self.templates[index]
        phase = np.asarray(times, dtype=float) - self.get_param(graph_state, "t0")
        flam = self.continued_template_sed(tmpl, phase, wavelengths)

        t_exp = phase - float(tmpl.times[0])
        after = t_exp > 0
        if after.any():
            m_ni, t0_trap = self.m_ni_of(index, graph_state), self.get_param(graph_state, "t0_trap")
            t_on = self.t_switch(index, m_ni, t0_trap, wavelengths)            # per wavelength
            # logistic switch centred 2 w0 before t_on (weight 0.88 at t_on): before it the 56Ni heating is part of
            # the template's photospheric light
            weight = 1.0 / (1.0 + np.exp(-(t_exp[after][:, None] - (t_on[None, :] - 2 * self.w0_transition))
                                         / self.w0_transition))
            tail = self.tail.flam(t_exp[after], wavelengths, m_ni, t0_trap) * weight / self.flux_scale
            n = SOFTMAX_N
            # v3: a H-rich SN's radioactive tail cannot outshine its plateau: the tail is scaled by s <= 1 so that in
            # each broad ~g/r/i/z window its flux at t_ref = t_PT - 20 d is at most 0.9 x the template's (tail_scale).
            # Only 56Ni-rich tails on faint plateaus are affected; this removes the plateau bump of those cases.
            capped = tail * self.tail_scale(index, m_ni, t0_trap) if self.tail_cap else tail
            flam[after] = (np.maximum(flam[after], 0) ** n + capped ** n) ** (1.0 / n)

        # as SIMSEDModel.compute_sed: flux scale, 10 pc -> distance, flam -> fnu [nJy]
        d_pc = self.get_param(graph_state, "distance")
        if d_pc is None or d_pc <= 0:
            raise ValueError(f"Received invalid luminosity distance (pc) in SIMSED model {d_pc}.")
        return flam_to_fnu(
            flux_flam=flam * self.flux_scale * (10 / d_pc) ** 2, wavelengths=wavelengths, wave_unit=u.AA,
            flam_unit=u.erg / u.s / u.cm**2 / u.AA, fnu_unit=u.nJy,
        )


def make_tail_sampler(spec, seed):
    """Seeded sampler f(size=None, **kw) for a tail-parameter prior (for SizeAwareFunctionNode).

    spec: ("lognormal", median, sigma_ln, lo, hi)   log-normal truncated to [lo, hi] (by redrawing)
          ("loguniform", lo, hi) | ("uniform", lo, hi) | ("fixed", value)
          ("normal", mean, sigma, lo, hi)   normal truncated to [lo, hi] (by redrawing)
          ("mixture", [(weight, spec), (weight, spec), ...])   each draw picks a component by weight
    """
    rng = np.random.default_rng(seed)

    def draw(n, spec=spec):
        kind = spec[0]
        if kind == "mixture":
            w = np.array([c[0] for c in spec[1]], dtype=float)
            pick = rng.choice(len(w), size=n, p=w / w.sum())
            out = np.empty(n)
            for i, (_, sub) in enumerate(spec[1]):
                if (pick == i).any():
                    out[pick == i] = draw(int((pick == i).sum()), sub)
            return out
        if kind == "lognormal":
            med, sig, lo, hi = spec[1:]
            out = np.exp(rng.normal(np.log(med), sig, n))
            bad = (out < lo) | (out > hi)
            while bad.any():
                out[bad] = np.exp(rng.normal(np.log(med), sig, int(bad.sum())))
                bad = (out < lo) | (out > hi)
            return out
        if kind == "normal":
            mu, sig, lo, hi = spec[1:]
            out = rng.normal(mu, sig, n)
            bad = (out < lo) | (out > hi)
            while bad.any():
                out[bad] = rng.normal(mu, sig, int(bad.sum()))
                bad = (out < lo) | (out > hi)
            return out
        if kind == "loguniform":
            return np.exp(rng.uniform(np.log(spec[1]), np.log(spec[2]), n))
        if kind == "uniform":
            return rng.uniform(spec[1], spec[2], n)
        if kind == "fixed":
            return np.full(n, float(spec[1]))
        raise ValueError(f"unknown prior {spec}")

    def sampler(size=None, **_kwargs):
        n = 1 if size is None else int(np.prod(size))
        v = draw(n)
        return v[0] if size is None else v.reshape(size)

    return sampler
