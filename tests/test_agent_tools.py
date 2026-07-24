"""Tests for agent/tools.py — the seven-tool contract, exercised on real engine output."""

from datetime import datetime, timezone

import pytest

from agent.tools import TOOL_SCHEMAS, AgentTools, ToolContext
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


def test_tool_schemas_complete():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == set(AgentTools.TOOL_NAMES)


def test_get_satellite_info(tools):
    info = tools.get_satellite_info()
    assert info["norad_id"] == 25544
    assert "ISS" in info["name"]
    assert info["perigee_alt_km"] > 400


def test_list_conjunctions(tools):
    result = tools.list_conjunctions(limit=5)
    assert result["count"] >= 1
    first = result["events"][0]
    assert first["event_id"] == 1
    assert first["secondary_norad"] == 99998
    assert first["secondary_type"] == "DEBRIS"
    assert first["miss_km"] > 0


def test_get_event_details(tools):
    detail = tools.get_event_details(1)
    assert detail["secondary_norad"] == 99998
    assert "miss_rsw_km" in detail
    assert detail["secondary_maneuverable"] is False  # DEBRIS
    # RSW components reconstruct the miss distance
    rsw = detail["miss_rsw_km"]
    import math

    recon = math.sqrt(rsw["radial"] ** 2 + rsw["in_track"] ** 2 + rsw["cross_track"] ** 2)
    assert recon == pytest.approx(detail["miss_km"], rel=1e-2)


def test_search_maneuvers(tools):
    result = tools.search_maneuvers(1, {"min_post_burn_miss_km": 5.0})
    assert result["original_miss_km"] > 0
    assert len(result["options"]) >= 1
    for opt in result["options"]:
        assert "dv_total_ms" in opt
        assert "post_burn_miss_km" in opt
        assert opt["propellant_g"] >= 0


def test_repropagate_with_burn(tools):
    result = tools.repropagate_with_burn(1, dv_s_ms=100.0, lead_time_min=60.0)
    assert "post_burn_miss_km" in result
    assert "miss_change_km" in result


def test_submit_maneuver_card_is_server_composed(tools):
    """The card's numbers come from the engine, not from any model input."""
    card = tools.submit_maneuver_card(
        1, dv_r_ms=0.0, dv_s_ms=100.0, dv_w_ms=0.0, lead_time_min=60.0, notes="test note"
    )
    assert card["card_type"] == "AVOIDANCE_MANEUVER"
    assert "human approval required" in card["status"]
    assert card["delta_v"]["total_ms"] == 100.0
    assert card["predicted_post_burn_miss_km"] > 0
    assert card["propellant_g"] > 0
    assert card["operator_notes"] == "test note"
    assert len(card["assumptions"]) >= 3


def test_dispatch_unknown_tool(tools):
    result = tools.dispatch("nonexistent_tool", {})
    assert "error" in result


def test_dispatch_bad_event_id(tools):
    result = tools.dispatch("get_event_details", {"event_id": 999})
    assert "error" in result


def test_dispatch_routes_correctly(tools):
    result = tools.dispatch("list_conjunctions", {"limit": 3})
    assert "events" in result
