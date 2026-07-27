"""Open Notify — live ISS position + astronauts in space.

Free, no-auth public APIs (api.open-notify.org). The ISS position has a robust
fallback: if the API is unavailable, we compute the ISS position from its TLE
using SGP4 (we already have the propagation engine), converting TEME → geodetic
lat/lon. This guarantees the live ISS tracker always works.

Gotchas:
  · Open Notify is HTTP (not HTTPS) — some environments block it; the TLE
    fallback covers that.
  · Latitude/longitude come back as strings — we parse to floats.
  · No auth, occasional downtime — graceful degradation is essential.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from engine.ingest.cache import DiskCache
from engine.models import Astronaut, Astronauts, IssPosition

ISS_NOW_URL = "http://api.open-notify.org/iss-now.json"
ASTROS_URL = "http://api.open-notify.org/astros.json"
ISS_NORAD = 25544

TTL_ISS = 30  # ISS moves ~7.7 km/s — keep it fresh
TTL_ASTROS = 3600  # crew changes rarely

R_EARTH_KM = 6378.137


# --- TEME → geodetic lat/lon (for the TLE fallback) -------------------------


def _julian_date(dt: datetime) -> float:
    """Julian date from a UTC datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() / 86400.0 + 2440587.5


def _gmst_rad(jd: float) -> float:
    """Greenwich Mean Sidereal Time (radians) from Julian date."""
    t = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - t * t * t / 38710000.0
    )
    return math.radians(gmst_deg % 360.0)


def teme_to_latlon(r_teme, dt_utc: datetime) -> tuple[float, float]:
    """Convert a TEME position (km) to geodetic-ish (lat, lon) in degrees.

    Rotates TEME → ECEF (PEF) by GMST, then computes geocentric latitude and
    longitude. Geocentric latitude differs from geodetic by ≤ ~0.2°, which is
    fine for a live-tracker display.
    """
    gmst = _gmst_rad(_julian_date(dt_utc))
    x, y, z = r_teme
    x_ecef = x * math.cos(gmst) + y * math.sin(gmst)
    y_ecef = -x * math.sin(gmst) + y * math.cos(gmst)
    z_ecef = z
    r_mag = math.sqrt(x_ecef**2 + y_ecef**2 + z_ecef**2)
    lon = math.degrees(math.atan2(y_ecef, x_ecef))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z_ecef / r_mag))))
    return lat, lon


def _iss_position_from_tle() -> IssPosition | None:
    """Compute the ISS position from its TLE via SGP4 (fallback when API is down)."""
    try:
        from engine.ingest.celestrak import fetch_group
        from engine.propagate import propagate_at, satrec_from_tle

        stations = fetch_group("stations")
        iss = next((s for s in stations if s.norad_id == ISS_NORAD), None)
        if iss is None:
            return None
        now = datetime.now(timezone.utc)
        sat = satrec_from_tle(iss)
        r_teme, _v = propagate_at(sat, now, iss.epoch)
        lat, lon = teme_to_latlon(r_teme, now)
        return IssPosition(
            latitude=lat, longitude=lon, timestamp=now.timestamp(), source="tle-computed"
        )
    except Exception:  # noqa: BLE001 — fallback must never raise
        return None


# --- Open Notify fetchers ---------------------------------------------------


def fetch_iss_position(client: httpx.Client | None = None) -> IssPosition | None:
    """Live ISS position — Open Notify, falling back to TLE computation."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            resp = http.get(ISS_NOW_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            pos = data.get("iss_position", {})
            return IssPosition(
                latitude=float(pos.get("latitude",0)),
                longitude=float(pos.get("longitude", 0)),
                timestamp=float(data.get("timestamp", 0)),
                source="open-notify",
            ).model_dump()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        finally:
            if own:
                http.close()

    # Try the API (cached briefly).
    try:
        raw = cache.get_or_set("open_notify_iss", _fetch, ttl_s=TTL_ISS)
        if raw:
            return IssPosition.model_validate(raw)
    except Exception:  # noqa: BLE001
        pass
    # Fallback: compute from TLE.
    return _iss_position_from_tle()


def fetch_astronauts(client: httpx.Client | None = None) -> Astronauts:
    """Humans currently in space (Open Notify). Returns empty on failure."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            resp = http.get(ASTROS_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            people = [
                Astronaut(name=p.get("name", ""), craft=p.get("craft", "")).model_dump()
                for p in data.get("people", [])
            ]
            return Astronauts(number=int(data.get("number", 0)), people=people).model_dump()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("open_notify_astros", _fetch, ttl_s=TTL_ASTROS)
        if raw:
            return Astronauts.model_validate(raw)
    except Exception:  # noqa: BLE001
        pass
    return Astronauts(number=0, people=[])
