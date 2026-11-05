"""Semillas por (clase, estrategia) de los sweeps (sweep_seeds.py, 2026-11-05).

    ~/.venvs/alces-lcl/bin/python -m pytest -q test_sweep_seeds.py      (desde exploration/lightcurvelynx)
"""
import pytest

import sweep_seeds as S


def test_per_class_seeds_differ_between_classes_and_strategies():
    a = S.effective_seed("SNIa-SALT2", True, 200)
    b = S.effective_seed("SLSN-I", True, 200)
    c = S.effective_seed("SNIa-SALT2", False, 200)
    assert len({a, b, c}) == 3
    # deterministic, and consecutive YAML seeds stay consecutive inside the class block
    assert S.effective_seed("SNIa-SALT2", True, 201) == a + 1
    assert S.effective_seed("SNIa-SALT2", True, 200) == a


def test_range_is_above_training_seeds_and_fits_int64():
    for c in ("SNIa-SALT2", "SLSN-I", "TDE-MOSFIT"):
        for wfd in (False, True):
            for seed in (0, S.SEED_BLOCK - 1):
                e = S.effective_seed(c, wfd, seed)
                assert S.NATIVE_SEED_FLOOR <= e < S.NATIVE_SEED_FLOOR + S.SEED_BLOCK * S.N_SLOTS
                assert e > 30_000_000                       # training-mode seeds stay below ~2.2e7
                assert 20260813 + e * 1_000_000 + 20 < 2 ** 63   # seed_base + sub-offsets in int64


def test_legacy_scheme_is_unchanged_and_bad_input_fails():
    assert S.effective_seed("SNIa-SALT2", True, 200, "legacy") == 200
    with pytest.raises(ValueError):
        S.effective_seed("SNIa-SALT2", True, S.SEED_BLOCK)
    with pytest.raises(ValueError):
        S.effective_seed("SNIa-SALT2", True, 1, "nope")


def test_all_known_classes_have_distinct_blocks():
    from run_simsed_poc import CLASS_CONFIGS
    S.check_unique_slots(CLASS_CONFIGS)                     # raises on any collision
    with pytest.raises(ValueError):
        S.check_unique_slots(["X", "X"])


def test_build_runs_gives_each_class_its_own_seeds():
    from sweep_compile import build_runs
    cfg = {"classes": ["SNIa-SALT2", "SLSN-I"], "seeds": [200, 201],
           "modes": [{"wfd": True, "simsed_t0_mode": "bolometric_peak"}]}
    rows = build_runs(cfg, "codehash")
    seeds = {(r["class_key"], r["seed_yaml"]): r["seed_index"] for r in rows}
    assert seeds[("SNIa-SALT2", 200)] != seeds[("SLSN-I", 200)]
    assert all(r["seed_scheme"] == "per_class" for r in rows)
    assert len({r["seed_index"] for r in rows}) == len(rows)
    legacy = build_runs({**cfg, "seed_scheme": "legacy"}, "codehash")
    assert {r["seed_index"] for r in legacy} == {200, 201}
    # the run hash follows the effective seed: old (legacy) runs are never mistaken for new ones
    assert not {r["run_hash"] for r in rows} & {r["run_hash"] for r in legacy}
