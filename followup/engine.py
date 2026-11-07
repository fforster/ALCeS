"""Follow-up potential of Rubin-detected transients from a ground site (ALCeS simulations, real-event weights).

Steps (per request):
 0. time grid [T0, T1 + longest follow-up window] with step dt;
 1. keep the steps where the Sun is below `sun_alt` (astronomical night by default) at the site;
 2. for each simulated detected object (first Rubin detection t_fd, time of maximum light t_peak) and each night step t
    in its follow-up window  t_fd + t_min <= t <= t_peak + t_max  (t_min: days after first detection; t_max: days after
    maximum light, the brightest model point in any band), interpolate the noiseless MODEL magnitude in `band` and
    require m <= mag_lim;
 3. require airmass(t) <= airmass_max at the site;
 4. per object: hours and nights it is followable, delay from first detection to the first opportunity;
 5. counts are expected REAL events: every simulated object carries a weight (real detected events per 10 yr it
    represents). Stores built from the flat-log-z training sets use W_EXPECTED, whose per-redshift-bin sum is the native
    rate times the detection efficiency measured in the simulations; native-rate stores use the sweep weights. Sums of
    weights over any selection are expected numbers, with Poisson-like errors sqrt(sum w^2).
Instantaneous counts N(t) cover t in [T0, T1]; per-object statistics cover the objects first detected in [T0, T1]
(followed to the end of their window even beyond T1, so they are not truncated).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import astro, etc

NATIVE_STORE = Path("~/data/alces_followup").expanduser()
TRAIN_STORE = Path("~/data/alces_followup_train").expanduser()
# default: the flat-log-z training-set store (user decision 2026-11-06) once built, else the native-rate store
STORE = TRAIN_STORE if (TRAIN_STORE / "catalog.json").exists() else NATIVE_STORE
TRAINSETS = Path("~/data/alces_trainsets_20261026").expanduser()
MAX_PAIRS = 8_000_000


@dataclass
class Query:
    lat: float = -30.2446            # Cerro Pachon
    lon: float = -70.7494
    height: float = 2700.0
    classes: list = field(default_factory=lambda: ["SNIa", "SNII"])
    surveys: list = field(default_factory=lambda: ["WFD"])
    band: str = "r"
    mag_lim: float = 20.0
    airmass_max: float = 2.0
    t_min: float = 0.0               # follow-up starts t_min days after the first Rubin detection
    t_max: float = 30.0              # ... and ends t_max days after maximum light (brightest point in any band)
    mjd_start: float = 61400.0
    mjd_end: float = 61765.0
    step_min: float = 15.0
    sun_alt: float = -18.0
    # False: the simulated objects at their simulated dates (default). True: also use the objects first detected in
    # the survey years `fold_year_list` (0 = first year; None = all), shifted by whole years into the window. This
    # assumes those years are equivalent (rolling stripes and other strategy changes make them differ): check with
    # the per-year breakdown returned in "by_year".
    fold_years: bool = False
    fold_year_list: list | None = None
    # "maglim": followable while model mag <= mag_lim. "etc": followable while the event reaches SNR >= snr_target
    # within t_exp_total seconds of integration with `instrument` (followup/etc.py), i.e. a limiting magnitude that
    # follows airmass and the Moon at every time step.
    mode: str = "maglim"
    instrument: str = "INO"
    snr_target: float = 10.0
    t_exp_total: float = 3600.0      # s
    seeing: float = 1.15             # arcsec FWHM
    binning: int = 1
    sky_model: str = "ino"          # ETC sky: "ino" (original INO calculator) or "ks91" (Krisciunas & Schaefer 1991)


@lru_cache(maxsize=None)
def catalog(store: str = str(STORE)):
    return json.loads((Path(store) / "catalog.json").read_text())


@lru_cache(maxsize=64)
def load(name: str, survey: str, store: str = str(STORE)):
    d = np.load(Path(store) / f"{name}_{survey}.npz")
    return {k: d[k] for k in d.files}


YEAR = 365.25
N_SURVEY_YEARS = 10


def grid_spec(cat):
    """(k0, n_days): the store's magnitude grid covers t_fd - k0 .. t_fd + n_days in daily steps (index = dt + k0)."""
    return int(cat.get("k0", 0)), int(cat["n_days"])


def window_end(d, q, n_days):
    """Follow-up window end relative to t_fd: t_peak - t_fd + t_max (t_peak = maximum light), within the store grid.
    Objects without a time of maximum fall back to t_fd + t_max."""
    dpk = d["t_peak"] - d["t_fd"]
    return np.clip(np.where(np.isfinite(dpk), dpk, 0.0) + q.t_max, None, n_days)


def check_mode(q):
    if q.mode not in ("maglim", "etc"):
        raise ValueError("mode must be 'maglim' or 'etc'")
    if q.mode == "etc":
        if q.instrument not in etc.INSTRUMENTS:
            raise ValueError(f"unknown instrument {q.instrument!r} (available: {list(etc.INSTRUMENTS)})")
        inst = etc.INSTRUMENTS[q.instrument]
        if q.band not in inst.bands:
            raise ValueError(f"the {q.instrument} ETC has no {q.band} band (available: {', '.join(inst.bands)})")
        if not (q.snr_target > 0 and q.seeing > 0 and q.binning >= 1):
            raise ValueError("need snr_target > 0, seeing > 0 and binning >= 1")
        if q.sky_model not in etc.SKY_MODELS:
            raise ValueError(f"sky_model must be one of {etc.SKY_MODELS}")
        etc.exposure_plan(inst, q.t_exp_total)            # raises below the shortest exposure


