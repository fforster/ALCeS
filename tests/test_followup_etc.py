"""followup.etc against the original INO calculator (followup/ETC/INO) and astropy."""
import warnings

import numpy as np
from astropy import units as u
from astropy.coordinates import get_body, get_sun
from astropy.time import Time
from astropy.utils import iers

from followup import etc

iers.conf.auto_download = False
INO = etc.INSTRUMENTS["INO"]


def reference_snr(magnitude, filter_choice, exposure_time, airmass, sky_mag, seeing, binning):
    """ETC_2.calculate_snr transcribed line by line, with the airmass and sky magnitude given (the original computes
    them from date/RA/Dec with astropy)."""
    h, c = 6.62620e-34, 2.9979250e8
    pixel_scale, readnoise, D, d, E, GAIN = 0.101, 3.7, 3.4, 0.6, 2.3e-2, 1
    S = np.pi * (D / 2) ** 2 - np.pi * (d / 2) ** 2
    CW = {'u': 3540e-10, 'g': 4770e-10, 'r': 6230e-10, 'i': 7630e-10}
    band_width = {'u': 600e-10, 'g': 1380e-10, 'r': 1380e-10, 'i': 1520e-10}
    extinction = {'u': 0.404, 'g': 0.35, 'r': 0.2, 'i': 0.15}
    if 30 <= exposure_time < 90:
        DARK_STD, SNR_MULT = 4.3117, 1.0
    elif 90 <= exposure_time < 150:
        DARK_STD, SNR_MULT = 4.7820, 1.2
    elif 150 <= exposure_time < 210:
        DARK_STD, SNR_MULT = 5.2813, 1.35
    else:
        DARK_STD, SNR_MULT = 8.5406, 1.52
    npix = np.pi * ((seeing / pixel_scale * 2 * binning) ** 2)
    wav_m, bw_m = CW[filter_choice], band_width[filter_choice]
    m_corrected = magnitude + (airmass * extinction[filter_choice])
    f_nu_J = 10 ** (-0.4 * (m_corrected + 48.6)) * 1e-7
    total_power = f_nu_J * c / (wav_m ** 2) * bw_m * (S * 1e4)
    electrons_per_s = total_power / (h * c / wav_m) * E * GAIN
    signal_e = electrons_per_s * exposure_time
    f_nu_s_J = 10 ** (-0.4 * (sky_mag + 48.6)) * 1e-7
    sky_power = f_nu_s_J * c / (wav_m ** 2) * bw_m * (S * 1e4)
    electrons_sky_per_s = sky_power / (h * c / wav_m) * E * GAIN
    N_sky_e_per_pix = electrons_sky_per_s * (pixel_scale ** 2) * exposure_time
    noise = np.sqrt(signal_e + (npix * N_sky_e_per_pix) + npix * ((readnoise) ** 2 + (DARK_STD ** 2)))
    return signal_e / noise * SNR_MULT


def test_single_exposure_matches_original():
    for band in "ugri":
        for t in (30, 60, 120, 180, 300, 320):
            for mag, x, sky, see, b in ((18.0, 1.1, 19.5, 1.15, 1), (21.3, 1.8, 18.2, 0.7, 2), (16.0, 1.0, 20.5, 1.75, 1)):
                ref = reference_snr(mag, band, t, x, sky, see, b)
                got = etc.snr(INO, mag, band, t, x, sky, seeing=see, binning=b)
                assert np.isclose(got, ref, rtol=1e-12), (band, t, mag)


def test_stacking_and_inversion():
    # 3600 s = 12 frames of 300 s: SNR = sqrt(12) x single-frame SNR
    single = reference_snr(20.0, "r", 300, 1.3, 19.4, 1.15, 1)
    assert np.isclose(etc.snr(INO, 20.0, "r", 3600, 1.3, 19.4), np.sqrt(12) * single)
    x = np.array([1.0, 1.3, 2.0, 2.0])
    sky = np.array([20.0, 19.0, 17.5, 19.0])
    for t in (30, 200, 320, 1000, 3600, 7200):
        m = etc.limiting_mag(INO, "r", 10.0, t, x, sky)
        assert np.allclose(etc.snr(INO, m, "r", t, x, sky), 10.0, rtol=1e-9)
    # longer integrations and darker skies reach fainter
    assert etc.limiting_mag(INO, "r", 10, 3600, 1.2, 19.5) > etc.limiting_mag(INO, "r", 10, 600, 1.2, 19.5)
    assert etc.limiting_mag(INO, "r", 10, 3600, 1.2, 20.0) > etc.limiting_mag(INO, "r", 10, 3600, 1.2, 18.0)


