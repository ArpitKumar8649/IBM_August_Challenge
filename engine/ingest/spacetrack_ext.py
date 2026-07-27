"""Space-Track extended classes — boxscore, decay, launch_site.

A richer space-situational-awareness picture:
  · boxscore — "who owns what's up there" (catalog statistics by country)
  · decay       — "what's coming back down" (predicted reentries → sustainability)
  · launch_site — "where did it launch from" (launch provenance)

Reuses the cookie-auth login from engine.ingest.spacetrack. Degrades gracefully
(returns [] on auth/query failure). Paces queries ~2 s apart (sessions drop
under rapid fire).

Rate limits: ~300 q/min, ~3,000/day.
"""

from __future__ import annotations

import time

import httpx

from engine.ingest.cache import DiskCache
from engine.ingest.spacetrack import QUERY_PAUSE_S, login
from engine.models import CountryStats, DecayEvent, LaunchSite

ST_BASE = "https://www.space-track.org/basicspacedata/query/class"

TTL_STAT = 24 * 3600  # catalog stats change slowly


def _query(client: httpx.Client, url: str) -> list[dict] | None:
    """Run a Space-Track query, returning the JSON list or None on failure."""
    try:
        resp = client.get(url, timeout=60.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _parse_boxscore(rows: list[dict]) -> list[dict]:
    stats = []
    for r in rows:
        stats.append(
            CountryStats(
                country=r.get("COUNTRY") or "",
                country_code=r.get("SPADOC_CD") or "",
                orbital_payloads=int(r.get("ORBITAL_PAYLOAD_COUNT") or 0),
                orbital_rocket_bodies=int(r.get("ORBITAL_ROCKET_BODY_COUNT") or 0),
                orbital_debris=int(r.get("ORBITAL_DEBRIS_COUNT") or 0),
                orbital_total=int(r.get("ORBITAL_TOTAL_COUNT") or 0),
                decayed_total=int(r.get("DECAYED_TOTAL_COUNT") or 0),
                country_total=int(r.get("COUNTRY_TOTAL") or 0),
            ).model_dump()
        )
    return stats


def fetch_boxscore(client: httpx.Client | None = None) -> list[CountryStats]:
    """Catalog statistics by country/orbiter (who owns what's in orbit)."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            if not login(http):
                return []
            time.sleep(QUERY_PAUSE_S)
            rows = _query(http, f"{ST_BASE}/boxscore/format/json/")
            return _parse_boxscore(rows) if rows else []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("st_boxscore", _fetch, ttl_s=TTL_STAT)
        return [CountryStats.model_validate(s) for s in raw]
    except Exception:  # noqa: BLE001
        return []


def _parse_decay(rows: list[dict]) -> list[dict]:
    events = []
    for r in rows:
        events.append(
            DecayEvent(
                norad_id=int(r.get("NORAD_CAT_ID") or 0),
                intl_des=r.get("INTLDES") or "",
                country=r.get("COUNTRY") or "",
                decay_epoch=r.get("DECAY_EPOCH") or "",
                msg_epoch=r.get("MSG_EPOCH") or "",
                msg_type=r.get("MSG_TYPE") or "",
            ).model_dump()
        )
    return events


def fetch_recent_decays(limit: int = 30, client: httpx.Client | None = None) -> list[DecayEvent]:
    """Recent predicted reentry/decay events (sustainability panel)."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            if not login(http):
                return []
            time.sleep(QUERY_PAUSE_S)
            rows = _query(http, f"{ST_BASE}/decay/LIMIT/{limit}/orderby/MSG_EPOCH desc/format/json/")
            return _parse_decay(rows) if rows else []
        finally:
            if own:
                http.close()

    params = {"limit": limit}
    try:
        raw = cache.get_or_set("st_decay", _fetch, params=params, ttl_s=TTL_STAT)
        return [DecayEvent.model_validate(e) for e in raw]
    except Exception:  # noqa: BLE001
        return []


def _parse_launch_sites(rows: list[dict]) -> list[dict]:
    sites = []
    for r in rows:
        sites.append(
            LaunchSite(
                code=r.get("LAUNCH_SITE") or r.get("SITE") or "",
                name=r.get("LAUNCH_SITE_NAME") or r.get("NAME") or "",
                country=r.get("COUNTRY") or "",
            ).model_dump()
        )
    return sites


def fetch_launch_sites(client: httpx.Client | None = None) -> list[LaunchSite]:
    """Launch sites (launch provenance)."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            if not login(http):
                return []
            time.sleep(QUERY_PAUSE_S)
            rows = _query(http, f"{ST_BASE}/launch_site/format/json/")
            return _parse_launch_sites(rows) if rows else []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("st_launch_site", _fetch, ttl_s=TTL_STAT)
        return [LaunchSite.model_validate(s) for s in raw]
    except Exception:  # noqa: BLE001
        return []
