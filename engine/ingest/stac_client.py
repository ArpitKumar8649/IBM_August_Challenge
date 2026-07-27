"""STAC client — satellite imagery (earth-search) + burnt-area (Copernicus CLMS).

Connects orbit to Earth impact: "what imagery is under my satellite's ground
track right now?" Queries the AWS earth-search STAC (free, no auth) for
Sentinel-2 (optical), Sentinel-1 (SAR, all-weather), and Landsat scenes, and the
Copernicus Data Space STAC for CLMS burnt-area (disaster monitoring).

Verified endpoints (2026-07-27):
  · earth-search root: https://earth-search.aws.element84.com/v1  (no auth)
  · earth-search search:POST /v1/search  (STAC ItemCollection)
  · Copernicus CLMS:    https://catalogue.dataspace.copernicus.eu/stac
    (collection clms_ba_global_300m_daily_v4_cog; STAC search is open, data
    download needs a free token)

Gotchas:
  · STAC search is a POST, not GET.
  · bbox is [west, south, east, north] in WGS84 degrees.
  · Cloud cover (eo:cloud_cover) matters — filter < 20% for usable optical.
  · Sentinel-1 (SAR) sees through clouds — the all-weather option.
  · Thumbnails are in item.assets.thumbnail.href.

Cache TTL 6 h (imagery updates per orbit).
"""

from __future__ import annotations

import httpx

from engine.ingest.cache import DiskCache
from engine.models import BurntAreaItem, StacItem

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
COPERNICUS_STAC = "https://catalogue.dataspace.copernicus.eu/stac"

TTL = 6 * 3600  # 6 h

# Collections available on earth-search.
COLLECTIONS = {
    "sentinel-2": "sentinel-2-l2a",  # optical (cloud-sensitive)
    "sentinel-1": "sentinel-1-grd",  # SAR (all-weather)
    "landsat": "landsat-c2-l2",      # optical
}
CLMS_COLLECTION = "clms_ba_global_300m_daily_v4_cog"


def _post_search(base_url: str, payload: dict, client: httpx.Client | None = None) -> dict | None:
    """POST a STAC search; return the JSON response or None on failure."""
    own = client is None
    http = client or httpx.Client()
    try:
        resp = http.post(f"{base_url}/search", json=payload, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            http.close()


def _parse_item(feature: dict, collection: str) -> StacItem:
    """Parse a STAC Feature into a StacItem."""
    props = feature.get("properties", {})
    assets = feature.get("assets", {})
    asset_urls = {key: a.get("href", "") for key, a in assets.items() if isinstance(a, dict)}
    thumbnail = assets.get("thumbnail", {}).get("href", "") if isinstance(assets.get("thumbnail"), dict) else ""
    bbox = feature.get("bbox", [])
    return StacItem(
        item_id=feature.get("id", ""),
        collection=collection,
        datetime=props.get("datetime", ""),
        bbox=bbox,
        cloud_cover=float(props.get("eo:cloud_cover", 100.0) or 100.0),
        platform=props.get("platform", ""),
        thumbnail_url=thumbnail,
        asset_urls=asset_urls,
    )


def search_imagery(
    bbox: tuple[float, float, float, float],
    datetime_range: str | None = None,
    collection: str = "sentinel-2",
    max_cloud_cover: float | None = 20.0,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[StacItem]:
    """Search earth-search for satellite imagery over a bbox.

    Args:
        bbox: (west, south, east, north) in WGS84 degrees.
        datetime_range: STAC datetime range "start/end" (ISO); None = any time.
        collection: "sentinel-2" (optical), "sentinel-1" (SAR), or "landsat".
        max_cloud_cover: filter out scenes above this cloud % (None = no filter;
            ignored for SAR, which has no cloud cover).
        limit: max number of scenes to return.

    Returns:
        List of StacItem, sorted by datetime (most recent first), filtered by cloud.
    """
    collection_id = COLLECTIONS.get(collection, collection)
    payload: dict = {
        "collections": [collection_id],
        "bbox": list(bbox),
        "limit": limit * 3 if max_cloud_cover is not None else limit,  # over-fetch to allow cloud filtering
    }
    if datetime_range:
        payload["datetime"] = datetime_range
    # SAR has no cloud cover; skip the cloud filter for it.
    is_sar = collection == "sentinel-1"

    cache = DiskCache()

    def _fetch():
        data = _post_search(EARTH_SEARCH, payload, client)
        if not data:
            return []
        items = [_parse_item(f, collection_id) for f in data.get("features", [])]
        return [it.model_dump() for it in items]

    try:
        raw = cache.get_or_set(
            f"stac_{collection}", _fetch,
            params={"bbox": list(bbox), "datetime": datetime_range, "limit": limit},
            ttl_s=TTL,
        )
        items = [StacItem.model_validate(i) for i in raw]
    except Exception:  # noqa: BLE001
        return []

    # Filter by cloud cover (optical only) and sort most-recent-first.
    if max_cloud_cover is not None and not is_sar:
        items = [it for it in items if it.cloud_cover <= max_cloud_cover]
    items.sort(key=lambda it: it.datetime or "", reverse=True)
    return items[:limit]


def search_burnt_area(
    bbox: tuple[float, float, float, float],
    datetime_range: str | None = None,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[BurntAreaItem]:
    """Search Copernicus CLMS burnt-area data over a bbox (disaster monitoring).

    Returns STAC metadata (bbox, date) — not the full raster (which would need a
    Copernicus Data Space token to download).
    """
    payload: dict = {
        "collections": [CLMS_COLLECTION],
        "bbox": list(bbox),
        "limit": limit,
    }
    if datetime_range:
        payload["datetime"] = datetime_range

    cache = DiskCache()

    def _fetch():
        data = _post_search(COPERNICUS_STAC, payload, client)
        if not data:
            return []
        items = []
        for f in data.get("features", []):
            props = f.get("properties", {})
            items.append(
                BurntAreaItem(
                    item_id=f.get("id", ""),
                    collection=CLMS_COLLECTION,
                    datetime=props.get("datetime", ""),
                    bbox=f.get("bbox", []),
                ).model_dump()
            )
        return items

    try:
        raw = cache.get_or_set(
            "stac_burnt_area", _fetch,
            params={"bbox": list(bbox), "datetime": datetime_range, "limit": limit},
            ttl_s=TTL,
        )
        return [BurntAreaItem.model_validate(i) for i in raw]
    except Exception:  # noqa: BLE001
        return []