def test_moon_against_astropy():
    mjd = np.linspace(61000, 61030, 61)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = Time(mjd, format="mjd")
        m = get_body("moon", t)                      # geocentric
        s = get_sun(t)
        ref_fli = (1 - np.cos(s.separation(m).to(u.rad).value)) / 2
    ra, dec = etc.moon_radec(mjd)
    sep = etc.separation_deg(ra, dec, m.ra.deg, m.dec.deg)
    assert np.max(sep) < 1.0      # formula: equinox of date; astropy: ICRS-aligned (~0.36 deg precession by 2027)
    _, _, _, fli = etc.moon_state(mjd, 33.674, 51.3188)
    assert np.max(np.abs(fli - ref_fli)) < 0.01


def test_best_limit_bounds_the_darkest_sky():
    """The engine's pre-cut must bound the limit under the darkest sky the INO model allows: a thin Moon (FLI floor
    1e-3) above the horizon, far from the target, at airmass 1 -- darker than 'Moon below the horizon'."""
    from followup import engine
    q = engine.Query(mode="etc", band="r", snr_target=10, t_exp_total=3600)
    thin_moon_up = etc.sky_mag(INO, 0.0, 0.0, 1.0, 180.0, 0.0, 30.0, 1e-3)
    moon_down = etc.sky_mag(INO, 0.0, 0.0, 1.0, 180.0, 0.0, -30.0, 0.5)
    assert thin_moon_up > moon_down
    lim = etc.limiting_mag(INO, "r", 10, 3600, 1.0, thin_moon_up)
    assert engine.best_limit(q) >= lim - 1e-9


def test_ks91_sky_model():
    """Krisciunas & Schaefer (1991): dark sky without Moon, moonlight only brightens, continuous at moonset, and a
    hand-worked V-band example."""
    import dataclasses
    # Moon down: dark zenith sky at the zenith, brighter at larger airmass
    for band in "ugri":
        assert np.isclose(etc.sky_mag_ks91(INO, band, 90.0, 90.0, -10.0, 1.0), etc.DARK_SKY_ZENITH[band])
        assert etc.sky_mag_ks91(INO, band, 30.0, 90.0, -10.0, 1.0) < etc.DARK_SKY_ZENITH[band]
    # moonlight only brightens; full Moon close by brightens a lot
    alts = np.linspace(-5, 80, 200)
    s = etc.sky_mag_ks91(INO, "r", 50.0, 40.0, alts, 1.0)
    assert np.all(s <= etc.sky_mag_ks91(INO, "r", 50.0, 40.0, -10.0, 1.0) + 1e-12)
    assert etc.sky_mag_ks91(INO, "r", 50.0, 10.0, 60.0, 1.0) < etc.DARK_SKY_ZENITH["r"] - 2.5
    # continuous at moonset (fade below the horizon): full Moon 40 deg away. The sky changes steeply but smoothly near
    # the horizon, so the largest step must shrink in proportion to the sampling (a jump would not)
    steps = []
    for h in (0.05, 0.005):
        s = etc.sky_mag_ks91(INO, "r", 50.0, 40.0, np.arange(-3.0, 3.0, h), 1.0)
        steps.append(np.max(np.abs(np.diff(s))))
    assert steps[1] < 0.2 * steps[0] and steps[1] < 0.005
    assert np.isclose(s[0], etc.sky_mag_ks91(INO, "r", 50.0, 40.0, -10.0, 1.0))     # no moonlight 3 deg below
    # hand-worked V example (k = 0.172, dark V 21.587): full Moon (alpha 0) 30 deg from a target, both at 60 deg
    v = dataclasses.replace(INO, extinction={**INO.extinction, "V": 0.172})
    etc.DARK_SKY_ZENITH["V"] = 21.587
    try:
        x = (1 - 0.96 * np.sin(np.radians(30)) ** 2) ** -0.5
        xm = 1 / (np.cos(np.radians(30)) + 0.025 * np.exp(-11 * np.cos(np.radians(30))))
        f = 10 ** 5.36 * (1.06 + np.cos(np.radians(30)) ** 2) + 10 ** (6.15 - 30 / 40)
        b_moon = f * 10 ** (-0.4 * 3.84) * 10 ** (-0.4 * 0.172 * xm) * (1 - 10 ** (-0.4 * 0.172 * x))
        b_dark = 34.08 * np.exp(20.7233 - 0.92104 * 21.587) * 10 ** (-0.4 * 0.172 * (x - 1)) * x
        expected = (20.7233 - np.log((b_moon + b_dark) / 34.08)) / 0.92104
        got = etc.sky_mag_ks91(v, "V", 60.0, 30.0, 60.0, 1.0)
        assert np.isclose(got, expected) and 17.3 < got < 18.2
    finally:
        del etc.DARK_SKY_ZENITH["V"]
