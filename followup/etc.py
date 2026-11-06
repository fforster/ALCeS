"""Exposure-time calculator (ETC) mode of the follow-up tool, vectorized (2026-11-06).

Port of the INO SNR calculator by Aysan Hemmatiortakand (followup/ETC/INO/ETC_2.py and ancillary_functions.py,
last updated 2025-11-17): same telescope, detector, band, extinction, sky and noise model, written for arrays so the
engine can evaluate every (event, time step) pair. Instead of a fixed limiting magnitude, the follow-up condition
becomes "the event reaches SNR >= snr_target within t_total seconds of integration", i.e. a limiting magnitude that
depends on airmass and sky brightness (Moon) at each time step:

    m_lim(t) = faintest AB magnitude with SNR(m, t_total; X(t), sky(t)) = snr_target

SNR of one exposure (ETC_2.calculate_snr), t_exp in [30, 320] s:
    F      = source e-/s:   AB mag + k_band * X  ->  f_nu -> f_lambda = f_nu c / lambda^2 -> * bandwidth * area / (h c / lambda) * E
    B      = sky e-/s/pixel: sky mag/arcsec^2 converted the same way, * pixel_scale^2
    npix   = pi * (seeing / pixel_scale * 2 * binning)^2
    SNR_1  = MULT(t_exp) * F t_exp / sqrt(F t_exp + npix (B t_exp + RN^2 + DARK(t_exp)^2))
Stacking N = ceil(t_total / 320) equal frames of t_exp = t_total / N (frames >= 30 s) gives SNR = sqrt(N) SNR_1, so
with s = snr_target / (MULT sqrt(N)) and Q = npix (B t_exp + RN^2 + DARK^2) the limit solves (F t)^2 = s^2 (F t + Q):
    F_lim t_exp = (s^2 + sqrt(s^4 + 4 s^2 Q)) / 2.

Sky model (ancillary_functions.calculate_sky_magnitude): sky = c_fit + a_fit exp(-b_fit * moon_separation_deg)
- k_sky * X, plus -2.5 log10(FLI) when the Moon is above the horizon. The original fit is calibrated for r only
(i is a placeholder) and is applied to every band here, as in the original.
Moon: low-precision ephemeris (Astronomical Almanac), geocentric, ~0.3 deg -- ample for this sky model; the original
uses astropy's get_body.

Faithful to the original, flagged in the GUI notes: the latitude differs between the two original files (35.674 in
ETC_2.py, 33.674 in ancillary_functions.py; INO is at 33.67 N: the site is whatever the user selects here); the
aperture npix grows with binning; the system efficiency (2.3%) is the value given "for i"; no z band.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import astro

H_PLANCK = 6.62620e-34
C_LIGHT = 2.9979250e8


@dataclass(frozen=True)
class Instrument:
    name: str = "INO 3.4 m (Iranian National Observatory)"
    D: float = 3.4                       # primary diameter [m]
    d: float = 0.6                       # central obstruction [m]
    efficiency: float = 2.3e-2           # total system efficiency (photon -> electron)
    pixel_scale: float = 0.101           # arcsec / pixel
    readnoise: float = 3.7               # e-
    gain: float = 1.0
    cw: dict = field(default_factory=lambda: {"u": 3540e-10, "g": 4770e-10, "r": 6230e-10, "i": 7630e-10})
    bandwidth: dict = field(default_factory=lambda: {"u": 600e-10, "g": 1380e-10, "r": 1380e-10, "i": 1520e-10})
    extinction: dict = field(default_factory=lambda: {"u": 0.404, "g": 0.35, "r": 0.2, "i": 0.15})
    t_exp_min: float = 30.0
    t_exp_max: float = 320.0
    # (t_lo, t_hi, dark std [e-], SNR multiplier) per single-exposure range (ETC_2.calculate_snr)
    exp_table: tuple = ((30, 90, 4.3117, 1.0), (90, 150, 4.7820, 1.2), (150, 210, 5.2813, 1.35),
                        (210, 320.0001, 8.5406, 1.52))
    sky_fit: tuple = (-3.0, 0.042, 19.705)   # a, b, c of sky = c + a exp(-b sep) [mag/arcsec^2] (r band)
    sky_extinction: float = 0.2

    @property
    def area_m2(self):
        return np.pi * (self.D / 2) ** 2 - np.pi * (self.d / 2) ** 2

    @property
    def bands(self):
        return list(self.cw)

    def dark_mult(self, t_exp):
        t = np.asarray(t_exp, float)
        dark = np.full(t.shape, np.nan)
        mult = np.full(t.shape, np.nan)
        for lo, hi, dk, mu in self.exp_table:
            sel = (t >= lo) & (t < hi)
            dark[sel], mult[sel] = dk, mu
        return dark, mult

    def e_per_s(self, mag, band):
        """electrons/s collected from a source of AB magnitude `mag` (already extinction-corrected)."""
        wav, bw = self.cw[band], self.bandwidth[band]
        f_nu_J = 10 ** (-0.4 * (np.asarray(mag, float) + 48.6)) * 1e-7      # erg -> J (per cm^2, as in the original)
        power = f_nu_J * C_LIGHT / wav ** 2 * bw * (self.area_m2 * 1e4)
        return power / (H_PLANCK * C_LIGHT / wav) * self.efficiency * self.gain

    def mag_from_e_per_s(self, e_s, band):
        """inverse of e_per_s"""
        return -2.5 * np.log10(np.asarray(e_s, float) / self.e_per_s(0.0, band))


INSTRUMENTS = {"INO": Instrument()}


def exposure_plan(inst: Instrument, t_total):
    """N equal frames of t_exp <= t_exp_max covering t_total (frames shorter than t_exp_min are not allowed)."""
    t_total = float(t_total)
    if t_total < inst.t_exp_min:
        raise ValueError(f"total integration must be >= {inst.t_exp_min:g} s (shortest exposure of the ETC)")
    n = int(np.ceil(t_total / inst.t_exp_max - 1e-9))
    return n, t_total / n


def snr(inst: Instrument, mag, band, t_total, airmass, sky_mag, seeing=1.15, binning=1):
    """SNR reached by stacking frames of total time t_total (ETC_2.calculate_snr per frame, x sqrt(N))."""
    n, t_exp = exposure_plan(inst, t_total)
    dark, mult = inst.dark_mult(t_exp)
    F = inst.e_per_s(np.asarray(mag) + np.asarray(airmass) * inst.extinction[band], band)
    B = inst.e_per_s(sky_mag, band) * inst.pixel_scale ** 2
    npix = np.pi * (seeing / inst.pixel_scale * 2 * binning) ** 2
    sig = F * t_exp
    return mult * np.sqrt(n) * sig / np.sqrt(sig + npix * (B * t_exp + inst.readnoise ** 2 + dark ** 2))


def limiting_mag(inst: Instrument, band, snr_target, t_total, airmass, sky_mag, seeing=1.15, binning=1):
    """Faintest AB magnitude (above the atmosphere) reaching snr_target within t_total; exact inverse of snr()."""
    n, t_exp = exposure_plan(inst, t_total)
    dark, mult = inst.dark_mult(t_exp)
    B = inst.e_per_s(sky_mag, band) * inst.pixel_scale ** 2
    npix = np.pi * (seeing / inst.pixel_scale * 2 * binning) ** 2
    Q = npix * (B * t_exp + inst.readnoise ** 2 + dark ** 2)
    s2 = (snr_target / (mult * np.sqrt(n))) ** 2
    sig = 0.5 * (s2 + np.sqrt(s2 * s2 + 4 * s2 * Q))
    return inst.mag_from_e_per_s(sig / t_exp, band) - np.asarray(airmass) * inst.extinction[band]


# ---------------------------------------------------------------- Moon and sky
def moon_radec(mjd):
    """Geocentric Moon RA, Dec [deg]; low-precision formulae of the Astronomical Almanac (~0.3 deg)."""
    T = (np.asarray(mjd, float) - astro.MJD_J2000) / 36525.0
    r = np.radians
    lam = (218.32 + 481267.881 * T + 6.29 * np.sin(r(135.0 + 477198.87 * T)) - 1.27 * np.sin(r(259.3 - 413335.36 * T))
           + 0.66 * np.sin(r(235.7 + 890534.22 * T)) + 0.21 * np.sin(r(269.9 + 954397.74 * T))
           - 0.19 * np.sin(r(357.5 + 35999.05 * T)) - 0.11 * np.sin(r(186.5 + 966404.03 * T)))
    beta = (5.13 * np.sin(r(93.3 + 483202.02 * T)) + 0.28 * np.sin(r(228.2 + 960400.89 * T))
            - 0.28 * np.sin(r(318.3 + 6003.15 * T)) - 0.17 * np.sin(r(217.6 - 407332.21 * T)))
    eps = r(23.439 - 0.013 * T)
    lam, beta = r(lam % 360.0), r(beta)
    x = np.cos(beta) * np.cos(lam)
    y = np.cos(eps) * np.cos(beta) * np.sin(lam) - np.sin(eps) * np.sin(beta)
    z = np.sin(eps) * np.cos(beta) * np.sin(lam) + np.cos(eps) * np.sin(beta)
    return np.degrees(np.arctan2(y, x)) % 360.0, np.degrees(np.arcsin(z))


def separation_deg(ra1, dec1, ra2, dec2):
    r = np.radians
    c = np.sin(r(dec1)) * np.sin(r(dec2)) + np.cos(r(dec1)) * np.cos(r(dec2)) * np.cos(r(np.asarray(ra1) - ra2))
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def moon_state(mjd, lat, lon):
    """per time: Moon RA, Dec, altitude at the site, illuminated fraction (elongation from the Sun, as the original)."""
    mra, mdec = moon_radec(mjd)
    sra, sdec = astro.sun_radec(mjd)
    alt = astro.altitude(mra, mdec, astro.local_sidereal_deg(mjd, lon), lat)
    fli = (1 - np.cos(np.radians(separation_deg(mra, mdec, sra, sdec)))) / 2
    return mra, mdec, alt, fli


def sky_mag(inst: Instrument, target_ra, target_dec, airmass, moon_ra, moon_dec, moon_alt, fli):
    """Sky brightness [mag/arcsec^2] (ancillary_functions.calculate_sky_magnitude, vectorized)."""
    a, b, c = inst.sky_fit
    sep = separation_deg(target_ra, target_dec, moon_ra, moon_dec)
    x = np.clip(airmass, 1.0, 10.0)
    sky = c + a * np.exp(-b * sep) - inst.sky_extinction * x
    return sky + np.where(moon_alt > 0, -2.5 * np.log10(np.maximum(fli, 1e-3)), 0.0)
