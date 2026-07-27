"""Tests for engine/ingest/open_notify.py — ISS position, astronauts, TEME→lat/lon."""

from datetime import datetime, timezone

import pytest

from engine.ingest.open_notify import _gmst_rad, _julian_date, teme_to_latlon


# --- TEME → lat/lon conversion ---

def test_julian_date_j2000():
    """J2000.0 epoch (2000-01-01 12:00 UTC) is JD 2451545.0."""
    dt = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _julian_date(dt) == pytest.approx(2451545.0, abs=1e-6)


def test_gmst_returns_radians():
    jd = _julian_date(datetime(2026, 7, 24, 12, tzinfo=timezone.utc))
    gmst = _gmst_rad(jd)
    assert 0 <= gmst < 2 * 3.14159265358979 * 1.001  # in [0, 2π)


def test_teme_to_latlon_on_equator():
    """A point on the equator at the Greenwich meridian should be lat≈0."""
    # Position on the equator (z=0) → latitude 0.
    r = [6778.0, 0.0, 0.0]
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    lat, lon = teme_to_latlon(r, dt)
    assert lat == pytest.approx(0.0, abs=0.01)
    assert -180 <= lon <= 180


def test_teme_to_latlon_pole():
    """A point on the +Z axis should be at latitude ≈ +90 (north pole)."""
    r = [0.0, 0.0, 6778.0]
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    lat, lon = teme_to_latlon(r, dt)
    assert lat == pytest.approx(90.0, abs=0.01)


def test_teme_to_latlon_range():
    """lat/lon must be in valid ranges for an arbitrary LEO position."""
    r = [4000.0, 5000.0, 3000.0]
    dt = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    lat, lon = teme_to_latlon(r, dt)
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180


# --- ISS position fallback (TLE-computed) ---

def test_iss_position_from_tle_returns_valid():
    """The TLE fallback must produce a valid lat/lon for the ISS (if TLEs fetchable)."""
    from engine.ingest.open_notify import _iss_position_from_tle

    pos = _iss_position_from_tle()
    if pos is None:
        pytest.skip("TLEs not fetchable in this environment")
    assert pos.source == "tle-computed"
    # ISS inclination ~51.6° → latitude must be within ±52°.
    assert -52.5 <= pos.latitude <= 52.5
    assert -180 <= pos.longitude <= 180


# --- graceful degradation (no network) ---

def test_fetch_astronauts_returns_model_on_failure(monkeypatch):
    """fetch_astronauts must return an Astronauts model (possibly empty) on failure."""
    import engine.ingest.open_notify as on
    from engine.models import Astronauts

    # Force the fetcher to fail by monkeypatching the client to raise.
    class _FailClient:
        def get(self, *a, **k):
            raise RuntimeError("no network")

        def close(self):
            pass

    # Clear any cache so the fetcher is actually invoked.
    monkeypatch.setattr(on, "DiskCache", lambda *a, **k: _NullCache())
    result = on.fetch_astronauts(client=_FailClient())
    assert isinstance(result, Astronauts)
    assert result.number == 0


class _NullCache:
    """A cache that never returns a hit and never stores (forces fetcher path)."""

    def get_or_set(self, source, fetcher, params=None, ttl_s=3600):
        return fetcher()
