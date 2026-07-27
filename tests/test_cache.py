"""Tests for engine/ingest/cache.py — TTL disk cache."""

import time

import pytest

from engine.ingest.cache import DiskCache


@pytest.fixture
def cache(tmp_path):
    return DiskCache(cache_dir=tmp_path)


def test_get_miss_returns_none(cache):
    assert cache.get("nonexistent", {"a": 1}) is None


def test_set_then_get(cache):
    cache.set("src", {"value": 42}, params={"k": "v"})
    assert cache.get("src", {"k": "v"}) == {"value": 42}


def test_different_params_different_keys(cache):
    cache.set("src", "A", params={"k": 1})
    cache.set("src", "B", params={"k": 2})
    assert cache.get("src", {"k": 1}) == "A"
    assert cache.get("src", {"k": 2}) == "B"


def test_ttl_expiry(cache):
    cache.set("src", "data", ttl_s=None) if False else cache.set("src", "data")
    # With a tiny TTL, the entry should be expired immediately.
    time.sleep(0.05)
    assert cache.get("src", ttl_s=0.01) is None
    # With a large TTL, it should still be present.
    assert cache.get("src", ttl_s=3600) == "data"


def test_corrupt_cache_returns_none(tmp_path):
    cache = DiskCache(cache_dir=tmp_path)
    cache.set("src", "data")
    # Corrupt the file.
    key_file = list(tmp_path.glob("*.json"))[0]
    key_file.write_text("{not valid json")
    assert cache.get("src") is None


def test_get_or_set_calls_fetcher_once(cache):
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        return "fresh"

    # First call fetches.
    assert cache.get_or_set("src", fetcher, ttl_s=3600) == "fresh"
    assert calls["n"] == 1
    # Second call uses cache.
    assert cache.get_or_set("src", fetcher, ttl_s=3600) == "fresh"
    assert calls["n"] == 1


def test_get_or_set_falls_back_to_stale_on_fetcher_error(cache):
    cache.set("src", "stale-value")
    time.sleep(0.05)

    def failing_fetcher():
        raise RuntimeError("network down")

    # TTL expired, fetcher fails → should return the stale cached value.
    result = cache.get_or_set("src", failing_fetcher, ttl_s=0.01)
    assert result == "stale-value"


def test_get_or_set_raises_when_no_stale_and_fetcher_fails(cache):
    def failing_fetcher():
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        cache.get_or_set("src", failing_fetcher, ttl_s=3600)


def test_set_never_raises_on_unserializable(cache):
    """cache.set must never raise, even on unserializable input (best-effort cache).

    The cache uses json.dumps(default=str), so unserializable objects are
    stringified rather than dropped — the contract is only that set() never raises.
    """
    cache.set("src", object())  # must not raise
    # Whatever get returns (a stringified repr or None), no exception is the point.
    result = cache.get("src")
    assert result is None or isinstance(result, str)
