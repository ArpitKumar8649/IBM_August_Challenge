"""TTL disk cache for external data sources.

A simple, robust JSON file cache keyed by (source, params). Every external API
call in the ingestion layer goes through this so that:
  · repeated calls are fast and cheap (no redundant network / rate-limit usage);
  · the app keeps working from cache when an API is down or rate-limited;
  · each source has an appropriate freshness (TLEs hourly, imagery daily, etc.).

Design goals: never raise on cache miss / corrupt file / disk error — caching is
an optimization, and a cache failure must degrade to "fetch fresh," never crash.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "ingest"


def _cache_key(source: str, params: dict[str, Any] | None) -> str:
    """A stable, filesystem-safe key from the source name and params."""
    params = params or {}
    # Sort for stability; serialize deterministically.
    blob = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    # Keep the source name human-readable in the filename.
    safe_source = "".join(c if c.isalnum() or c in "-_" else "_" for c in source)
    return f"{safe_source}_{digest}"


class DiskCache:
    """JSON file cache with per-entry TTL."""

    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, source: str, params: dict[str, Any] | None = None, ttl_s: float = 3600.0) -> Any | None:
        """Return the cached value if present and fresh (age < ttl_s), else None.

        Never raises — returns None on any problem (missing, corrupt, expired).
        """
        try:
            path = self._path(_cache_key(source, params))
            if not path.exists():
                return None
            payload = json.loads(path.read_text())
            if time.time() - payload.get("ts", 0) > ttl_s:
                return None  # expired
            return payload.get("value")
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None

    def set(self, source: str, value: Any, params: dict[str, Any] | None = None) -> None:
        """Store a value. Never raises — a write failure is silently ignored."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._path(_cache_key(source, params))
            path.write_text(json.dumps({"ts": time.time(), "value": value}, default=str))
        except (OSError, TypeError):
            pass  # caching is best-effort

    def get_or_set(
        self,
        source: str,
        fetcher,
        params: dict[str, Any] | None = None,
        ttl_s: float = 3600.0,
    ) -> Any:
        """Return cached value if fresh, else call fetcher(), cache, and return it.

        `fetcher` is a zero-arg callable returning the fresh value. If the fetcher
        raises, a stale cached value (if any) is returned as a fallback; if there
        is no stale value either, the exception propagates.
        """
        fresh = self.get(source, params, ttl_s)
        if fresh is not None:
            return fresh
        try:
            value = fetcher()
        except Exception:
            # Fall back to a stale cache entry if we have one.
            stale = self.get(source, params, ttl_s=float("inf"))
            if stale is not None:
                return stale
            raise
        self.set(source, value, params)
        return value
