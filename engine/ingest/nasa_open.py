"""NASA Open APIs — NEO Feed, EPIC Earth imagery, APOD, and ADS literature.

Free, public NASA data sources (api.nasa.gov). Each fetch is cached to disk with
an appropriate TTL and degrades gracefully (returns empty on any failure), so the
app never breaks when an API is down or rate-limited.

Sources:
  · NEO Feed   — near-Earth objects approaching Earth (planetary defense)
  · EPIC       — full-disc Earth imagery from DSCOVR (~12×/day)
  · APOD       — Astronomy Picture of the Day (public engagement)
  · ADS        — peer-reviewed literature search (needs a free key)

Rate limits: DEMO_KEY is heavily limited (~30 req/hr); use a free personal key
(NASA_API_KEY in .env) for production.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from engine.ingest.cache import DiskCache
from engine.models import ApodEntry, EpicImage, NeoCloseApproach, NeoObject, Paper

API_BASE = "https://api.nasa.gov"
ADS_BASE = "https://api.adsabs.harvard.edu/v1"

# Cache TTLs (seconds).
TTL_NEO = 24 * 3600  # daily
TTL_EPIC = 3600  # ~12 images/day
TTL_APOD = 24 * 3600  # daily
TTL_ADS = 7 * 24 * 3600  # papers don't change


def _load_env() -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _nasa_key() -> str:
    _load_env()
    return os.environ.get("NASA_API_KEY", "DEMO_KEY")


def _ads_key() -> str:
    _load_env()
    return os.environ.get("ADS_API_KEY", "")


def _get_json(client: httpx.Client, url: str, params: dict) -> dict | list | None:
    """GET JSON, returning None on any HTTP/parse error (graceful degradation)."""
    try:
        resp = client.get(url, params=params, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


# --- NEO Feed ---------------------------------------------------------------


def _parse_neo(data: dict) -> list[dict]:
    """Parse a NEO Feed response into NeoObject dicts."""
    objects: list[dict] = []
    for _date, entries in (data.get("near_earth_objects") or {}).items():
        for e in entries:
            approaches = []
            for ca in e.get("close_approach_data", []):
                approaches.append(
                    NeoCloseApproach(
                        date=ca.get("close_approach_date", _date),
                        relative_velocity_kmh=float(
                            ca.get("relative_velocity", {}).get("kilometers_per_hour", 0) or 0
                        ),
                        miss_distance_km=float(ca.get("miss_distance", {}).get("kilometers", 0) or 0),
                        miss_distance_lunar=float(
                            ca.get("miss_distance", {}).get("lunar", 0) or 0
                        ),
                        orbiting_body=ca.get("orbiting_body", "Earth"),
                    ).model_dump()
                )
            diameter = (
                e.get("estimated_diameter", {}).get("kilometers", {}).get("estimated_diameter_max", 0)
                or 0
            )
            objects.append(
                NeoObject(
                    neo_id=str(e.get("id", "")),
                    name=e.get("name", ""),
                    is_potentially_hazardous=bool(e.get("is_potentially_hazardous_asteroid", False)),
                    estimated_diameter_km=float(diameter),
                    close_approaches=[NeoCloseApproach.model_validate(a) for a in approaches],
                ).model_dump()
            )
    return objects


def fetch_neo_feed(
    start_date: date | None = None,
    end_date: date | None = None,
    client: httpx.Client | None = None,
) -> list[NeoObject]:
    """Fetch near-Earth objects approaching Earth over a date range (default: next 7 days)."""
    if end_date is None:
        end_date = date.today() + timedelta(days=7)
    if start_date is None:
        start_date = end_date - timedelta(days=7)
    params = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "api_key": _nasa_key(),
    }
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            data = _get_json(http, f"{API_BASE}/neo/rest/v1/feed", params)
            return _parse_neo(data) if data else []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("nasa_neo", _fetch, params=params, ttl_s=TTL_NEO)
        return [NeoObject.model_validate(o) for o in raw]
    except Exception:  # noqa: BLE001 — graceful degradation
        return []


# --- EPIC -------------------------------------------------------------------


def _epic_image_url(identifier: str, date_str: str, api_key: str) -> str:
    """Construct the EPIC archive image URL from the identifier and date.

    date_str is like "2026-07-20 00:55:16"; the archive path uses YYYY/MM/DD.
    """
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (
            f"{API_BASE}/EPIC/archive/natural/{d.year:04d}/{d.month:02d}/{d.day:02d}"
            f"/png/epic_1b_{identifier}.png?api_key={api_key}"
        )
    except ValueError:
        return ""


def _parse_epic(data: list, api_key: str) -> list[dict]:
    images = []
    for e in data:
        centroid = e.get("centroid_coordinates", {})
        images.append(
            EpicImage(
                identifier=e.get("identifier", ""),
                date=e.get("date", ""),
                caption=e.get("caption", ""),
                centroid_lat=float(centroid.get("lat", 0) or 0),
                centroid_lon=float(centroid.get("lon", 0) or 0),
                image_url=_epic_image_url(e.get("identifier", ""), e.get("date", ""), api_key),
            ).model_dump()
        )
    return images


def fetch_epic_latest(
    image_date: date | None = None, client: httpx.Client | None = None
) -> list[EpicImage]:
    """Fetch full-disc Earth images for a date (default: most recent available).

    EPIC data lags ~2 days; if the requested date has no images, we step back a
    few days to find the most recent available.
    """
    api_key = _nasa_key()
    if image_date is None:
        image_date = date.today() - timedelta(days=2)  # EPIC lags
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            # Try the target date, then step back up to 5 days.
            for offset in range(6):
                d = image_date - timedelta(days=offset)
                data = _get_json(http, f"{API_BASE}/EPIC/api/natural/date/{d.isoformat()}", {"api_key": api_key})
                if data:
                    return _parse_epic(data, api_key)
            return []
        finally:
            if own:
                http.close()

    params = {"date": image_date.isoformat()}
    try:
        raw = cache.get_or_set("nasa_epic", _fetch, params=params, ttl_s=TTL_EPIC)
        return [EpicImage.model_validate(i) for i in raw]
    except Exception:  # noqa: BLE001
        return []


# --- APOD -------------------------------------------------------------------


def _parse_apod(data: dict) -> dict:
    return ApodEntry(
        title=data.get("title", ""),
        explanation=data.get("explanation", ""),
        url=data.get("url", ""),
        hd_url=data.get("hdurl", ""),
        media_type=data.get("media_type", "image"),
        date=data.get("date", ""),
    ).model_dump()


def fetch_apod(client: httpx.Client | None = None) -> ApodEntry | None:
    """Fetch today's Astronomy Picture of the Day."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            data = _get_json(http, f"{API_BASE}/planetary/apod", {"api_key": _nasa_key()})
            return _parse_apod(data) if data else None
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("nasa_apod", _fetch, ttl_s=TTL_APOD)
        return ApodEntry.model_validate(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


# --- ADS literature ---------------------------------------------------------


def _parse_ads(data: dict) -> list[dict]:
    papers = []
    for doc in data.get("response", {}).get("docs", []):
        title = doc.get("title", [""])[0] if doc.get("title") else ""
        papers.append(
            Paper(
                bibcode=doc.get("bibcode", ""),
                title=title,
                authors=doc.get("author", []),
                year=str(doc.get("year", "")),
                abstract=doc.get("abstract", "") or "",
                url=f"https://ui.adsabs.harvard.edu/abs/{doc.get('bibcode', '')}",
            ).model_dump()
        )
    return papers


def search_ads(query: str, rows: int = 5, client: httpx.Client | None = None) -> list[Paper]:
    """Search NASA ADS for peer-reviewed papers. Returns [] if no API key or on error."""
    api_key = _ads_key()
    if not api_key:
        return []  # ADS requires a free key; degrade gracefully
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            data = _get_json(
                http,
                f"{ADS_BASE}/search/query",
                {"q": query, "rows": rows, "fl": "title,author,year,abstract,bibcode"},
            )
            return _parse_ads(data) if data else []
        finally:
            if own:
                http.close()

    params = {"q": query, "rows": rows}
    try:
        raw = cache.get_or_set("nasa_ads", _fetch, params=params, ttl_s=TTL_ADS)
        return [Paper.model_validate(p) for p in raw]
    except Exception:  # noqa: BLE001
        return []
