"""Astronomy & discovery — ZTF transients, exoplanets, and Gaia stars.

Extends OrbitWarden from protecting satellites to discovering new things — the
"AI for astronomy research and discovery" challenge area.

Sources (all free, no auth; verified 2026-07-27):
  · ALeRCE broker (ZTF transients) — https://api.alerce.online/ztf/v1/objects/
  · NASA Exoplanet Archive (TAP)   — https://exoplanetarchive.ipac.caltech.edu/TAP/sync
  · ESA Gaia (TAP)                 — https://gea.esac.esa.int/tap-server/tap/sync

Gotchas (documented, handled):
  · ALeRCE's main domain (alerce.online) is CloudFront-blocked (403) — use
    api.alerce.online. Its list endpoint is SLOW (~30-60 s) and its `count`
    query param is broken (a Flask-RESTx version bug), so we omit it.
  · Gaia TAP requires REQUEST=doQuery & LANG=ADQL, and the fully-qualified
    table name gaiadr3.gaia_source (bare `gaia_source` is unresolved).
  · TAP responses are JSON arrays of row dicts.

Cache TTL: transients 1 h, exoplanets 7 d, Gaia 1 d.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from engine.ingest.cache import DiskCache
from engine.models import Exoplanet, Star, Transient

ALERC_BASE = "https://api.alerce.online/ztf/v1"
EXOPLANET_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"

TTL_TRANSIENTS = 3600  # 1 h
TTL_EXOPLANETS = 7 * 24 * 3600  # 7 d
TTL_GAIA = 24 * 3600  # 1 d

# ALeRCE is slow; give it a generous timeout.
ALERC_TIMEOUT = 60.0
_BROWSER_UA = "Mozilla/5.0"


def mjd_to_iso(mjd: float) -> str:
    """Convert Modified Julian Date to an ISO UTC string (empty if invalid)."""
    if not mjd:
        return ""
    try:
        # MJD 0 = 1858-11-17 00:00 UTC
        epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
        return (epoch + timedelta(days=float(mjd))).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


# --- E.1 ZTF transients (ALeRCE) --------------------------------------------


def _parse_transient(item: dict) -> Transient:
    last_mjd = float(item.get("lastmjd") or 0)
    classification = item.get("class") or "unclassified"
    return Transient(
        oid=item.get("oid", ""),
        ra=float(item.get("meanra") or 0),
        dec=float(item.get("meandec") or 0),
        classification=str(classification),
        last_mjd=last_mjd,
        first_mjd=float(item.get("firstmjd") or 0),
        n_detections=int(item.get("ndethist") or 0),
        last_observed=mjd_to_iso(last_mjd),
    )


def fetch_recent_transients(
    limit: int = 10, client: httpx.Client | None = None
) -> list[Transient]:
    """Fetch the most recently observed ZTF transients from the ALeRCE broker.

    Returns up to `limit` transients, most-recent-first. Empty on failure
    (ALeRCE is occasionally slow/unavailable — degrades gracefully).
    """
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client(timeout=ALERC_TIMEOUT)
        try:
            # NOTE: omit the `count` param (broken server-side) and use a trailing
            # slash on the objects endpoint (the non-slash form 308-redirects).
            resp = http.get(
                f"{ALERC_BASE}/objects/",
                params={"page": 1, "order_by": "lastmjd", "order_mode": "DESC"},
                headers={"User-Agent": _BROWSER_UA},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else []
            return [_parse_transient(it).model_dump() for it in items[:limit]]
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("alerce_transients", _fetch, params={"limit": limit}, ttl_s=TTL_TRANSIENTS)
        return [Transient.model_validate(t) for t in raw]
    except Exception:  # noqa: BLE001
        return []


# --- E.2 NASA Exoplanet Archive (TAP) ---------------------------------------


def _normalize_tap_rows(data) -> list[dict]:
    """Normalize a TAP JSON response into a list of row dicts.

    TAP servers return JSON in two common shapes:
      1. A top-level list of row dicts (NASA Exoplanet Archive).
      2. A dict with "metadata" (column defs) + "data" (rows). Rows may be
         dicts (keyed) or positional lists (matching metadata column order) —
         the standard IVOA TAP serialization. ESA Gaia uses shape 2.

    Returns a uniform list of {column_name: value} dicts.
    """
    # Shape 1: top-level list of dicts.
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]

    if not isinstance(data, dict):
        return []

    rows = data.get("data", [])
    if not isinstance(rows, list):
        return []

    # Shape 2a: rows are already dicts.
    if rows and isinstance(rows[0], dict):
        return rows

    # Shape 2b: rows are positional lists — zip with metadata column names.
    columns = [m.get("name") for m in data.get("metadata", [])]
    if not columns:
        return []
    normalized = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) == len(columns):
            normalized.append(dict(zip(columns, row)))
    return normalized


def _tap_query(url: str, query: str, client: httpx.Client, timeout: float = 40.0) -> list[dict]:
    """Run a TAP sync query, returning normalized row dicts (see _normalize_tap_rows).

    Uses lowercase query/format params (the convention of the NASA Exoplanet
    Archive). ESA Gaia uses uppercase params and is handled separately in
    query_gaia.
    """
    params = {"query": query, "format": "json"}
    resp = client.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return _normalize_tap_rows(resp.json())


def fetch_recent_exoplanets(
    since_year: int = 2020, limit: int = 20, client: httpx.Client | None = None
) -> list[Exoplanet]:
    """Fetch confirmed exoplanets discovered since a given year (NASA Exoplanet Archive)."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            query = (
                f"SELECT TOP {limit} pl_name, discoverymethod, disc_year, hostname "
                f"FROM ps WHERE disc_year >= {since_year} AND default_flag = 1 "
                f"ORDER BY disc_year DESC"
            )
            rows = _tap_query(EXOPLANET_TAP, query, http)
            return [
                Exoplanet(
                    name=r.get("pl_name", ""),
                    discovery_method=r.get("discoverymethod", ""),
                    discovery_year=int(r.get("disc_year") or 0),
                    host_star=r.get("hostname", ""),
                ).model_dump()
                for r in rows
            ]
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set(
            "exoplanets", _fetch, params={"since": since_year, "limit": limit}, ttl_s=TTL_EXOPLANETS
        )
        return [Exoplanet.model_validate(e) for e in raw]
    except Exception:  # noqa: BLE001
        return []


