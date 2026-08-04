"""Tests for engine/viz/bplane.py — B-plane projection + covariance ellipse.

The load-bearing property: the diagram must be the *same* geometry the Pc
computation sees. Several tests below pin that agreement numerically, so the plot
can never drift from the number it explains.
"""

import numpy as np
import pytest

from engine.pc import collision_probability
from engine.viz.bplane import SIGMA_LEVELS, analytic_covariance_rsw, bplane_data


def test_bplane_miss_projection_intrack_velocity():
    """For a purely in-track relative velocity, the B-plane is the (radial,
    cross-track) plane, so the in-track component of the miss is projected out."""
    miss_rsw = np.array([2.0, 1.0, 0.5])  # r=2, s=1, w=0.5
    rel_vel = np.array([0.0, 10.0, 0.0])  # purely in-track
    data = bplane_data(miss_rsw, rel_vel, hbr_km=0.005)
    assert data is not None
    assert not data["degenerate"]
    # The in-track component (1.0) lies along the velocity and is removed, leaving
    # sqrt(2^2 + 0.5^2) in plane.
    assert data["miss_norm_km"] == pytest.approx(np.sqrt(2.0**2 + 0.5**2), rel=1e-6)


def test_bplane_in_plane_miss_never_exceeds_3d_miss():
    """Projection removes a component, so the in-plane miss is <= the 3-D miss."""
    miss_rsw = np.array([1.0, 2.0, 0.3])
    rel_vel = np.array([0.5, 9.0, 0.2])
    data = bplane_data(miss_rsw, rel_vel)
    assert data is not None
    assert data["miss_norm_km"] <= np.linalg.norm(miss_rsw) + 1e-12


def test_bplane_axes_are_orthonormal_and_perpendicular_to_vrel():
    """The reported ξ/ζ axes must be an orthonormal basis of the plane
    perpendicular to the relative velocity — that is what makes them labelable."""
    rel_vel = np.array([0.5, 9.0, 0.2])
    data = bplane_data(np.array([1.0, 2.0, 0.3]), rel_vel)
    assert data is not None
    xi = np.array(data["axes_rsw"]["xi"])
    zeta = np.array(data["axes_rsw"]["zeta"])
    assert np.linalg.norm(xi) == pytest.approx(1.0, abs=1e-12)
    assert np.linalg.norm(zeta) == pytest.approx(1.0, abs=1e-12)
    assert float(xi @ zeta) == pytest.approx(0.0, abs=1e-12)
    v_hat = rel_vel / np.linalg.norm(rel_vel)
    assert float(xi @ v_hat) == pytest.approx(0.0, abs=1e-12)
    assert float(zeta @ v_hat) == pytest.approx(0.0, abs=1e-12)


def test_bplane_ellipse_semi_axes_ordered():
    """Semi-major axis must be >= semi-minor axis."""
    data = bplane_data(np.array([1.0, 2.0, 0.3]), np.array([0.5, 9.0, 0.2]))
    assert data is not None
    e = data["ellipse"]
    assert e["semi_major_km"] >= e["semi_minor_km"]
    assert e["semi_minor_km"] > 0.0


def test_bplane_ellipse_rotation_normalised_to_half_turn():
    """An ellipse's orientation is defined mod 180°, so the reported angle must
    live in [-90, 90) — a major axis along +ξ reads as ~0°, never as ~-180°."""
    for vel in ([0.0, 10.0, 0.0], [0.5, 9.0, 0.2], [7.0, 7.0, 1.0], [1.0, 0.0, 0.0]):
        data = bplane_data(np.array([1.0, 2.0, 0.3]), np.array(vel))
        assert data is not None
        assert -90.0 <= data["ellipse"]["rotation_deg"] < 90.0


