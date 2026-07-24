"""Tests for api/main.py — endpoints via TestClient (offline, injected context)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from agent.session import AgentLoop
from agent.tools import ToolContext
from agent.validator import Validator
from api.main import create_app
from engine.models import ObjectInfo, ScreeningConfig
from engine.screen import full_screen

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"
NEAR_L2 = "2 99998  51.6400 209.5700 0006859  39.6000 320.5300 15.50100000431234"


def _tle(norad, name, l2):
    from engine.models import TLEData

    return TLEData(
        norad_id=norad, name=name, line1=ISS_L1, line2=l2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


@pytest.fixture
def client():
    primary = _tle(25544, "ISS (ZARYA)", ISS_L2)
    secondary = _tle(99998, "COSMOS 2251 DEB", NEAR_L2)
    config = ScreeningConfig(window_days=1.0, time_step_s=60.0, miss_threshold_km=100.0)
    object_info = {99998: ObjectInfo(norad_id=99998, object_type="DEBRIS", size_m=0.5)}
    scored, _ = full_screen(primary, [primary, secondary], object_info=object_info, config=config)
    ctx = ToolContext(
        primary=primary,
        catalog_by_id={primary.norad_id: primary, secondary.norad_id: secondary},
        events=scored,
        object_info=object_info,
        config=config,
    )
    return TestClient(create_app(ctx))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["primary_norad"] == 25544
    assert body["events"] >= 1


def test_primary_satellite(client):
    r = client.get("/api/satellite")
    assert r.status_code == 200
    assert "ISS" in r.json()["name"]


def test_satellite_not_found(client):
    r = client.get("/api/satellites/999999")
    assert r.status_code == 404


def test_events(client):
    r = client.get("/api/events?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["events"][0]["event_id"] == 1


def test_event_detail(client):
    r = client.get("/api/events/1")
    assert r.status_code == 200
    body = r.json()
    assert "miss_rsw_km" in body
    assert body["secondary_type"] == "DEBRIS"


def test_event_detail_not_found(client):
    r = client.get("/api/events/999")
    assert r.status_code == 404


def test_maneuvers(client):
    r = client.get("/api/events/1/maneuvers?min_post_burn_miss_km=80")
    assert r.status_code == 200
    body = r.json()
    assert "options" in body
    assert body["original_miss_km"] > 0


def test_space_weather(client):
    r = client.get("/api/space-weather")
    assert r.status_code == 200
    assert "available" in r.json()


def test_chat_with_scripted_model(client, monkeypatch):
    """POST /api/chat runs the agent; inject a scripted model to stay offline."""
    from agent import session as session_mod

    class ScriptedClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "list_conjunctions", "arguments": '{"limit": 3}'}}
                    ],
                }
            return {"role": "assistant", "content": "Your top threat is event 1.", "tool_calls": None}

    monkeypatch.setattr(session_mod, "WatsonxClient", lambda *a, **k: ScriptedClient())
    r = client.post("/api/chat", json={"message": "What's my top threat?"})
    assert r.status_code == 200
    body = r.json()
    assert "list_conjunctions" in body["tool_calls_made"]
    assert "event 1" in body["content"]


def test_chat_stream_sse(client, monkeypatch):
    """GET /api/chat/events streams SSE events."""
    from agent import session as session_mod

    class ScriptedClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "get_space_weather", "arguments": "{}"}}
                    ],
                }
            return {"role": "assistant", "content": "Space weather is calm.", "tool_calls": None}

    monkeypatch.setattr(session_mod, "WatsonxClient", lambda *a, **k: ScriptedClient())
    with client.stream("GET", "/api/chat/events", params={"message": "How's space weather?"}) as r:
        assert r.status_code == 200
        text = "".join(chunk for chunk in r.iter_text())
    assert "tool_call" in text
    assert "content" in text
    assert "done" in text
