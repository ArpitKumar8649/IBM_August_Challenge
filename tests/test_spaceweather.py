"""Tests for engine/ingest/spaceweather.py — storm flag logic + live fetch."""

from datetime import datetime, timedelta, timezone

import pytest

from engine.ingest.spaceweather import (
    STORM_KP_THRESHOLD,
    fetch_space_weather,
    storm_flag_for_event,
)
from engine.models import SpaceWeatherState

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _state(max_kp, forecast, active_storm=False):
    return SpaceWeatherState(
        max_kp_3day=max_kp, kp_forecast=forecast, active_storm=active_storm,
        fetched_at=NOW,
    )


def test_flag_on_active_storm(monkeypatch):
    monkeypatch.setattr("engine.ingest.spaceweather.datetime", _FrozenNow(NOW))
    state = _state(2.0, [], active_storm=True)
    tca = NOW + timedelta(days=2)
    assert storm_flag_for_event(tca, state) is True


def test_flag_on_high_kp_forecast(monkeypatch):
    monkeypatch.setattr("engine.ingest.spaceweather.datetime", _FrozenNow(NOW))
    forecast = [
        {"time": (NOW + timedelta(hours=6)).isoformat(), "kp": 7.0},
    ]
    state = _state(7.0, forecast)
    tca = NOW + timedelta(days=1)
    assert storm_flag_for_event(tca, state) is True


def test_no_flag_when_calm(monkeypatch):
    monkeypatch.setattr("engine.ingest.spaceweather.datetime", _FrozenNow(NOW))
    forecast = [{"time": (NOW + timedelta(hours=6)).isoformat(), "kp": 3.0}]
    state = _state(3.0, forecast)
    tca = NOW + timedelta(days=1)
    assert storm_flag_for_event(tca, state) is False


def test_no_flag_when_storm_after_tca(monkeypatch):
    """A storm forecast *after* the TCA must not flag an earlier event."""
    monkeypatch.setattr("engine.ingest.spaceweather.datetime", _FrozenNow(NOW))
    forecast = [{"time": (NOW + timedelta(days=2)).isoformat(), "kp": 8.0}]
    state = _state(8.0, forecast)
    tca = NOW + timedelta(hours=12)  # before the storm
    assert storm_flag_for_event(tca, state) is False


def test_live_fetch_returns_state():
    """Live: SWPC is reachable; returns a well-formed state."""
    state = fetch_space_weather()
    assert 0.0 <= state.max_kp_3day <= 9.0
    assert isinstance(state.active_storm, bool)


class _FrozenNow:
    """Stand-in for datetime with a frozen now() for deterministic tests."""

    def __init__(self, now):
        self._now = now

    def now(self, tz=None):
        return self._now

    def fromisoformat(self, s):
        return datetime.fromisoformat(s)
