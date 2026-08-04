"""Precision numerical propagation — J2 geopotential, atmospheric drag, SRP.

A high-fidelity propagator for the conjunctions that matter. SGP4 stays for
catalog-wide screening (fast, analytic); this propagator is used to *confirm*
the top-N highest-risk events with realistic perturbations.

Perturbations modeled:
  · J2 (and optionally J3) oblateness — the dominant geopotential term
  · Atmospheric drag — NRLMSISE-00 density (engine.atmosphere), space-weather-driven
  · Solar radiation pressure (SRP) — cannonball model

References:
  Vallado, "Fundamentals of Astrodynamics and Applications" (J2, SRP)
  Montenbruck & Gill, "Satellite Orbits: Models, Methods, Applications"
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.integrate import solve_ivp

from engine.atmosphere import DEFAULT_AP, DEFAULT_F107, DEFAULT_F107A, drag_acceleration_from_alt
from engine.frames import rsw_rotation

# WGS-84 / EGM96 constants
MU_EARTH = 398600.4418  # km³/s²
R_EARTH = 6378.137  # km
J2 = 1.08262668e-3  # dimensionless
J3 = -2.53265649e-6  # dimensionless

# SRP constants
SOLAR_FLUX_W_M2 = 1367.0  # solar constant at 1 AU (W/m²)
C_LIGHT = 299792.458  # km/s
SRP_PRESSURE_1AU = SOLAR_FLUX_W_M2 / (C_LIGHT * 1000.0) * 1000.0  # N/m² at 1 AU
# SRP pressure at 1 AU ≈ 4.56e-6 N/m² = 4.56e-6 kg·m/s²/m²
AU_KM = 1.495978707e8  # km


def j2_acceleration(r: np.ndarray, include_j3: bool = False) -> np.ndarray:
    """J2 (and optional J3) geopotential acceleration (km/s²).

    The J2 term accounts for Earth's equatorial bulge — the largest perturbation
    for LEO satellites, causing nodal regression and perigee precession.
    """
    x, y, z = r
    r_mag = np.linalg.norm(r)
    r2 = r_mag * r_mag
    r5 = r2 * r2 * r_mag
    factor = -1.5 * J2 * MU_EARTH * R_EARTH**2 / r5

    z2_r2 = (z / r_mag) ** 2
    ax = factor * x * (1.0 - 5.0 * z2_r2)
    ay = factor * y * (1.0 - 5.0 * z2_r2)
    az = factor * z * (3.0 - 5.0 * z2_r2)
    a = np.array([ax, ay, az])

    if include_j3:
        r7 = r5 * r2
        factor3 = -0.5 * J3 * MU_EARTH * R_EARTH**3 / r7
        ax3 = factor3 * x * (10.0 * z - (35.0 / 3.0) * z**3 / r2)
        ay3 = factor3 * y * (10.0 * z - (35.0 / 3.0) * z**3 / r2)
        az3 = factor3 * (3.0 * r2 - 30.0 * z**2 + (35.0 / 3.0) * z**4 / r2)
        a += np.array([ax3, ay3, az3])

    return a


def srp_acceleration(
    r: np.ndarray,
    area_m2: float,
    mass_kg: float,
    cr: float = 1.3,
    sun_dir: np.ndarray | None = None,
    check_shadow: bool = False,
) -> np.ndarray:
    """Solar radiation pressure acceleration (km/s²), cannonball model.

    a_SRP = -P · Cr · (A/m) · ŝ_sun
    where P is the SRP pressure at 1 AU and ŝ_sun is the Sun direction.

    If sun_dir is None, a default (+X, equinox approximation) is used; pass the
    real geocentric Sun direction (from JPL Horizons) for precision. If
    check_shadow is True and the satellite is in Earth's shadow, SRP is zero
    (eclipse).
    """
    if sun_dir is None:
        # Default: Sun along +X (equinox approximation) — anti-sunward force
        sun_dir = np.array([1.0, 0.0, 0.0])
    sun_hat = sun_dir / np.linalg.norm(sun_dir)

    # Eclipse check: no SRP in Earth's shadow.
    if check_shadow:
        from engine.ingest.horizons import in_earth_shadow

        if in_earth_shadow(np.asarray(r, float), sun_hat.tolist()):
            return np.zeros(3)

    # SRP pressure at 1 AU: P = S/c ≈ 4.56e-6 N/m²
    p_srp = 4.56e-6  # N/m² = kg/(m·s²)
    # a = P * Cr * (A/m)  in m/s², then convert to km/s²
    a_mag_ms2 = p_srp * cr * (area_m2 / mass_kg)  # m/s²
    a_mag_kms2 = a_mag_ms2 / 1000.0  # km/s²
    # Force is away from the Sun (anti-sunward)
    return -a_mag_kms2 * sun_hat


def _build_rhs(
    start_time: datetime,
    include_j2: bool = True,
    include_j3: bool = False,
    include_drag: bool = True,
    include_srp: bool = False,
    mass_kg: float = 4.0,
    area_m2: float = 0.04,
    cd: float = 2.2,
    cr: float = 1.3,
    f107: float = DEFAULT_F107,
    f107a: float = DEFAULT_F107A,
    ap: float = DEFAULT_AP,
    sun_dir: np.ndarray | None = None,
    srp_eclipse: bool = True,
):
    """Assemble the perturbed equations of motion, resolving the Sun once.

    Shared by precision_propagate (one integration) and the trajectory
    sampling path (t_eval), so both always integrate exactly the same physics.
    """
    srp_sun_dir = None
    if include_srp:
        if sun_dir is not None:
            srp_sun_dir = np.asarray(sun_dir, float)
        else:
            try:
                from engine.ingest.horizons import sun_direction_geocentric

                fetched = sun_direction_geocentric(start_time.date().isoformat())
                if fetched is not None:
                    srp_sun_dir = np.asarray(fetched, float)
            except Exception:  # noqa: BLE001 — fall back to default in srp_acceleration
                srp_sun_dir = None

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        r = y[:3]
        v = y[3:]

        # Two-body
        a = -MU_EARTH * r / np.linalg.norm(r) ** 3

        # J2 (and J3)
        if include_j2:
            a += j2_acceleration(r, include_j3=include_j3)

        # Atmospheric drag — dated to the propagated epoch so space-weather-
        # dependent density matches the event, not the developer's wall clock.
        if include_drag:
            current_time = start_time + timedelta(seconds=t)
            a += drag_acceleration_from_alt(
                r, v, date=current_time, mass_kg=mass_kg, area_m2=area_m2,
                cd=cd, f107=f107, f107a=f107a, ap=ap,
            )

        # Solar radiation pressure (real Sun direction + eclipse check)
        if include_srp:
            a += srp_acceleration(
                r, area_m2, mass_kg, cr,
                sun_dir=srp_sun_dir, check_shadow=srp_eclipse,
            )

        return np.concatenate([v, a])

    return rhs


def precision_propagate(
    r0: np.ndarray,
    v0: np.ndarray,
    duration_s: float,
    include_j2: bool = True,
    include_j3: bool = False,
    include_drag: bool = True,
    include_srp: bool = False,
    mass_kg: float = 4.0,
    area_m2: float = 0.04,
    cd: float = 2.2,
    cr: float = 1.3,
    start_time: datetime | None = None,
    f107: float = DEFAULT_F107,
    f107a: float = DEFAULT_F107A,
    ap: float = DEFAULT_AP,
    sun_dir: np.ndarray | None = None,
    srp_eclipse: bool = True,
    rtol: float = 1e-11,
    atol: float = 1e-11,
    t_eval: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """High-fidelity numerical propagation with perturbations.

    Args:
        r0, v0: initial ECI position (km) and velocity (km/s).
        duration_s: propagation duration (seconds; negative = backward).
        include_j2/j3/drag/srp: toggle perturbations.
        mass_kg, area_m2, cd, cr: spacecraft parameters.
        start_time: epoch for space-weather-dependent drag (defaults to now).
        f107, f107a, ap: space-weather indices for drag.
        sun_dir: geocentric Sun unit vector (ICRF) for SRP; if None and SRP is
            on, fetched once from JPL Horizons (falls back to +X default).
        srp_eclipse: if True, zero SRP when the satellite is in Earth's shadow.
        rtol, atol: integrator tolerances.
        t_eval: optional times (s, relative to start, monotonic in the
            integration direction) at which to sample the arc.

    Returns:
        (position, velocity) at the end of the arc (km, km/s) — or, with
        ``t_eval``, two (N, 3) arrays of state samples along the arc.
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc)

    rhs = _build_rhs(
        start_time,
        include_j2=include_j2,
        include_j3=include_j3,
        include_drag=include_drag,
        include_srp=include_srp,
        mass_kg=mass_kg,
        area_m2=area_m2,
        cd=cd,
        cr=cr,
        f107=f107,
        f107a=f107a,
        ap=ap,
        sun_dir=sun_dir,
        srp_eclipse=srp_eclipse,
    )

    y0 = np.concatenate([np.asarray(r0, float), np.asarray(v0, float)])
    sol = solve_ivp(
        rhs, (0.0, duration_s), y0,
        method="DOP853", rtol=rtol, atol=atol, t_eval=t_eval,
    )
    if t_eval is not None:
        return sol.y[:3].T.copy(), sol.y[3:].T.copy()
    y = sol.y[:, -1]
    return y[:3], y[3:]


