"""Tests for engine/viz/passes.py — visible-pass prediction (5.3).

Covers the physics primitives deterministically (hand-computed geometry, fixed
sun vectors) and the full pipeline with a construction that GUARANTEES the ISS
produces a visible pass: choose a moment the satellite is sunlit near the
terminator, place the observer 25° toward the night side, and the pass must be
found. The TLE is the standard fixture — old, so the pass *times* are nonsense,
but the machinery (propagation, topocentric geometry, sunlight logic) is what
is under test.
"""

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from engine.ingest.open_notify import _gmst_rad, _julian_date, teme_to_latlon
from engine.models import TLEData
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes
from engine.viz import passes as pmod
from engine.viz.passes import (
    _dark_span,
    _segments,
    _sunlit_mask,
    _teme_to_ecef,
    apparent_magnitude,
    brightness_label,
    compass_point,
    compute_passes_for_location,
    elevation_azimuth_range,
    sun_position_eci,
)

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"


def _iss_tle() -> TLEData:
    return TLEData(
        norad_id=25544, name="ISS (ZARYA)", line1=ISS_L1, line2=ISS_L2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


# ---------------------------------------------------------------------------
# Sun position
# ---------------------------------------------------------------------------


def test_sun_position_unit_norm():
    s = sun_position_eci(datetime(2026, 8, 8, 12, tzinfo=timezone.utc))
    assert np.linalg.norm(s) == pytest.approx(1.0, abs=1e-6)


def test_sun_position_seasonal_declination():
    june = sun_position_eci(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
    dec = sun_position_eci(datetime(2026, 12, 21, 12, tzinfo=timezone.utc))
    assert june[2] > 0.35  # northern summer: declination ≈ +23.4°
    assert dec[2] < -0.35  # southern summer: declination ≈ −23.4°


# ---------------------------------------------------------------------------
# Topocentric geometry
# ---------------------------------------------------------------------------


def test_elevation_zenith():
    """A satellite straight above the observer (same ECEF ray) → elevation 90°."""
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    gmst = _gmst_rad(_julian_date(dt))
    R = 6778.0
    # TEME vector that rotates to ECEF (R, 0, 0) — directly above (0°, 0°).
    r = np.array([R * math.cos(gmst), R * math.sin(gmst), 0.0])
    elev, az, rng = elevation_azimuth_range(r, dt, 0.0, 0.0)
    assert elev == pytest.approx(90.0, abs=0.5)
    assert rng == pytest.approx(R - 6378.137, abs=0.1)


def test_azimuth_east():
    """A satellite at (lat 0, lon +10°) seen from (0, 0) → azimuth ≈ 90° (E)."""
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    gmst = _gmst_rad(_julian_date(dt))
    R = 6778.0
    s10, c10 = math.sin(math.radians(10)), math.cos(math.radians(10))
    x_e, y_e = R * c10, R * s10
    r = np.array(
        [x_e * math.cos(gmst) - y_e * math.sin(gmst),
         x_e * math.sin(gmst) + y_e * math.cos(gmst),
         0.0]
    )
    elev, az, _rng = elevation_azimuth_range(r, dt, 0.0, 0.0)
    assert az == pytest.approx(90.0, abs=0.5)
    assert elev > 5.0  # above the horizon


def test_compass_point():
    assert compass_point(0) == "N"
    assert compass_point(90) == "E"
    assert compass_point(180) == "S"
    assert compass_point(270) == "W"
    assert compass_point(315) == "NW"
    assert compass_point(337.5) == "NNW"
    assert compass_point(22.5) == "NNE"


# ---------------------------------------------------------------------------
# Sunlight / shadow
# ---------------------------------------------------------------------------


def test_sunlit_day_side():
    sun = np.array([1.0, 0.0, 0.0])
    assert _sunlit_mask(np.array([[7000.0, 0.0, 0.0]]), sun)[0]


def test_in_shadow_night_side():
    sun = np.array([1.0, 0.0, 0.0])
    assert not _sunlit_mask(np.array([[-7000.0, 0.0, 0.0]]), sun)[0]


def test_outside_shadow_cylinder():
    sun = np.array([1.0, 0.0, 0.0])
    # Night side but ~9000 km off the Earth-Sun line → still sunlit.
    assert _sunlit_mask(np.array([[-7000.0, 9000.0, 0.0]]), sun)[0]


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------


def test_magnitude_closer_is_brighter():
    assert apparent_magnitude(500, 1.0, -1.8) < apparent_magnitude(2000, 1.0, -1.8)


def test_magnitude_full_phase_is_brighter():
    assert apparent_magnitude(800, 1.0, -1.8) < apparent_magnitude(800, 0.0, -1.8)


def test_magnitude_calibration_iss():
    # At 1000 km, full phase: M0 − 15.75 + 2.5·log10(10^6) = M0 − 0.75.
    assert apparent_magnitude(1000.0, 1.0, -1.8) == pytest.approx(-2.55, abs=1e-9)


def test_brightness_label_bands():
    assert "extremely bright" in brightness_label(-1.0)
    assert "very bright" in brightness_label(1.0)
    assert "bright" in brightness_label(3.0)
    assert "faint" in brightness_label(4.0)


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


def test_segments_merges_small_gaps():
    """A sub-minute visibility gap is absorbed into one pass."""
    mask = np.array([True, True, False, False, True, True])
    assert _segments(mask) == [(0, 6)]


def test_segments_splits_long_gaps():
    mask = np.array([True, True, False, False, False, False, True, True])
    assert _segments(mask) == [(0, 2), (6, 8)]


# ---------------------------------------------------------------------------
# Dark span
# ---------------------------------------------------------------------------


def test_dark_span_bangalore_reasonable():
    span = _dark_span(12.97, 77.59, datetime(2026, 8, 8, tzinfo=timezone.utc))
    assert span is not None
    start, end = span
    assert start < end
    assert timedelta(hours=4) <= (end - start) <= timedelta(hours=13)


# ---------------------------------------------------------------------------
# Pass pipeline — envelope & honesty
# ---------------------------------------------------------------------------


def test_passes_envelope_shape():
    resp = compute_passes_for_location([_iss_tle()], 12.97, 77.59)
    assert resp.available is True
    assert resp.latitude == 12.97
    starts = [p.start for p in resp.passes]
    assert starts == sorted(starts)
    for p in resp.passes:
        assert p.max_elevation_deg >= 10.0
        assert p.start < p.max_elevation_time < p.end
        assert p.name and p.look_instruction and p.brightness_label
        assert p.direction_from in pmod.COMPASS_POINTS
    assert resp.note  # assumptions are stated in plain language


def test_passes_rejects_stale_date():
    resp = compute_passes_for_location([_iss_tle()], 12.97, 77.59, date="2020-01-01")
    assert resp.available is False
    assert "reliable" in resp.note


def test_passes_rejects_bad_date():
    resp = compute_passes_for_location([_iss_tle()], 0.0, 0.0, date="not-a-date")
    assert resp.available is False


# ---------------------------------------------------------------------------
# The spec's headline test: the ISS produces a visible pass, deterministically
# ---------------------------------------------------------------------------


def _anti_sun_bearing(r_teme: np.ndarray, sun: np.ndarray, dt: datetime) -> float:
    """Bearing from the sub-satellite point toward the anti-sun direction."""
    up = r_teme / np.linalg.norm(r_teme)
    east = np.cross(np.array([0.0, 0.0, 1.0]), up)
    east = east / np.linalg.norm(east)
    north = np.cross(up, east)
    sun_ecef = _teme_to_ecef(sun, dt)
    az = math.degrees(math.atan2(float(np.dot(east, sun_ecef)), float(np.dot(north, sun_ecef)))) % 360.0
    return (az + 180.0) % 360.0


def _offset_point(lat_deg: float, lon_deg: float, dist_deg: float, bearing_deg: float):
    """Move a point on the sphere by dist_deg along bearing_deg (great circle)."""
    lat1, lon1 = math.radians(lat_deg), math.radians(lon_deg)
    brg, d = math.radians(bearing_deg), math.radians(dist_deg)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 180.0) % 360.0 - 180.0


def test_iss_produces_visible_pass(monkeypatch):
    """The ISS pass must be found for a constructed 'guaranteed' geometry.

    Freeze the Sun at a fixed unit vector and find a moment when the ISS is
    sunlit (cylindrical shadow test) while its sub-point is already dark — the
    geometry of a visible pass just after sunset. The observer is placed a few
    degrees from the sub-point toward the night side: dark (Sun < −6°), the
    satellite lit, and a moderately high pass. The pipeline must find it.

    (The naive 'observer 25° from the sub-point' idea fails for a real reason:
    the horizon at 400 km altitude is only ~21° away, so 25° is below it.)
    """
    sun = np.array([0.95, 0.2, 0.25])
    sun = sun / np.linalg.norm(sun)
    monkeypatch.setattr(pmod, "sun_position_eci", lambda dt: sun)

    tle = _iss_tle()
    sat = satrec_from_tle(tle)
    now = datetime.now(timezone.utc)
    offsets_min = np.arange(0, 30 * 60, 2.0)  # 2-min grid over 30 h
    pos, _vel = propagate_grid(sat, tsince_minutes(now, tle) + offsets_min)

    chosen = None
    for i in range(len(pos)):
        r = pos[i]
        if not np.isfinite(r).all():
            continue
        t = now + timedelta(minutes=float(offsets_min[i]))
        if t < now + timedelta(minutes=5):
            continue
        # Sunlit satellite whose sub-point is already dark (the visible-pass
        # geometry: the satellite is above the shadow despite the dark ground).
        if not pmod._sunlit_mask(np.array([r]), sun)[0]:
            continue
        up_sub = r / np.linalg.norm(r)
        if float(np.dot(up_sub, sun)) >= -0.08:
            continue
        lat, lon = teme_to_latlon(r, t)
        # Observer a few degrees from the sub-point toward the night side.
        obs_lat, obs_lon = _offset_point(lat, lon, 3.0, _anti_sun_bearing(r, sun, t))
        up_obs = pmod.observer_ecef(obs_lat, obs_lon)
        up_obs = up_obs / np.linalg.norm(up_obs)
        if float(np.dot(up_obs, _teme_to_ecef(sun, t))) >= -0.12:
            continue
        # Verify with the engine's own geometry, then mirror its dark-span logic.
        elev, _az, _rng = pmod.elevation_azimuth_range(r, t, obs_lat, obs_lon)
        if elev < 30.0:
            continue
        local_date = (now + timedelta(hours=obs_lon / 15.0)).date().strftime("%Y-%m-%d")
        span = _dark_span(
            obs_lat, obs_lon,
            datetime.strptime(local_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        )
        if span is None or not (span[0] <= t <= span[1]):
            continue
        chosen = (t, obs_lat, obs_lon)
        break

    assert chosen is not None, "could not construct a guaranteed-visible geometry"
    _t, obs_lat, obs_lon = chosen

    resp = compute_passes_for_location([tle], obs_lat, obs_lon)
    iss_passes = [p for p in resp.passes if p.norad_id == 25544]
    assert iss_passes, (
        f"no ISS pass found at ({obs_lat:.1f}, {obs_lon:.1f}) — note: {resp.note}"
    )
    best = max(iss_passes, key=lambda p: p.max_elevation_deg)
    # The observer was only ~3° from the sub-point, so the pass must rise well
    # above the 10° threshold.
    assert best.max_elevation_deg >= 30.0
    assert "ISS" in best.name
    assert best.look_instruction.startswith("Look ")
    assert "AM" in best.look_instruction or "PM" in best.look_instruction
    assert best.brightness_label
    assert best.direction_from in pmod.COMPASS_POINTS
