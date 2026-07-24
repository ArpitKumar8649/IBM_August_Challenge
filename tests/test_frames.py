"""Tests for engine/frames.py — hand-computed RSW cases."""

import numpy as np
import pytest

from engine.frames import miss_distance, relative_state_rsw, rsw_rotation


def test_rsw_identity_for_equatorial_x_axis_orbit():
    """r along +x, v along +y -> RSW axes align with TEME axes."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    R = rsw_rotation(r, v)
    assert np.allclose(R, np.eye(3), atol=1e-12)


def test_rsw_radial_displacement():
    """A secondary 5 km further out along r is +5 radial, 0 in-track/cross."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    dr_rsw, _ = relative_state_rsw(r, v, r + np.array([5.0, 0.0, 0.0]), v)
    assert np.allclose(dr_rsw, [5.0, 0.0, 0.0], atol=1e-12)


def test_rsw_intrack_displacement():
    """A secondary 3 km ahead along v is +3 in-track."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    dr_rsw, _ = relative_state_rsw(r, v, r + np.array([0.0, 3.0, 0.0]), v)
    assert np.allclose(dr_rsw, [0.0, 3.0, 0.0], atol=1e-12)


def test_rsw_crosstrack_displacement():
    """A secondary 2 km north is +2 cross-track."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    dr_rsw, _ = relative_state_rsw(r, v, r + np.array([0.0, 0.0, 2.0]), v)
    assert np.allclose(dr_rsw, [0.0, 0.0, 2.0], atol=1e-12)


def test_rsw_rotated_orbit():
    """r along +y, v along -x: r_hat=[0,1,0], w_hat=[0,0,1], t_hat=[-1,0,0]."""
    r = np.array([0.0, 7000.0, 0.0])
    v = np.array([-7.5, 0.0, 0.0])
    R = rsw_rotation(r, v)
    expected = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    assert np.allclose(R, expected, atol=1e-12)


def test_relative_velocity_intrack():
    """Secondary 0.1 km/s faster -> +0.1 in-track relative velocity."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    _, dv_rsw = relative_state_rsw(r, v, r, v + np.array([0.0, 0.1, 0.0]))
    assert np.allclose(dv_rsw, [0.0, 0.1, 0.0], atol=1e-12)


def test_miss_distance_345():
    assert miss_distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0]) == pytest.approx(5.0)


def test_rotation_is_orthonormal():
    """R @ R.T == I and det(R) == +1 for an arbitrary inclined orbit."""
    r = np.array([5000.0, 3000.0, 4000.0])
    v = np.array([-2.0, 6.5, 1.5])
    R = rsw_rotation(r, v)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(R) == pytest.approx(1.0)
