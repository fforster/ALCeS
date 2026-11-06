"""Analytic Sun / sidereal time / airmass of followup.astro against astropy (sub-0.3 deg is plenty for night and
airmass cuts)."""
import warnings

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
from astropy.time import Time
from astropy.utils import iers

from followup import astro

iers.conf.auto_download = False
LAT, LON = -30.2446, -70.7494


def _frame(mjd):
    t = Time(mjd, format="mjd", scale="utc")
    loc = EarthLocation(lat=LAT * u.deg, lon=LON * u.deg, height=2700 * u.m)
    return t, AltAz(obstime=t, location=loc, pressure=0)


def test_sun_altitude():
    mjd = astro.time_grid(61000, 61010, 37)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t, fr = _frame(mjd)
        ref = get_sun(t).transform_to(fr).alt.deg
    assert np.max(np.abs(astro.sun_altitude(mjd, LAT, LON) - ref)) < 0.1


def test_altitude_and_airmass():
    mjd = astro.time_grid(61000, 61002, 13)
    ra, dec = 150.0, -10.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t, fr = _frame(mjd)
        alt_ref = SkyCoord(ra * u.deg, dec * u.deg).transform_to(fr).alt.deg
    alt = astro.altitude(ra, dec, astro.local_sidereal_deg(mjd, LON), LAT)
    assert np.max(np.abs(alt - alt_ref)) < 0.5          # J2000 vs date precession (~50"/yr) dominates
    x = astro.airmass([ra], [dec], astro.local_sidereal_deg(mjd, LON), LAT)[0]
    up = alt_ref > 30
    assert np.max(np.abs(x[up] - 1 / np.sin(np.radians(alt_ref[up])))) < 0.02
