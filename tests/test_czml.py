"""Tests for engine/viz/czml.py — the CZML generator backing the 3D globe (5.1)."""

import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pytest

from engine.maneuvers import search_maneuvers
from engine.models import ManeuverConstraints, ManeuverOption, ScoredConjunction, TLEData
from engine.propagate import satrec_from_tle
from engine.tca import TCAState, refine_tca
from engine.viz.czml import (
    build_czml_document,
    conjunction_entities,
    covariance_ellipsoid_czml,
    event_czml_document,
    maneuver_track_czml,
    orbit_czml,
    teme_to_ecef,
    _iso,
    _rotation_to_quaternion,
    VISUAL_COV_SCALE,
)

# ── test fixtures ────────────────────────────────────────────────────────────

T0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=90)

ISS_L1 = "1 25544U 98067A   24202.50000000  .00016717  00000-0  30709-3 0  9998"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"
NEAR_L2 = "2 99998  51.6400 209.5700 0006859  39.6000 320.5300 15.50100000431234"


def _iss_tle() -> TLEData:
    return TLEData(
        norad_id=25544, name="ISS (ZARYA)", line1=ISS_L1, line2=ISS_L2,
        epoch=datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


def _near_tle() -> TLEData:
    return TLEData(
        norad_id=99998, name="NEAR OBJ", line1=ISS_L1, line2=NEAR_L2,
        epoch=datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


def _tca_state() -> TCAState:
    """Refine a conjunction between ISS and the near object."""
    primary = satrec_from_tle(_iss_tle())
    secondary = satrec_from_tle(_near_tle())
    return refine_tca(primary, secondary, 0.0, 0.0, step_s=60.0)


def _event() -> ScoredConjunction:
    st = _tca_state()
    return ScoredConjunction(
        primary_norad=25544, secondary_norad=99998,
        secondary_name="NEAR OBJ", secondary_type="DEBRIS",
        secondary_maneuverable=False,
        tca=T0 + timedelta(seconds=st.tca_offset_s),
        miss_distance_km=round(st.miss_distance_km, 3),
        relative_velocity_kms=7.5,
        miss_r_km=1.0, miss_s_km=2.0, miss_w_km=0.5,
        geometry="in-track",
        hbr_km=0.005, pc=1e-5,
        risk_score=15.0, storm_flag=False,
    )


@lru_cache(maxsize=1)
def _maneuver_option() -> ManeuverOption:
    """The cheapest feasible maneuver — cached, since the grid search is slow."""
    st = _tca_state()
    event = _event()
    options = search_maneuvers(
        event.tca, st.r_primary, st.v_primary, st.r_secondary,
        constraints=ManeuverConstraints(min_post_burn_miss_km=10.0),
        mass_kg=4.0, isp_s=60.0,
    )
    feasible = [o for o in options if o.satisfies_constraints]
    feasible.sort(key=lambda o: o.propellant_g)
    return feasible[0] if feasible else options[0]


# ── TEME → ECEF ──────────────────────────────────────────────────────────────

def test_teme_to_ecef_shape():
    r = np.array([7000.0, 0.0, 0.0])
    ecef = teme_to_ecef(r, T0)
    assert ecef.shape == (3,)
    assert all(np.isfinite(ecef))


def test_teme_to_ecef_preserves_magnitude():
    r = np.array([7000.0, 1000.0, -5000.0])
    ecef = teme_to_ecef(r, T0)
    assert np.linalg.norm(ecef) == pytest.approx(np.linalg.norm(r), rel=1e-12)


def test_teme_to_ecef_z_unchanged():
    """GMST rotation is about the z-axis — z is preserved."""
    r = np.array([1000.0, 2000.0, 3000.0])
    ecef = teme_to_ecef(r, T0)
    assert ecef[2] == pytest.approx(3000.0)


def test_teme_to_ecef_quadrant():
    """A vector along +x in TEME rotates away after ~1 hour (Earth turns ~15°/h)."""
    r = np.array([7000.0, 0.0, 0.0])
    ecef0 = teme_to_ecef(r, T0)
    ecef1 = teme_to_ecef(r, T0 + timedelta(hours=1))
    # The x-component changes due to Earth rotation
    assert abs(ecef0[0] - ecef1[0]) > 10  # nontrivial rotation


# ── rotation → quaternion ────────────────────────────────────────────────────

def test_identity_quaternion():
    q = _rotation_to_quaternion(np.eye(3))
    # Identity quaternion: [0, 0, 0, 1]
    assert q[3] == pytest.approx(1.0)
    assert abs(q[0]) < 1e-15
    assert abs(q[1]) < 1e-15
    assert abs(q[2]) < 1e-15


def test_quaternion_unit_length():
    for angle in [0, 45, 90, 135, 180]:
        rad = math.radians(angle)
        R = np.array([
            [math.cos(rad), -math.sin(rad), 0],
            [math.sin(rad), math.cos(rad), 0],
            [0, 0, 1],
        ])
        q = _rotation_to_quaternion(R)
        assert sum(x**2 for x in q) == pytest.approx(1.0, abs=1e-12)


# ── orbit CZML ───────────────────────────────────────────────────────────────

def test_orbit_czml_structure():
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=60)
    assert pkt is not None
    assert "id" in pkt
    assert pkt["id"].startswith("orbit-")
    assert "availability" in pkt
    assert "path" in pkt
    assert "position" in pkt
    # Position must have cartesian array with epoch
    assert "cartesian" in pkt["position"]
    assert "epoch" in pkt["position"]
    assert pkt["position"]["referenceFrame"] == "FIXED"


def test_orbit_czml_valid_json_cartesian():
    """cartesian must be a flat list of floats (3 * N)."""
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=30)
    cart = pkt["position"]["cartesian"]
    assert isinstance(cart, list)
    assert len(cart) >= 6  # at least 2 points
    assert len(cart) % 3 == 0
    for v in cart:
        assert isinstance(v, (int, float))
        assert math.isfinite(v)