def best_limit(q):
    """Faintest magnitude the follow-up can ever reach: mag_lim, or the ETC limit at airmass 1 under the darkest
    sky the model can produce. Used as a pre-cut, so it must be a true upper bound. In the INO sky model the darkest
    sky is NOT "Moon below the horizon" but a thin Moon above it: the phase term -2.5 log10(FLI), with FLI floored at
    1e-3, adds up to +7.5 mag (fixed 2026-11-06; the earlier bound could drop events in thin-Moon nights)."""
    if q.mode != "etc":
        return q.mag_lim
    inst = etc.INSTRUMENTS[q.instrument]
    if q.sky_model == "ks91":
        # KS91: airmass and moonlight only brighten the dark zenith sky
        dark_sky = etc.DARK_SKY_ZENITH[q.band]
    else:
        a, b, c = inst.sky_fit
        dark_sky = c + a * np.exp(-b * 180.0) - inst.sky_extinction * 1.0 - 2.5 * np.log10(1e-3)
    return float(etc.limiting_mag(inst, q.band, q.snr_target, q.t_exp_total, 1.0, dark_sky, q.seeing, q.binning))


def limit_at(q, ra, dec, airmass, moon, alt=None):
    """Limiting magnitude for (event, time) pairs: mag_lim, or the ETC limit for the pair's airmass and sky.
    moon = (ra, dec, alt, fli) of the Moon at each pair's time (etc.moon_state); alt = the event's altitude [deg]
    (needed by the KS91 sky model; derived from the airmass if not given)."""
    if q.mode != "etc":
        return np.full(np.shape(airmass), float(q.mag_lim))
    inst = etc.INSTRUMENTS[q.instrument]
    if alt is None:
        alt = np.degrees(np.arcsin(np.clip(1.0 / np.asarray(airmass, float), 0.0, 1.0)))
    sky = etc.sky(inst, q.sky_model, q.band, ra, dec, alt, airmass, moon)
    return etc.limiting_mag(inst, q.band, q.snr_target, q.t_exp_total, airmass, sky, q.seeing, q.binning)


def interp_mag(magb, rows, dt, k0, n_days):
    """Linear interpolation of store magnitudes (rows of magb) at dt days after t_fd; +inf outside or without flux."""
    kf = np.clip(dt + k0, 0, k0 + n_days - 1e-6)
    k = kf.astype(np.int64)
    f = (kf - k).astype(np.float32)
    m0 = magb[rows, k].astype(np.float32)
    m1 = magb[rows, np.minimum(k + 1, k0 + n_days)].astype(np.float32)
    inside = (dt + k0 >= 0) & (dt <= n_days)
    with np.errstate(invalid="ignore"):
        return np.where(inside & np.isfinite(m0) & np.isfinite(m1), m0 + f * (m1 - m0), np.inf)


def survey_year(t_fd, t_survey0):
    """0-based survey year of a first detection (year 0 starts at the first simulated detection)."""
    return np.clip(np.floor((np.asarray(t_fd) - t_survey0) / YEAR).astype(int), 0, N_SURVEY_YEARS - 1)


def _instances(d, q, years_used, t_survey0, lead):
    """(source index, first-detection MJD, weight, source survey year) of the objects used for this query.

    fold_years=False: the simulated objects at their simulated dates.
    fold_years=True : every simulated object first detected in one of `years_used` is also placed at
    t_fd + m * 365.25 d for every integer m that lands in [T0 - lead, T1] (lead: longest follow-up window after first
    detection). RA/Dec, light curve and the Sun-object
    geometry are unchanged by a whole-year shift; the Rubin strategy is NOT (rolling stripes, survey changes), so the
    result is the window as it would be if every year were like the average of `years_used`. Each copy is weighted by
    1 / len(years_used), which preserves the expected rate of those years."""
    t_fd, w = d["t_fd"], d["weight"]
    n = len(t_fd)
    yr = survey_year(t_fd, t_survey0)
    if not q.fold_years:
        return np.arange(n), t_fd, w, yr
    keep = np.isin(yr, years_used)
    lo, hi = q.mjd_start - lead, q.mjd_end
    m0 = np.ceil((lo - t_fd) / YEAR).astype(int)
    m1 = np.floor((hi - t_fd) / YEAR).astype(int)
    cnt = np.where(keep, np.maximum(m1 - m0 + 1, 0), 0)
    src = np.repeat(np.arange(n), cnt)
    m = np.repeat(m0, cnt) + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    return src, t_fd[src] + m * YEAR, w[src] / len(years_used), yr[src]


MAX_SKY_FOLLOWABLE = 6000      # per class and survey
MAX_SKY_BACKGROUND = 600


