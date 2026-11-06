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


def test_sky_points_and_object_detail_agree(tmp_path):
    """Every followable event is on the sky map, and its detail view gives the same followable hours."""
    _store(tmp_path)
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["X"], surveys=["WFD"], band="r", mag_lim=19.5, airmass_max=1.8, t_min=1.0, t_max=25.0,
                     mjd_start=61000, mjd_end=61060, step_min=10)
    r = engine.run(q, tmp_path)
    sky = r["sky"]["followable"]
    assert sky["n"] == r["classes"][0]["n_sim_followable"] > 0
    for i in range(sky["n"]):
        o = engine.object_detail(q, "X", "WFD", sky["idx"][i], sky["shift"][i], store=tmp_path)
        assert abs(o["followable_hours"] - sky["hours"][i]) <= 0.005   # sky table rounds to 0.01 h
        assert all(q.t_min - 1e-9 <= a and b <= q.t_max + q.step_min / 1440 + 1e-9 for a, b in o["followable"])


def test_shared_draws_are_correlated(tmp_path):
    """Two classes with the same (RA, Dec, t0) draws: the combined error adds their weights per draw first."""
    d = _store(tmp_path)
    np.savez(tmp_path / "Y_WFD.npz", **{**d, "weight": 3 * d["weight"]})
    cat = json.loads((tmp_path / "catalog.json").read_text())
    cat["entries"]["Y_WFD"] = {**cat["entries"]["X_WFD"], "class": "Y"}
    (tmp_path / "catalog.json").write_text(json.dumps(cat))
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["X", "Y"], surveys=["WFD"], band="r", mag_lim=19.5, airmass_max=1.8, t_max=25.0,
                     mjd_start=61000, mjd_end=61060, step_min=10)
    t = engine.run(q, tmp_path)["totals"]
    assert np.isclose(t["N_detected_err"], np.sqrt(((d["weight"] + 3 * d["weight"]) ** 2).sum()))
    assert t["N_detected_err"] > np.sqrt((d["weight"] ** 2).sum() + ((3 * d["weight"]) ** 2).sum())


def test_fold_years_preserves_rate(tmp_path):
    """Folding: a 1-year window holds one copy of every simulated object of the years used, weighted by
    1/(number of years used); the per-year breakdown reproduces the folded totals."""
    d = _store(tmp_path)          # all first detections fall in survey year 0
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["X"], surveys=["WFD"], band="r", mag_lim=19.5, airmass_max=1.8, t_max=10.0,
                     mjd_start=61500, mjd_end=61500 + 365.25 - 1e-6, step_min=30, fold_years=True,
                     fold_year_list=[0])
    r = engine.run(q, tmp_path)
    c = r["classes"][0]
    assert c["n_instances_detected"] == len(d["t_fd"])
    assert np.isclose(c["N_detected"], d["weight"].sum())
    assert np.isclose(r["by_year"]["detected"][0], c["N_detected"])
    assert np.isclose(r["by_year"]["followable"][0], c["N_followable"])
    # two years used, only year 0 populated: half the rate, and year 1 estimates zero
    q.fold_year_list = [0, 1]
    r = engine.run(q, tmp_path)
    assert np.isclose(r["classes"][0]["N_detected"], d["weight"].sum() / 2)
    assert r["by_year"]["detected"][1] == 0
    q.fold_year_list = [1]
    assert engine.run(q, tmp_path)["classes"][0]["N_detected"] == 0
    # literal dates outside the simulated span see nothing
    q.fold_years = False
    assert engine.run(q, tmp_path)["classes"][0]["N_detected"] == 0


def _store_peak(tmp_path, n=30, seed=5, k0=30, dpk=10.0):
    """Store with a pre-detection offset (k0) and maximum light dpk days after first detection."""
    rng = np.random.default_rng(seed)
    t_fd = rng.uniform(61000, 61040, n)
    k = np.arange(-k0, N_DAYS + 1)
    mag = np.full((n, len(BANDS), len(k)), np.inf, np.float32)
    mag[:, 2, :] = 17.0 + 0.05 * np.abs(k[None, :] - dpk)       # brightest at t_fd + dpk, linear in time
    d = dict(ra=rng.uniform(0, 360, n), dec=rng.uniform(-80, 20, n), z=np.full(n, 0.05), t_peak=t_fd + dpk,
             weight=rng.uniform(0.5, 2, n), t_fd=t_fd, mag=mag.astype(np.float16))
    np.savez(tmp_path / "P_WFD.npz", **d)
    (tmp_path / "catalog.json").write_text(json.dumps({"bands": BANDS, "n_days": N_DAYS, "k0": k0, "entries": {
        "P_WFD": {"class": "P", "survey": "WFD", "n_sim": n, "N_det_10yr": float(d["weight"].sum()),
                  "t_fd_range": [61000, 61040], "survey_years": 2.0, "parts": []}}}))
    return d


