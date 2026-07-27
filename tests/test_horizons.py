"""Tests for engine/ingest/horizons.py — parsing, body lookup, Sun direction, shadow."""

import numpy as np
import pytest

from engine.ingest.horizons import (
    BODY_CODES,
    _JD_LINE,
    _SOE_BLOCK,
    _STATE_LINE,
    body_code,
    in_earth_shadow,
    parse_ephemeris,
    sun_direction_geocentric,
)
from engine.models import EphemerisState

# --- recorded Horizons VECTOR response (Sun, geocentric, 2026-07-27/28) ---

HORIZONS_RESULT = """
*******************************************************************************
 Revised: July 31, 2017                 Sun                                 10
*******************************************************************************
$$SOE
2461248.500000000 = A.D. 2026-Jul-27 00:00:00.0000 TDB
 X =-8.416281170395860E+07 Y = 1.264766596486527E+08 Z =-7.458443864971399E+03
 VX=-2.430519123121140E+01 VY=-1.638977988351058E+01 VZ= 1.755021915086807E-03
2461249.500000000 = A.D. 2026-Jul-28 00:00:00.0000 TDB
 X =-8.625080721585318E+07 Y = 1.250428902644551E+08 Z =-7.297865120314062E+03
 VX=-2.402697450664750E+01 VY=-1.679857917272701E+01 VZ= 1.956841598851050E-03
$$EOE
"""


# --- body_code lookup ---

def test_body_code_known_names():
    assert body_code("sun") == "10"
    assert body_code("mars") == "499"
    assert body_code("moon") == "301"
    assert body_code("earth") == "399"
    assert body_code("jupiter") == "599"


def test_body_code_case_insensitive():
    assert body_code("MARS") == "499"
    assert body_code("  Venus ") == "299"


def test_body_code_raw_code_passthrough():
    assert body_code("499") == "499"
    assert body_code("-1") == "-1"


def test_body_code_unknown_raises():
    with pytest.raises(ValueError):
        body_code("krypton")


def test_body_codes_complete():
    """All major bodies should be in the lookup."""
    for body in ["sun", "mercury", "venus", "earth", "moon", "mars",
                 "jupiter", "saturn", "uranus", "neptune", "pluto"]:
        assert body in BODY_CODES


# --- parse_ephemeris ---

def test_parse_ephemeris_state_count():
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    assert len(states) == 2


def test_parse_ephemeris_first_state_position():
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    s = states[0]
    assert s.r_eci[0] == pytest.approx(-8.416281170395860e7)
    assert s.r_eci[1] == pytest.approx(1.264766596486527e8)
    assert s.r_eci[2] == pytest.approx(-7.458443864971399e3)


def test_parse_ephemeris_first_state_velocity():
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    s = states[0]
    assert s.v_eci[0] == pytest.approx(-2.430519123121140e1)
    assert s.v_eci[1] == pytest.approx(-1.638977988351058e1)


def test_parse_ephemeris_jd_and_time():
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    assert states[0].jd == pytest.approx(2461248.5)
    assert "2026-Jul-27" in states[0].time
    assert states[1].jd == pytest.approx(2461249.5)


def test_parse_ephemeris_body_name():
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    assert all(s.body_name == "sun" for s in states)


def test_parse_ephemeris_sun_distance_1au():
    """The Sun's geocentric distance should be ~1 AU (1.496e8 km)."""
    states = parse_ephemeris(HORIZONS_RESULT, "sun")
    r = states[0].r_eci
    dist = (r[0] ** 2 + r[1] ** 2 + r[2] ** 2) ** 0.5
    assert dist == pytest.approx(1.496e8, rel=0.02)  # within 2% of 1 AU


def test_parse_ephemeris_model_validates():
    for s in parse_ephemeris(HORIZONS_RESULT, "sun"):
        EphemerisState.model_validate(s.model_dump())


def test_parse_ephemeris_no_block():
    """No $$SOE block → empty list."""
    assert parse_ephemeris("no ephemeris here", "x") == []


def test_soe_block_regex():
    m = _SOE_BLOCK.search(HORIZONS_RESULT)
    assert m is not None
    assert "X =" in m.group(1)


def test_state_line_regex_count():
    m = _SOE_BLOCK.search(HORIZONS_RESULT)
    vectors = list(_STATE_LINE.finditer(m.group(1)))
    assert len(vectors) == 2


