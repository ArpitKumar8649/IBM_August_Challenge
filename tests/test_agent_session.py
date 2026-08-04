"""Tests for agent/session.py — the tool-calling loop with a scripted model."""

from datetime import datetime, timezone

import pytest

from agent.session import AgentLoop, parse_tool_arguments
from agent.tools import AgentTools, ToolContext
from agent.validator import Validator
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
def tools():
    primary = _tle(25544, "ISS (ZARYA)", ISS_L2)
    secondary = _tle(99998, "NEAR-OBJ", NEAR_L2)
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
    return AgentTools(ctx)


class ScriptedModel:
    """A fake model that returns a pre-written sequence of assistant messages."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, messages, tools):
        resp = self.responses[self.calls]
        self.calls += 1
        return resp


def test_parse_tool_arguments_plain_json():
    assert parse_tool_arguments('{"event_id": 1}') == {"event_id": 1}


def test_parse_tool_arguments_double_encoded():
    """Granite sometimes double-encodes arguments as a JSON string."""
    assert parse_tool_arguments('"{\\"event_id\\": 1}"') == {"event_id": 1}


def test_parse_tool_arguments_empty():
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments(None) == {}


def test_loop_calls_tool_then_answers(tools):
    """Model calls list_conjunctions, then answers using the returned numbers."""
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_conjunctions", "arguments": '{"limit": 5}'},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Your top conjunction is NEAR-OBJ with a miss of 73.5 km.",
            "tool_calls": None,
        },
    ]
    loop = AgentLoop(tools, Validator(), ScriptedModel(responses))
    resp = loop.run("What's my top threat?")
    assert "list_conjunctions" in resp.tool_calls_made
    assert "NEAR-OBJ" in resp.content
    assert resp.audit_passed is True


def test_loop_flags_invented_number(tools):
    """A number not in any tool result must be flagged as unverified."""
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_conjunctions", "arguments": '{"limit": 5}'},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "The miss distance is 12345.6 km.",  # invented
            "tool_calls": None,
        },
    ]
    loop = AgentLoop(tools, Validator(), ScriptedModel(responses))
    resp = loop.run("What's the miss?")
    assert "⚠[unverified]" in resp.content
    assert resp.audit_passed is False


def test_loop_produces_maneuver_card(tools):
    """End-to-end: model searches maneuvers and submits a server-composed card."""
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "search_maneuvers", "arguments": '{"event_id": 1}'}},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c2", "type": "function",
                 "function": {"name": "submit_maneuver_card",
                              "arguments": '{"event_id": 1, "dv_r_ms": 0.0, "dv_s_ms": 50.0, "dv_w_ms": 0.0, "lead_time_min": 60.0, "notes": "go"}'}},
            ],
        },
        {
            "role": "assistant",
            "content": "Maneuver card ready for your approval.",
            "tool_calls": None,
        },
    ]
    loop = AgentLoop(tools, Validator(), ScriptedModel(responses))
    resp = loop.run("Plan an avoidance burn.")
    assert "search_maneuvers" in resp.tool_calls_made
    assert "submit_maneuver_card" in resp.tool_calls_made
    assert "Maneuver card ready" in resp.content


def test_loop_handles_tool_error_gracefully(tools):
    """A bad tool call returns an error the model can see, not a crash."""
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "get_event_details", "arguments": '{"event_id": 999}'}},
            ],
        },
        {"role": "assistant", "content": "Sorry, no such event.", "tool_calls": None},
    ]
    loop = AgentLoop(tools, Validator(), ScriptedModel(responses))
    resp = loop.run("Show event 999.")
    assert "Sorry, no such event." in resp.content
