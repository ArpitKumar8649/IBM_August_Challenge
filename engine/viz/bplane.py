"""B-plane visualization data — the canonical conjunction-assessment diagram.

The B-plane is the plane perpendicular to the relative-velocity vector at TCA.
The miss vector projects onto it, and the combined position covariance projects to
a 2-D ellipse. This is *the* diagram a conjunction analyst looks at: the miss
point, the hard-body radius (the "collision" circle), and the 1σ/2σ/3σ covariance
ellipses (the uncertainty).

This module reuses the B-plane basis and the fixed covariance from engine/pc.py, so
the plot is *exactly* the geometry the Pc computation sees: the returned ``pc`` is
recomputed from the projected quantities and equals ``engine.pc.collision_probability``
to floating-point precision. The plot cannot drift from the number it explains.

The in-plane orientation of the (ξ, ζ) axes is not itself physical — Pc is invariant
under rotation within the B-plane — so the basis vectors are reported in RSW
components, letting a plot label its axes honestly ("ξ is mostly radial").

References:
  Alfriend & Akella (2000), "Collision Probability for Spacecraft" — general 2-D Pc
  Foster (1992), short-term encounter probability
  Hall & Do, "Covariance Realism" — the realism factor (Σ_real = k·Σ_analytic)
"""

from __future__ import annotations

import numpy as np

from engine.pc import (
    DEFAULT_HBR_KM,
    SIGMA_CROSSTRACK_KM,
    SIGMA_INTRACK_KM,
    SIGMA_RADIAL_KM,
    _b_plane_basis,
)

# The sigma contours a conjunction plot draws. 1σ ≈ 39% of the 2-D probability
# mass, 2σ ≈ 86%, 3σ ≈ 99%.
SIGMA_LEVELS = (1, 2, 3)


def _ellipse(sigma_bp: np.ndarray) -> dict:
    """1σ covariance ellipse (semi-axes in km, orientation in degrees).

    The semi-axes are the square roots of the eigenvalues of the projected
    covariance; the orientation is the angle of the major-axis eigenvector.
    An ellipse's orientation is defined modulo 180°, so the angle is normalised
    into [-90, 90) — otherwise a major axis lying along +ξ can be reported as
    -179.6° instead of the equivalent +0.4°, which reads as a bug in a plot.
    """
    eigvals, eigvecs = np.linalg.eigh(sigma_bp)  # ascending eigenvalues
    major_vec = eigvecs[:, -1]
    rotation = float(np.degrees(np.arctan2(major_vec[1], major_vec[0])))
    return {
        "semi_major_km": float(np.sqrt(max(eigvals[-1], 0.0))),
        "semi_minor_km": float(np.sqrt(max(eigvals[0], 0.0))),
        "rotation_deg": ((rotation + 90.0) % 180.0) - 90.0,
    }


def _scaled_levels(ellipse: dict) -> list[dict]:
    """The 1σ/2σ/3σ contours — an nσ ellipse is the 1σ ellipse scaled by n."""
    return [
        {
            "level": n,
            "semi_major_km": ellipse["semi_major_km"] * n,
            "semi_minor_km": ellipse["semi_minor_km"] * n,
            "rotation_deg": ellipse["rotation_deg"],
        }
        for n in SIGMA_LEVELS
    ]


def _pc_from_projection(m_bp: np.ndarray, sigma_bp: np.ndarray, hbr_km: float) -> float:
    """Short-term encounter Pc evaluated from the already-projected quantities.

    Pc = HBR² / (2·sqrt(det Σ_bp)) · exp(−½ · m_bpᵀ Σ_bp⁻¹ m_bp) — the same closed
    form as engine.pc.collision_probability, so the plot and the number agree.
    """
    det = float(np.linalg.det(sigma_bp))
    if det <= 0:
        return 0.0
    exponent = -0.5 * float(m_bp @ np.linalg.inv(sigma_bp) @ m_bp)
    return float(min((hbr_km**2 / (2.0 * np.sqrt(det))) * np.exp(exponent), 1.0))


def analytic_covariance_rsw() -> np.ndarray:
    """The fixed diagonal combined covariance (km²) that engine.pc.Pc uses.

    Built from engine/pc.py's own sigmas rather than a copy, so the plot can never
    show an ellipse the Pc computation does not share.
    """
    return np.diag(
        [SIGMA_RADIAL_KM**2, SIGMA_INTRACK_KM**2, SIGMA_CROSSTRACK_KM**2]
    )