# --- in_earth_shadow ---

def test_shadow_day_side_false():
    """A satellite toward the Sun (day side) is NOT in shadow."""
    sun_dir = [1.0, 0.0, 0.0]
    r_sat = [7000.0, 0.0, 0.0]  # toward the Sun
    assert in_earth_shadow(r_sat, sun_dir) is False


def test_shadow_night_side_true():
    """A satellite opposite the Sun (night side, near Earth-Sun line) IS in shadow."""
    sun_dir = [1.0, 0.0, 0.0]
    r_sat = [-7000.0, 0.0, 0.0]  # opposite the Sun, on the line
    assert in_earth_shadow(r_sat, sun_dir) is True


def test_shadow_night_side_outside_cylinder_false():
    """A night-side satellite far from the Earth-Sun line is NOT in shadow."""
    sun_dir = [1.0, 0.0, 0.0]
    r_sat = [-7000.0, 20000.0, 0.0]  # night side but 20,000 km off-axis
    assert in_earth_shadow(r_sat, sun_dir) is False


def test_shadow_arbitrary_sun_direction():
    """Shadow test works for an arbitrary (non-axis-aligned) Sun direction."""
    sun_dir = [0.5540, -0.8325, 0.0]  # a real-ish Sun direction
    norm = np.linalg.norm(sun_dir)
    sun_hat = [x / norm for x in sun_dir]
    # Day side
    r_day = [sun_hat[0] * 7000, sun_hat[1] * 7000, sun_hat[2] * 7000]
    assert in_earth_shadow(r_day, sun_hat) is False
    # Night side (on the line)
    r_night = [-sun_hat[0] * 7000, -sun_hat[1] * 7000, -sun_hat[2] * 7000]
    assert in_earth_shadow(r_night, sun_hat) is True


# --- SRP eclipse integration (offline) ---

def test_srp_zero_in_shadow():
    """SRP acceleration must be zero when the satellite is in Earth's shadow."""
    from engine.precision import srp_acceleration

    sun_dir = np.array([1.0, 0.0, 0.0])
    # Night side → shadow → zero SRP
    a = srp_acceleration(np.array([-7000.0, 0.0, 0.0]), 0.04, 4.0,
                         sun_dir=sun_dir, check_shadow=True)
    assert np.linalg.norm(a) == 0.0


def test_srp_nonzero_in_sunlight():
    """SRP acceleration must be nonzero when the satellite is in sunlight."""
    from engine.precision import srp_acceleration

    sun_dir = np.array([1.0, 0.0, 0.0])
    # Day side → sunlight → nonzero SRP
    a = srp_acceleration(np.array([7000.0, 0.0, 0.0]), 0.04, 4.0,
                         sun_dir=sun_dir, check_shadow=True)
    assert np.linalg.norm(a) > 0.0


def test_srp_without_shadow_check_always_nonzero():
    """Without the shadow check, SRP is nonzero even on the night side."""
    from engine.precision import srp_acceleration

    sun_dir = np.array([1.0, 0.0, 0.0])
    a = srp_acceleration(np.array([-7000.0, 0.0, 0.0]), 0.04, 4.0,
                         sun_dir=sun_dir, check_shadow=False)
    assert np.linalg.norm(a) > 0.0


def test_srp_anti_sunward_direction():
    """SRP force must point away from the Sun (anti-sunward)."""
    from engine.precision import srp_acceleration

    sun_dir = np.array([1.0, 0.0, 0.0])  # Sun toward +X
    a = srp_acceleration(np.array([7000.0, 0.0, 0.0]), 0.04, 4.0, sun_dir=sun_dir)
    # Acceleration should be in the -X direction (away from Sun)
    assert a[0] < 0


# --- sun_direction_geocentric (live, graceful) ---

def test_sun_direction_geocentric_live():
    """Live: the Sun direction must be a unit vector (skip if Horizons is down)."""
    sun_dir = sun_direction_geocentric("2026-07-27")
    if sun_dir is None:
        pytest.skip("Horizons unavailable")
    norm = np.linalg.norm(sun_dir)
    assert norm == pytest.approx(1.0, abs=1e-6)
    assert len(sun_dir) == 3