def _sky_table(parts):
    """Column-wise table of sky points (rounded to keep the JSON small); 'sampled' < 1 when a cap applied."""
    if not parts:
        return {"n": 0}
    cat = lambda k: np.concatenate([np.asarray(p[k]) for p in parts]) if parts else np.zeros(0)  # noqa: E731
    n = [len(p["idx"]) for p in parts]
    return {
        "n": int(sum(n)),
        "cls": sum(([p["cls"]] * m for p, m in zip(parts, n)), []),
        "survey": sum(([p["survey"]] * m for p, m in zip(parts, n)), []),
        "idx": cat("idx").astype(int).tolist(), "shift": np.round(cat("shift"), 5).tolist(),
        "ra": np.round(cat("ra"), 4).tolist(), "dec": np.round(cat("dec"), 4).tolist(),
        "z": np.round(cat("z"), 4).tolist(),
        "w": np.round(cat("w"), 4).tolist(), "hours": np.round(cat("hours"), 2).tolist(),
        "first": [None if not np.isfinite(x) else round(float(x), 3) for x in cat("first")],
        "sampled": {f"{p['cls']}_{p['survey']}": p["frac"] for p in parts},
    }


def _intervals(t, mask, step_days):
    """Contiguous True runs of mask on grid t -> [[start, end], ...] (end = last step + one step)."""
    if not mask.any():
        return []
    m = np.concatenate([[False], mask, [False]]).astype(int)
    d = np.diff(m)
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1
    return [[float(t[a]), float(t[b] + step_days)] for a, b in zip(s, e)]


@lru_cache(maxsize=8)
def _run_tables(sweep: str, run: str):
    """phot_df and model_dense of one ALCeS run (cached: clicks often hit the same run)."""
    import pandas as pd
    from .build import SWEEPS
    rd = SWEEPS / sweep / "runs" / run
    ph = pd.read_parquet(rd / "phot_df.parquet", columns=["SNID", "MJD", "FLT", "FLUXCAL", "FLUXCALERR", "PHOTFLAG"])
    dn = pd.read_parquet(rd / "model_dense.parquet", columns=["SNID", "MJD", "FLT", "FLUX_MODEL"])
    return ph.astype({"SNID": str}), dn.astype({"SNID": str})


@lru_cache(maxsize=4)
def _train_phot(case: str):
    """Rubin photometry of a training set's selected objects (flat-log-z sets), indexed by (run, SNID)."""
    import pandas as pd
    ph = pd.read_parquet(TRAINSETS / "transients" / case / "selected_phot.parquet",
                         columns=["run", "SNID", "MJD", "FLT", "FLUXCAL", "FLUXCALERR", "PHOTFLAG"])
    return ph.astype({"SNID": str}).set_index(["run", "SNID"]).sort_index()


def _phot_table(p, shift, t_fd, zp=31.4):
    phot = {}
    for b, g in p.groupby("FLT"):
        det = (g.PHOTFLAG.astype(int) & 4096) > 0
        fl, er = g.FLUXCAL.to_numpy(), g.FLUXCALERR.to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            mag = np.where(fl > 0, zp - 2.5 * np.log10(fl), np.nan)
            merr = 1.0857 * er / np.abs(fl)
            lim5 = zp - 2.5 * np.log10(5 * er)
        t = g.MJD.to_numpy() + shift - t_fd
        phot[b] = {"t": np.round(t, 4).tolist(), "det": det.tolist(),
                   "mag": [None if not np.isfinite(x) else round(float(x), 3) for x in mag],
                   "err": [None if not np.isfinite(x) else round(float(x), 3) for x in merr],
                   "lim5": [None if not np.isfinite(x) else round(float(x), 3) for x in lim5]}
    return phot


