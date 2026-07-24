"""Tests for engine/pc.py — collision probability behavior + hand-computed case."""

import numpy as np
import pytest

from engine.pc import collision_probability


def test_pc_hand_computed_zero_miss():
    """Zero miss, pure cross-track velocity -> Pc = hbr² (derivation in pc.py)."""
    pc = collision_probability(
        miss_rsw=np.array([0.0, 0.0, 0.0]),
        rel_vel_rsw=np.array([0.0, 0.0, 10.0]),
        hbr_km=0.005,
    )
    assert pc == pytest.approx(0.005**2, rel=1e-6)  # 2.5e-5


def test_pc_decreases_with_miss():
    # Miss perpendicular to velocity (radial) so it projects fully onto the B-plane.
    vrel = np.array([0.0, 0.0, 10.0])
    pc_near = collision_probability([0.001, 0.0, 0.0], vrel)
    pc_mid = collision_probability([0.01, 0.0, 0.0], vrel)
    pc_far = collision_probability([0.1, 0.0, 0.0], vrel)
    assert pc_near > pc_mid > pc_far


def test_pc_along_track_miss_does_not_reduce():
    """A miss parallel to velocity projects to zero on the B-plane (no separation)."""
    vrel = np.array([0.0, 0.0, 10.0])
    pc_zero = collision_probability([0.0, 0.0, 0.0], vrel)
    pc_along = collision_probability([0.0, 0.0, 0.01], vrel)  # along velocity
    assert pc_along == pytest.approx(pc_zero, rel=1e-6)


def test_pc_increases_with_hbr():
    miss, vrel = [0.0, 0.0, 0.0], [0.0, 0.0, 10.0]
    assert collision_probability(miss, vrel, hbr_km=0.01) > collision_probability(
        miss, vrel, hbr_km=0.005
    )


def test_pc_bounded():
    for miss in ([0, 0, 0], [0.001, 0, 0], [0.05, 0.02, 0.01], [1.0, 0, 0]):
        pc = collision_probability(miss, [0.0, 10.0, 0.0], hbr_km=0.005)
        assert 0.0 <= pc <= 1.0


def test_pc_general_orientation():
    """An arbitrary relative-velocity direction must still give a sane Pc."""
    pc = collision_probability([0.002, 0.001, 0.0], [-3.0, 9.0, 4.0], hbr_km=0.005)
    assert 0.0 < pc < 1e-2


def test_pc_zero_relative_velocity_is_degenerate():
    """Near-zero relative velocity -> B-plane undefined -> Pc 0.0 (not NaN)."""
    import math

    pc = collision_probability([0.001, 0.0, 0.0], [0.0, 0.0, 0.0], hbr_km=0.005)
    assert pc == 0.0
    assert not math.isnan(pc)
