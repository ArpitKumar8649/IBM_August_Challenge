"""Realistic collision probability — general 2-D Alfriend-Foster with covariance realism.

Extends the fixed-covariance Pc (engine/pc.py) with:
  · The *general* 2-D encounter probability for an arbitrary (possibly
    correlated) combined covariance on the B-plane.
  · A documented **covariance realism factor** that inflates the analytic
    covariance toward operational realism (Foster/Hall). Real Pc needs each
    object's tracking covariance, which only CDM issuers possess; the realism
    factor is the standard, honest way to bridge that gap.

The fixed-covariance Pc remains the default (fast, transparent); this module
adds the realism-adjusted Pc as a documented, defensible refinement.

References:
  Alfriend & Akella (2000), "Collision Probability for Spacecraft" — general 2-D Pc
  Foster (1992), short-term encounter probability
  Hall & Do, "Covariance Realism" — realism factor methodology
  CCSDS 508.0-B-1 (Conjunction Data Message)
"""

from __future__ import annotations

import numpy as np

from engine.pc import _b_plane_basis

# Documented covariance realism factor. Operational analyses inflate analytic
# covariance by a factor k (Σ_real = k·Σ_analytic) to match observed miss
# statistics. k in [1.5, 3] is typical for LEO TLE-based screening; we use a
# conservative, documented default. This is an explicit assumption, stated in
# the UI and the card — not hidden.
DEFAULT_REALISM_FACTOR = 2.0

# Baseline analytic combined covariance (1-sigma, km) in RSW — matches engine/pc.py.
SIGMA_RADIAL_KM = 0.5
SIGMA_INTRACK_KM = 1.0
SIGMA_CROSSTRACK_KM = 0.5


def analytic_covariance_rsw() -> np.ndarray:
    """Baseline diagonal combined covariance in RSW (km²)."""
    return np.diag(
        [SIGMA_RADIAL_KM**2, SIGMA_INTRACK_KM**2, SIGMA_CROSSTRACK_KM**2]
    )


def realistic_covariance_rsw(realism_factor: float = DEFAULT_REALISM_FACTOR) -> np.ndarray:
    """Realism-adjusted combined covariance in RSW: Σ_real = k · Σ_analytic."""
    return realism_factor * analytic_covariance_rsw()


def collision_probability_general(
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    hbr_km: float,
    covariance_rsw: np.ndarray | None = None,
    realism_factor: float = DEFAULT_REALISM_FACTOR,
) -> float:
    """General 2-D Alfriend-Foster collision probability with realistic covariance.

    Projects the combined covariance onto the B-plane (perpendicular to relative
    velocity), then evaluates the general 2-D Gaussian encounter integral:

        Pc = HBR² / (2·sqrt(det Σ_bp)) · exp(−½ · m_bpᵀ Σ_bp⁻¹ m_bp)

    This reduces to the fixed-covariance formula when Σ_bp is diagonal, but
    correctly handles correlated covariance projected onto an arbitrary B-plane.

    Args:
        miss_rsw: relative position at TCA (km), primary's RSW frame.
        rel_vel_rsw: relative velocity at TCA (km/s), primary's RSW frame.
        hbr_km: hard-body radius (km).
        covariance_rsw: combined covariance in RSW (km²); defaults to the
            realism-adjusted analytic covariance.
        realism_factor: covariance realism factor k (Σ_real = k·Σ_analytic).

    Returns:
        Collision probability in [0, 1]. Returns 0.0 for degenerate (zero-vrel)
        encounters where the B-plane is undefined.
    """
    basis = _b_plane_basis(rel_vel_rsw)
    if basis is None:
        return 0.0

    if covariance_rsw is None:
        covariance_rsw = realistic_covariance_rsw(realism_factor)

    # Project covariance and miss onto the B-plane
    sigma_bp = basis @ covariance_rsw @ basis.T  # [2, 2]
    m_bp = basis @ np.asarray(miss_rsw, float)  # [2]

    det = float(np.linalg.det(sigma_bp))
    if det <= 0:
        return 0.0
    inv = np.linalg.inv(sigma_bp)
    exponent = -0.5 * float(m_bp @ inv @ m_bp)
    pc = (hbr_km**2 / (2.0 * np.sqrt(det))) * np.exp(exponent)
    return float(min(pc, 1.0))


def collision_probability_both(
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    hbr_km: float,
    realism_factor: float = DEFAULT_REALISM_FACTOR,
) -> dict:
    """Return both the analytic (fixed) and realism-adjusted Pc for transparency.

    Reporting both lets the operator see the effect of the realism assumption.
    """
    from engine.pc import collision_probability as pc_fixed

    pc_analytic = pc_fixed(miss_rsw, rel_vel_rsw, hbr_km)
    pc_realistic = collision_probability_general(
        miss_rsw, rel_vel_rsw, hbr_km, realism_factor=realism_factor
    )
    return {
        "pc_analytic": pc_analytic,
        "pc_realistic": pc_realistic,
        "realism_factor": realism_factor,
    }