def exoplanet_count(since_year: int = 2020, client: httpx.Client | None = None) -> int:
    """Count confirmed exoplanets discovered since a given year."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            query = f"SELECT COUNT(*) AS n FROM ps WHERE disc_year >= {since_year} AND default_flag = 1"
            rows = _tap_query(EXOPLANET_TAP, query, http)
            return int(rows[0]["n"]) if rows else 0
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return 0
        finally:
            if own:
                http.close()

    try:
        return cache.get_or_set("exoplanet_count", _fetch, params={"since": since_year}, ttl_s=TTL_EXOPLANETS)
    except Exception:  # noqa: BLE001
        return 0


# --- E.3 Gaia stars (TAP cone search) ---------------------------------------


def query_gaia(
    ra: float, dec: float, radius_arcmin: float = 5.0, limit: int = 10,
    client: httpx.Client | None = None,
) -> list[Star]:
    """Cone search the Gaia DR3 catalog for stars near a sky position.

    Args:
        ra, dec: center of the field (deg, ICRS).
        radius_arcmin: search radius (arcminutes).
        limit: max stars to return.

    Returns:
        Stars sorted by brightness (G magnitude), brightest first.
    """
    cache = DiskCache()
    radius_deg = radius_arcmin / 60.0

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            query = (
                f"SELECT TOP {limit} source_id, ra, dec, phot_g_mean_mag "
                f"FROM gaiadr3.gaia_source "
                f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) "
                f"ORDER BY phot_g_mean_mag ASC"
            )
            # Gaia TAP uses UPPERCASE params (REQUEST/LANG/FORMAT/QUERY) — unlike
            # the Exoplanet Archive's lowercase — and requires REQUEST=doQuery.
            resp = http.get(
                GAIA_TAP,
                params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query},
                timeout=50.0,
            )
            resp.raise_for_status()
            rows = _normalize_tap_rows(resp.json())
            return [
                Star(
                    source_id=str(r.get("source_id", "")),
                    ra=float(r.get("ra") or 0),
                    dec=float(r.get("dec") or 0),
                    g_mag=float(r.get("phot_g_mean_mag") or 0),
                ).model_dump()
                for r in rows
            ]
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set(
            "gaia_stars", _fetch,
            params={"ra": ra, "dec": dec, "radius": radius_arcmin, "limit": limit},
            ttl_s=TTL_GAIA,
        )
        return [Star.model_validate(s) for s in raw]
    except Exception:  # noqa: BLE001
        return []