def precision_miss_at_tca(
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    dv_rsw_kms: np.ndarray,
    lead_time_s: float,
    epoch_tca: datetime | None = None,
    **prop_kwargs,
) -> float:
    """Predicted miss distance (km) at TCA after a burn, using precision propagation.

    Back-propagates the primary to the burn epoch, applies Δv in RSW, and
    forward-propagates with the same perturbations to TCA. The secondary is
    held at its refined TCA position (it is assumed un-maneuvered).

    The Δv is expressed in the primary's RSW frame AT THE BURN EPOCH, and the
    frame is re-derived here from the back-propagated state. The RSW frame
    rotates with the orbit (~4°/min in LEO — over 230° across a one-hour lead),
    so a frame carried in from another epoch (e.g. TCA) applies the burn in the
    wrong direction; that was a real bug — the caller used to supply the frame.

    Args:
        r_primary_tca, v_primary_tca: primary state at TCA (km, km/s).
        r_secondary_tca: secondary position at TCA (km).
        dv_rsw_kms: Δv in the burn-epoch RSW frame (km/s).
        lead_time_s: burn lead time (seconds).
        epoch_tca: the event's TCA. Anchors the space-weather-dependent drag
            epoch correctly for each leg — the backward leg starts at TCA, the
            forward leg at the burn epoch. A single shared epoch cannot be
            right for both. If omitted, the drag model defaults to "now".
        **prop_kwargs: passed to precision_propagate for both legs.

    Returns:
        Post-burn miss distance (km) at the original TCA.
    """
    prop_kwargs.pop("start_time", None)  # the per-leg epochs below take precedence
    if epoch_tca is not None:
        back_kwargs = {**prop_kwargs, "start_time": epoch_tca}
        fwd_kwargs = {
            **prop_kwargs,
            "start_time": epoch_tca - timedelta(seconds=lead_time_s),
        }
    else:
        back_kwargs = fwd_kwargs = prop_kwargs
    # Back-propagate primary to burn epoch
    r_p_b, v_p_b = precision_propagate(
        r_primary_tca, v_primary_tca, -lead_time_s, **back_kwargs
    )
    # The Δv frame is the primary's RSW frame AT THE BURN EPOCH.
    rotation = rsw_rotation(r_p_b, v_p_b)
    dv_inertial = rotation.T @ np.asarray(dv_rsw_kms, float)
    # Forward-propagate maneuvered primary to TCA
    r_p_new, _ = precision_propagate(
        r_p_b, v_p_b + dv_inertial, lead_time_s, **fwd_kwargs
    )
    return float(np.linalg.norm(r_p_new - np.asarray(r_secondary_tca, float)))
