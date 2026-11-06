"""Site geometry for the follow-up tool: astronomical night and airmass on a time grid.

Fast analytic forms (no astropy transforms, so 10-year grids at minute resolution take milliseconds):
  - Sun: low-precision ephemeris of the Astronomical Almanac (accurate to ~0.01 deg, 1950-2050);
  - sidereal time: GMST linear in UT (IAU 1982; error << 1 s over the LSST decade, UT1-UTC ignored);
  - airmass: Pickering (2002), valid to the horizon.
Target coordinates are ICRS/J2000 and are not precessed (<= 0.3 deg by 2036: negligible for airmass cuts).
Validated against astropy in tests/test_followup_astro.py.
"""
from __future__ import annotations

import numpy as np

ASTRO_TWILIGHT_DEG = -18.0
MJD_J2000 = 51544.5


def time_grid(mjd_start: float, mjd_end: float, step_min: float) -> np.ndarray:
    n = int(np.floor((mjd_end - mjd_start) * 1440.0 / step_min)) + 1
    return mjd_start + np.arange(n) * step_min / 1440.0


def gmst_deg(mjd) -> np.ndarray:
    d = np.asarray(mjd, float) - MJD_J2000
    return (280.46061837 + 360.98564736629 * d) % 360.0


def local_sidereal_deg(mjd, lon: float) -> np.ndarray:
    return (gmst_deg(mjd) + lon) % 360.0


def sun_radec(mjd):
    """Apparent-ish Sun RA, Dec (deg), Astronomical Almanac low-precision formulae."""
    n = np.asarray(mjd, float) - MJD_J2000
    L = np.radians((280.460 + 0.9856474 * n) % 360.0)
    g = np.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = L + np.radians(1.915) * np.sin(g) + np.radians(0.020) * np.sin(2 * g)
    eps = np.radians(23.439 - 4.0e-7 * n)
    ra = np.degrees(np.arctan2(np.cos(eps) * np.sin(lam), np.cos(lam))) % 360.0
    dec = np.degrees(np.arcsin(np.sin(eps) * np.sin(lam)))
    return ra, dec


def altitude(ra_deg, dec_deg, lst_deg, lat: float):
    phi = np.radians(lat)
    dec = np.radians(dec_deg)
    ha = np.radians(np.asarray(lst_deg) - np.asarray(ra_deg))
    s = np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(ha)
    return np.degrees(np.arcsin(np.clip(s, -1, 1)))


def sun_altitude(mjd, lat: float, lon: float, height: float = 0.0) -> np.ndarray:
    ra, dec = sun_radec(mjd)
    return altitude(ra, dec, local_sidereal_deg(mjd, lon), lat)


def airmass_from_alt(alt):
    alt = np.asarray(alt, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        x = 1.0 / np.sin(np.radians(alt + 244.0 / (165.0 + 47.0 * np.abs(alt) ** 1.1)))
    return np.where(alt > 0, x, np.inf)


def airmass(ra_deg, dec_deg, lst_deg, lat: float) -> np.ndarray:
    """Airmass for objects (N,) at sidereal times (T,) -> (N, T); +inf below the horizon."""
    alt = altitude(np.asarray(ra_deg, float)[:, None], np.asarray(dec_deg, float)[:, None],
                   np.asarray(lst_deg, float)[None, :], lat)
    return airmass_from_alt(alt)


def night_mask(mjd, lat: float, lon: float, height: float = 0.0,
               sun_limit: float = ASTRO_TWILIGHT_DEG) -> np.ndarray:
    return sun_altitude(mjd, lat, lon, height) < sun_limit
