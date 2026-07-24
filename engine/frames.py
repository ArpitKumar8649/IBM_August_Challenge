"""RSW (Radial / in-track / cross-track) frame transforms.

The RSW frame is anchored to the primary satellite:
  R (radial)     = along the position vector
  W (cross-track) = along the orbit normal (r × v)
  S (in-track)   = completes the right-handed triad (W × R), ~velocity direction

Miss geometry expressed in RSW tells the operator *how* the encounter looks:
in-track-dominated approaches are the common, predictable kind; radial-
dominated ones are rarer and harder. (Phase 2 adds the B-plane projection
and collision probability on top of these.)
"""

from __future__ import annotations

import numpy as np


def rsw_rotation(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rotation matrix from TEME to the primary's RSW frame.

    Returns R [3,3] such that ``x_rsw = R @ x_teme``.
    """
    r = np.asarray(r, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    r_hat = r / np.linalg.norm(r)
    w_hat = np.cross(r, v)
    w_hat /= np.linalg.norm(w_hat)
    t_hat = np.cross(w_hat, r_hat)
    return np.stack([r_hat, t_hat, w_hat])


def relative_state_rsw(
    r_primary: np.ndarray,
    v_primary: np.ndarray,
    r_secondary: np.ndarray,
    v_secondary: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Secondary-minus-primary relative position/velocity in the primary's RSW."""
    rotation = rsw_rotation(r_primary, v_primary)
    dr = np.asarray(r_secondary, dtype=np.float64) - np.asarray(r_primary, dtype=np.float64)
    dv = np.asarray(v_secondary, dtype=np.float64) - np.asarray(v_primary, dtype=np.float64)
    return rotation @ dr, rotation @ dv


def miss_distance(r_primary: np.ndarray, r_secondary: np.ndarray) -> float:
    """Separation between two TEME positions, km."""
    return float(np.linalg.norm(np.asarray(r_secondary) - np.asarray(r_primary)))