def object_detail(q: Query, cls: str, survey: str, idx: int, shift: float = 0.0, store: Path = STORE,
                  pad_before: float = 30.0, pad_after: float = 30.0):
    """Everything the GUI shows for one simulated event: model light curve, Rubin photometry and visibility windows.

    `shift` (days, a whole number of years when folding) moves the event in time; the Rubin photometry is shifted
    with it, i.e. it shows the cadence of the year the event was actually simulated in."""
    cat = catalog(str(store))
    d = load(cls, survey, str(store))
    if not 0 <= idx < len(d["ra"]):
        raise ValueError("object index out of range")
    bands = cat["bands"]
    k0_grid, n_days = grid_spec(cat)
    zp = 31.4
    ra, dec = float(d["ra"][idx]), float(d["dec"][idx])
    t_fd = float(d["t_fd"][idx]) + shift
    wend = float(window_end(d, q, n_days)[idx])
    out = {"cls": cls, "survey": survey, "idx": idx, "shift_days": shift, "ra": ra, "dec": dec,
           "z": float(d["z"][idx]), "t_fd": t_fd, "t_peak": float(d["t_peak"][idx]) + shift,
           "window": [q.t_min, wend], "weight_10yr": float(d["weight"][idx]), "bands": bands,
           "t_peak_is_max_light": bool(cat.get("k0", 0) > 0)}
    native = "sweep" in d                     # native-rate store: full dense curves on disk
    training = "case" in d                    # flat-log-z training store: daily grid + selected_phot
    if native:
        out.update(sweep=str(d["sweep"][idx]), run=str(d["run"][idx]), snid=str(d["snid"][idx]))
    elif training:
        out.update(case=str(d["case"][idx]), run=str(d["run"][idx]), snid=str(d["snid"][idx]))
    # --- light curves (relative to the first detection); the store's daily model mags are the fallback
    model, phot = {}, {}
    if training:
        try:
            phot = _phot_table(_train_phot(out["case"]).loc[(out["run"], out["snid"])].reset_index(), shift, t_fd)
        except KeyError:
            phot = {}
    if native:
        ph, dn = _run_tables(out["sweep"], out["run"])
        m = dn[dn.SNID == out["snid"]]
        for b, g in m.groupby("FLT"):
            g = g.sort_values("MJD")
            f = g.FLUX_MODEL.to_numpy()
            ok = f > 0
            model[b] = {"t": np.round(g.MJD.to_numpy()[ok] + shift - t_fd, 3).tolist(),
                        "mag": np.round(zp - 2.5 * np.log10(f[ok]), 3).tolist()}
        p = ph[ph.SNID == out["snid"]]
        for b, g in p.groupby("FLT"):
            det = (g.PHOTFLAG.astype(int) & 4096) > 0
            fl, er = g.FLUXCAL.to_numpy(), g.FLUXCALERR.to_numpy()
            with np.errstate(divide="ignore", invalid="ignore"):
                mag = np.where(fl > 0, zp - 2.5 * np.log10(fl), np.nan)
                merr = 1.0857 * er / np.abs(fl)
                lim5 = zp - 2.5 * np.log10(5 * er)
            t = g.MJD.to_numpy() + shift - t_fd
            phot[b] = {"t": np.round(t, 4).tolist(), "det": det.tolist(),
                       "mag": [None if not np.isfinite(x) else round(float(x), 3) for x in mag],
                       "err": [None if not np.isfinite(x) else round(float(x), 3) for x in merr],
                       "lim5": [None if not np.isfinite(x) else round(float(x), 3) for x in lim5]}
    if not native:
        k = np.arange(-k0_grid, n_days + 1)
        for i, b in enumerate(bands):
            mm = d["mag"][idx, i].astype(float)
            ok = np.isfinite(mm)
            model[b] = {"t": k[ok].tolist(), "mag": np.round(mm[ok], 3).tolist()}
    out["model"], out["phot"] = model, phot
    # --- visibility on the query grid, from t_fd - pad_before to the window end + pad_after
    step = q.step_min / 1440.0
    # same phase as the counting grid (which starts at mjd_start), so the followable hours agree exactly
    t0 = q.mjd_start + np.floor((t_fd - pad_before - q.mjd_start) / step) * step
    t1 = t_fd + max(wend, 0.0) + pad_after
    grid = astro.time_grid(t0, t1, q.step_min)
    dark = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    alt = astro.altitude(ra, dec, astro.local_sidereal_deg(grid, q.lon), q.lat)
    x = astro.airmass_from_alt(alt)
    observable = dark & (x <= q.airmass_max)
    # the same model magnitudes as the counting engine (store grid, linear interpolation)
    b = bands.index(q.band)
    dt = grid - t_fd
    mag_q = interp_mag(d["mag"][:, b, :], np.full(len(dt), idx), dt, k0_grid, n_days)
    check_mode(q)
    lim = np.full(len(grid), np.inf)
    if observable.any():
        sel = np.flatnonzero(observable)
        moon = etc.moon_state(grid[sel], q.lat, q.lon) if q.mode == "etc" else None
        lim[sel] = limit_at(q, np.full(len(sel), ra), np.full(len(sel), dec), x[sel], moon, alt=alt[sel])
    followable = observable & (dt >= q.t_min) & (dt <= wend) & (mag_q <= lim)
    # limiting magnitude at the event's position per night: the deepest value while observable (dark, airmass cut)
    lim_t, lim_m = [], []
    if observable.any():
        sel = np.flatnonzero(observable)
        nid = np.floor(grid[sel] + q.lon / 360.0 - 0.5)
        for nn in np.unique(nid):
            ii = sel[nid == nn]
            k = ii[np.argmax(lim[ii])]
            lim_t.append(round(float(grid[k] - t_fd), 4))
            lim_m.append(round(float(lim[k]), 3))
    out["limit_nightly"] = {"t": lim_t, "mag": lim_m}
    out["observable"] = [[a - t_fd, e - t_fd] for a, e in _intervals(grid, observable, step)]
    out["followable"] = [[a - t_fd, e - t_fd] for a, e in _intervals(grid, followable, step)]
    out["followable_hours"] = float(followable.sum() * q.step_min / 60.0)
    out["query"] = query_summary(q)
    out["mag_limit_best"] = best_limit(q)
    # Moon phase at local midnight of every night of the light-curve span (illuminated fraction, Moon altitude)
    n0 = np.floor(t0 + q.lon / 360.0 - 0.5)
    midn = np.arange(n0, np.floor(t1 + q.lon / 360.0 - 0.5) + 1) + 1.0 - q.lon / 360.0
    mra, _, malt, fli = etc.moon_state(midn, q.lat, q.lon)
    sra, _ = astro.sun_radec(midn)
    out["moon"] = {"t": np.round(midn - t_fd, 3).tolist(), "fli": np.round(fli, 3).tolist(),
                   "alt": np.round(malt, 1).tolist(),
                   # elongation east of the Sun (RA difference): 0 new, 90 first quarter, 180 full, 270 last quarter
                   "elong": np.round((mra - sra) % 360.0, 1).tolist()}
    return out


def _moon_night(grid, q, ra, dec):
    """Moon through one night: airmass (None below the horizon), altitude, illuminated fraction, distance to the
    event [deg]."""
    mra, mdec, malt, fli = etc.moon_state(grid, q.lat, q.lon)
    mx = astro.airmass_from_alt(malt)
    fin = lambda a: [None if not np.isfinite(v) else round(float(v), 3) for v in a]  # noqa: E731
    sep = etc.separation_deg(ra, dec, mra, mdec)
    return {"airmass": fin(np.where(malt > 0, mx, np.nan)), "alt": np.round(malt, 2).tolist(),
            "fli": float(np.round(np.mean(fli), 3)), "sep_deg": float(np.round(np.mean(sep), 1))}