def test_orbit_czml_no_nan():
    """The cartesian array must not contain NaN."""
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=60)
    cart = pkt["position"]["cartesian"]
    for v in cart:
        assert not math.isnan(v)


def test_orbit_czml_monotonic_epochs():
    """The epoch should be the earliest time, and availability covers the window."""
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=60)
    iso = pkt["availability"]
    parts = iso.split("/")
    assert len(parts) == 2
    t_start = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
    t_end = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
    assert t_start < t_end
    assert t_start >= T0


def test_orbit_czml_finite_cartesian():
    """All cartesian values must be finite (not inf)."""
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=120)
    for v in pkt["position"]["cartesian"]:
        assert math.isfinite(v)


def test_orbit_czml_id_override():
    tle = _iss_tle()
    pkt = orbit_czml(tle, "ISS", [0, 128, 255, 255], T0, 90, step_s=60, entity_id="my-orbit")
    assert pkt["id"] == "my-orbit"


# ── conjunction entities ─────────────────────────────────────────────────────

def test_conjunction_entities_count():
    state = _tca_state()
    entities = conjunction_entities(state, T0, "ISS", "NEAR")
    assert len(entities) == 4  # primary point, secondary point, miss line, vel arrow


def test_conjunction_entities_ids():
    state = _tca_state()
    entities = conjunction_entities(state, T0, "ISS", "NEAR")
    ids = {e["id"] for e in entities}
    assert "tca-primary" in ids
    assert "tca-secondary" in ids
    assert "tca-miss-line" in ids
    assert "tca-vel-vector" in ids


def test_conjunction_availability_bounded():
    """Availability should be ±5 s around TCA."""
    state = _tca_state()
    entities = conjunction_entities(state, T0, "ISS", "NEAR")
    for e in entities:
        avail = e["availability"]
        parts = avail.split("/")
        t0 = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
        assert t1 - t0 <= timedelta(seconds=11)  # ±5 s ≈ 10 s total
        assert t0 <= T0 <= t1


def test_conjunction_miss_line_cartesian():
    """Miss line should have 6 cartesian values (2 points)."""
    state = _tca_state()
    entities = conjunction_entities(state, T0, "ISS", "NEAR")
    miss = [e for e in entities if e["id"] == "tca-miss-line"][0]
    cart = miss["polyline"]["positions"]["cartesian"]
    assert len(cart) == 6
    assert all(math.isfinite(v) for v in cart)


# ── covariance ellipsoid ─────────────────────────────────────────────────────

def test_covariance_ellipsoid_structure():
    state = _tca_state()
    pkt = covariance_ellipsoid_czml(
        T0, state.r_primary, state.v_primary, state.r_secondary,
    )
    assert pkt["id"] == "covariance-ellipsoid"
    assert "ellipsoid" in pkt
    assert "radii" in pkt["ellipsoid"]
    assert "orientation" in pkt
    assert "unitQuaternion" in pkt["orientation"]


def test_covariance_ellipsoid_radii():
    from engine.pc import SIGMA_CROSSTRACK_KM, SIGMA_INTRACK_KM, SIGMA_RADIAL_KM

    state = _tca_state()
    pkt = covariance_ellipsoid_czml(
        T0, state.r_primary, state.v_primary, state.r_secondary,
    )
    radii = pkt["ellipsoid"]["radii"]["cartesian"]
    # Radii should be sigma * 1000 * VISUAL_SCALE (km→m→visual)
    expected_r = SIGMA_RADIAL_KM * 1000 * VISUAL_COV_SCALE
    expected_s = SIGMA_INTRACK_KM * 1000 * VISUAL_COV_SCALE
    expected_w = SIGMA_CROSSTRACK_KM * 1000 * VISUAL_COV_SCALE
    assert radii[0] == pytest.approx(expected_r)
    assert radii[1] == pytest.approx(expected_s)
    assert radii[2] == pytest.approx(expected_w)