def test_window_ends_t_max_after_maximum_light(tmp_path):
    """Follow-up window t_fd + t_min .. t_peak + t_max (store with a pre-detection offset); the object view and the
    night view agree with the counting engine."""
    d = _store_peak(tmp_path)
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["P"], surveys=["WFD"], band="r", mag_lim=18.0, airmass_max=2.0, t_min=2.0, t_max=5.0,
                     mjd_start=61000, mjd_end=61040, step_min=10)
    r = engine.run(q, tmp_path)
    grid = astro.time_grid(q.mjd_start, q.mjd_end + 10 + q.t_max, q.step_min)
    dark = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    x = astro.airmass(d["ra"], d["dec"], astro.local_sidereal_deg(grid, q.lon), q.lat)
    hours = np.zeros(len(d["ra"]))
    for i in range(len(d["ra"])):
        dt = grid - d["t_fd"][i]
        m = 17.0 + 0.05 * np.abs(dt - 10.0)                      # same model (float16 grid: ~0.01 mag)
        win = (dt >= q.t_min) & (dt <= 10.0 + q.t_max)
        hours[i] = (win & dark & (m <= q.mag_lim) & (x[i] <= q.airmass_max)).sum() * q.step_min / 60
    c = r["classes"][0]
    fu = hours > 0
    assert c["n_sim_followable"] == fu.sum() > 0
    assert np.isclose(c["N_followable"], d["weight"][fu].sum())
    sky = r["sky"]["followable"]
    for i in range(sky["n"]):
        j = sky["idx"][i]
        o = engine.object_detail(q, "P", "WFD", j, 0.0, store=tmp_path)
        assert o["window"] == [q.t_min, 10.0 + q.t_max]
        assert abs(o["followable_hours"] - hours[j]) <= 1e-6
        # night views (5-min grid) of the followable nights add up to the object's followable hours
        nights = sorted({float(np.floor(a + o["t_fd"] + q.lon / 360 - 0.5)) for a, _ in o["followable"]})
        tot = sum(engine.night_detail(q, "P", "WFD", j, 0.0, n + 1.0 - q.lon / 360, store=tmp_path)["followable_hours"]
                  for n in nights)
        assert abs(tot - o["followable_hours"]) <= 0.25 * len(nights)


def test_etc_mode_matches_brute_force(tmp_path):
    """ETC mode: followable while the model mag is brighter than the SNR/exposure-time limit of each (event, time)
    pair (airmass, Moon, sky); engine, object view and night view against a direct evaluation."""
    from followup import etc
    d = _store_peak(tmp_path, n=40, seed=11)
    engine.catalog.cache_clear(); engine.load.cache_clear()
    q = engine.Query(classes=["P"], surveys=["WFD"], band="r", airmass_max=2.0, t_min=0.0, t_max=10.0,
                     mjd_start=61000, mjd_end=61040, step_min=10, lat=33.674, lon=51.3188, height=3600,
                     mode="etc", snr_target=10.0, t_exp_total=600.0, seeing=1.15, binning=1)
    r = engine.run(q, tmp_path)
    inst = etc.INSTRUMENTS["INO"]
    grid = astro.time_grid(q.mjd_start, q.mjd_end + 10 + q.t_max, q.step_min)
    dark = astro.night_mask(grid, q.lat, q.lon, q.height, q.sun_alt)
    lst = astro.local_sidereal_deg(grid, q.lon)
    moon = etc.moon_state(grid, q.lat, q.lon)
    hours = np.zeros(len(d["ra"]))
    for i in range(len(d["ra"])):
        dt = grid - d["t_fd"][i]
        m = 17.0 + 0.05 * np.abs(dt - 10.0)
        x = astro.airmass([d["ra"][i]], [d["dec"][i]], lst, q.lat)[0]
        sky = etc.sky_mag(inst, d["ra"][i], d["dec"][i], x, *moon)
        lim = etc.limiting_mag(inst, "r", q.snr_target, q.t_exp_total, x, sky, q.seeing, q.binning)
        win = (dt >= q.t_min) & (dt <= 10.0 + q.t_max)
        hours[i] = (win & dark & (x <= q.airmass_max) & (m <= lim)).sum() * q.step_min / 60
    c = r["classes"][0]
    fu = hours > 0
    assert 0 < fu.sum() < len(fu)                       # the limit actually bites for some events
    assert c["n_sim_followable"] == fu.sum()
    assert np.isclose(c["N_followable"], d["weight"][fu].sum())
    sky_tab = r["sky"]["followable"]
    for i in range(sky_tab["n"]):
        jj = sky_tab["idx"][i]
        o = engine.object_detail(q, "P", "WFD", jj, 0.0, store=tmp_path)
        assert abs(o["followable_hours"] - hours[jj]) <= 1e-6
    # the faintest possible limit is a true upper bound of every per-pair limit
    assert r["mag_limit_best"] >= np.nanmax(lim)
    # magnitude mode is untouched by the new fields
    q2 = engine.Query(**{**q.__dict__, "mode": "maglim", "mag_lim": 18.0})
    assert engine.run(q2, tmp_path)["mag_limit_best"] == 18.0
