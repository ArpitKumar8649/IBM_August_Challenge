"""Tests for engine/atmosphere.py — NRLMSISE-00 density & drag."""

import numpy as np
import pytest

from engine.atmosphere import (
    atmospheric_density,
    ballistic_coefficient,
    drag_acceleration,
    drag_acceleration_from_alt,
    _exponential_density,
)


def test_density_order_of_magnitude():
    """Density at 400 km should be ~1e-12 to 1e-11 kg/m³ (quiet, moderate solar)."""
    rho = atmospheric_density(400.0, f107=150.0, f107a=150.0, ap=4.0)
    assert 1e-13 < rho < 1e-10


def test_density_decreases_with_altitude():
    """Density must decrease monotonically with altitude in LEO."""
    alts = [200.0, 300.0, 400.0, 500.0, 600.0]
    densities = [atmospheric_density(a, f107=150.0, f107a=150.0, ap=4.0) for a in alts]
    for i in range(len(densities) - 1):
        assert densities[i] > densities[i + 1], f"density did not decrease at {alts[i]} km"


def test_density_storm_inflation():
    """High geomagnetic activity (AP=200) must inflate LEO density vs quiet (AP=4)."""
    quiet = atmospheric_density(400.0, f107=150.0, f107a=150.0, ap=4.0)
    storm = atmospheric_density(400.0, f107=150.0, f107a=150.0, ap=200.0)
    assert storm > quiet, "storm density should exceed quiet density"
    assert storm / quiet > 1.2, "storm inflation should be significant (>20%)"


def test_density_solar_activity_dependence():
    """Higher F10.7 (more solar activity) must increase density."""
    low = atmospheric_density(400.0, f107=70.0, f107a=70.0, ap=4.0)
    high = atmospheric_density(400.0, f107=250.0, f107a=250.0, ap=4.0)
    assert high > low, "high solar activity should increase density"


def test_exponential_fallback_reasonable():
    """The exponential fallback should give a sane order of magnitude."""
    rho = _exponential_density(400.0)
    assert 1e-13 < rho < 1e-10
    assert _exponential_density(300.0) > _exponential_density(500.0)


def test_ballistic_coefficient():
    """B = Cd·A/m. For Cd=2.2, A=0.04, m=4: B = 0.022 m²/kg."""
    b = ballistic_coefficient(4.0, 0.04, 2.2)
    assert b == pytest.approx(0.022)
    # Higher mass → lower ballistic coefficient (less drag-sensitive)
    assert ballistic_coefficient(8.0, 0.04, 2.2) < ballistic_coefficient(4.0, 0.04, 2.2)


def test_drag_acceleration_opposes_velocity():
    """Drag must oppose the velocity vector."""
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    rho = 3.5e-12
    a = drag_acceleration(r, v, rho)
    # Drag should be anti-parallel to velocity (negative y component)
    assert a[1] < 0, "drag should oppose +y velocity"
    assert abs(a[0]) < 1e-15 and abs(a[2]) < 1e-15, "drag should be along velocity only"


def test_drag_acceleration_magnitude():
    """Drag acceleration at 400 km should be ~1e-9 to 1e-5 km/s² (order check).

    For B=0.022 m²/kg, rho=3.5e-12 kg/m³, v=7.67 km/s: a ≈ 2.3e-9 km/s²
    (= 2.3e-6 m/s²), the correct order for LEO drag.
    """
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    rho = 3.5e-12
    a = drag_acceleration(r, v, rho)
    a_mag = np.linalg.norm(a)
    assert 1e-10 < a_mag < 1e-4, f"drag accel {a_mag} km/s² out of expected range"


def test_drag_increases_with_density():
    """Higher density → larger drag acceleration."""
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    a_low = np.linalg.norm(drag_acceleration(r, v, 1e-12))
    a_high = np.linalg.norm(drag_acceleration(r, v, 1e-11))
    assert a_high > a_low


def test_drag_acceleration_from_alt_uses_nrlmsise():
    """drag_acceleration_from_alt should look up density and produce nonzero drag."""
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    a = drag_acceleration_from_alt(r, v, f107=150.0, f107a=150.0, ap=4.0)
    assert np.linalg.norm(a) > 0, "drag should be nonzero at 400 km"
