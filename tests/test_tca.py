"""Tests for engine/tca.py — refinement precision vs brute force."""

from datetime import datetime, timezone

import numpy as np
import pytest

from engine.models import TLEData
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes
from engine.tca import refine_tca

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"
# Slightly different RAAN -> intersecting orbits with a real close approach
NEAR_L2 = "2 99998  51.6400 209.1000 0006859  39.6000 320.5300 15.50100000431234"


def _tle(norad, l2):
    return TLEData(
        norad_id=norad, name="X", line1=ISS_L1, line2=l2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


@pytest.fixture
def pair():
    p = _tle(25544, ISS_L2)
    s = _tle(99998, NEAR_L2)
    return satrec_from_tle(p), satrec_from_tle(s), p, s


def test_refine_within_window(pair):
    ps, ss, p, s = pair
    start = datetime(2026, 7, 21, tzinfo=timezone.utc)
    state = refine_tca(ps, ss, tsince_minutes(start, p), tsince_minutes(start, s), step_s=60.0)
    assert -60.0 <= state.tca_offset_s <= 60.0


def _find_coarse_minimum(ps, ss, p, s, start, span_hours=24.0):
    """Scan a window to locate the coarse grid point of closest approach."""
    n = int(span_hours * 60)
    offsets_min = np.arange(n, dtype=float)
    pp, _ = propagate_grid(ps, tsince_minutes(start, p) + offsets_min)
    sp, _ = propagate_grid(ss, tsince_minutes(start, s) + offsets_min)
    dist = np.linalg.norm(pp - sp, axis=1)
    dist[~np.isfinite(dist)] = 1e9
    idx = int(np.argmin(dist))
    return idx, float(dist[idx])


def test_refine_is_a_minimum(pair):
    """Refined separation must be <= the coarse center and its neighbors."""
    ps, ss, p, s = pair
    start = datetime(2026, 7, 21, tzinfo=timezone.utc)
    idx, _ = _find_coarse_minimum(ps, ss, p, s, start)
    t0_p = tsince_minutes(start, p) + idx
    t0_s = tsince_minutes(start, s) + idx
    state = refine_tca(ps, ss, t0_p, t0_s, step_s=60.0)

    def sep(dt_min):
        pp, _ = propagate_grid(ps, np.array([t0_p + dt_min]))
        sp, _ = propagate_grid(ss, np.array([t0_s + dt_min]))
        return float(np.linalg.norm(pp[0] - sp[0]))

    assert state.miss_distance_km <= sep(0.0) + 1e-9
    assert state.miss_distance_km <= sep(-1.0) + 1e-9  # -60 s
    assert state.miss_distance_km <= sep(1.0) + 1e-9   # +60 s


def test_refine_matches_brute_force(pair):
    """Refined miss must match a 0.05 s brute-force grid minimum (< 10 m)."""
    ps, ss, p, s = pair
    start = datetime(2026, 7, 21, tzinfo=timezone.utc)
    idx, _ = _find_coarse_minimum(ps, ss, p, s, start)
    t0_p = tsince_minutes(start, p) + idx
    t0_s = tsince_minutes(start, s) + idx
    state = refine_tca(ps, ss, t0_p, t0_s, step_s=60.0)

    offsets = np.arange(-60.0, 60.05, 0.05)
    pp, _ = propagate_grid(ps, t0_p + offsets / 60.0)
    sp, _ = propagate_grid(ss, t0_s + offsets / 60.0)
    dist = np.linalg.norm(pp - sp, axis=1)
    brute_min = float(np.nanmin(dist))

    assert abs(state.miss_distance_km - brute_min) < 0.01


def test_refine_returns_full_state(pair):
    ps, ss, p, s = pair
    start = datetime(2026, 7, 21, tzinfo=timezone.utc)
    idx, _ = _find_coarse_minimum(ps, ss, p, s, start)
    state = refine_tca(
        ps, ss, tsince_minutes(start, p) + idx, tsince_minutes(start, s) + idx
    )
    assert state.r_primary.shape == (3,)
    assert state.v_secondary.shape == (3,)
    assert np.linalg.norm(state.r_primary - state.r_secondary) == pytest.approx(
        state.miss_distance_km, abs=1e-6
    )