def bplane_data(
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    hbr_km: float = DEFAULT_HBR_KM,
    covariance_rsw: np.ndarray | None = None,
    realism_factor: float | None = None,
) -> dict | None:
    """Compute the B-plane plot data for a conjunction.

    Args:
        miss_rsw: relative position at TCA (km), primary's RSW frame [r, s, w].
        rel_vel_rsw: relative velocity at TCA (km/s), primary's RSW frame.
        hbr_km: hard-body radius (km) — the combined collision cross-section.
        covariance_rsw: combined position covariance in RSW (km²). Defaults to
            engine/pc.py's documented fixed covariance.
        realism_factor: optional covariance-realism factor k (Σ_real = k·Σ_analytic,
            Foster/Hall). When given, a second set of contours and a second Pc are
            returned alongside the analytic ones, so a plot can show both.

    Returns:
        A dict with:
          miss_bp: [ξ, ζ] — the miss point projected onto the B-plane (km)
          miss_norm_km: |miss_bp| (km) — the in-plane miss distance
          hbr_km / miss_inside_hbr: the collision circle and whether the miss is in it
          ellipse: the 1σ ellipse {semi_major_km, semi_minor_km, rotation_deg}
          sigma_levels: the 1σ/2σ/3σ contours, each with its own semi-axes
          mahalanobis_sigma: |miss| in sigmas — how far out the miss sits on the
            uncertainty distribution (the honest "how close was this really?")
          sigma_contour_containing_miss: the smallest integer contour the miss falls
            inside, or None when it lies beyond 3σ
          pc: Pc recomputed from this projection (== engine.pc.collision_probability)
          axes_rsw: the ξ/ζ basis vectors in RSW components, for honest axis labels
          realism: present only when realism_factor is given — {factor, ellipse,
            sigma_levels, pc, mahalanobis_sigma} for the inflated covariance
          degenerate: always False (a degenerate encounter returns None instead)
        Returns None if the relative velocity is (near) zero — the B-plane, and
        therefore the whole diagram, is undefined.
    """
    basis = _b_plane_basis(rel_vel_rsw)
    if basis is None:
        return None

    miss_rsw = np.asarray(miss_rsw, float)
    sigma_rsw = (
        analytic_covariance_rsw() if covariance_rsw is None
        else np.asarray(covariance_rsw, float)
    )

    # Project the miss vector and the covariance onto the B-plane. The in-plane
    # miss is shorter than the 3-D miss: the component along the relative velocity
    # is removed, because at TCA the objects are closest *across* the encounter,
    # and only the in-plane separation can put them inside the hard-body circle.
    miss_bp = basis @ miss_rsw  # [ξ, ζ]
    sigma_bp = basis @ sigma_rsw @ basis.T  # [2, 2]
    miss_norm = float(np.linalg.norm(miss_bp))

    ellipse = _ellipse(sigma_bp)
    levels = _scaled_levels(ellipse)

    # Mahalanobis distance — the miss expressed in sigmas of the uncertainty
    # distribution. This is what makes the plot readable: a 3 km miss with a 1 km
    # covariance is a 3σ event; the same miss with a 5 km covariance is not.
    inv = np.linalg.inv(sigma_bp)
    mahalanobis = float(np.sqrt(max(float(miss_bp @ inv @ miss_bp), 0.0)))
    containing = next((n for n in SIGMA_LEVELS if mahalanobis <= n), None)

    result = {
        "miss_bp": [float(miss_bp[0]), float(miss_bp[1])],
        "miss_norm_km": miss_norm,
        "hbr_km": float(hbr_km),
        "miss_inside_hbr": bool(miss_norm < hbr_km),
        "ellipse": ellipse,
        "sigma_levels": levels,
        "mahalanobis_sigma": mahalanobis,
        "sigma_contour_containing_miss": containing,
        "pc": _pc_from_projection(miss_bp, sigma_bp, hbr_km),
        "axes_rsw": {
            "xi": [float(v) for v in basis[0]],
            "zeta": [float(v) for v in basis[1]],
        },
        "degenerate": False,
    }

    if realism_factor is not None:
        sigma_real = float(realism_factor) * sigma_bp
        real_ellipse = _ellipse(sigma_real)
        inv_real = np.linalg.inv(sigma_real)
        result["realism"] = {
            "factor": float(realism_factor),
            "ellipse": real_ellipse,
            "sigma_levels": _scaled_levels(real_ellipse),
            "pc": _pc_from_projection(miss_bp, sigma_real, hbr_km),
            "mahalanobis_sigma": float(
                np.sqrt(max(float(miss_bp @ inv_real @ miss_bp), 0.0))
            ),
        }

    return result
