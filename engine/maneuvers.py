"""Avoidance-maneuver search — numerical relative-motion propagation.

Given the primary and secondary inertial states at TCA (from the refinement
step), we predict the post-burn miss distance by *actually propagating* the
maneuvered primary with a high-accuracy numerical two-body integrator
(scipy DOP853). This is exact to the integrator tolerance — no linearization
error — which is what a credible maneuver product requires.

For each candidate burn (lead time × direction × magnitude):
  1. Back-propagate the primary from TCA to the burn epoch.
  2. Apply the Δv (specified in the primary's RSW frame at the burn epoch).
  3. Forward-propagate the maneuvered primary back to TCA.
  4. Post-burn miss = separation from the (un-maneuvered) secondary at TCA.

The secondary is not maneuvered, so its TCA state is reused for every candidate.

A Clohessy-Wiltshire state-transition matrix is also provided as a documented
*fast estimate* (linearized, accurate only for small separations / short arcs)
— useful for explaining the linear Δv→miss sensitivity to the operator, but the
authoritative post-burn miss is the numerical result.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from scipy.integrate import solve_ivp

from engine.frames import rsw_rotation
from engine.models import ManeuverConstraints, ManeuverOption

G0 = 9.80665  # m/s², standard gravity for the rocket equation
MU_EARTH = 398600.8  # km³/s²

# Default spacecraft parameters (user-overridable via the API/agent).
DEFAULT_MASS_KG = 4.0  # typical 3U-6U CubeSat wet mass
DEFAULT_ISP_S = 60.0  # cold-gas / resistojet CubeSat thruster

# Search grid. Lead times span "commit early (cheaper, less certain)" to "burn
# late (more certain, less time)". Magnitudes span cm/s to m/s — real LEO
# avoidance burns are typically a few cm/s to a few tens of cm/s.
LEAD_TIMES_MIN = [360.0, 240.0, 120.0, 60.0, 30.0]  # 6 h .. 30 min before TCA
DIRECTIONS = np.array(
    [
        [1.0, 0.0, 0.0],   # +radial
        [-1.0, 0.0, 0.0],  # -radial
        [0.0, 1.0, 0.0],   # +in-track
        [0.0, -1.0, 0.0],  # -in-track
        [0.0, 0.0, 1.0],   # +cross-track
        [0.0, 0.0, -1.0],  # -cross-track
    ]
)
MAGNITUDES_MS = [5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]  # 0.005 .. 0.5 m/s


def _two_body_rhs(_t: float, y: np.ndarray) -> np.ndarray:
    r = y[:3]
    v = y[3:]
    a = -MU_EARTH * r / np.linalg.norm(r) ** 3
    return np.concatenate([v, a])


def propagate_two_body(r0: np.ndarray, v0: np.ndarray, duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    """High-accuracy two-body propagation over `duration_s` (negative = backward).

    Returns (position, velocity) at the end of the arc. DOP853 with tight
    tolerances conserves energy to ~machine precision over these short arcs.
    """
    if abs(duration_s)< 1e-9:
        return np.asarray(r0, float).copy(), np.asarray(v0, float).copy()
    y0 = np.concatenate([np.asarray(r0, float), np.asarray(v0, float)])
    sol = solve_ivp(
        _two_body_rhs,
        (0.0, duration_s),
        y0,
        method="DOP853",
        rtol=1e-11,
        atol=1e-11,
        dense_output=False,
    )
    y = sol.y[:, -1]
    return y[:3], y[3:]


def cw_state_transition(n: float, tau: float) -> np.ndarray:
    """Clohessy-Wiltshire state-transition matrix Φ(τ) — documented fast estimate.

    Linearized near-circular relative motion. Accurate only for small separations
    and short arcs; the authoritative maneuver prediction uses numerical
    propagation (see search_maneuvers). Provided for the linear Δv→miss
    sensitivity explanation and quick estimates.
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


def mean_motion_from_alt(alt_km: float, r_earth_km: float = 6378.135, mu: float = MU_EARTH) -> float:
    """Mean motion n [rad/s] for a circular orbit at the given altitude."""
    a = r_earth_km + alt_km
    return float(np.sqrt(mu / a**3))


def propellant_g(dv_ms: float, mass_kg: float, isp_s: float) -> float:
    """Tsiolkovsky rocket equation: propellant mass (g) for a given Δv (m/s)."""
    if isp_s <= 0:
        return float("inf")
    return float(mass_kg * 1000.0 * (1.0 - np.exp(-dv_ms / (G0 * isp_s))))


