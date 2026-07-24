"""Collision probability — Alfriend–Foster short-term encounter model.

Projects the relative state onto the B-plane (perpendicular to the relative
velocity at TCA) and evaluates the 2-D encounter probability with a documented
fixed covariance. This is an MVP simplification: a true Pc needs each object's
tracking covariance, which only CDM issuers possess. We use a fixed diagonal RSW
covariance and state the assumption in the UI and docs/ASSUMPTIONS.md. Ranking is
driven by miss distance + relative velocity + geometry — not by Pc alone.
"""

from __future__ import annotations

import numpy as np

# Documented fixed combined position covariance (1-sigma, km) in RSW.
SIGMA_RADIAL_KM = 0.5
SIGMA_INTRACK_KM = 1.0
SIGMA_CROSSTRACK_KM = 0.5
DEFAULT_HBR_KM = 0.005  # 5 m per object when size is unknown -> 5 m HBR for a pair


def _b_plane_basis(rel_vel_rsw: np.ndarray) -> np.ndarray | None:
    """Two orthonormal B-plane basis vectors (rows), expressed in RSW coords.

    Returns None if the relative velocity is (near) zero — the B-plane is
    undefined and collision probability is not meaningful.
    """
    v_hat = np.asarray(rel_vel_rsw, float)
    speed = np.linalg.norm(v_hat)
    if speed < 1e-9:
        return None
    v_hat = v_hat / speed
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(v_hat, ref)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    b1 = np.cross(v_hat, ref)
    b1 /= np.linalg.norm(b1)
    b2 = np.cross(v_hat, b1)
    b2 /= np.linalg.norm(b2)
    return np.stack([b1, b2])  # [2, 3]


def collision_probability(
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    hbr_km: float = DEFAULT_HBR_KM,
) -> float:
    """Short-term 2-D encounter probability in [0,1].

    Args:
        miss_rsw: relative position at TCA (km), primary's RSW frame.
        rel_vel_rsw: relative velocity at TCA (km/s), primary's RSW frame.
        hbr_km: hard-body radius = (size_primary + size_secondary) / 2.

    The fixed RSW covariance is rotated into the B-plane basis, then the general
    2-D Gaussian encounter integral is evaluated:
        Pc = HBR² / (2·sqrt(det Σ_bp)) · exp(−½ · m_bpᵀ Σ_bp⁻¹ m_bp)

    Returns 0.0 for a degenerate (near-zero relative velocity) encounter, where
    the B-plane — and thus Pc — is undefined.
    """
    basis = _b_plane_basis(rel_vel_rsw)
    if basis is None:
        return 0.0
    m_bp = basis @ np.asarray(miss_rsw, float)  # [2]
    sigma_rsw = np.diag(
        [SIGMA_RADIAL_KM**2, SIGMA_INTRACK_KM**2, SIGMA_CROSSTRACK_KM**2]
    )
    sigma_bp = basis @ sigma_rsw @ basis.T  # [2, 2]
    det = float(np.linalg.det(sigma_bp))
    inv = np.linalg.inv(sigma_bp)
    exponent = -0.5 * float(m_bp @ inv @ m_bp)
    pc = (hbr_km**2 / (2.0 * np.sqrt(det))) * np.exp(exponent)
    return float(min(pc, 1.0))
