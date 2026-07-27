"""Tests for engine/covariance.py — realistic collision probability."""

import numpy as np
import pytest

from engine.covariance import (
    DEFAULT_REALISM_FACTOR,
    analytic_covariance_rsw,
    realistic_covariance_rsw,
    collision_probability_general,
    collision_probability_both,
)
from engine.pc import collision_probability as pc_fixed


def test_realism_factor_inflates_covariance():
    """Realism-adjusted covariance must be k× the analytic covariance."""
    analytic = analytic_covariance_rsw()
    realistic = realistic_covariance_rsw(DEFAULT_REALISM_FACTOR)
    assert np.allclose(realistic, DEFAULT_REALISM_FACTOR * analytic)


def test_general_pc_matches_fixed_for_diagonal():
    """For a diagonal covariance, the general formula must match the fixed one
    (up to the realism factor). With realism_factor=1, they should be identical."""
    miss = np.array([1.0, 2.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    hbr = 0.005
    pc_general = collision_probability_general(miss, vrel, hbr, realism_factor=1.0)
    pc_ref = pc_fixed(miss, vrel, hbr)
    assert pc_general == pytest.approx(pc_ref, rel=1e-6)


def test_realism_factor_dilutes_at_origin():
    """For a miss AT the origin, a larger realism factor monotonically reduces Pc
    (pure probability dilution — the peak density at the origin falls as 1/det Σ)."""
    miss = np.array([0.0, 0.0, 0.0])
    vrel = np.array([0.0, 10.0, 0.0])
    hbr = 0.005
    pc_k1 = collision_probability_general(miss, vrel, hbr, realism_factor=1.0)
    pc_k3 = collision_probability_general(miss, vrel, hbr, realism_factor=3.0)
    assert pc_k3 < pc_k1, "at the origin, larger covariance must dilute (reduce) Pc"


def test_pc_nonmonotonic_in_covariance_for_offset_miss():
    """Physics subtlety: for an OFF-CENTER miss, Pc is non-monotonic in covariance.

    Increasing covariance first *increases* Pc (spreading probability density
    toward the hard body) before dilution dominates. This is a well-known feature
    of the 2-D encounter integral — we verify the peak exists rather than assuming
    monotonic dilution.
    """
    miss = np.array([1.0, 2.0, 0.5])  # off-center
    vrel = np.array([0.0, 10.0, 0.0])
    hbr = 0.005
    pcs = [
        collision_probability_general(miss, vrel, hbr, realism_factor=k)
        for k in [0.2, 0.5, 1.0, 2.0, 5.0, 20.0]
    ]
    # Pc should rise then fall — there's an interior maximum.
    peak_idx = int(np.argmax(pcs))
    assert 0 < peak_idx < len(pcs) - 1, (
        f"Pc should be non-monotonic (peak in the interior), got {pcs}"
    )
    # And for very large covariance, dilution must eventually dominate.
    assert pcs[-1] < max(pcs), "very large covariance should dilute below the peak"


def test_pc_decreases_with_miss():
    """Pc must decrease as miss distance increases."""
    vrel = np.array([0.0, 10.0, 0.0])
    hbr = 0.005
    pc_near = collision_probability_general([0.5, 0.0, 0.0], vrel, hbr)
    pc_far = collision_probability_general([5.0, 0.0, 0.0], vrel, hbr)
    assert pc_near > pc_far


def test_pc_bounded():
    """Pc must be in [0, 1]."""
    for miss in ([0, 0, 0], [0.001, 0, 0], [1.0, 2.0, 0.5], [10.0, 0, 0]):
        pc = collision_probability_general(miss, [0.0, 10.0, 0.0], 0.005)
        assert 0.0 <= pc <= 1.0


def test_pc_zero_vrel_degenerate():
    """Zero relative velocity → undefined B-plane → Pc = 0."""
    pc = collision_probability_general([1.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0.005)
    assert pc == 0.0


def test_collision_probability_both_returns_both():
    """collision_probability_both must return analytic, realistic, and the factor.

    Note: pc_realistic is NOT guaranteed to be <= pc_analytic — for off-center
    misses, increasing covariance can increase Pc (see non-monotonicity test).
    We only assert both are valid probabilities and the factor is reported.
    """
    result = collision_probability_both([1.0, 2.0, 0.5], [0.0, 10.0, 0.0], 0.005)
    assert "pc_analytic" in result
    assert "pc_realistic" in result
    assert "realism_factor" in result
    assert result["realism_factor"] == DEFAULT_REALISM_FACTOR
    assert 0.0 <= result["pc_analytic"] <= 1.0
    assert 0.0 <= result["pc_realistic"] <= 1.0


def test_correlated_covariance_handled():
    """The general formula must handle a correlated (non-diagonal) covariance."""
    miss = np.array([1.0, 2.0, 0.5])
    vrel = np.array([0.0, 10.0, 0.0])
    # A correlated covariance (off-diagonal terms)
    cov = np.array([
        [0.25, 0.1, 0.0],
        [0.1, 1.0, 0.0],
        [0.0, 0.0, 0.25],
    ])
    pc = collision_probability_general(miss, vrel, 0.005, covariance_rsw=cov)
    assert 0.0 <= pc <= 1.0
