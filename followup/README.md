# Follow-up potential of Rubin transients (ALCeS native-rate simulations)

How many transients detected by Rubin can a ground site follow up? You choose a site, a band and model-magnitude limit,
a maximum airmass, a window of days since the first Rubin detection, a date range and a time step. The tool returns
the expected number of real events that are followable, nightly counts, and distributions of how long each event
stays followable.

It uses **only native-rate ALCeS sweeps** (realistic SNANA class rates). It never uses the flat-log z training-mode
sets, whose weights are not population estimates.

## Run

```bash
python -m followup.build            # once (~10 min, 6 processes): ~/data/alces_followup, 1.05 GB
python -m followup.server           # http://127.0.0.1:8790/   (--port, --host, --store)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_followup_*.py
```

- Python: `~/.venvs/main` (numpy, pandas, pyarrow, fastapi, uvicorn, plotly). `ALCES_TOOLS` points at
  `LSST_sim_lcs/tools` (for `expected_counts.py`).
- The GUI serves plotly.js from the plotly Python package. Leaflet and the OpenStreetMap tiles need network access.

API: `GET /api/meta` (classes, surveys, bands, simulated date span, site presets) and `POST /api/run` with the
fields of `engine.Query` (`lat, lon, height, classes, surveys, band, mag_lim, airmass_max, t_min, t_max,
mjd_start, mjd_end, step_min, sun_alt, fold_years`). Python: `followup.engine.run(Query(...))`.

## Method

1. **Store** (`build.py`). For each class and survey, the finished runs of
   `~/data/alces_lcl/sweep_runs/<TAG>_{WFD_80k,DDF_40k}` are pooled.
   - Every simulated object is weighted to expected real events over 10 years with
     `expected_counts.object_weights`: the native rate, over the footprint with ≥ 100 (WFD) or ≥ 1000 (DDF) visits,
     area-uniform. These are the same weights as `class_redshift_plots.py` and the SNII tail analysis.
   - Detected objects in the footprint are kept, with:
     - RA and Dec;
     - first detection: the first epoch with `PHOTFLAG & 4096`;
     - the noiseless model magnitude per band (`model_dense` `FLUX_MODEL`, nJy, zp 31.4, Milky Way and host
       extinction included) at t_fd + 0…400 observer-frame days.
2. **Query** (`engine.py`).
   - Time grid over [T0, T1 + t_max]. Night means the Sun is below `sun_alt` (default −18°).
   - For each object and night step with t_min ≤ t − t_fd ≤ t_max, the model magnitude is interpolated, and both
     m ≤ mag_lim and airmass ≤ airmass_max (Pickering 2002) are required.
   - Objects that can never pass (too faint in the window, or a declination that never reaches the airmass) are
     dropped first, so a 10-year window takes under 1 s.
3. **Outputs.**
   - Expected numbers detected in [T0, T1] and followable, with errors √Σw².
   - Distinct followable objects per night, and the instantaneous number.
   - Per object: followable hours, number of nights, and the delay from first detection to the first opportunity.
4. **Typical year** (`fold_years`, default on). Each simulated object is also placed at t_fd + m × 365.25 d.
   - A whole-year shift keeps the RA, the light curve and the Sun–object geometry, and the weights are scaled by
     365.25 d / survey span.
   - Any window then uses all 10 survey years: about 10× the statistics, at the cost of ignoring year-to-year
     cadence changes (rolling).
   - Errors treat the copies of one simulated object as fully correlated. With it off, only the simulated dates are
     used.

Astronomy uses fast analytic forms:
- Sun: Astronomical Almanac, to ~0.01°.
- Sidereal time: GMST linear in UT.
- Target coordinates are J2000 and not precessed (~0.35° by 2026, i.e. 0.02 in airmass at X = 2).

These are validated against astropy in `tests/test_followup_astro.py`. `tests/test_followup_engine.py` checks the
engine against a brute-force object × time evaluation and checks that folding conserves the rate.

## Classes

| Class | Sweep(s) | Note |
|---|---|---|
| SNIa, SNIa-91bg, SNIax | SNIASALT2, SNIA91BGELASTIC, SNIAXELASTIC | |
| SNII | SNIINMFTAILLOWZ (z ≤ 0.3) + SNIINMFTAIL (z > 0.3), × 4 | all normal SNe II, as in the SNII tail talk; reproduces its 1,237,201 WFD / 6,961 DDF detected at z ≤ 0.3 |
| SNIIn | SNIINMOSFIT | |
| SLSN-I, TDE | SLSNI, TDEMOSFIT | |
| KN-Bulla19, KN-K17, ILOT, CaRT | KNBULLA19, KNK17, ILOTMOSFIT, CART | |
| PISN-MOSFIT, PISN-He, PISN-H | PISNMOSFIT, PISNSTELLAHECORE, PISNSTELLAHYDROGENIC | |

Non-transients are not included: the native LCLIB runs have no light curves.

## Caveats

- **Bright-end statistics.** Native sweeps sample the whole volume, so few simulated objects are bright. For
  example, about 70 simulated SNe Ia carry the r ≤ 20 estimate for one year from Pachón, even with folding. The GUI
  flags classes with fewer than 20 simulated followable objects. Dedicated low-z native sweeps (as was done for
  SNII) would tighten bright limits.
- Moon, weather, telescope slews and the time a site needs to react are ignored.
- WFD and DDF are separate simulations: selecting both double-counts the DDF fields (≈0.3% of the WFD area).
- Only Rubin detection is modelled: an object enters at its first Rubin detection, not at its explosion.
