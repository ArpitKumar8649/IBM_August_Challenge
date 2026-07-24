"""Phase 3 exit gate — the golden-path integration test.

Proves the full judgment-layer contract end-to-end, offline (scripted model):
  1. A realistic operator exchange drives the agent through triage -> maneuver
     search -> a server-composed maneuver card.
  2. Every number in the card traces to the engine (server-composed).
  3. The validator passes on honest output and blocks an injected fabrication.
  4. The card is human-in-the-loop (recommendation, never autonomous).

This is the make-or-break guarantee: the AI judges, the physics computes, and no
invented number ever reaches the operator.
"""

from datetime import datetime, timezone

import pytest

from agent.session import AgentLoop
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
def context():
    primary = _tle(25544, "ISS (ZARYA)", ISS_L2)
    secondary = _tle(99998, "COSMOS 2251 DEB", NEAR_L2)
    config = ScreeningConfig(window_days=1.0, time_step_s=60.0, miss_threshold_km=100.0)
    object_info = {99998: ObjectInfo(norad_id=99998, object_type="DEBRIS", size_m=0.5)}
    scored, _ = full_screen(primary, [primary, secondary], object_info=object_info, config=config)
    return ToolContext(
        primary=primary,
        catalog_by_id={primary.norad_id: primary, secondary.norad_id: secondary},
        events=scored,
        object_info=object_info,
        config=config,
    )


class GoldenPathModel:
    """Scripted model that walks the full operator workflow, then answers with a
    number drawn from the tool results (honest) — and a variant that fabricates."""

    def __init__(self, fabricate=False):
        self.fabricate = fabricate
        self.step = 0
        self.last_search = None

    def __call__(self, messages, tools):
        self.step += 1
        if self.step == 1:  # triage
            return self._tool("c1", "list_conjunctions", '{"limit": 3}')
        if self.step == 2:  # inspect the top event
            return self._tool("c2", "get_event_details", '{"event_id": 1}')
        if self.step == 3:  # search maneuvers with operator constraints
            return self._tool(
                "c3", "search_maneuvers",
                '{"event_id": 1, "constraints": {"min_post_burn_miss_km": 80}}',
            )
        if self.step == 4:  # produce the card from the burn the search returned
            # Read the actual search result from the transcript and pick its first option.
            search_result = self._find_tool_result(messages, "c3")
            opt = search_result["options"][0]
            dv = opt["dv_rsw_ms"]
            args = (
                f'{{"event_id": 1, "dv_r_ms": {dv["radial"]}, "dv_s_ms": {dv["in_track"]}, '
                f'"dv_w_ms": {dv["cross_track"]}, "lead_time_min": {opt["lead_time_min"]}, '
                f'"notes": "operator concurs"}}'
            )
            return self._tool("c4", "submit_maneuver_card", args)
        # final answer
        if self.fabricate:
            # 1234.5 km is a plausible-sounding miss distance that is NOT in any
            # tool result and won't collide with a NORAD id (5-digit integers).
            content = "The post-burn miss will be 1234.5 km. Card ready."
        else:
            content = "Maneuver card ready for your approval. The burn raises the miss above 80 km."
        return {"role": "assistant", "content": content, "tool_calls": None}

    @staticmethod
    def _find_tool_result(messages, call_id):
        import json

        for m in messages:
            if m.get("role") == "tool" and m.get("tool_call_id") == call_id:
                return json.loads(m["content"])
        raise AssertionError(f"no tool result for {call_id}")

    @staticmethod
    def _tool(call_id, name, arguments):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": name, "arguments": arguments}}
            ],
        }


def test_golden_path_full_workflow(context):
    """The full operator workflow runs end-to-end and the audit passes."""
    tools = AgentTools(context)
    validator = Validator()
    loop = AgentLoop(tools, validator, GoldenPathModel())
    resp = loop.run("Triage my conjunctions and plan an avoidance burn for the top one.")

    # All four tools were exercised in order.
    assert resp.tool_calls_made == [
        "list_conjunctions",
        "get_event_details",
        "search_maneuvers",
        "submit_maneuver_card",
    ]
    # Honest output passes the validator.
    assert resp.audit_passed is True
    assert "⚠[unverified]" not in resp.content


def test_golden_path_card_is_server_composed(context):
    """The maneuver card's numbers come from the engine, not the model."""
    tools = AgentTools(context)
    # The agent picks a burn from the search; the server composes the card from it.
    maneuvers = tools.search_maneuvers(1, {"min_post_burn_miss_km": 80})
    opt = maneuvers["options"][0]
    dv = opt["dv_rsw_ms"]
    card = tools.submit_maneuver_card(
        1, dv_r_ms=dv["radial"], dv_s_ms=dv["in_track"], dv_w_ms=dv["cross_track"],
        lead_time_min=opt["lead_time_min"], notes="test",
    )

    assert card["card_type"] == "AVOIDANCE_MANEUVER"
    assert "human approval required" in card["status"]
    # The card's Δv and propellant match the engine's option exactly.
    assert card["delta_v"]["total_ms"] == opt["dv_total_ms"]
    assert card["predicted_post_burn_miss_km"] == opt["post_burn_miss_km"]
    assert card["propellant_g"] == opt["propellant_g"]


def test_golden_path_blocks_fabrication(context):
    """If the model invents a number, the validator flags it and the audit fails."""
    tools = AgentTools(context)
    validator = Validator()
    loop = AgentLoop(tools, validator, GoldenPathModel(fabricate=True))
    resp = loop.run("Triage my conjunctions and plan an avoidance burn for the top one.")

    assert "⚠[unverified]" in resp.content  # the invented 1234.5 is flagged
    assert resp.audit_passed is False


def test_golden_path_human_in_loop(context):
    """The card is a recommendation requiring human approval — never autonomous."""
    tools = AgentTools(context)
    card = tools.submit_maneuver_card(1, dv_s_ms=100.0, lead_time_min=60.0)
    assert "RECOMMENDATION" in card["status"]
    assert "human approval required" in card["status"]
    assert "verification" in card  # re-screen guidance present