def query_summary(q):
    s = {"band": q.band, "mag_lim": q.mag_lim, "airmass_max": q.airmass_max, "t_min": q.t_min, "t_max": q.t_max,
         "sun_alt": q.sun_alt, "mode": q.mode}
    if q.mode == "etc":
        s.update(instrument=q.instrument, instrument_name=etc.INSTRUMENTS[q.instrument].name,
                 snr_target=q.snr_target, t_exp_total=q.t_exp_total, seeing=q.seeing, binning=q.binning,
                 sky_model=q.sky_model)
    return s


def night_detail(q: Query, cls: str, survey: str, idx: int, shift: float, mjd: float, store: Path = STORE,
                 step_min: float = 5.0):
    """One event during one local night (local noon to noon around `mjd`): model magnitudes in every band, airmass,
    Sun altitude, and when it meets all follow-up limits."""
    cat = catalog(str(store))
    d = load(cls, survey, str(store))
    bands = cat["bands"]
    k0_grid, n_days = grid_spec(cat)
    t_fd = float(d["t_fd"][idx]) + shift
    wend = float(window_end(d, q, n_days)[idx])
    night = np.floor(mjd + q.lon / 360.0 - 0.5)
    noon = night + 0.5 - q.lon / 360.0                       # MJD of the local noon that starts the night
    grid = astro.time_grid(noon, noon + 1.0, step_min)
    sun = astro.sun_altitude(grid, q.lat, q.lon)
    keep = sun < 0.0                                          # sunset to sunrise
    if not keep.any():
        raise ValueError("the Sun does not set at this site on that date")
    grid, sun = grid[keep], sun[keep]
    alt = astro.altitude(float(d["ra"][idx]), float(d["dec"][idx]), astro.local_sidereal_deg(grid, q.lon), q.lat)
    x = astro.airmass_from_alt(alt)
    dt = grid - t_fd
    mags = {bb: interp_mag(d["mag"][:, i, :], np.full(len(dt), idx), dt, k0_grid, n_days)
            for i, bb in enumerate(bands)}
    dark = sun < q.sun_alt
    in_window = (dt >= q.t_min) & (dt <= wend)
    check_mode(q)
    ra, dec = float(d["ra"][idx]), float(d["dec"][idx])
    up = alt > 0
    lim = np.full(len(grid), np.nan)
    skym = np.full(len(grid), np.nan)
    if up.any():
        if q.mode == "etc":
            moon = etc.moon_state(grid[up], q.lat, q.lon)
            inst = etc.INSTRUMENTS[q.instrument]
            skym[up] = etc.sky(inst, q.sky_model, q.band, ra, dec, alt[up], x[up], moon)
        lim[up] = limit_at(q, np.full(up.sum(), ra), np.full(up.sum(), dec), x[up],
                           moon if q.mode == "etc" else None, alt=alt[up])
    followable = dark & (x <= q.airmass_max) & in_window & (mags[q.band] <= np.where(up, lim, -np.inf))
    step = step_min / 1440.0
    fin = lambda a: [None if not np.isfinite(v) else round(float(v), 3) for v in a]  # noqa: E731
    return {"mjd": np.round(grid, 6).tolist(), "days_since_fd": np.round(dt, 4).tolist(),
            "sun_alt": np.round(sun, 2).tolist(), "airmass": fin(np.where(up, x, np.nan)),
            "alt": np.round(alt, 2).tolist(), "mag": {bb: fin(m) for bb, m in mags.items()},
            "mag_limit": fin(lim), "sky_mag": fin(skym),
            "moon": _moon_night(grid, q, float(d["ra"][idx]), float(d["dec"][idx])),
            "dark": _intervals(grid, dark, step), "followable": _intervals(grid, followable, step),
            "followable_hours": float(followable.sum() * step_min / 60.0), "in_window": bool(in_window.any()),
            "night_noon_mjd": float(noon), "query": query_summary(q)}


def _hist(x, w, bins):
    h = np.histogram(x, bins=bins, weights=w)[0]
    e = np.sqrt(np.histogram(x, bins=bins, weights=w ** 2)[0])
    return h, e