def test_bplane_sigma_levels_scale_linearly():
    """An nσ ellipse is the 1σ ellipse scaled by n, at the same orientation."""
    data = bplane_data(np.array([1.0, 2.0, 0.3]), np.array([0.5, 9.0, 0.2]))
    assert data is not None
    base = data["ellipse"]
    assert [lvl["level"] for lvl in data["sigma_levels"]] == list(SIGMA_LEVELS)
    for lvl in data["sigma_levels"]:
        n = lvl["level"]
        assert lvl["semi_major_km"] == pytest.approx(base["semi_major_km"] * n)
        assert lvl["semi_minor_km"] == pytest.approx(base["semi_minor_km"] * n)
        assert lvl["rotation_deg"] == pytest.approx(base["rotation_deg"])


def test_bplane_miss_inside_hbr():
    """A miss smaller than the HBR should be flagged as inside."""
    data = bplane_data(np.array([0.001, 0.001, 0.001]), np.array([0.0, 10.0, 0.0]), hbr_km=0.005)
    assert data is not None
    assert data["miss_inside_hbr"] is True


def test_bplane_miss_outside_hbr():
    """A km-scale miss is far outside a 5 m hard-body radius."""
    data = bplane_data(np.array([2.0, 1.0, 0.5]), np.array([0.0, 10.0, 0.0]), hbr_km=0.005)
    assert data is not None
    assert data["miss_inside_hbr"] is False


def test_bplane_degenerate_zero_velocity():
    """Zero relative velocity -> B-plane undefined -> returns None."""
    assert bplane_data(np.array([1.0, 2.0, 0.3]), np.array([0.0, 0.0, 0.0])) is None


def test_bplane_pc_matches_engine_pc_exactly():
    """The plot's Pc must equal engine.pc.collision_probability to floating-point
    precision — same basis, same covariance, same closed form."""
    miss_rsw = np.array([1.0, 2.0, 0.3])
    rel_vel = np.array([0.5, 9.0, 0.2])
    hbr = 0.005
    data = bplane_data(miss_rsw, rel_vel, hbr_km=hbr)
    assert data is not None
    assert data["pc"] == pytest.approx(
        collision_probability(miss_rsw, rel_vel, hbr_km=hbr), rel=1e-12
    )


def test_bplane_pc_matches_engine_pc_for_a_close_approach():
    """Agreement must hold where Pc is actually non-negligible, not just in the
    far-miss tail where both are ~0."""
    miss_rsw = np.array([0.05, 0.02, 0.01])  # ~50 m miss
    rel_vel = np.array([0.0, 7.5, 0.0])
    hbr = 0.02
    data = bplane_data(miss_rsw, rel_vel, hbr_km=hbr)
    assert data is not None
    assert data["pc"] > 1e-6  # a real, readable probability
    assert data["pc"] == pytest.approx(
        collision_probability(miss_rsw, rel_vel, hbr_km=hbr), rel=1e-12
    )


def test_bplane_uses_engine_pc_covariance():
    """The plot's covariance is engine/pc.py's, not a private copy — otherwise the
    ellipse could silently disagree with the Pc it is drawn beside."""
    from engine.pc import SIGMA_CROSSTRACK_KM, SIGMA_INTRACK_KM, SIGMA_RADIAL_KM

    cov = analytic_covariance_rsw()
    assert np.allclose(
        np.diag(cov),
        [SIGMA_RADIAL_KM**2, SIGMA_INTRACK_KM**2, SIGMA_CROSSTRACK_KM**2],
    )


def test_bplane_mahalanobis_and_containing_contour_agree():
    """mahalanobis_sigma is the miss in sigmas; the reported contour is the
    smallest of 1/2/3 that contains it, or None beyond 3σ."""
    rel_vel = np.array([0.0, 10.0, 0.0])
    # Radial sigma is 0.5 km, so a 0.4 km radial miss sits inside 1σ.
    near = bplane_data(np.array([0.4, 0.0, 0.0]), rel_vel)
    assert near is not None
    assert near["mahalanobis_sigma"] == pytest.approx(0.8, rel=1e-9)
    assert near["sigma_contour_containing_miss"] == 1
    # A 20 km miss is far beyond 3σ.
    far = bplane_data(np.array([20.0, 0.0, 0.0]), rel_vel)
    assert far is not None
    assert far["mahalanobis_sigma"] > 3.0
    assert far["sigma_contour_containing_miss"] is None


