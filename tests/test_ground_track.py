"""Tests for engine/ground_track.py — sub-satellite point, ground track, bbox."""

from datetime import datetime, timezone

import numpy as np
import pytest

from engine.ground_track import (
    _crosses_antimeridian,
    ground_track,
    ground_track_bbox,
    ground_track_center,
    sub_satellite_point,
)
from engine.models import GroundTrackPoint, TLEData

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"


def _iss_tle():
    return TLEData(
        norad_id=25544, name="ISS (ZARYA)", line1=ISS_L1, line2=ISS_L2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


# --- sub_satellite_point ---

def test_sub_satellite_point_equator():
    """A point on the equator at the prime meridian → lat ≈ 0."""
    r = np.array([6778.0, 0.0, 0.0])
    # Choose a time when GMST ≈ 0 so the point maps near lon 0.
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    lat, lon, alt = sub_satellite_point(r, dt)
    assert lat == pytest.approx(0.0, abs=0.01)
    assert -180 <= lon <= 180


def test_sub_satellite_point_altitude():
    """Altitude = |r| − R_earth."""
    r = np.array([6778.0, 0.0, 0.0])
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    _lat, _lon, alt = sub_satellite_point(r, dt)
    assert alt == pytest.approx(6778.0 - 6378.137, abs=0.1)


def test_sub_satellite_point_pole():
    """A point on the +Z axis → latitude ≈ +90."""
    r = np.array([0.0, 0.0, 6778.0])
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    lat, lon, alt = sub_satellite_point(r, dt)
    assert lat == pytest.approx(90.0, abs=0.01)


# --- ground_track ---

def test_ground_track_point_count():
    """duration/step + 1 points."""
    track = ground_track(_iss_tle(), duration_min=10, step_s=60)
    assert len(track) == 11  # 10 min / 1 min + 1


def test_ground_track_iss_latitude_bounds():
    """ISS ground track must stay within ±(inclination + margin) latitude."""
    track = ground_track(_iss_tle(), duration_min=90, step_s=60)
    assert len(track) > 0
    for p in track:
        # ISS inclination 51.6°; allow a small margin for geocentric/geodetic diff.
        assert -52.5 <= p.latitude <= 52.5, f"latitude {p.latitude} out of ISS bounds"


def test_ground_track_longitudes_valid():
    """All longitudes must be in [-180, 180]."""
    track = ground_track(_iss_tle(), duration_min=90, step_s=60)
    for p in track:
        assert -180 <= p.longitude <= 180


def test_ground_track_altitude_reasonable():
    """ISS altitude should be ~400-430 km throughout."""
    track = ground_track(_iss_tle(), duration_min=30, step_s=60)
    for p in track:
        assert 380 < p.altitude_km < 450


# --- bbox ---

def test_ground_track_bbox_contains_points():
    """Every track point's lat/lon must lie within the bbox (non-dateline case)."""
    track = ground_track(_iss_tle(), duration_min=20, step_s=60)
    west, south, east, north = ground_track_bbox(track)
    for p in track:
        assert south <= p.latitude <= north
        # For a non-dateline-crossing track, west <= lon <= east.
        if west <= east:
            assert west <= p.longitude <= east


def test_ground_track_center_is_mean():
    """The center should be the mean lat/lon of the track."""
    track = ground_track(_iss_tle(), duration_min=20, step_s=60)
    lat_c, lon_c = ground_track_center(track)
    mean_lat = sum(p.latitude for p in track) / len(track)
    assert lat_c == pytest.approx(mean_lat, abs=0.01)


def test_empty_track_bbox():
    assert ground_track_bbox([]) == (0.0, 0.0, 0.0, 0.0)


def test_empty_track_center():
    assert ground_track_center([]) == (0.0, 0.0)


# --- antimeridian handling ---

def test_crosses_antimeridian_true():
    lons = [170.0, 175.0, 179.0, -179.0, -175.0]  # crosses ±180
    assert _crosses_antimeridian(lons) is True


def test_crosses_antimeridian_false():
    lons = [10.0, 20.0, 30.0, 40.0]
    assert _crosses_antimeridian(lons) is False


def test_bbox_antimeridian_crossing():
    """A track crossing the dateline should produce west > east (valid antimeridian bbox)."""
    track = [
        GroundTrackPoint(latitude=0.0, longitude=178.0, time="t1", altitude_km=400),
        GroundTrackPoint(latitude=0.0, longitude=179.5, time="t2", altitude_km=400),
        GroundTrackPoint(latitude=0.0, longitude=-179.5, time="t3", altitude_km=400),
        GroundTrackPoint(latitude=0.0, longitude=-178.0, time="t4", altitude_km=400),
    ]
    west, south, east, north = ground_track_bbox(track)
    # For an antimeridian-crossing bbox, west > east.
    assert west > east
    assert west == pytest.approx(178.0, abs=0.01)
    assert east == pytest.approx(-178.0, abs=0.01)
