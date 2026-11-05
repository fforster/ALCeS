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

The GUI's site presets are in `followup/sites.py`: 74 optical/IR observatories in 10 regions, from the South
Pole and Dome A/C to PEARL (Eureka, 80° N), and from Hawai'i to New Zealand. Coordinates marked [a] come from the
astropy observatory registry; the others are published site coordinates (~0.01°). Every site is a clickable dot
on the map, and every control has a hover explanation.

**Sky map and single events.** The results include a Mollweide sky map (equatorial; RA increases to the left).
- It shows every followable event first detected in the window, coloured by class, plus a grey sample of detected
  events that are never followable, the declination limits reachable within the airmass limit, and the Galactic
  plane.
- Clicking an event opens its noiseless model light curve per band (`model_dense`) and Rubin's photometry
  (`phot_df`: detections with 1σ errors; 5σ limits of non-detections on request).
- Shaded intervals show when it is observable from the site (night and airmass) and when it is followable (all
  limits). Its followable hours equal the engine's count exactly (test).
- The store records each event's sweep, run and SNID for this purpose. In folding mode the event and its Rubin
  points are shifted by whole years, so the points show the cadence of the year it was simulated in.

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
4. **Dates vs folding.** By default only the events detected on the selected simulated dates are used. This
   follows the strategy actually scheduled then (rolling stripes, survey phases).
   - Optional `fold_years`: events first detected in the survey years `fold_year_list` (0-based; default all) are
     also placed at t_fd + m × 365.25 d, with weights divided by the number of years used.
   - A whole-year shift keeps the RA, the light curve and the Sun–object geometry, **but not the Rubin strategy**.
     For one example window (WFD, Pachón), the detected rate differs between years by χ²/dof = 45–131 / 9 per
     class, and the weakest year has 0.52–0.86× the strongest. Followable counts at r ≤ 22 differ by ~±20%
     (χ² 21/9).
   - The result therefore includes `by_year`: the window estimated from each year alone, plus a χ² of their
     scatter, so you can see whether the chosen years are equivalent for the given cuts.
   - Errors treat the copies of one simulated object as fully correlated.
   - Neither mode models missing difference-imaging templates early in the survey: the simulations detect by S/N
     from the first night.

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
  example, only ~8 simulated SNe Ia carry the r ≤ 20 estimate for one year from Pachón (±35%). The GUI shows the
  number of simulated objects behind every result and flags classes with fewer than 20. Folding helps but biases
  (see above). The clean fix is dedicated low-z native sweeps for the bright end, as was done for SNII
  (SNIINMFTAILLOWZ): same rates, z range cut, many more nearby events.
- Moon, weather, telescope slews and the time a site needs to react are ignored.
- WFD and DDF are separate simulations: selecting both double-counts the DDF fields (≈0.3% of the WFD area).
- Only Rubin detection is modelled: an object enters at its first Rubin detection, not at its explosion.
