"""Add the class "SNIbc-MOSFIT" to ALCeS CLASS_CONFIGS (run on Leftraru, in exploration/lightcurvelynx/).

LSST_sim_lcs, 2026-10-06 (docs/logz_flat_mode.md). SIMSED.SNIbc-MOSFIT (Guillochon & Villar MOSFIT SNe Ib/c,
~700 SEDs, PARNAMES IBC_INDEX Mejecta Kinetic_energy F_nickel) exists in run_SNANA/plasticc_models but no SNANA
SIMGEN_INCLUDE uses it, so the generation settings are ours:
  rate         MD14 star-formation shape, rate0 = 1.5e-5 /yr/Mpc^3 (SED.INFO: "local rate ~15000 /yr/Gpc^3, traces the SFR")
  redshift     0.011-1.0 to start (class_pipeline.sh pilots extend it if detections reach the top)
  time window  GENRANGE_TREST -50/300 (as SNANA's SNIb/SNIc templates and SNIIn-MOSFIT)
  host dust    WV07 (A_V 0-3, R_V 3.1), as the other MOSFIT core-collapse classes
  weights      uniform over the SEDs (SIMSED_GRIDONLY), as SNIIn-MOSFIT
  RESTLAMBDA   1000-11000 A (SED.INFO)
  SNTYPE       62 (PLAsTiCC SN Ibc code)
Backup: run_simsed_poc.py.bak_snibc_20261006.
"""
import shutil
from pathlib import Path

p = Path.cwd() / "run_simsed_poc.py"
s = p.read_text()
if '"SNIbc-MOSFIT"' in s:
    raise SystemExit("already patched")
anchor = '    "SNIIn-MOSFIT": dict(\n'
assert s.count(anchor) == 1
entry = '''    # SNIbc-MOSFIT (LSST_sim_lcs 2026-10-06): MOSFIT SNe Ib/c (Guillochon & Villar), no SNANA SIMGEN_INCLUDE uses it,
    # settings chosen in LSST_sim_lcs/tools/snibc/patch_alces_snibc.py (rate from SED.INFO, window/dust as SNIIn-MOSFIT).
    "SNIbc-MOSFIT": dict(
        simsed_dir=SNANA_HOME / "run_SNANA/plasticc_models/SIMSED.SNIbc-MOSFIT",
        genrange_redshift=(0.011, 1.0),
        dndz=("md14", 1.5e-5),
        sntype=62,
        host_av=dict(kind="wv07", av_range=(0.0, 3.0), rewgt_expav=None, r_v=3.1),
        restlambda_range=(1000.0, 11000.0),
        trest_range=(-50.0, 300.0),
    ),
'''
shutil.copy2(p, p.with_suffix(".py.bak_snibc_20261006"))
p.write_text(s.replace(anchor, entry + anchor))
print("patched")