def test_covariance_ellipsoid_center():
    """Center should be at the secondary's ECEF position."""
    state = _tca_state()
    pkt = covariance_ellipsoid_czml(
        T0, state.r_primary, state.v_primary, state.r_secondary,
    )
    center = pkt["position"]["cartesian"]
    # Secondary ECEF position in meters
    expected = teme_to_ecef(state.r_secondary, T0) * 1000
    for i in range(3):
        assert center[i] == pytest.approx(float(expected[i]))


def test_covariance_quaternion_unit():
    state = _tca_state()
    pkt = covariance_ellipsoid_czml(
        T0, state.r_primary, state.v_primary, state.r_secondary,
    )
    q = pkt["orientation"]["unitQuaternion"]
    norm = sum(x**2 for x in q)
    assert norm == pytest.approx(1.0, abs=1e-10)


# ── maneuver track ───────────────────────────────────────────────────────────

def test_maneuver_track_structure():
    state = _tca_state()
    event = _event()
    opt = _maneuver_option()
    tle = _iss_tle()
    pkt = maneuver_track_czml(tle, state, opt)
    assert pkt is not None
    assert pkt["id"] == "maneuver-track"
    assert "path" in pkt
    assert "position" in pkt
    assert "cartesian" in pkt["position"]


def test_maneuver_track_covers_burn_epoch():
    """The maneuver track availability must include the burn epoch."""
    state = _tca_state()
    opt = _maneuver_option()
    tle = _iss_tle()
    pkt = maneuver_track_czml(tle, state, opt)
    parts = pkt["availability"].split("/")
    t_start = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
    t_end = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
    burn = opt.burn_epoch
    assert t_start <= burn <= t_end, f"burn {burn} outside [{t_start}, {t_end}]"


# ── event_czml_document ──────────────────────────────────────────────────────

def test_event_czml_document_scene():
    """The scene assembler produces a complete document: both orbits, the TCA
    moment, and the covariance ellipsoid, with the clock starting at TCA."""
    event = _event()
    doc = event_czml_document(_iss_tle(), _near_tle(), _tca_state(), event)
    assert doc is not None
    assert doc[0]["id"] == "document"
    ids = {p["id"] for p in doc}
    assert {
        "orbit-primary", "orbit-secondary", "tca-primary", "tca-secondary",
        "tca-miss-line", "tca-vel-vector", "covariance-ellipsoid",
    } <= ids
    assert doc[0]["clock"]["currentTime"] == _iso(event.tca)
    # The orbit windows must be JSON-clean cartesian arrays.
    cart = next(p["position"]["cartesian"] for p in doc if p["id"] == "orbit-primary")
    assert len(cart) >= 6 and len(cart) % 3 == 0
    assert all(isinstance(v, (int, float)) for v in cart)


def test_event_czml_document_with_maneuver():
    """With a maneuver option the scene adds the maneuver track and widens the
    clock to cover burn−60 min … TCA+15 min."""
    event = _event()
    opt = _maneuver_option()
    doc = event_czml_document(
        _iss_tle(), _near_tle(), _tca_state(), event, maneuver_option=opt
    )
    assert doc is not None
    assert "maneuver-track" in {p["id"] for p in doc}
    start, stop = doc[0]["clock"]["interval"].split("/")
    burn = opt.burn_epoch
    if burn.tzinfo is None:
        burn = burn.replace(tzinfo=timezone.utc)
    assert start <= _iso(burn - timedelta(minutes=60))
    assert stop >= _iso(event.tca + timedelta(minutes=15))


# ── build_czml_document ──────────────────────────────────────────────────────

def test_build_document_structure():
    doc = build_czml_document([], T0, T1, T0, "Test Conjunction")
    assert isinstance(doc, list)
    assert len(doc) == 1  # just the document packet
    assert doc[0]["id"] == "document"
    assert doc[0]["version"] == "1.0"


def test_build_document_clock():
    doc = build_czml_document([], T0, T1, T0, "Test")
    clock = doc[0]["clock"]
    assert "interval" in clock
    assert "currentTime" in clock
    assert clock["currentTime"] == _iso(T0)


def test_build_document_with_packets():
    pkt = {"id": "entity-1", "availability": _iso(T0) + "/" + _iso(T1)}
    doc = build_czml_document([pkt], T0, T1, T0, "Test")
    assert len(doc) == 2
    assert doc[0]["id"] == "document"
    assert doc[1]["id"] == "entity-1"


def test_build_document_includes_label():
    doc = build_czml_document([], T0, T1, T0, "ISS vs DEBRIS")
    assert doc[0]["name"] == "ISS vs DEBRIS"
