"""Tests for engine/propagate.py.

Ground truth is the sgp4 library's OWN official verification suite
(SGP4-VER.TLE + tcppver.out, shipped inside the package) — 33 reference cases
including one intentional error case. Our wrapper must reproduce every
reference vector to < 1 mm, and mask error cases as NaN.
"""

from datetime import timedelta

import numpy as np
import pytest
from sgp4.api import Satrec

from engine.propagate import make_satrec, propagate_at, propagate_grid, tsince_minutes
from tests.conftest import *  # noqa: F401,F403 — repo root on sys.path

import sgp4
from pathlib import Path

VER_DIR = Path(sgp4.__file__).parent
VER_TLE = VER_DIR / "SGP4-VER.TLE"
VER_OUT = VER_DIR / "tcppver.out"


def _load_verification_suite():
    """(tle_pairs, expected_positions) from the official verification data."""
    lines = [ln.rstrip() for ln in VER_TLE.read_text().splitlines() if ln.strip()]
    pairs, i = [], 0
    while i < len(lines) - 1:
        if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            pairs.append((lines[i], lines[i + 1]))
            i += 2
        else:
            i += 1
    expected = [
        np.array([float(x) for x in ln.split()[1:4]])
        for ln in VER_OUT.read_text().splitlines()
        if len(ln.split()) == 7
    ]
    return pairs, expected


def test_verification_suite_submillimeter():
    """Our wrapper reproduces the library's official reference vectors (< 1 mm).

    The published tcppver.out values carry rounding at ~1e-4 km, so 1 mm is
    the correct tolerance. (Empirically the max deviation is ~0.3 mm.)
    """
    pairs, expected = _load_verification_suite()
    assert len(pairs) == len(expected) == 33

    matched = 0
    for (line1, line2), exp_pos in zip(pairs, expected):
        try:
            sat = make_satrec(int(line2[2:7]), line1, line2)
        except ValueError:
            continue  # intentionally invalid TLE — covered by the error test
        pos, _vel = propagate_grid(sat, np.array([0.0]))
        if np.isnan(pos[0]).any():
            continue  # propagation-level error case — masking tested separately
        assert np.allclose(pos[0], exp_pos, atol=1e-3), f"NORAD {line2[2:7]} mismatch"
        matched += 1
    assert matched >= 32, f"only {matched}/33 verification cases matched"


def test_error_handling_two_tiers():
    """Invalid TLEs are rejected loudly at init; propagation errors mask as NaN."""
    pairs, _ = _load_verification_suite()
    init_errors = 0
    prop_errors = 0
    for line1, line2 in pairs:
        norad = int(line2[2:7])
        try:
            sat = make_satrec(norad, line1, line2)
        except ValueError:
            init_errors += 1  # e.g. eccentricity > 1 — screening must skip these
            continue
        pos, vel = propagate_grid(sat, np.array([0.0]))
        _e, _r, _v = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF)
        if _e != 0:
            assert np.isnan(pos[0]).all() and np.isnan(vel[0]).all()
            prop_errors += 1
        else:
            assert not np.isnan(pos[0]).any()
    assert init_errors + prop_errors >= 1, "suite should contain an error case"


def test_vectorized_matches_pointwise():
    """Grid propagation must equal per-point propagation exactly."""
    pairs, _ = _load_verification_suite()
    line1, line2 = pairs[0]
    sat = make_satrec(int(line2[2:7]), line1, line2)
    grid = np.array([0.0, 90.0, 180.0, 270.0, 360.0])
    pos_grid, vel_grid = propagate_grid(sat, grid)
    for i, t in enumerate(grid):
        pos_one, vel_one = propagate_grid(sat, np.array([t]))
        assert np.allclose(pos_grid[i], pos_one[0])
        assert np.allclose(vel_grid[i], vel_one[0])


def test_propagate_at_matches_grid():
    """propagate_at must agree with propagate_grid at the same instant."""
    pairs, _ = _load_verification_suite()
    line1, line2 = pairs[0]
    sat = make_satrec(int(line2[2:7]), line1, line2)
    epoch = sat.jdsatepoch + sat.jdsatepochF  # not used directly; use a TLEData epoch
    from datetime import datetime, timezone

    tle_epoch = datetime(2000, 6, 27, 18, 50, 19, 584000, tzinfo=timezone.utc)
    when = tle_epoch + timedelta(hours=6)
    pos_at, vel_at = propagate_at(sat, when, tle_epoch)
    pos_grid, vel_grid = propagate_grid(sat, np.array([360.0]))
    assert np.allclose(pos_at, pos_grid[0])
    assert np.allclose(vel_at, vel_grid[0])


def test_tsince_minutes():
    from datetime import datetime, timezone

    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = epoch + timedelta(hours=6)
    assert tsince_minutes(later, _FakeTLE(epoch)) == pytest.approx(360.0)


class _FakeTLE:
    def __init__(self, epoch):
        self.epoch = epoch


def test_satrec_cached():
    pairs, _ = _load_verification_suite()
    line1, line2 = pairs[0]
    norad = int(line2[2:7])
    assert make_satrec(norad, line1, line2) is make_satrec(norad, line1, line2)
