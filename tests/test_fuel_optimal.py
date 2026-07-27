"""Tests for engine/fuel_optimal.py — minimum-Δv avoidance maneuvers."""

import numpy as np
import pytest

from engine.fuel_optimal import (
    cw_state_transition,
    optimal_burn_direction,
    fuel_optimal_burn,
)
from engine.precision import MU_EARTH, R_EARTH


def mean_motion_from_alt(alt_km: float) -> float:
    a = R_EARTH + alt_km
    return float(np.sqrt(MU_EARTH / a**3))


def test_cw_identity_at_zero():
    """Φ(0) must be the identity matrix."""
    n = mean_motion_from_alt(400.0)
    assert np.allclose(cw_state_transition(n, 0.0), np.eye(6), atol=1e-12)


def test_optimal_burn_direction_is_unit():
    """The optimal burn direction must be a unit vector."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([2.0, 1.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    d = optimal_burn_direction(n, 3600.0, miss, vrel)
    assert np.linalg.norm(d) == pytest.approx(1.0)


def test_optimal_burn_direction_increases_miss():
    """A small burn along the optimal direction must increase the miss distance."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([2.0, 1.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    lead = 3600.0
    d = optimal_burn_direction(n, lead, miss, vrel)
    phi = cw_state_transition(n, lead)
    phi_rv = phi[:3, 3:6]
    # Miss after a small Δv along d
    small_dv = d * 0.001  # 1 m/s in km/s
    miss_after = np.linalg.norm(miss + phi_rv @ small_dv)
    miss_before = np.linalg.norm(miss)
    assert miss_after > miss_before, "optimal direction should increase the miss"


def test_fuel_optimal_achieves_target():
    """The fuel-optimal burn must achieve (at least) the target miss distance."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([2.0, 1.0, 0.5])  # ~2.3 km initial miss
    vrel = np.array([0.0, 10.0, 0.0])
    target = 10.0  # km
    result = fuel_optimal_burn(n, 3600.0, miss, vrel, target)
    assert result["cw_predicted_miss_km"] >= target * 0.99, "should reach the target"
    assert result["dv_total_ms"] > 0, "should require a nonzero burn"
    assert result["propellant_g"] > 0


def test_fuel_optimal_is_efficient():
    """The fuel-optimal burn should use less Δv than a naive in-track-only burn
    to achieve the same target (it picks the best direction)."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([2.0, 1.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    target = 10.0
    lead = 3600.0
    # Fuel-optimal
    opt = fuel_optimal_burn(n, lead, miss, vrel, target)
    # Naive: brute-force search along in-track only
    phi = cw_state_transition(n, lead)
    phi_rv = phi[:3, 3:6]
    naive_dv = None
    for dv_ms in np.linspace(1, 2000, 2000):
        dv_kms = np.array([0.0, dv_ms / 1000.0, 0.0])  # in-track only
        if np.linalg.norm(miss + phi_rv @ dv_kms) >= target:
            naive_dv = dv_ms
            break
    assert naive_dv is not None, "naive search should find a solution"
    assert opt["dv_total_ms"] <= naive_dv * 1.05, (
        f"fuel-optimal ({opt['dv_total_ms']:.1f}) should beat naive ({naive_dv:.1f})"
    )


def test_fuel_optimal_no_burn_if_already_safe():
    """If the current miss already exceeds the target, no burn is needed."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([20.0, 0.0, 0.0])  # already 20 km
    vrel = np.array([0.0, 10.0, 0.0])
    target = 10.0
    result = fuel_optimal_burn(n, 3600.0, miss, vrel, target)
    assert result["dv_total_ms"] == 0.0
    assert result["propellant_g"] == 0.0
    assert "no burn required" in result.get("note", "")


def test_fuel_optimal_propellant_scales_with_dv():
    """More Δv must cost more propellant (rocket equation)."""
    n = mean_motion_from_alt(400.0)
    miss = np.array([2.0, 1.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    r1 = fuel_optimal_burn(n, 3600.0, miss, vrel, 5.0)
    r2 = fuel_optimal_burn(n, 3600.0, miss, vrel, 20.0)
    assert r2["propellant_g"] > r1["propellant_g"], "larger target should cost more propellant"
