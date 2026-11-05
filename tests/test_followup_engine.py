"""followup.engine against a brute-force (object x time) evaluation on a small synthetic store."""
import json

import numpy as np

from followup import astro, engine

BANDS = ["u", "g", "r", "i", "z", "Y"]
N_DAYS = 60


def _store(tmp_path, n=40, seed=3):
    rng = np.random.default_rng(seed)
    t_fd = rng.uniform(61000, 61060, n)
    k = np.arange(N_DAYS + 1)
    peak = rng.uniform(16, 22, n)
    mag = np.full((n, len(BANDS), N_DAYS + 1), np.inf, np.float32)
    # linear decline 0.08 mag/d after first detection, r band; model ends after 40 d for half of them
    mag[:, 2, :] = peak[:, None] + 0.08 * k[None, :]
    mag[: n // 2, 2, 41:] = np.inf
    d = dict(ra=rng.uniform(0, 360, n), dec=rng.uniform(-80, 30, n), z=np.full(n, 0.05), t_peak=t_fd,
             weight=rng.uniform(0.5, 2, n), t_fd=t_fd, mag=mag.astype(np.float16))
    np.savez(tmp_path / "X_WFD.npz", **d)
    (tmp_path / "catalog.json").write_text(json.dumps({"bands": BANDS, "n_days": N_DAYS, "entries": {
        "X_WFD": {"class": "X", "survey": "WFD", "n_sim": n, "N_det_10yr": float(d["weight"].sum()),
                  "t_fd_range": [61000, 61060], "survey_years": 2.0, "parts": []}}}))
    return d


def test_engine_matches_brute_force(tmp_path):
    d = _store(tmp_path)
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["X"], surveys=["WFD"], band="r", mag_lim=19.5, airmass_max=1.8, t_min=1.0, t_max=25.0,
                     mjd_start=61000, mjd_end=61060, step_min=10, fold_years=False)
    r = engine.run(q, tmp_path)
    # brute force
    grid = astro.time_grid(q.mjd_start, q.mjd_end + q.t_max, q.step_min)
    dark = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    x = astro.airmass(d["ra"], d["dec"], astro.local_sidereal_deg(grid, q.lon), q.lat)
    mag = d["mag"][:, 2, :].astype(np.float32)
    hours = np.zeros(len(d["ra"]))
    for i in range(len(d["ra"])):
        dt = grid - d["t_fd"][i]
        win = (dt >= q.t_min) & (dt <= q.t_max)
        k = np.clip(dt, 0, N_DAYS - 1e-6).astype(int)
        f = np.clip(dt, 0, N_DAYS) - k
        m = mag[i, k] + f * (mag[i, np.minimum(k + 1, N_DAYS)] - mag[i, k])
        m = np.where(np.isfinite(mag[i, k]) & np.isfinite(mag[i, np.minimum(k + 1, N_DAYS)]), m, np.inf)
        hours[i] = (win & dark & (m <= q.mag_lim) & (x[i] <= q.airmass_max)).sum() * q.step_min / 60
    c = r["classes"][0]
    fu = hours > 0
    assert c["n_sim_followable"] == fu.sum()
    assert np.isclose(c["N_followable"], d["weight"][fu].sum())
    assert np.isclose(c["N_detected"], d["weight"].sum())
    assert np.isclose(np.sum(c["hist_hours"]), d["weight"][fu].sum())
    assert sum(c["hist_hours_nsim"]) == sum(c["hist_nights_nsim"]) == c["n_sim_followable"] == fu.sum()
    # weighted mean hours via histogram mass is coarse; compare total weighted hours via the time series instead
    tot_engine = np.sum(r["timeseries"]["total"]) * q.step_min / 60   # only steps inside [T0, T1], thinned = none here
    ts_mask = grid[dark] <= q.mjd_end
    assert len(r["timeseries"]["mjd"]) == ts_mask.sum()
    tot_brute = 0.0
    for i in range(len(d["ra"])):
        dt = grid - d["t_fd"][i]
        k = np.clip(dt, 0, N_DAYS - 1e-6).astype(int)
        f = np.clip(dt, 0, N_DAYS) - k
        m = mag[i, k] + f * (mag[i, np.minimum(k + 1, N_DAYS)] - mag[i, k])
        ok = (dt >= q.t_min) & (dt <= q.t_max) & dark & (m <= q.mag_lim) & (x[i] <= q.airmass_max) & (grid <= q.mjd_end)
        tot_brute += d["weight"][i] * ok.sum() * q.step_min / 60
    assert np.isclose(tot_engine, tot_brute, rtol=1e-6)


def test_fold_years_preserves_rate(tmp_path):
    """Folding: a 1-year window holds one copy of every simulated object, weighted by 1/(survey years)."""
    d = _store(tmp_path)
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["X"], surveys=["WFD"], band="r", mag_lim=19.5, airmass_max=1.8, t_max=10.0,
                     mjd_start=61500, mjd_end=61500 + 365.25 - 1e-6, step_min=30, fold_years=True)
    c = engine.run(q, tmp_path)["classes"][0]
    assert c["n_instances_detected"] == len(d["t_fd"])
    assert np.isclose(c["N_detected"], d["weight"].sum() / 2.0)
    # literal dates outside the simulated span see nothing
    q.fold_years = False
    assert engine.run(q, tmp_path)["classes"][0]["N_detected"] == 0