def test_bplane_realism_inflates_uncertainty_and_is_optional():
    """The realism factor scales the covariance by k, so the ellipse grows by
    sqrt(k) and the miss sits at fewer sigmas. Absent unless requested."""
    miss_rsw = np.array([1.0, 2.0, 0.3])
    rel_vel = np.array([0.5, 9.0, 0.2])
    plain = bplane_data(miss_rsw, rel_vel)
    assert plain is not None
    assert "realism" not in plain

    k = 2.0
    data = bplane_data(miss_rsw, rel_vel, realism_factor=k)
    assert data is not None
    r = data["realism"]
    assert r["factor"] == k
    assert r["ellipse"]["semi_major_km"] == pytest.approx(
        data["ellipse"]["semi_major_km"] * np.sqrt(k)
    )
    # More uncertainty -> the same miss is fewer sigmas out, and Pc rises.
    assert r["mahalanobis_sigma"] < data["mahalanobis_sigma"]
    assert r["pc"] > data["pc"]


def test_bplane_realism_pc_matches_realistic_pc_module():
    """The realism-inflated Pc must match engine/covariance.py's general 2-D Pc —
    the plot's second contour set explains that number, so it must be that number."""
    from engine.covariance import collision_probability_general

    miss_rsw = np.array([0.05, 0.02, 0.01])
    rel_vel = np.array([0.0, 7.5, 0.0])
    hbr, k = 0.02, 2.0
    data = bplane_data(miss_rsw, rel_vel, hbr_km=hbr, realism_factor=k)
    assert data is not None
    assert data["realism"]["pc"] == pytest.approx(
        collision_probability_general(miss_rsw, rel_vel, hbr, realism_factor=k),
        rel=1e-12,
    )


def test_bplane_accepts_custom_covariance():
    """A caller-supplied covariance must drive the ellipse — an isotropic one
    projects to a circle (semi-major == semi-minor)."""
    iso = np.diag([0.25, 0.25, 0.25])  # 0.5 km sigma in every axis
    data = bplane_data(
        np.array([1.0, 2.0, 0.3]), np.array([0.5, 9.0, 0.2]), covariance_rsw=iso
    )
    assert data is not None
    e = data["ellipse"]
    assert e["semi_major_km"] == pytest.approx(0.5, rel=1e-9)
    assert e["semi_minor_km"] == pytest.approx(0.5, rel=1e-9)


def test_bplane_ellipse_anisotropic_for_default_covariance():
    """The default RSW covariance is anisotropic (in-track 1.0 km vs 0.5 km), so a
    general B-plane orientation projects to a genuinely elongated ellipse."""
    data = bplane_data(np.array([1.0, 2.0, 0.3]), np.array([0.5, 9.0, 0.2]))
    assert data is not None
    assert data["ellipse"]["semi_major_km"] > data["ellipse"]["semi_minor_km"]


def test_bplane_invariant_under_rotation_within_the_plane():
    """Pc and the in-plane miss magnitude must not depend on how the ξ/ζ axes
    happen to be oriented inside the plane — only on the geometry."""
    miss_rsw = np.array([1.0, 2.0, 0.3])
    a = bplane_data(miss_rsw, np.array([0.0, 9.0, 0.0]), hbr_km=0.01)
    b = bplane_data(miss_rsw, np.array([0.0, -9.0, 0.0]), hbr_km=0.01)
    assert a is not None and b is not None
    assert a["miss_norm_km"] == pytest.approx(b["miss_norm_km"], rel=1e-12)
    assert a["pc"] == pytest.approx(b["pc"], rel=1e-12)