def post_burn_miss(
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    dv_rsw_kms: np.ndarray,
    lead_time_s: float,
) -> float:
    """Predicted miss distance (km) at TCA after applying dv_rsw at TCA−lead_time.

    Back-propagates the primary to the burn epoch, applies the Δv in the
    primary's RSW frame there, and forward-propagates the maneuvered primary to
    TCA. The secondary is un-maneuvered (its TCA state is reused).
    """
    r_p_b, v_p_b = propagate_two_body(r_primary_tca, v_primary_tca, -lead_time_s)
    rotation = rsw_rotation(r_p_b, v_p_b)  # inertial -> RSW at burn epoch
    dv_inertial = rotation.T @ np.asarray(dv_rsw_kms, float)  # RSW -> inertial
    _r_p_tca_new, _ = propagate_two_body(r_p_b, v_p_b + dv_inertial, lead_time_s)
    return float(np.linalg.norm(_r_p_tca_new - np.asarray(r_secondary_tca, float)))


def _in_blackout(burn_epoch: datetime, windows: list[tuple[datetime, datetime]]) -> bool:
    return any(start <= burn_epoch <= end for start, end in windows)


def search_maneuvers(
    tca: datetime,
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    constraints: ManeuverConstraints | None = None,
    mass_kg: float = DEFAULT_MASS_KG,
    isp_s: float = DEFAULT_ISP_S,
) -> list[ManeuverOption]:
    """Shoot-and-score search over a grid of burns, scored by post-burn miss.

    Returns all grid candidates sorted by propellant (feasible first), with up to
    three curated options tagged cheapest-safe / nominal / conservative.
    """
    constraints = constraints or ManeuverConstraints()
    min_miss = max(constraints.min_post_burn_miss_km, 0.0)
    r_p_tca = np.asarray(r_primary_tca, float)
    v_p_tca = np.asarray(v_primary_tca, float)
    r_s_tca = np.asarray(r_secondary_tca, float)

    options: list[ManeuverOption] = []
    for lead_min in LEAD_TIMES_MIN:
        lead_s = lead_min * 60.0
        burn_epoch = tca - timedelta(minutes=lead_min)
        if _in_blackout(burn_epoch, constraints.blackout_windows):
            continue
        # Back-propagate the primary to the burn epoch once per lead time — this
        # is independent of the Δv, so it's shared across all directions/magnitudes.
        r_p_b, v_p_b = propagate_two_body(r_p_tca, v_p_tca, -lead_s)
        rotation = rsw_rotation(r_p_b, v_p_b)  # inertial -> RSW at burn epoch
        for direction in DIRECTIONS:
            for mag_ms in MAGNITUDES_MS:
                dv_rsw_kms = direction * (mag_ms / 1000.0)
                dv_inertial = rotation.T @ dv_rsw_kms
                r_p_tca_new, _ = propagate_two_body(r_p_b, v_p_b + dv_inertial, lead_s)
                new_miss = float(np.linalg.norm(r_p_tca_new - r_s_tca))
                grams = propellant_g(mag_ms, mass_kg, isp_s)

                satisfies = new_miss >= min_miss
                if constraints.fuel_margin_g is not None:
                    satisfies = satisfies and grams <= constraints.fuel_margin_g

                options.append(
                    ManeuverOption(
                        burn_epoch=burn_epoch,
                        lead_time_min=lead_min,
                        dv_r_ms=float(dv_rsw_kms[0] * 1000.0),
                        dv_s_ms=float(dv_rsw_kms[1] * 1000.0),
                        dv_w_ms=float(dv_rsw_kms[2] * 1000.0),
                        dv_total_ms=float(mag_ms),
                        propellant_g=grams,
                        post_burn_miss_km=new_miss,
                        satisfies_constraints=satisfies,
                    )
                )

    feasible = [o for o in options if o.satisfies_constraints]
    feasible.sort(key=lambda o: (o.propellant_g, -o.post_burn_miss_km))
    if feasible:
        feasible[0].kind = "cheapest-safe"
        nominal = max(feasible, key=lambda o: o.post_burn_miss_km / max(o.propellant_g, 1e-6))
        nominal.kind = "nominal"
        conservative = max(feasible, key=lambda o: o.post_burn_miss_km)
        conservative.kind = "conservative"

    options.sort(key=lambda o: (not o.satisfies_constraints, o.propellant_g))
    return options


def curated_options(options: list[ManeuverOption]) -> list[ManeuverOption]:
    """Return the up-to-three curated options (cheapest-safe / nominal / conservative)."""
    seen: dict[str, ManeuverOption] = {}
    for o in options:
        if o.kind and o.kind not in seen:
            seen[o.kind] = o
    order = ["cheapest-safe", "nominal", "conservative"]
    return [seen[k] for k in order if k in seen]
