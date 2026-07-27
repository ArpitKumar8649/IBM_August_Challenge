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

    Returns:
        (position, velocity) at the end of the arc (km, km/s).
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc)

    # Resolve the Sun direction once (outside the integrator) for SRP.
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
        r_mag = np.linalg.norm(r)

        # Two-body
        a = -MU_EARTH * r / r_mag**3

        # J2 (and J3)
        if include_j2:
            a += j2_acceleration(r, include_j3=include_j3)

        # Atmospheric drag
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

    y0 = np.concatenate([np.asarray(r0, float), np.asarray(v0, float)])
    sol = solve_ivp(
        rhs, (0.0, duration_s), y0,
        method="DOP853", rtol=rtol, atol=atol,
    )
    y = sol.y[:, -1]
    return y[:3], y[3:]


def precision_miss_at_tca(
    r_primary_tca: np.ndarray,
    v_primary_tca: np.ndarray,
    r_secondary_tca: np.ndarray,
    dv_rsw_kms: np.ndarray,
    lead_time_s: float,
    rsw_rotation: np.ndarray,
    **prop_kwargs,
) -> float:
    """Predicted miss distance (km) at TCA after a burn, using precision propagation.

    Back-propagates the primary to the burn epoch, applies Δv in RSW, and
    forward-propagates with full perturbations to TCA. The secondary is
    propagated un-maneuvered.

    Args:
        r_primary_tca, v_primary_tca: primary state at TCA (km, km/s).
        r_secondary_tca: secondary position at TCA (km).
        dv_rsw_kms: Δv in RSW (km/s).
        lead_time_s: burn lead time (seconds).
        rsw_rotation: 3×3 RSW rotation matrix at the burn epoch.
        **prop_kwargs: passed to precision_propagate.

    Returns:
        Post-burn miss distance (km).
    """
    # Back-propagate primary to burn epoch
    r_p_b, v_p_b = precision_propagate(
        r_primary_tca, v_primary_tca, -lead_time_s, **prop_kwargs
    )
    # Apply Δv in RSW → inertial
    dv_inertial = rsw_rotation.T @ np.asarray(dv_rsw_kms, float)
    # Forward-propagate maneuvered primary to TCA
    r_p_new, _ = precision_propagate(
        r_p_b, v_p_b + dv_inertial, lead_time_s, **prop_kwargs
    )
    return float(np.linalg.norm(r_p_new - np.asarray(r_secondary_tca, float)))
