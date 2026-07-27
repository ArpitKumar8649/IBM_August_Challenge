"""Atmospheric density & drag — NRLMSISE-00 (NASA's empirical thermosphere model).

Wraps pymsis to provide real, space-weather-driven atmospheric density for LEO
drag modeling. Density is the dominant non-gravitational perturbation in LEO and
the main reason TLEs go stale — coupling it to live space-weather inputs makes
conjunction predictions degrade gracefully and honestly during storms.

References:
  Picone et al. (2002), "NRLMSISE-00 empirical model of the atmosphere"
  pymsis: github.com/space-physics/pymsis
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

# Default spacecraft parameters (user-overridable).
DEFAULT_CD = 2.2  # drag coefficient (typical for LEO satellites)
DEFAULT_AREA_M2 = 0.04  # cross-sectional area (m²), ~20×20 cm CubeSat face
DEFAULT_MASS_KG = 4.0  # mass (kg), typical 3U-6U CubeSat

# Default space-weather indices (moderate activity; override with live data).
DEFAULT_F107 = 150.0  # daily F10.7 solar radio flux (sfu)
DEFAULT_F107A = 150.0  # 81-day centered average F10.7
DEFAULT_AP = 4.0  # geomagnetic AP index (quiet)


def atmospheric_density(
    alt_km: float,
    date: datetime | None = None,
    lon_deg: float = 0.0,
    lat_deg: float = 0.0,
    f107: float = DEFAULT_F107,
    f107a: float = DEFAULT_F107A,
    ap: float = DEFAULT_AP,
) -> float:
    """Total mass density (kg/m³) at a given altitude from NRLMSISE-00.

    Args:
        alt_km: altitude above the WGS-84 ellipsoid (km).
        date: UTC datetime (defaults to now).
        lon_deg, lat_deg: geodetic longitude/latitude (deg).
        f107: daily F10.7 solar radio flux (sfu).
        f107a: 81-day centered average F10.7 (sfu).
        ap: geomagnetic AP index (0–400; 4=quiet, 200+=storm).

    Returns:
        Total mass density in kg/m³.
    """
    try:
        from pymsis import msis
    except ImportError:
        # Fallback: simple exponential model if pymsis is unavailable.
        return _exponential_density(alt_km)

    if date is None:
        date = datetime.now(timezone.utc)
    # pymsis wants a naive datetime64 (it interprets it as UTC); strip tzinfo.
    if date.tzinfo is not None:
        date = date.astimezone(timezone.utc).replace(tzinfo=None)
    dates = np.array([date], dtype="datetime64[s]")
    out = msis.run(
        dates,
        lons=lon_deg,
        lats=lat_deg,
        alts=float(alt_km),
        f107s=f107,
        f107as=f107a,
        aps=ap,
    )
    return float(out[0, 0])  # total mass density, kg/m³


def _exponential_density(alt_km: float) -> float:
    """Simple exponential fallback density model (kg/m³).

    ρ = ρ0 · exp(-(h - h0) / H), with H ≈ 60 km scale height near 400 km.
    """
    rho0 = 3.5e-12  # kg/m³ at 400 km (quiet, moderate solar)
    h0 = 400.0
    H = 60.0
    return rho0 * np.exp(-(alt_km - h0) / H)


def ballistic_coefficient(mass_kg: float, area_m2: float, cd: float = DEFAULT_CD) -> float:
    """Ballistic coefficient B = Cd · A / m (m²/kg). Higher B = more drag-sensitive."""
    return cd * area_m2 / mass_kg


def drag_acceleration(
    r_eci: np.ndarray,
    v_eci: np.ndarray,
    rho: float,
    mass_kg: float = DEFAULT_MASS_KG,
    area_m2: float = DEFAULT_AREA_M2,
    cd: float = DEFAULT_CD,
) -> np.ndarray:
    """Atmospheric drag acceleration (km/s²) in ECI.

    a_drag = -(1/2) · (Cd·A/m) · ρ · |v_rel| · v_rel

    The atmosphere co-rotates with Earth; for LEO the co-rotation velocity is
    small (~0.46 km/s at the equator) and we approximate v_rel ≈ v_eci.

    Args:
        r_eci: position (km) — used only for altitude lookup if rho not provided.
        v_eci: velocity (km/s).
        rho: atmospheric density (kg/m³).
        mass_kg, area_m2, cd: spacecraft parameters.

    Returns:
        Drag acceleration vector (km/s²).
    """
    v_mag = np.linalg.norm(v_eci)  # km/s
    if v_mag < 1e-12:
        return np.zeros(3)
    # Convert units: rho (kg/m³) → (kg/km³) = rho * 1e9
    rho_km3 = rho * 1e9
    b = ballistic_coefficient(mass_kg, area_m2, cd)  # m²/kg
    # a = -0.5 * B * rho * |v| * v  (in km/s², with B in m²/kg and rho in kg/km³)
    # B [m²/kg] * rho [kg/km³] = m²/km³ = 1/km; * v² [km²/s²] = km/s² ✓
    a_mag = 0.5 * b * rho_km3 * v_mag  # 1/km * km/s = 1/s ... wait
    # Actually: 0.5 * B[m²/kg] * rho[kg/km³] * v[km/s] * v_vec[km/s]
    # = 0.5 * (m²/kg) * (kg/km³) * (km/s) * (km/s) = 0.5 * m²/km³ * km²/s² = 0.5 * m²/(km·s²)
    # Need to convert m² to km²: m² = 1e-6 km²
    # So: 0.5 * B * rho_km3 * v_mag * v_eci * 1e-6  [km/s²]
    a_vec = -0.5 * b * rho_km3 * v_mag * v_eci * 1e-6
    return a_vec


def drag_acceleration_from_alt(
    r_eci: np.ndarray,
    v_eci: np.ndarray,
    date: datetime | None = None,
    mass_kg: float = DEFAULT_MASS_KG,
    area_m2: float = DEFAULT_AREA_M2,
    cd: float = DEFAULT_CD,
    f107: float = DEFAULT_F107,
    f107a: float = DEFAULT_F107A,
    ap: float = DEFAULT_AP,
    r_earth_km: float = 6378.137,
) -> np.ndarray:
    """Drag acceleration with density looked up from altitude via NRLMSISE-00."""
    alt_km = np.linalg.norm(r_eci) - r_earth_km
    # Geodetic lat/lon from ECI (approximate, ignoring Earth rotation for density)
    lat_deg = np.degrees(np.arcsin(np.clip(r_eci[2] / np.linalg.norm(r_eci), -1, 1)))
    lon_deg = np.degrees(np.arctan2(r_eci[1], r_eci[0]))
    rho = atmospheric_density(alt_km, date, lon_deg, lat_deg, f107, f107a, ap)
    return drag_acceleration(r_eci, v_eci, rho, mass_kg, area_m2, cd)
