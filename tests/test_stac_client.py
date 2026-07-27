"""Tests for engine/ingest/stac_client.py — STAC parsing, cloud filtering, collections."""

import pytest

from engine.ingest.stac_client import (
    CLMS_COLLECTION,
    COLLECTIONS,
    _parse_item,
    search_imagery,
)
from engine.models import StacItem

# --- recorded STAC Feature fixture (representative earth-search Sentinel-2 item) ---

STAC_FEATURE = {
    "id": "S2B_36UVV_20260727_0_L2A",
    "type": "Feature",
    "bbox": [33.0, -1.0, 34.0, 0.0],
    "properties": {
        "datetime": "2026-07-27T08:56:35.749000Z",
        "eo:cloud_cover": 31.7,
        "platform": "sentinel-2b",
    },
    "assets": {
        "thumbnail": {"href": "https://example.com/thumb.png"},
        "visual": {"href": "https://example.com/visual.tif"},
        "B04": {"href": "https://example.com/B04.tif"},
    },
}


# --- _parse_item ---

def test_parse_item_fields():
    item = _parse_item(STAC_FEATURE, "sentinel-2-l2a")
    assert item.item_id == "S2B_36UVV_20260727_0_L2A"
    assert item.collection == "sentinel-2-l2a"
    assert item.datetime == "2026-07-27T08:56:35.749000Z"
    assert item.cloud_cover == pytest.approx(31.7)
    assert item.platform == "sentinel-2b"
    assert item.bbox == [33.0, -1.0, 34.0, 0.0]


def test_parse_item_thumbnail():
    item = _parse_item(STAC_FEATURE, "sentinel-2-l2a")
    assert item.thumbnail_url == "https://example.com/thumb.png"


def test_parse_item_asset_urls():
    item = _parse_item(STAC_FEATURE, "sentinel-2-l2a")
    assert "visual" in item.asset_urls
    assert "B04" in item.asset_urls
    assert item.asset_urls["visual"] == "https://example.com/visual.tif"


def test_parse_item_missing_cloud_cover_defaults():
    """Missing cloud cover should default to 100 (worst case)."""
    feature = {"id": "x", "properties": {}, "assets": {}}
    item = _parse_item(feature, "sentinel-2-l2a")
    assert item.cloud_cover == 100.0


def test_parse_item_no_thumbnail():
    feature = {"id": "x", "properties": {}, "assets": {"visual": {"href": "v.tif"}}}
    item = _parse_item(feature, "sentinel-2-l2a")
    assert item.thumbnail_url == ""


# --- collections ---

def test_collections_defined():
    assert COLLECTIONS["sentinel-2"] == "sentinel-2-l2a"
    assert COLLECTIONS["sentinel-1"] == "sentinel-1-grd"
    assert COLLECTIONS["landsat"] == "landsat-c2-l2"


def test_clms_collection_defined():
    assert CLMS_COLLECTION == "clms_ba_global_300m_daily_v4_cog"


# --- cloud filtering (with mocked search) ---

def test_cloud_filtering(monkeypatch):
    """search_imagery must filter out scenes above max_cloud_cover (optical)."""
    # Mock _post_search to return a fixed set of items with varying cloud cover.
    def fake_post(base_url, payload, client=None):
        return {
            "features": [
                {"id": "clear", "properties": {"datetime": "2026-07-27T10:00:00Z", "eo:cloud_cover": 5.0}, "assets": {}},
                {"id": "cloudy", "properties": {"datetime": "2026-07-27T09:00:00Z", "eo:cloud_cover": 80.0}, "assets": {}},
                {"id": "medium", "properties": {"datetime": "2026-07-27T08:00:00Z", "eo:cloud_cover": 15.0}, "assets": {}},
            ]
        }

    monkeypatch.setattr("engine.ingest.stac_client._post_search", fake_post)
    # Disable caching so the mock is used directly.
    monkeypatch.setattr(
        "engine.ingest.stac_client.DiskCache",
        lambda *a, **k: _NullCache(),
    )

    items = search_imagery((33.0, -1.0, 34.0, 0.0), collection="sentinel-2", max_cloud_cover=20.0, limit=5)
    ids = {it.item_id for it in items}
    assert "clear" in ids
    assert "medium" in ids
    assert "cloudy" not in ids  # 80% > 20% threshold


def test_cloud_filtering_sorted_recent_first(monkeypatch):
    """Filtered results must be sorted most-recent-first."""
    def fake_post(base_url, payload, client=None):
        return {
            "features": [
                {"id": "older", "properties": {"datetime": "2026-07-25T10:00:00Z", "eo:cloud_cover": 5.0}, "assets": {}},
                {"id": "newer", "properties": {"datetime": "2026-07-27T10:00:00Z", "eo:cloud_cover": 5.0}, "assets": {}},
            ]
        }

    monkeypatch.setattr("engine.ingest.stac_client._post_search", fake_post)
    monkeypatch.setattr("engine.ingest.stac_client.DiskCache", lambda *a, **k: _NullCache())

    items = search_imagery((33.0, -1.0, 34.0, 0.0), collection="sentinel-2", max_cloud_cover=20.0, limit=5)
    assert items[0].item_id == "newer"
    assert items[1].item_id == "older"


def test_sar_skips_cloud_filter(monkeypatch):
    """Sentinel-1 (SAR) must NOT apply the cloud filter (SAR has no cloud cover)."""
    def fake_post(base_url, payload, client=None):
        return {
            "features": [
                {"id": "sar1", "properties": {"datetime": "2026-07-27T10:00:00Z"}, "assets": {}},
            ]
        }

    monkeypatch.setattr("engine.ingest.stac_client._post_search", fake_post)
    monkeypatch.setattr("engine.ingest.stac_client.DiskCache", lambda *a, **k: _NullCache())

    # Even with a strict cloud threshold, SAR scenes should pass (no cloud filter).
    items = search_imagery((33.0, -1.0, 34.0, 0.0), collection="sentinel-1", max_cloud_cover=1.0, limit=5)
    assert len(items) == 1


def test_search_returns_empty_on_failure(monkeypatch):
    """search_imagery must return [] when the search fails (graceful degradation)."""
    monkeypatch.setattr("engine.ingest.stac_client._post_search", lambda *a, **k: None)
    monkeypatch.setattr("engine.ingest.stac_client.DiskCache", lambda *a, **k: _NullCache())
    items = search_imagery((33.0, -1.0, 34.0, 0.0), collection="sentinel-2")
    assert items == []


class _NullCache:
    """A cache that never hits and never stores (forces the fetcher path)."""

    def get_or_set(self, source, fetcher, params=None, ttl_s=3600):
        return fetcher()
