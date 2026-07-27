"""Fuel-optimal avoidance maneuvers — minimum-Δv burn for a target miss.

Uses the Clohessy-Wiltshire (Hill) relative-motion state-transition matrix to
solve for the *minimum-Δv* impulsive burn that achieves a target post-burn miss
distance. CW gives the linear Δv→miss map; the optimal burn direction is the one
that maximizes miss-per-Δv, and the optimal magnitude follows from the target.
The result is verified against the numerical two-body propagator.

This is the fuel-optimal companion to the shoot-and-score grid search
(engine/maneuvers.py): the grid finds *good* options; this finds the *cheapest*.

References:
  Clohessy & Wiltshire (1960), "Terminal Guidance System for Satellite Rendezvous"
  Edelbaum, "Propulsion Requirements for Controllable Satellites"
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize_scalar

from engine.maneuvers import (
    DEFAULT_ISP_S,
    DEFAULT_MASS_KG,
    propellant_g,
)
from engine.precision import precision_miss_at_tca
from engine.tca import refine_tca  # noqa: F401 (re-export for convenience)


def cw_state_transition(n: float, tau: float) -> np.ndarray:
    """Clohessy-Wiltshire state-transition matrix Φ(τ) for mean motion n [rad/s].

    Maps [r; v] (RSW, km & km/s) forward by τ seconds in linearized near-circular
    relative motion. (Mirrors engine/maneuvers.py; duplicated here to keep the
    fuel-optimal module self-contained.)
    """
    nt = n * tau
    c, s = np.cos(nt), np.sin(nt)
    return np.array(
        [
            [4 - 3 * c, 0, 0, s / n, 2 * (1 - c) / n, 0],
            [6 * (s - nt), 1, 0, 2 * (c - 1) / n, (4 * s - 3 * nt) / n, 0],
            [0, 0, c, 0, 0, s / n],
            [3 * n * s, 0, 0, c, 2 * s, 0],
            [6 * n * (c - 1), 0, 0, -2 * s, 4 * c - 3, 0],
            [0, 0, -n * s, 0, 0, c],
        ]
    )


def optimal_burn_direction(
    mean_motion: float,
    lead_time_s: float,
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
) -> np.ndarray:
    """The unit Δv direction (RSW) that maximizes post-burn miss per unit Δv.

    The post-burn miss at TCA is |m + Φ_rv · Δv| where Φ_rv is the 3×3
    velocity-to-position block of the CW STM. The direction that most increases
    the miss is the one aligned with the gradient of |m + Φ_rv·Δv| w.r.t. Δv,
    which is Φ_rvᵀ · (m + Φ_rv·Δv) / |...|. For the optimal *direction* (small Δv
    limit), this is approximately Φ_rvᵀ · m̂ where m̂ is the miss direction — but
    we solve it properly via the dominant right-singular vector of Φ_rv that
    aligns with increasing the miss.
    """
    phi = cw_state_transition(mean_motion, lead_time_s)
    phi_rv = phi[:3, 3:6]  # 3×3 velocity→position block

    # The miss after a small Δv: m_new = m + Φ_rv · Δv.
    # To maximize |m_new|, Δv should point along Φ_rvᵀ · m̂ (gradient direction).
    m = np.asarray(miss_rsw, float)
    m_norm = np.linalg.norm(m)
    if m_norm < 1e-12:
        # No miss to increase — pick the direction of max leverage (top singular vector)
        _u, _s, vt = np.linalg.svd(phi_rv)
        return vt[0]
    m_hat = m / m_norm
    grad = phi_rv.T @ m_hat  # direction in Δv space that increases |m|
    grad_norm = np.linalg.norm(grad)
    if grad_norm < 1e-12:
        _u, _s, vt = np.linalg.svd(phi_rv)
        return vt[0]
    return grad / grad_norm


def fuel_optimal_burn(
    mean_motion: float,
    lead_time_s: float,
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    target_miss_km: float,
    mass_kg: float = DEFAULT_MASS_KG,
    isp_s: float = DEFAULT_ISP_S,
) -> dict:
    """Minimum-Δv burn (RSW, m/s) achieving at least `target_miss_km`.

    Solves for the smallest Δv magnitude along the optimal direction such that
    the CW-predicted post-burn miss ≥ target. Returns the burn and its
    propellant cost.

    Args:
        mean_motion: orbital mean motion n (rad/s).
        lead_time_s: burn lead time before TCA (seconds).
        miss_rsw, rel_vel_rsw: relative state at TCA (RSW, km & km/s).
        target_miss_km: required post-burn miss distance (km).
        mass_kg, isp_s: spacecraft parameters for propellant.

    Returns:
        dict with dv_rsw_ms, dv_total_ms, propellant_g, cw_predicted_miss_km.
    """
    direction = optimal_burn_direction(mean_motion, lead_time_s, miss_rsw, rel_vel_rsw)
    phi = cw_state_transition(mean_motion, lead_time_s)
    phi_rv = phi[:3, 3:6]
    m = np.asarray(miss_rsw, float)

    def miss_for_dv_ms(dv_ms: float) -> float:
        dv_kms = direction * (dv_ms / 1000.0)
        m_new = m + phi_rv @ dv_kms
        return float(np.linalg.norm(m_new))

    # If already above target with zero Δv, no burn needed.
    current_miss = float(np.linalg.norm(m))
    if current_miss >= target_miss_km:
        return {
            "dv_rsw_ms": np.zeros(3),
            "dv_total_ms": 0.0,
            "propellant_g": 0.0,
            "cw_predicted_miss_km": current_miss,
            "lead_time_min": lead_time_s / 60.0,
            "note": "already above target — no burn required",
        }

    # Find the minimum Δv magnitude that reaches the target (miss is monotonic
    # increasing along the optimal direction for small-to-moderate burns).
    result = minimize_scalar(
        lambda dv: (miss_for_dv_ms(dv) - target_miss_km) ** 2,
        bounds=(0.0, 5000.0),
        method="bounded",
        options={"xatol": 0.01},
    )
    dv_total_ms = float(result.x)
    dv_rsw_ms = direction * dv_total_ms
    return {
        "dv_rsw_ms": dv_rsw_ms,
        "dv_total_ms": dv_total_ms,
        "propellant_g": propellant_g(dv_total_ms, mass_kg, isp_s),
        "cw_predicted_miss_km": miss_for_dv_ms(dv_total_ms),
        "lead_time_min": lead_time_s / 60.0,
        "direction": direction,
    }


def fuel_optimal_with_verification(
    mean_motion: float,
    lead_time_s: float,
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    target_miss_km: float,
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    rsw_rotation: np.ndarray,
    mass_kg: float = DEFAULT_MASS_KG,
    isp_s: float = DEFAULT_ISP_S,
    **prop_kwargs,
) -> dict:
    """Fuel-optimal burn with numerical-propagation verification.

    Computes the CW fuel-optimal burn, then verifies the actual post-burn miss
    with the high-fidelity numerical propagator (engine.precision). Reports both
    so the operator sees the CW estimate and the verified result.
    """
    burn = fuel_optimal_burn(
        mean_motion, lead_time_s, miss_rsw, rel_vel_rsw, target_miss_km,
        mass_kg, isp_s,
    )
    dv_rsw_kms = burn["dv_rsw_ms"] / 1000.0
    verified_miss = precision_miss_at_tca(
        r_primary_tca, v_primary_tca, r_secondary_tca,
        dv_rsw_kms, lead_time_s, rsw_rotation, **prop_kwargs,
    )
    burn["verified_miss_km"] = verified_miss
    burn["satisfies_target"] = verified_miss >= target_miss_km
    return burn