def run(q: Query, store: Path = STORE):
    cat = catalog(str(store))
    bands = cat["bands"]
    k0_grid, n_days = grid_spec(cat)
    if q.band not in bands:
        raise ValueError(f"band must be one of {bands}")
    if not (0 <= q.t_min < n_days and 0 < q.t_max <= n_days):
        raise ValueError(f"need 0 <= t_min < {n_days} d and 0 < t_max <= {n_days} d")
    if q.mjd_end <= q.mjd_start:
        raise ValueError("mjd_end must be after mjd_start")
    check_mode(q)
    mlim_best = best_limit(q)
    span = q.mjd_end - q.mjd_start
    # longest follow-up window after first detection among the requested classes (maximum light + t_max)
    lead = 0.0
    for name in q.classes:
        for survey in q.surveys:
            if f"{name}_{survey}" in cat["entries"]:
                we = window_end(load(name, survey, str(store)), q, n_days)
                lead = max(lead, float(np.max(we)) if len(we) else 0.0)
    lead = max(lead, q.t_max)
    step = max(q.step_min, 1.0)
    # keep the grid manageable for long windows
    step = max(step, (span + lead) * 1440.0 / 400_000)
    b = bands.index(q.band)
    t_survey0 = min(e["t_fd_range"][0] for e in cat["entries"].values())
    years_used = sorted({int(y) for y in (q.fold_year_list if q.fold_year_list is not None
                                           else range(N_SURVEY_YEARS))})
    if q.fold_years and (not years_used or not all(0 <= y < N_SURVEY_YEARS for y in years_used)):
        raise ValueError(f"fold_year_list must hold survey years 0..{N_SURVEY_YEARS - 1}")

    grid = astro.time_grid(q.mjd_start, q.mjd_end + lead, step)
    night = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    tn = grid[night]
    lst = astro.local_sidereal_deg(tn, q.lon) if len(tn) else np.zeros(0)
    # ETC mode: Moon position, altitude and phase at every night step (sky brightness per pair)
    moon_tn = etc.moon_state(tn, q.lat, q.lon) if (q.mode == "etc" and len(tn)) else None
    night_id = np.floor(tn + q.lon / 360.0 - 0.5).astype(np.int64)     # changes at local noon
    in_win = tn <= q.mjd_end
    phi = np.radians(q.lat)
    # min zenith distance |dec - lat| must allow airmass <= airmass_max (plane-parallel is fine for a pre-cut)
    zmax_deg = np.degrees(np.arccos(1.0 / q.airmass_max)) + 0.5

    # followable objects have >= 1 step; log bins from one step to the longest possible (12 h per night)
    wlen = max(lead - q.t_min, 1.0)
    hours_bins = np.geomspace(0.999 * step / 60.0, max((wlen + 1) * 12.0, 1.0), 25)
    delay_bins = np.linspace(q.t_min, q.t_min + wlen, 31)
    nights_bins = np.arange(0, int(np.ceil(wlen)) + 3) - 0.5

    ts_total = np.zeros(len(tn))
    per_class, ts_class, night_class = [], {}, {}
    sky = {"followable": [], "detected": []}
    draws = []
    rng = np.random.default_rng(12345)
    u_nights = np.unique(night_id[in_win]) if len(tn) else np.zeros(0, int)

    for name in q.classes:
        ts = np.zeros(len(tn))
        objs = []   # per-object arrays for t_fd in [T0, T1]
        n_sim_det = n_inst_det = 0
        w_det = w2_det = 0.0
        night_w = {}
        for survey in q.surveys:
            key = f"{name}_{survey}"
            if key not in cat["entries"]:
                continue
            d = load(name, survey, str(store))
            # instances: the simulated objects themselves, or (fold_years) copies shifted by whole years
            src, t_fd, w, yr = _instances(d, q, years_used, t_survey0, lead)
            ra, dec = d["ra"][src], d["dec"][src]
            wend = window_end(d, q, n_days)[src]          # window end relative to t_fd, per instance
            in_range = (t_fd >= q.mjd_start) & (t_fd <= q.mjd_end)
            n_sim_det += int(len(np.unique(src[in_range])))
            n_inst_det += int(in_range.sum())
            w_det += float(w[in_range].sum())
            w2_det += float((w[in_range] ** 2).sum())
            cand = (t_fd + wend >= q.mjd_start) & (t_fd <= q.mjd_end) & (wend >= q.t_min)
            cand &= np.abs(dec - q.lat) <= zmax_deg
            magb = d["mag"][:, b, :]
            # pre-cut: brightest model point from t_fd + t_min to the end of the grid (window ends earlier)
            magmin = np.min(magb[:, k0_grid + int(np.floor(q.t_min)):].astype(np.float32), axis=1)
            cand &= magmin[src] <= mlim_best
            idx = np.flatnonzero(cand)
            # every object in range gets a stats row (zeros if never followable)
            hours = np.zeros(len(t_fd))
            first = np.full(len(t_fd), np.nan)
            nnights = np.zeros(len(t_fd))
            if len(idx) and len(tn):
                lo = np.searchsorted(tn, t_fd[idx] + q.t_min)
                hi = np.searchsorted(tn, t_fd[idx] + wend[idx], side="right")
                cnt = np.maximum(hi - lo, 0)
                # chunk the objects so that the (object, time) pairs stay bounded
                csum = np.cumsum(cnt)
                starts = np.searchsorted(csum, np.arange(0, csum[-1] if len(csum) else 0, MAX_PAIRS), side="right")
                bounds = list(starts) + [len(idx)]
                for c0, c1 in zip(bounds[:-1], bounds[1:]):
                    if c1 <= c0:
                        continue
                    sl = slice(c0, c1)
                    o_loc = np.repeat(np.arange(c0, c1), cnt[sl])
                    if not len(o_loc):
                        continue
                    j = np.concatenate([np.arange(a, z) for a, z in zip(lo[sl], hi[sl])])
                    o = idx[o_loc]
                    dt = tn[j] - t_fd[o]
                    m = interp_mag(magb, src[o], dt, k0_grid, n_days)
                    ok = m <= mlim_best                      # exact in maglim mode, a pre-cut in ETC mode
                    o, j, dt, m = o[ok], j[ok], dt[ok], m[ok]
                    dec_r = np.radians(dec[o])
                    ha = np.radians(lst[j] - ra[o])
                    sin_alt = np.sin(phi) * np.sin(dec_r) + np.cos(phi) * np.cos(dec_r) * np.cos(ha)
                    alt = np.degrees(np.arcsin(np.clip(sin_alt, -1, 1)))
                    x = 1.0 / np.sin(np.radians(alt + 244.0 / (165.0 + 47.0 * np.abs(alt) ** 1.1)))
                    ok = (alt > 0) & (x <= q.airmass_max)
                    o, j, dt, m, x, alt = o[ok], j[ok], dt[ok], m[ok], x[ok], alt[ok]
                    if q.mode == "etc" and len(o):
                        # SNR >= snr_target within t_exp_total for this pair's airmass and sky (Moon)
                        lim = limit_at(q, ra[o], dec[o], x, tuple(v[j] for v in moon_tn), alt=alt)
                        ok = m <= lim
                        o, j, dt = o[ok], j[ok], dt[ok]
                    if not len(o):
                        continue
                    ts += np.bincount(j, weights=w[o], minlength=len(tn))
                    hours += np.bincount(o, minlength=len(t_fd)) * step / 60.0
                    np.fmin.at(first, o, dt)
                    on = np.unique(np.stack([o, night_id[j]]), axis=1)
                    nnights += np.bincount(on[0], minlength=len(t_fd))
                    # distinct objects per night (only nights inside the window)
                    sel_n = np.isin(on[1], u_nights)
                    if sel_n.any():
                        nn, inv = np.unique(on[1][sel_n], return_inverse=True)
                        ws = np.bincount(inv, weights=w[on[0][sel_n]])
                        for a, v in zip(nn, ws):
                            night_w[int(a)] = night_w.get(int(a), 0.0) + float(v)
            r = in_range
            # sky map: every followable event, plus a sample of detected-but-not-followable ones for context
            shift = t_fd - d["t_fd"][src]
            for kind, sel_k, cap in (("followable", r & (hours > 0), MAX_SKY_FOLLOWABLE),
                                     ("detected", r & (hours == 0), MAX_SKY_BACKGROUND)):
                ii = np.flatnonzero(sel_k)
                if len(ii) > cap:
                    ii = np.sort(rng.choice(ii, cap, replace=False))
                sky[kind].append({"cls": name, "survey": survey, "idx": src[ii], "shift": shift[ii],
                                  "ra": ra[ii], "dec": dec[ii], "z": d["z"][src[ii]],
                                  "w": w[ii], "hours": hours[ii], "first": first[ii],
                                  "frac": len(ii) / max(int(sel_k.sum()), 1)})
            # source id unique across surveys (copies of one simulated object are fully correlated)
            objs.append(dict(w=w[r], hours=hours[r], first=first[r], nights=nnights[r],
                             src=src[r] + (len(objs) << 32), yr=yr[r]))
            # ALCeS reuses its random seeds across classes: object k of a run has the same (RA, Dec, t0) in every
            # class. Events sharing a draw (and the year-shifted copies of one object) fluctuate together, so
            # errors of sums over classes group them by (survey, RA, Dec) before squaring.
            draws.append(dict(key=np.stack([np.full(int(r.sum()), q.surveys.index(survey)),
                                            np.round(ra[r] * 1e6).astype(np.int64),
                                            np.round(dec[r] * 1e6).astype(np.int64)], axis=1),
                              w=w[r], fu=hours[r] > 0, yr=yr[r]))
        if not objs:
            continue
        o = {k: np.concatenate([x[k] for x in objs]) for k in objs[0]}
        fu = o["hours"] > 0

        def src_err(sel):
            """sqrt(sum over simulated objects of (sum of their copies' weights)^2)."""
            if not sel.any():
                return 0.0
            _, inv = np.unique(o["src"][sel], return_inverse=True)
            return float(np.sqrt((np.bincount(inv, weights=o["w"][sel]) ** 2).sum()))
        hh, he = _hist(o["hours"][fu], o["w"][fu], hours_bins)
        dh, de = _hist(o["first"][fu], o["w"][fu], delay_bins)
        nh, ne = _hist(o["nights"][fu], o["w"][fu], nights_bins)
        wf = o["w"][fu]

        def nsim_hist(x, bins):
            """distinct simulated objects per bin (folded copies of one object count once per bin)."""
            ib = np.digitize(x, bins) - 1
            ok = (ib >= 0) & (ib < len(bins) - 1)
            pairs = np.unique(np.stack([ib[ok], o["src"][fu][ok]]), axis=1) if ok.any() else np.zeros((2, 0), int)
            return np.bincount(pairs[0], minlength=len(bins) - 1)[: len(bins) - 1].astype(int).tolist()

        def wq(x, p):
            if not fu.any():
                return None
            s = np.argsort(x)
            c = np.cumsum(wf[s]) / wf.sum()
            return float(x[s][np.searchsorted(c, p)])
        per_class.append({
            "class": name, "n_sim_detected": n_sim_det, "n_sim_followable": int(len(np.unique(o["src"][fu]))),
            "n_instances_detected": n_inst_det, "n_instances_followable": int(fu.sum()),
            "N_detected": w_det, "N_detected_err": src_err(np.ones(len(fu), bool)),
            "N_followable": float(wf.sum()), "N_followable_err": src_err(fu),
            "frac_followable": float(wf.sum() / w_det) if w_det > 0 else None,
            "median_hours": wq(o["hours"][fu], 0.5), "median_nights": wq(o["nights"][fu], 0.5),
            "median_delay_days": wq(o["first"][fu], 0.5),
            "hist_hours": hh.tolist(), "hist_hours_err": he.tolist(),
            "hist_delay": dh.tolist(), "hist_delay_err": de.tolist(),
            "hist_nights": nh.tolist(), "hist_nights_err": ne.tolist(),
            "hist_hours_nsim": nsim_hist(o["hours"][fu], hours_bins),
            "hist_delay_nsim": nsim_hist(o["first"][fu], delay_bins),
            "hist_nights_nsim": nsim_hist(o["nights"][fu], nights_bins),
        })
        if q.fold_years:
            # the window's numbers as estimated from each survey year alone (copy weights x number of years used):
            # years that disagree beyond their errors are not equivalent for these cuts
            k = len(years_used)
            by = {"detected": [], "detected_err": [], "followable": [], "followable_err": [], "n_sim_followable": []}
            for y in years_used:
                sy = o["yr"] == y
                by["detected"].append(k * float(o["w"][sy].sum()))
                by["detected_err"].append(k * src_err(sy))
                by["followable"].append(k * float(o["w"][sy & fu].sum()))
                by["followable_err"].append(k * src_err(sy & fu))
                by["n_sim_followable"].append(int(len(np.unique(o["src"][sy & fu]))))
            per_class[-1]["by_year"] = by
        ts_class[name] = ts
        night_class[name] = night_w
        ts_total += ts

    # instantaneous counts on night steps inside [T0, T1]; thin to <= 6000 points for plotting
    sel = np.flatnonzero(in_win)
    thin = sel[:: max(1, len(sel) // 6000)] if len(sel) else sel
    nights = [int(n) for n in u_nights]
    night_series = {c: [night_class[c].get(n, 0.0) for n in nights] for c in night_class}
    totals = {k: float(sum(pc[k] for pc in per_class)) for k in ("N_detected", "N_followable")}
    totals.update({k: int(sum(pc[k] for pc in per_class)) for k in ("n_sim_detected", "n_sim_followable")})
    if draws:
        dk = np.concatenate([x["key"] for x in draws])
        dw = np.concatenate([x["w"] for x in draws])
        dfu = np.concatenate([x["fu"] for x in draws])
        dyr = np.concatenate([x["yr"] for x in draws])
    else:
        dk, dw, dfu, dyr = np.zeros((0, 3), np.int64), np.zeros(0), np.zeros(0, bool), np.zeros(0, int)

    def draw_err(sel, scale=1.0):
        """error of a sum over classes: weights of events sharing a simulated draw are added before squaring."""
        if not sel.any():
            return 0.0
        _, inv = np.unique(dk[sel], axis=0, return_inverse=True)
        return float(scale * np.sqrt((np.bincount(inv.ravel(), weights=dw[sel]) ** 2).sum()))
    totals["N_detected_err"] = draw_err(np.ones(len(dw), bool))
    totals["N_followable_err"] = draw_err(dfu)
    totals["n_shared_draws_followable"] = int(len(np.unique(dk[dfu], axis=0))) if dfu.any() else 0
    n_nights = len(nights)
    dark_hours = float(in_win.sum() * step / 60.0)
    by_year = None
    if q.fold_years and per_class:
        by_year = {"years": years_used, "survey_start_mjd": t_survey0}
        for key in ("detected", "followable", "n_sim_followable"):
            by_year[key] = np.sum([pc["by_year"][key] for pc in per_class], axis=0).tolist()
        k_years = len(years_used)
        by_year["detected_err"] = [draw_err(dyr == y, k_years) for y in years_used]
        by_year["followable_err"] = [draw_err((dyr == y) & dfu, k_years) for y in years_used]
        f, e = np.array(by_year["followable"]), np.array(by_year["followable_err"])
        # chi^2 of the per-year estimates around their weighted mean: >> dof means the years differ
        ok = e > 0
        if ok.sum() >= 2:
            mean = np.sum(f[ok] / e[ok] ** 2) / np.sum(1 / e[ok] ** 2)
            by_year["chi2"] = float(np.sum(((f[ok] - mean) / e[ok]) ** 2))
            by_year["dof"] = int(ok.sum() - 1)
    return {
        "query": q.__dict__, "query_summary": query_summary(q), "mag_limit_best": mlim_best,
        "step_min_used": step, "by_year": by_year,
        "sky": {k: _sky_table(v) for k, v in sky.items()},
        "airmass_dec_band": [max(-90.0, q.lat - (zmax_deg - 0.5)), min(90.0, q.lat + (zmax_deg - 0.5))],
        "n_nights": n_nights, "dark_hours": dark_hours, "window_days": span,
        "totals": totals,
        "per_night_mean": (sum(sum(v) for v in night_series.values()) / n_nights) if n_nights else 0.0,
        "classes": per_class,
        "bins": {"hours": hours_bins.tolist(), "delay": delay_bins.tolist(), "nights": nights_bins.tolist()},
        "timeseries": {"mjd": tn[thin].tolist(), "total": ts_total[thin].tolist(),
                       "by_class": {c: v[thin].tolist() for c, v in ts_class.items()}},
        # night label = MJD of the local noon that starts the night
        "nightly": {"night_mjd": [n + 0.5 - q.lon / 360.0 for n in nights], "by_class": night_series},
    }
