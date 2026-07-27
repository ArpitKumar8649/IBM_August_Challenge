"""Ground-track computation — the satellite's sub-satellite point over time.

Computes where a satellite is *over* (lat/lon on Earth's surface) by propagating
its TLE with SGP4 and converting each ECI position to geodetic coordinates,
accounting for Earth's rotation (GMST). Powers "what is my satellite looking at
right now?" and the imagery-under-ground-track feature.

Reuses the Julian-date / GMST / TEME→lat-lon helpers from open_notify.py to avoid
duplicating the astronomy math.

Note: latitude is geocentric (differs from geodetic by ≤ ~0.2°) — fine for
ground-track display and imagery-region queries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from engine.ingest.open_notify import _gmst_rad, _julian_date, teme_to_latlon
from engine.models import GroundTrackPoint, TLEData
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes

R_EARTH_KM = 6378.137


def sub_satellite_point(r_eci: np.ndarray, dt_utc: datetime) -> tuple[float, float, float]:
    """Convert an ECI position (km) to (latitude, longitude, altitude).

    Returns:
        (lat_deg, lon_deg, alt_km) — longitude in [-180, 180].
    """
    lat, lon = teme_to_latlon(r_eci, dt_utc)
    alt = float(np.linalg.norm(r_eci) - R_EARTH_KM)
    return lat, lon, alt


def ground_track(
    tle: TLEData,
    start: datetime | None = None,
    duration_min: float = 90.0,
    step_s: float = 30.0,
) -> list[GroundTrackPoint]:
    """Compute the ground track (sub-satellite points) over a time window.

    Args:
        tle: the satellite's TLE.
        start: start time (UTC); defaults to now.
        duration_min: duration of the track (minutes).
        step_s: time step between points (seconds).

    Returns:
        A list of GroundTrackPoint (lat, lon, time, altitude).
    """
    if start is None:
        start = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    n_points = int(duration_min * 60.0 / step_s) + 1
    offsets_s = np.arange(n_points) * step_s
    offsets_min = offsets_s / 60.0

    sat = satrec_from_tle(tle)
    t0_min = tsince_minutes(start, tle)
    positions, _velocities = propagate_grid(sat, t0_min + offsets_min)

    track: list[GroundTrackPoint] = []
    for i, offset_s in enumerate(offsets_s):
        r = positions[i]
        if not np.isfinite(r).all():
            continue
        t = start + timedelta(seconds=float(offset_s))
        lat, lon, alt = sub_satellite_point(r, t)
        track.append(
            GroundTrackPoint(
                latitude=round(lat, 4),
                longitude=round(lon, 4),
                time=t.isoformat(),
                altitude_km=round(alt, 1),
            )
        )
    return track


def _crosses_antimeridian(lons: list[float]) -> bool:
    """Detect an antimeridian (±180°) crossing via a large consecutive jump."""
    for i in range(len(lons) - 1):
        if abs(lons[i + 1] - lons[i]) > 180.0:
            return True
    return False


def ground_track_bbox(track: list[GroundTrackPoint]) -> tuple[float, float, float, float]:
    """Compute the bounding box [west, south, east, north] of a ground track.

    Handles antimeridian (±180°) crossings: if the track crosses the dateline,
    longitudes are normalized to [0, 360) to compute a contiguous box, then
    converted back so that west may be > east (a valid STAC/GeoJSON antimeridian
    bbox).

    Returns:
        (lon_min/west, lat_min/south, lon_max/east, lat_max/north).
    """
    if not track:
        return (0.0, 0.0, 0.0, 0.0)

    lats = [p.latitude for p in track]
    lons = [p.longitude for p in track]
    lat_min, lat_max = min(lats), max(lats)

    if _crosses_antimeridian(lons):
        # Normalize to [0, 360) so the box is contiguous across the dateline.
        lons_360 = [lon if lon >= 0 else lon + 360.0 for lon in lons]
        west_360, east_360 = min(lons_360), max(lons_360)
        # Convert back to [-180, 180]; west may be > east (antimeridian bbox).
        west = west_360 if west_360 <= 180.0 else west_360 - 360.0
        east = east_360 if east_360 <= 180.0 else east_360 - 360.0
    else:
        west, east = min(lons), max(lons)

    return (round(west,4), round(lat_min, 4), round(east, 4), round(lat_max, 4))


def ground_track_center(track: list[GroundTrackPoint]) -> tuple[float, float]:
    """The mean (lat, lon) of the track — a representative point for imagery queries."""
    if not track:
        return (0.0, 0.0)
    lats = [p.latitude for p in track]
    lons = [p.longitude for p in track]
    return (round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4))
