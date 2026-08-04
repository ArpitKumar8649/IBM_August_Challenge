"""Fuel-optimal avoidance maneuvers — minimum-Δv burn for a target miss.

Uses the Clohessy-Wiltshire (Hill) relative-motion state-transition matrix to
solve for the *minimum-Δv* impulsive burn that achieves a target post-burn miss
distance, then verifies the result with the high-fidelity numerical propagator
(engine.precision) — and re-screens the post-burn trajectories, because what
protects the spacecraft is the closest approach *after* the burn, not just the
separation at the original TCA instant.

Conventions (each pinned by tests against numerical propagation):

· Sign. The miss vector is secondary-minus-primary and the burn is applied to
  the primary, so a Δv moves the miss by −Φ_rv·Δv:

      m_new = m − Φ_rv · Δv

  where Φ_rv is the velocity→position block of the CW STM. (An earlier version
  of this module used a plus sign, which predicts the opposite of what a burn
  does and recommended closing burns.)

· Frame. Δv is expressed in the primary's RSW frame AT THE BURN EPOCH
  (TCA − lead time). Φ_rv maps that frame directly to the TCA-anchored RSW
  miss — no extra rotation is needed in the plan — but the burn must actually
  be applied in the burn-epoch frame. The RSW frame rotates with the orbit
  (~4°/min in LEO, ~230° over a one-hour lead), so applying the same Δv triple
  in a frame from another epoch lands the spacecraft elsewhere entirely. The
  verification step derives the frame internally at the burn epoch; callers no
  longer supply one.

· Exact optimum. Minimizing |Δv| subject to |m − Φ_rv·Δv| = T has a closed
  form: with the SVD Φ_rv = U·diag(s)·Vᵀ and μ = Uᵀm, the secular equation

      Σᵢ ( μᵢ / (1 − κ·sᵢ²) )² = T²

  increases monotonically from |m|² at κ = 0 to +∞ as κ → 1/s_max², so for
  T > |m| it has a unique root, and Δv = −V·diag(κ·sᵢ/(1 − κ·sᵢ²))·μ is the
  cheapest burn that reaches T. This replaces a gradient-direction heuristic
  that spent up to ~60% extra Δv at half-orbit lead times. If the root does
  not exist (miss orthogonal to the controllable subspace — pathological),
  the code falls back to the small-Δv gradient direction with a magnitude
  bisection and says so.

· Eccentric primaries. CW is a near-circular linearization. For osculating
  eccentricity ≥ 0.2 (or when it cannot be determined) the planning map is
  instead the finite-difference two-body Δv→miss map — the exact local
  linearization of the dynamics, valid at any eccentricity.

· Verification and re-screening. The plan is linearized; the truth check
  propagates BOTH objects with the caller's perturbation settings (J2 + drag
  by default) and reports the separation at the original TCA — the quantity
  the Δv was sized against — plus the re-screened closest approach over a
  window around TCA. A burn component along the relative velocity buys
  separation only at the old TCA instant, so the closest approach can fall
  well short of the at-TCA number; when it does, the burn is rescaled with a
  secant step on the verified metric and re-verified (at most three passes).

This is the fuel-optimal companion to the shoot-and-score grid search
(engine/maneuvers.py): the grid finds *good* options; this finds the *cheapest*.

References:
  Clohessy & Wiltshire (1960), "Terminal Guidance System for Satellite Rendezvous"
  Alfriend et al., "Spacecraft Formation Flying", ch. 4 (CW/Hill equations)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import brentq

from engine.frames import rsw_rotation
from engine.maneuvers import (
    DEFAULT_ISP_S,
    DEFAULT_MASS_KG,
    MU_EARTH,
    propellant_g,
    propagate_two_body,
)
from engine.precision import precision_propagate

# Planning-map gate: CW is a near-circular linearization; above this osculating
# eccentricity the finite-difference two-body map is used instead.
CW_MAX_ECCENTRICITY = 0.2

# Re-screen window: the closest approach can move from the original TCA after a
# burn, roughly by target_miss / vrel; 4× that is generous. Slow co-orbital
# encounters (vrel → 0) get the cap, fast ones the floor.
RESCREEN_WINDOW_MAX_S = 1800.0
RESCREEN_WINDOW_MIN_S = 300.0
RESCREEN_SAMPLES = 41

# A planned Δv smaller than this (km/s = 1 mm/s) is below any plausible thruster
# resolution and is reported as "no burn" rather than mm/s noise.
_DV_NOISE_KMS = 1e-6


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


def orbital_eccentricity(r: np.ndarray, v: np.ndarray) -> float | None:
    """Osculating eccentricity of an inertial state, or None if not elliptical."""
    r = np.asarray(r, float)
    v = np.asarray(v, float)
    r_mag = float(np.linalg.norm(r))
    if r_mag < 1.0:
        return None
    energy = 0.5 * float(v @ v) - MU_EARTH / r_mag
    if energy >= 0.0:  # parabolic/hyperbolic — outside both planning maps
        return None
    h = np.cross(r, v)
    e_vec = np.cross(v, h) / MU_EARTH - r / r_mag
    return float(np.linalg.norm(e_vec))


def _finite_difference_map(
    r_primary_tca: np.ndarray, v_primary_tca: np.ndarray, lead_time_s: float
) -> np.ndarray:
    """True-orbit Δv→primary-displacement-at-TCA map, by finite differences.

    The planning map for eccentric primaries, where CW is invalid: column i is
    the TCA-frame displacement of the primary caused by a small burn along
    burn-epoch RSW axis i, propagated with the numerical two-body dynamics.
    Units are km per (km/s), i.e. seconds.
    """
    delta = 1e-5  # km/s — truncation ∝ δ, round-off ∝ tol/δ at rtol 1e-11
    r_b, v_b = propagate_two_body(r_primary_tca, v_primary_tca, -lead_time_s)
    rotation_b = rsw_rotation(r_b, v_b)  # Δv frame at the burn epoch
    r_nom, _ = propagate_two_body(r_b, v_b, lead_time_s)
    rotation_tca = rsw_rotation(r_primary_tca, v_primary_tca)
    a_map = np.zeros((3, 3))
    for i in range(3):
        dv_inertial = rotation_b.T @ (np.eye(3)[i] * delta)
        r_i, _ = propagate_two_body(r_b, v_b + dv_inertial, lead_time_s)
        a_map[:, i] = rotation_tca @ ((r_i - r_nom) / delta)
    return a_map


def planning_map(
    mean_motion: float,
    lead_time_s: float,
    r_primary_tca: np.ndarray | None = None,
    v_primary_tca: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
    """The linear Δv→miss-response map used to plan the burn.

    Near-circular primaries (osculating e < 0.2) use the CW velocity→position
    block; eccentric ones use the finite-difference two-body map. Without a
    state (pure-CW callers) the CW block is used. Returns (map, kind).
    """
    if r_primary_tca is None or v_primary_tca is None:
        return cw_state_transition(mean_motion, lead_time_s)[:3, 3:6], "clohessy-wiltshire"
    ecc = orbital_eccentricity(r_primary_tca, v_primary_tca)
    if ecc is None or ecc >= CW_MAX_ECCENTRICITY:
        return (
            _finite_difference_map(r_primary_tca, v_primary_tca, lead_time_s),
            "two-body finite-difference",
        )
    return cw_state_transition(mean_motion, lead_time_s)[:3, 3:6], "clohessy-wiltshire"


def min_dv_exact(
    a_map: np.ndarray, miss_rsw: np.ndarray, target_miss_km: float
) -> np.ndarray | None:
    """Exact minimum-|Δv| solution of |m − A·Δv| = T, in km/s — or None.

    SVD + secular equation (see the module docstring). Returns None when the
    secular equation has no root on (0, 1/s_max²) — the miss is orthogonal to
    the controllable subspace — and the caller falls back.
    """
    m = np.asarray(miss_rsw, float)
    u, s, vt = np.linalg.svd(a_map)
    mu = u.T @ m
    t2 = float(target_miss_km) ** 2
    smax2 = float(s[0]) ** 2
    if smax2 <= 0.0:
        return None

    def secular(kappa: float) -> float:
        return float(np.sum((mu / (1.0 - kappa * s**2)) ** 2)) - t2

    # Walk in from the pole until the secular function exceeds T².
    kappa_hi = None
    for k in range(1, 60):
        trial = (1.0 - 10.0**-k) / smax2
        if secular(trial) > 0.0:
            kappa_hi = trial
            break
    if kappa_hi is None:
        return None
    try:
        kappa = brentq(secular, 0.0, kappa_hi, xtol=1e-18, rtol=1e-15, maxiter=300)
    except ValueError:
        return None
    return vt.T @ (-kappa * s * mu / (1.0 - kappa * s**2))


def optimal_burn_direction(
    mean_motion: float,
    lead_time_s: float,
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    a_map: np.ndarray | None = None,
) -> np.ndarray:
    """The unit Δv direction (burn-epoch RSW) that increases the miss fastest.

    The small-Δv limit of the exact solution: the gradient of |m − A·Δv| with
    respect to Δv at Δv = 0 is −Aᵀm̂, which is therefore the direction of
    steepest miss *increase*. For finite burns prefer ``min_dv_exact`` /
    ``fuel_optimal_burn``, which also account for the target magnitude.

    ``rel_vel_rsw`` is accepted for interface continuity: the impulsive
    Δv→position map at a fixed TCA does not depend on the relative velocity.
    """
    a = cw_state_transition(mean_motion, lead_time_s)[:3, 3:6] if a_map is None else a_map
    m = np.asarray(miss_rsw, float)
    m_norm = float(np.linalg.norm(m))
    if m_norm < 1e-12:
        # No miss to increase — any direction of maximal leverage will do.
        _u, _s, vt = np.linalg.svd(a)
        return vt[0]
    grad = -(a.T @ (m / m_norm))
    grad_norm = float(np.linalg.norm(grad))
    if grad_norm < 1e-12:
        _u, _s, vt = np.linalg.svd(a)
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
    a_map: np.ndarray | None = None,
    map_kind: str = "clohessy-wiltshire",
) -> dict:
    """Minimum-Δv burn (burn-epoch RSW, m/s) reaching ``target_miss_km``.

    Uses the exact closed-form solution of |m − A·Δv| = T when it exists and
    falls back to the gradient direction with a magnitude bisection otherwise.

    Args:
        mean_motion: orbital mean motion n (rad/s) — used for the CW map.
        lead_time_s: burn lead time before TCA (seconds).
        miss_rsw: secondary-minus-primary miss at TCA (primary's RSW, km).
        rel_vel_rsw: relative velocity at TCA (unused by the impulsive map;
            kept for interface continuity and for verification context).
        target_miss_km: required post-burn miss distance (km).
        mass_kg, isp_s: spacecraft parameters for the propellant cost.
        a_map: planning map override (defaults to the CW Φ_rv block).
        map_kind: label recorded in the result.

    Returns:
        dict with dv_rsw_ms, dv_total_ms, propellant_g, cw_predicted_miss_km,
        lead_time_min, direction, method, planning_map (and note if no burn).
    """
    if a_map is None:
        a_map = cw_state_transition(mean_motion, lead_time_s)[:3, 3:6]
    m = np.asarray(miss_rsw, float)
    base = {"lead_time_min": lead_time_s / 60.0, "planning_map": map_kind}

    current_miss = float(np.linalg.norm(m))
    if current_miss >= target_miss_km:
        return {
            **base,
            "dv_rsw_ms": np.zeros(3),
            "dv_total_ms": 0.0,
            "propellant_g": 0.0,
            "cw_predicted_miss_km": current_miss,
            "direction": np.zeros(3),
            "method": "none",
            "note": "already above target — no burn required",
        }

    dv_kms = min_dv_exact(a_map, m, target_miss_km)
    method = "closed-form"
    if dv_kms is None or float(np.linalg.norm(dv_kms)) < _DV_NOISE_KMS:
        # Degenerate geometry: fall back to the small-Δv gradient direction
        # with a magnitude bisection, and be explicit about it.
        direction = optimal_burn_direction(
            mean_motion, lead_time_s, m, rel_vel_rsw, a_map=a_map
        )

        def miss_for(kappa: float) -> float:
            return float(np.linalg.norm(m - a_map @ (direction * kappa)))

        hi = 1e-6  # km/s = 1 mm/s
        while miss_for(hi) < target_miss_km and hi < 0.05:  # cap at 50 m/s
            hi *= 2.0
        if miss_for(hi) < target_miss_km:
            dv_kms = direction * hi
            method = "gradient fallback (target unreachable within 50 m/s)"
        else:
            lo = 0.0
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                if miss_for(mid) < target_miss_km:
                    lo = mid
                else:
                    hi = mid
            dv_kms = direction * (0.5 * (lo + hi))
            method = "gradient fallback"

    dv_rsw_ms = dv_kms * 1000.0
    dv_total_ms = float(np.linalg.norm(dv_rsw_ms))
    dv_norm = float(np.linalg.norm(dv_kms))
    return {
        **base,
        "dv_rsw_ms": dv_rsw_ms,
        "dv_total_ms": dv_total_ms,
        "propellant_g": propellant_g(dv_total_ms, mass_kg, isp_s),
        "cw_predicted_miss_km": float(np.linalg.norm(m - a_map @ dv_kms)),
        "direction": dv_kms / dv_norm if dv_norm > 0 else np.zeros(3),
        "method": method,
    }


def _rescreen_window_s(target_miss_km: float, rel_vel_rsw: np.ndarray) -> float:
    """Half-width (s) of the closest-approach re-screen window around TCA."""
    vrel = max(float(np.linalg.norm(np.asarray(rel_vel_rsw, float))), 0.02)
    return float(np.clip(4.0 * target_miss_km / vrel, RESCREEN_WINDOW_MIN_S, RESCREEN_WINDOW_MAX_S))


def _rescreen_closest_approach(
    r_p_tca: np.ndarray,
    v_p_tca: np.ndarray,
    r_s_tca: np.ndarray,
    v_s_tca: np.ndarray,
    window_s: float,
    epoch_tca: datetime,
    prop_kwargs: dict,
) -> tuple[float, float]:
    """Minimum separation of the two objects over [TCA−W, TCA+W].

    Both objects are propagated with the caller's perturbation settings — this
    is a re-screen, not an at-TCA snapshot. The coarse minimum of sep²(t) is
    refined with a parabola through its three samples. Returns
    (closest_km, offset_s), the offset relative to the original TCA.
    """
    t_grid = np.linspace(0.0, 2.0 * window_s, RESCREEN_SAMPLES)
    dt = float(t_grid[1] - t_grid[0])

    def trajectory(r0: np.ndarray, v0: np.ndarray) -> np.ndarray:
        r_w0, v_w0 = precision_propagate(
            r0, v0, -window_s, start_time=epoch_tca, **prop_kwargs
        )
        positions, _ = precision_propagate(
            r_w0,
            v_w0,
            2.0 * window_s,
            start_time=epoch_tca - timedelta(seconds=window_s),
            t_eval=t_grid,
            **prop_kwargs,
        )
        return positions

    sep2 = np.sum(
        (trajectory(r_p_tca, v_p_tca) - trajectory(r_s_tca, v_s_tca)) ** 2, axis=1
    )
    i = int(np.argmin(sep2))
    if 0 < i < RESCREEN_SAMPLES - 1:
        # Parabola through the samples at i−1, i, i+1, centered on sample i.
        y0, y1, y2 = sep2[i - 1], sep2[i], sep2[i + 1]
        a = (y0 + y2 - 2.0 * y1) / (2.0 * dt * dt)
        if a > 0.0:
            b = (y2 - y0) / (2.0 * dt)
            t_star = float(np.clip(-b / (2.0 * a), -dt, dt))
            s2 = y1 + b * t_star + a * t_star * t_star
            return float(np.sqrt(max(s2, 0.0))), (i * dt - window_s) + t_star
    return float(np.sqrt(sep2[i])), i * dt - window_s


def _verify_burn(
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    v_secondary_tca: np.ndarray,
    dv_rsw_kms: np.ndarray,
    lead_time_s: float,
    window_s: float,
    epoch_tca: datetime,
    prop_kwargs: dict,
) -> tuple[float, float, float]:
    """Truth check of one candidate burn with precision dynamics.

    Applies the Δv in the primary's RSW frame at the burn epoch (derived
    internally), propagates the maneuvered primary to TCA, then re-screens the
    closest approach of BOTH objects over a window around TCA. Each leg gets
    the correct drag epoch. Returns (at_tca_km, closest_km, offset_s).
    """
    back_kwargs = {**prop_kwargs, "start_time": epoch_tca}
    fwd_kwargs = {
        **prop_kwargs,
        "start_time": epoch_tca - timedelta(seconds=lead_time_s),
    }
    r_b, v_b = precision_propagate(r_primary_tca, v_primary_tca, -lead_time_s, **back_kwargs)
    rotation = rsw_rotation(r_b, v_b)  # Δv frame at the BURN EPOCH
    dv_inertial = rotation.T @ np.asarray(dv_rsw_kms, float)
    r_p_new, v_p_new = precision_propagate(
        r_b, v_b + dv_inertial, lead_time_s, **fwd_kwargs
    )
    at_tca = float(np.linalg.norm(r_p_new - np.asarray(r_secondary_tca, float)))
    closest, offset = _rescreen_closest_approach(
        r_p_new,
        v_p_new,
        np.asarray(r_secondary_tca, float),
        np.asarray(v_secondary_tca, float),
        window_s,
        epoch_tca,
        prop_kwargs,
    )
    return at_tca, closest, offset


def fuel_optimal_with_verification(
    mean_motion: float,
    lead_time_s: float,
    miss_rsw: np.ndarray,
    rel_vel_rsw: np.ndarray,
    target_miss_km: float,
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    v_secondary_tca: np.ndarray,
    mass_kg: float = DEFAULT_MASS_KG,
    isp_s: float = DEFAULT_ISP_S,
    epoch_tca: datetime | None = None,
    **prop_kwargs,
) -> dict:
    """Minimum-Δv burn planned on the linear map, verified with truth dynamics.

    The verification propagates BOTH objects (J2 + drag by default, via
    ``prop_kwargs``) and reports the separation at the original TCA
    (``verified_miss_km`` — the quantity the Δv was sized against) plus the
    re-screened closest approach around it (``closest_approach_km`` — the
    quantity that actually protects the spacecraft). If the closest approach
    falls short of the target, the burn is rescaled with a secant step on the
    verified metric and re-verified; at most three verifications.

    Args:
        mean_motion: orbital mean motion n (rad/s).
        lead_time_s: burn lead time before TCA (seconds).
        miss_rsw, rel_vel_rsw: relative state at TCA (primary's RSW, km & km/s).
        target_miss_km: required post-burn miss distance (km).
        r_primary_tca, v_primary_tca: primary state at TCA (km, km/s).
        r_secondary_tca, v_secondary_tca: secondary state at TCA (km, km/s).
        mass_kg, isp_s: spacecraft parameters for the propellant cost.
        epoch_tca: the event's TCA — anchors the drag model's space-weather
            epoch (defaults to now if omitted).
        **prop_kwargs: perturbation settings for precision_propagate.

    Returns:
        dict with the burn (dv_rsw_ms in the burn-epoch RSW frame, dv_total_ms,
        propellant_g, direction), the plan (cw_predicted_miss_km, planning_map,
        method), the truth checks (verified_miss_km at the original TCA,
        closest_approach_km and its offset, satisfies_target), and a note.
    """
    if epoch_tca is None:
        epoch_tca = datetime.now(timezone.utc)
    prop_kwargs.pop("start_time", None)  # per-leg epochs are derived internally

    m = np.asarray(miss_rsw, float)
    vrel = np.asarray(rel_vel_rsw, float)
    miss0 = float(np.linalg.norm(m))
    a_map, map_kind = planning_map(mean_motion, lead_time_s, r_primary_tca, v_primary_tca)
    plan = fuel_optimal_burn(
        mean_motion, lead_time_s, m, vrel, target_miss_km, mass_kg, isp_s,
        a_map=a_map, map_kind=map_kind,
    )
    dv_plan_kms = np.asarray(plan["dv_rsw_ms"], float) / 1000.0
    window_s = _rescreen_window_s(target_miss_km, vrel)

    history: list[tuple[float, float, float, float]] = []  # (scale, at_tca, closest, offset)
    scale = 1.0
    for _ in range(3):
        at_tca, closest, offset = _verify_burn(
            r_primary_tca, v_primary_tca, r_secondary_tca, v_secondary_tca,
            dv_plan_kms * scale, lead_time_s, window_s, epoch_tca, prop_kwargs,
        )
        history.append((scale, at_tca, closest, offset))
        if float(np.linalg.norm(dv_plan_kms)) < _DV_NOISE_KMS or closest >= target_miss_km:
            break
        # Secant step on the verified closest-approach metric, anchored at
        # (scale=0, miss0) and the points already verified.
        if len(history) == 1:
            gain = closest - miss0
            scale = 2.0 if gain <= 0.0 else (target_miss_km - miss0) / gain
        else:
            (s_a, _a1, c_a, _a2), (s_b, _b1, c_b, _b2) = history[-2], history[-1]
            gain = c_b - c_a
            if gain <= 0.0:
                scale = 2.0 * s_b
            else:
                scale = s_b + (target_miss_km - c_b) * (s_b - s_a) / gain
        scale = float(np.clip(scale, 0.0, 100.0))
        if abs(scale - history[-1][0]) < 1e-9:
            break

    scale, at_tca, closest, offset = history[-1]
    dv_kms = dv_plan_kms * scale
    dv_rsw_ms = dv_kms * 1000.0
    dv_total_ms = float(np.linalg.norm(dv_rsw_ms))
    satisfies = closest >= target_miss_km

    notes: list[str] = []
    if plan.get("note"):
        notes.append(plan["note"])
    if len(history) > 1:
        notes.append(
            f"burn rescaled x{scale:.2f} so the re-screened closest approach meets the target"
        )
    if not satisfies and dv_total_ms > 0.0:
        notes.append(
            "target not reached after numerical verification — consider a longer "
            "lead time or a larger burn"
        )
    return {
        "dv_rsw_ms": dv_rsw_ms,
        "dv_total_ms": dv_total_ms,
        "propellant_g": propellant_g(dv_total_ms, mass_kg, isp_s),
        "cw_predicted_miss_km": float(np.linalg.norm(m - a_map @ dv_kms)),
        "verified_miss_km": at_tca,
        "closest_approach_km": closest,
        "closest_approach_offset_s": offset,
        "satisfies_target": satisfies,
        "lead_time_min": lead_time_s / 60.0,
        "planning_map": map_kind,
        "method": plan["method"],
        "direction": plan["direction"],
        "note": "; ".join(notes)
        if notes
        else "fuel-optimal burn (exact CW plan, numerically verified, re-screened)",
    }
