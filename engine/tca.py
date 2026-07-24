"""Golden-section TCA refinement.

The coarse scan locates the 60 s grid point nearest each close approach. This
refines it to ~0.01 s with a bounded scalar minimization (Brent's method) of the
separation distance over [t0 ± step], and returns the full TEME state of both
objects at the refined TCA — the input to geometry, Pc, and scoring.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar
from sgp4.api import Satrec

from engine.propagate import propagate_grid


@dataclass
class TCAState:
    """Full state at a refined time of closest approach."""

    tca_offset_s: float  # seconds from the coarse grid point
    miss_distance_km: float
    r_primary: np.ndarray  # TEME km
    v_primary: np.ndarray  # TEME km/s
    r_secondary: np.ndarray
    v_secondary: np.ndarray


def refine_tca(
    primary_sat: Satrec,
    secondary_sat: Satrec,
    primary_t0_min: float,
    secondary_t0_min: float,
    step_s: float = 60.0,
    tol_s: float = 0.01,
) -> TCAState:
    """Refine a coarse grid point to the true TCA within [t0 ± step].

    Args:
        primary_t0_min / secondary_t0_min: tsince (minutes from each TLE epoch) of
            the *same* coarse grid point for the two objects.
        step_s: half-width of the refinement window (the coarse grid spacing).
        tol_s: minimizer tolerance, seconds.

    A wall-clock shift of the primary by Δt shifts the secondary by the same Δt,
    so the secondary tsince tracks the primary's offset.
    """
    half_min = step_s / 60.0

    def separation(t_min: float) -> float:
        p, _ = propagate_grid(primary_sat, np.array([t_min]))
        s, _ = propagate_grid(
            secondary_sat, np.array([secondary_t0_min + (t_min - primary_t0_min)])
        )
        d = float(np.linalg.norm(p[0] - s[0]))
        return d if np.isfinite(d) else 1e9

    result = minimize_scalar(
        separation,
        bounds=(primary_t0_min - half_min, primary_t0_min + half_min),
        method="bounded",
        options={"xatol": tol_s / 60.0},
    )
    t_min = float(result.x)

    # Full state at the refined TCA
    p, pv = propagate_grid(primary_sat, np.array([t_min]))
    s, sv = propagate_grid(
        secondary_sat, np.array([secondary_t0_min + (t_min - primary_t0_min)])
    )
    return TCAState(
        tca_offset_s=(t_min - primary_t0_min) * 60.0,
        miss_distance_km=float(result.fun),
        r_primary=p[0],
        v_primary=pv[0],
        r_secondary=s[0],
        v_secondary=sv[0],
    )
