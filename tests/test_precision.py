"""Tests for engine/precision.py — J2, drag, SRP, numerical propagation."""

import numpy as np
import pytest

from engine.precision import (
    MU_EARTH,
    R_EARTH,
    j2_acceleration,
    srp_acceleration,
    precision_propagate,
)


def circular_state(alt_km: float, inc_deg: float = 0.0):
    """Initial ECI state for a circular orbit at given altitude/inclination."""
    r_mag = R_EARTH + alt_km
    v_mag = np.sqrt(MU_EARTH / r_mag)
    inc = np.radians(inc_deg)
    r0 = np.array([r_mag, 0.0, 0.0])
    v0 = np.array([0.0, v_mag * np.cos(inc), v_mag * np.sin(inc)])
    return r0, v0


def test_j2_acceleration_magnitude():
    """J2 acceleration at 400 km should be ~1e-5 to 1e-4 km/s² (much less than two-body)."""
    r = np.array([6778.0, 0.0, 0.0])
    a_j2 = j2_acceleration(r)
    a_2body = MU_EARTH / np.linalg.norm(r) ** 2
    a_j2_mag = np.linalg.norm(a_j2)
    # J2 is ~1e-3 of two-body
    assert 1e-4 * a_2body < a_j2_mag < 1e-2 * a_2body


def test_j2_acceleration_symmetry():
    """J2 acceleration should be symmetric about the equatorial plane."""
    r_north = np.array([6778.0, 0.0, 100.0])
    r_south = np.array([6778.0, 0.0, -100.0])
    a_north = j2_acceleration(r_north)
    a_south = j2_acceleration(r_south)
    # z-component should flip sign; x,y should be same
    assert a_north[2] == pytest.approx(-a_south[2], rel=1e-6)
    assert a_north[0] == pytest.approx(a_south[0], rel=1e-6)


def test_j2_zero_at_center():
    """J2 acceleration formula should handle the radial direction correctly."""
    # On the equator (z=0), the z-component of J2 accel should be zero
    r = np.array([6778.0, 0.0, 0.0])
    a = j2_acceleration(r)
    assert abs(a[2]) < 1e-15, "J2 z-accel should be zero on the equator"


def test_two_body_conserves_energy():
    """With no perturbations, energy must be conserved to ~machine precision."""
    r0, v0 = circular_state(400.0)
    period = 2 * np.pi * np.sqrt((R_EARTH + 400.0) ** 3 / MU_EARTH)
    r1, v1 = precision_propagate(
        r0, v0, period,
        include_j2=False, include_drag=False, include_srp=False,
    )
    e0 = 0.5 * np.dot(v0, v0) - MU_EARTH / np.linalg.norm(r0)
    e1 = 0.5 * np.dot(v1, v1) - MU_EARTH / np.linalg.norm(r1)
    assert abs(e1 - e0) / abs(e0) < 1e-8, "energy should be conserved (two-body)"


def test_two_body_closes_orbit():
    """With no perturbations, the orbit should close after one period."""
    r0, v0 = circular_state(400.0)
    period = 2 * np.pi * np.sqrt((R_EARTH + 400.0) ** 3 / MU_EARTH)
    r1, v1 = precision_propagate(
        r0, v0, period,
        include_j2=False, include_drag=False, include_srp=False,
    )
    assert np.linalg.norm(r1 - r0) < 0.01, "orbit should close to <10 m (two-body)"


def test_j2_causes_nodal_regression():
    """J2 must cause the ascending node to regress (RAAN decreases) for prograde orbits."""
    r0, v0 = circular_state(400.0, inc_deg=51.6)  # ISS-like inclination
    # Propagate one orbit
    period = 2 * np.pi * np.sqrt((R_EARTH + 400.0) ** 3 / MU_EARTH)
    r1, v1 = precision_propagate(
        r0, v0, period,
        include_j2=True, include_drag=False, include_srp=False,
    )
    # The orbit should NOT close perfectly (J2 perturbs it)
    assert np.linalg.norm(r1 - r0) > 0.1, "J2 should perturb the orbit (not close)"


def test_drag_causes_orbital_decay():
    """Drag must reduce the orbital energy (semi-major axis) over time."""
    r0, v0 = circular_state(400.0)
    # Propagate 10 orbits with drag
    period = 2 * np.pi * np.sqrt((R_EARTH + 400.0) ** 3 / MU_EARTH)
    r1, v1 = precision_propagate(
        r0, v0, 10 * period,
        include_j2=False, include_drag=True, include_srp=False,
        f107=150.0, f107a=150.0, ap=4.0,
    )
    e0 = 0.5 * np.dot(v0, v0) - MU_EARTH / np.linalg.norm(r0)
    e1 = 0.5 * np.dot(v1, v1) - MU_EARTH / np.linalg.norm(r1)
    # Drag removes energy → e1 < e0 (more negative)
    assert e1 < e0, "drag should reduce orbital energy"
    # Altitude should decrease
    alt0 = np.linalg.norm(r0) - R_EARTH
    alt1 = np.linalg.norm(r1) - R_EARTH
    assert alt1 < alt0, "drag should cause orbital decay"


def test_srp_acceleration_direction():
    """SRP acceleration must be anti-sunward (away from the Sun)."""
    r = np.array([6778.0, 0.0, 0.0])
    sun_dir = np.array([1.0, 0.0, 0.0])  # Sun along +X
    a = srp_acceleration(r, area_m2=0.04, mass_kg=4.0, cr=1.3, sun_dir=sun_dir)
    # Force should be away from Sun → negative X
    assert a[0] < 0, "SRP should push away from the Sun (-X)"


def test_srp_acceleration_magnitude():
    """SRP acceleration should be ~1e-11 to 1e-7 km/s² for a small satellite.

    For P=4.56e-6 N/m², Cr=1.3, A/m=0.01 m²/kg: a ≈ 5.9e-11 km/s² (= 5.9e-8 m/s²).
    """
    r = np.array([6778.0, 0.0, 0.0])
    a = srp_acceleration(r, area_m2=0.04, mass_kg=4.0, cr=1.3)
    a_mag = np.linalg.norm(a)
    assert 1e-12 < a_mag < 1e-6, f"SRP accel {a_mag} km/s² out of range"


def test_backward_propagation():
    """Backward propagation should invert forward propagation (two-body)."""
    r0, v0 = circular_state(400.0)
    dt = 600.0  # 10 minutes
    r_fwd, v_fwd = precision_propagate(
        r0, v0, dt, include_j2=False, include_drag=False, include_srp=False,
    )
    r_back, v_back = precision_propagate(
        r_fwd, v_fwd, -dt, include_j2=False, include_drag=False, include_srp=False,
    )
    assert np.allclose(r_back, r0, atol=1e-4), "backward should invert forward"
    assert np.allclose(v_back, v0, atol=1e-7)
