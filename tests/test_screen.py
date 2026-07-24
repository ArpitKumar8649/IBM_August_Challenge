"""Tests for engine/screen.py — band filter, minima detection, end-to-end synthetic."""

from datetime import datetime, timezone

import numpy as np
import pytest

from engine.models import ScreeningConfig, TLEData
from engine.screen import _find_local_minima, _parabolic_refine, altitude_band_filter, screen_satellite


def _tle(norad: int, name: str, line1: str, line2: str, perigee: float, apogee: float) -> TLEData:
    return TLEData(
        norad_id=norad,
        name=name,
        line1=line1,
        line2=line2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6,
        perigee_alt_km=perigee,
        apogee_alt_km=apogee,
    )


# Real-format TLE lines (ISS) for the propagation path
ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"


def test_band_filter_excludes_geo():
    primary = _tle(25544, "ISS", ISS_L1, ISS_L2, 410.0, 420.0)
    geo = _tle(99999, "GEO-SAT", ISS_L1, ISS_L2, 35780.0, 35790.0)
    leo = _tle(88888, "LEO-SAT", ISS_L1, ISS_L2, 500.0, 520.0)
    filtered = altitude_band_filter([primary, geo, leo], primary, margin_km=150.0)
    ids = {o.norad_id for o in filtered}
    assert ids == {88888}  # GEO excluded, primary excluded, LEO kept


def test_band_filter_margin():
    primary = _tle(25544, "ISS", ISS_L1, ISS_L2, 410.0, 420.0)
    just_outside = _tle(77777, "EDGE", ISS_L1, ISS_L2, 600.0, 610.0)  # 180 km above
    assert altitude_band_filter([just_outside], primary, margin_km=150.0) == []
    assert len(altitude_band_filter([just_outside], primary, margin_km=200.0)) == 1


def test_find_local_minima_basic():
    d = np.array([10.0, 5.0, 2.0, 5.0, 10.0])
    assert list(_find_local_minima(d, threshold=3.0)) == [2]
    assert list(_find_local_minima(d, threshold=1.0)) == []  # below threshold -> none


def test_find_local_minima_nan_safe():
    d = np.array([np.nan, 5.0, 2.0, 5.0, np.nan])
    assert list(_find_local_minima(d, threshold=3.0)) == [2]


def test_find_local_minima_multiple():
    d = np.array([10.0, 1.0, 10.0, 10.0, 2.0, 10.0])
    assert list(_find_local_minima(d, threshold=3.0)) == [1, 4]


def test_parabolic_refine_symmetric():
    """Symmetric parabola y=(x-2)^2+1 -> minimum exactly at grid point."""
    d = np.array([5.0, 2.0, 1.0, 2.0, 5.0])
    offset, refined = _parabolic_refine(d, 2, step_s=60.0)
    assert offset == pytest.approx(0.0)
    assert refined == pytest.approx(1.0)


def test_parabolic_refine_offset():
    """Asymmetric points -> sub-grid refinement between samples."""
    d = np.array([10.0, 4.0, 2.0, 3.0, 10.0])
    offset, refined = _parabolic_refine(d, 2, step_s=60.0)
    assert -60.0 < offset < 60.0
    assert refined < 2.0  # refined minimum is lower than the grid sample


def test_screen_end_to_end_iss():
    """Screen the ISS against itself-ish catalog: runs, returns a valid run record."""
    primary = _tle(25544, "ISS (ZARYA)", ISS_L1, ISS_L2, 411.0, 421.0)
    # A second object on a nearly identical orbit (same TLE, different id) will
    # produce a very close approach — guarantees the pipeline finds something.
    twin = _tle(99998, "ISS-TWIN", ISS_L1, ISS_L2, 411.0, 421.0)
    config = ScreeningConfig(window_days=1.0, time_step_s=60.0, miss_threshold_km=100.0)
    candidates, run = screen_satellite(primary, [primary, twin], config)
    assert run.catalog_size == 2
    assert run.band_filtered_size == 1
    assert len(candidates) >= 1
    assert candidates[0].miss_distance_km < 1.0  # identical orbit -> ~0 miss
    assert candidates[0].secondary_norad == 99998
    assert run.duration_s > 0
