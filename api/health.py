"""Operational health monitoring.

Reports the real operational state of the platform: whether the database is
populated and fresh, and whether each external data source is reachable (using
the cache as the signal — a fresh cached result means the source is working; a
stale or missing one means degraded). This is what makes the platform operable:
an operator (or a monitoring system) can see at a glance what's healthy and
what's degraded, rather than discovering failures silently.

Health checks are lightweight — they read the cache and do at most a cheap
liveness probe, never a full data fetch.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from engine.ingest.cache import DiskCache

# Max age (s) for a cached result to count as "fresh" (source working).
FRESH_THRESHOLDS = {
    "nasa_neo": 26 * 3600,
    "nasa_epic": 2 * 3600,
    "nasa_apod": 26 * 3600,
    "nasa_ads": 8 * 24 * 3600,
    "open_notify_iss": 300,
    "open_notify_astros": 2 * 3600,
    "st_boxscore": 26 * 3600,
    "st_decay": 26 * 3600,
    "swpc_solar_wind": 600,
    "swpc_xray": 600,
    "swpc_proton": 600,
    "donki_all": 2 * 3600,
    "horizons": 26 * 3600,
    "alerce_transients": 2 * 3600,
    "exoplanets": 8 * 24 * 3600,
    "exoplanet_count": 8 * 24 * 3600,
    "gaia_stars": 26 * 3600,
}

# Human-readable source names.
SOURCE_NAMES = {
    "nasa_neo": "NASA NEO Feed",
    "nasa_epic": "NASA EPIC (Earth imagery)",
    "nasa_apod": "NASA APOD",
    "nasa_ads": "NASA ADS (literature)",
    "open_notify_iss": "Open Notify (ISS)",
    "open_notify_astros": "Open Notify (astronauts)",
    "st_boxscore": "Space-Track (boxscore)",
    "st_decay": "Space-Track (decay)",
    "swpc_solar_wind": "NOAA SWPC (solar wind)",
    "swpc_xray": "NOAA SWPC (X-ray)",
    "swpc_proton": "NOAA SWPC (protons)",
    "donki_all": "NASA DONKI (alerts)",
    "horizons": "JPL Horizons",
    "alerce_transients": "ALeRCE (ZTF transients)",
    "exoplanets": "NASA Exoplanet Archive",
    "exoplanet_count": "NASA Exoplanet Archive (count)",
    "gaia_stars": "ESA Gaia",
}


def _cache_entry_age(cache: DiskCache, source: str) -> float | None:
    """Age (s) of the newest cache entry for a source, or None if no entry."""
    try:
        if not cache.cache_dir.exists():
            return None
        ages = []
        for path in cache.cache_dir.glob(f"{source}_*.json"):
            try:
                import json

                ts = json.loads(path.read_text()).get("ts", 0)
                if ts:
                    ages.append(time.time() - ts)
            except (ValueError, OSError):
                continue
        return min(ages) if ages else None
    except OSError:
        return None


def source_health(cache: DiskCache | None = None) -> list[dict]:
    """Health status for each external data source (from cache freshness)."""
    cache = cache or DiskCache()
    statuses = []
    for source, name in SOURCE_NAMES.items():
        age = _cache_entry_age(cache, source)
        threshold = FRESH_THRESHOLDS.get(source, 24 * 3600)
        if age is None:
            status, detail = "unknown", "never fetched"
        elif age <= threshold:
            status, detail = "ok", f"fresh ({int(age)}s ago)"
        else:
            status = "stale"
            if age < 3600:
                detail = f"{int(age / 60)}m since last fetch"
            else:
                detail = f"{int(age / 3600)}h since last fetch"
        statuses.append({"source": source, "name": name, "status": status, "detail": detail})
    return statuses


def database_health(db_path: str = "data/orbitwarden.db") -> dict:
    """Health of the screening database: present, populated, and freshness of the last run."""
    path = Path(db_path)
    if not path.exists():
        return {"status": "missing", "detail": "no screening database — run the batch first"}
    try:
        import sqlite3

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT run_at, candidates_found FROM screening_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            return {"status": "empty", "detail": "database has no screening runs"}
        return {
            "status": "ok",
            "last_run": row["run_at"],
            "candidates": row["candidates_found"],
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def system_health(db_path: str = "data/orbitwarden.db") -> dict:
    """Overall platform health: database + all data sources + summary counts."""
    db = database_health(db_path)
    sources = source_health()
    ok = sum(1 for s in sources if s["status"] == "ok")
    stale = sum(1 for s in sources if s["status"] == "stale")
    unknown = sum(1 for s in sources if s["status"] == "unknown")

    # Overall status: ok if DB is ok; degraded if some sources are stale.
    if db["status"] != "ok":
        overall = "degraded"
    elif stale > 0:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": db,
        "sources_ok": ok,
        "sources_stale": stale,
        "sources_unknown": unknown,
        "sources_total": len(sources),
        "sources": sources,
    }
