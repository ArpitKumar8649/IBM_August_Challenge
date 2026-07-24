"""Tests for engine/ingest/celestrak.py — parsing, epoch math, geometry, caching."""

from datetime import datetime, timezone

import pytest

from engine.ingest.celestrak import (
    _derive_geometry,
    _parse_epoch,
    fetch_group,
    parse_tle_text,
)

# ISS TLE (representative real record)
ISS_TLE = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993
2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234
"""


def test_parse_tle_text_iss():
    objects = parse_tle_text(ISS_TLE)
    assert len(objects) == 1
    iss = objects[0]
    assert iss.norad_id == 25544
    assert iss.name == "ISS (ZARYA)"
    assert iss.inclination_deg == pytest.approx(51.64)
    # ISS: ~410-420 km circular orbit
    assert 380 < iss.perigee_alt_km < 450
    assert 380 < iss.apogee_alt_km < 450
    assert iss.apogee_alt_km >= iss.perigee_alt_km


def test_parse_epoch():
    line1 = ISS_TLE.splitlines()[1]
    epoch = _parse_epoch(line1)
    # 2024, day 1.5 -> Jan 1 2024 12:00 UTC
    assert epoch == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_epoch_y2k_pivot():
    # Year 57+ -> 1900s; below -> 2000s
    line1_1999 = "1 25544U 98067A   99001.50000000  .00016717  00000-0  30709-3 0  9993"
    line1_2026 = "1 25544U 98067A   26001.50000000  .00016717  00000-0  30709-3 0  9993"
    assert _parse_epoch(line1_1999).year == 1999
    assert _parse_epoch(line1_2026).year == 2026


def test_derive_geometry_geo():
    # Geostationary: ~1.0027 rev/day -> ~35,786 km altitude
    line2 = "2 25544   0.0500 100.0000 0001000  90.0000 270.0000  1.00270000 12345"
    inclination, perigee_alt, apogee_alt = _derive_geometry(line2)
    assert 35_700 < perigee_alt < 35_900
    assert 35_700 < apogee_alt < 35_900


def test_parse_tolerates_stray_lines():
    text = ISS_TLE + "\nGARBAGE LINE\n" + ISS_TLE
    objects = parse_tle_text(text)
    assert len(objects) == 2


def test_fetch_group_live_cached(tmp_path):
    """Live network test: fetch 'stations' (small, ~5 objects), verify cache round-trip."""
    objects = fetch_group("stations", catalog_dir=tmp_path)
    assert len(objects) >= 3
    assert any(o.norad_id == 25544 for o in objects)
    # Second call must hit cache (no network) — same data
    cached = fetch_group("stations", catalog_dir=tmp_path)
    assert {o.norad_id for o in cached} == {o.norad_id for o in objects}
