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


def test_fuel_optimal_maneuver_tool(tools):
    """The fuel-optimal maneuver tool returns a verified burn."""
    result = tools.fuel_optimal_maneuver(1, target_miss_km=10.0, lead_time_min=60.0)
    assert result["event_id"] == 1
    assert "dv_total_ms" in result
    assert "verified_miss_km" in result
    assert "cw_predicted_miss_km" in result
    assert result["propellant_g"] >= 0
    # If a burn was needed, it should be verified
    if result["dv_total_ms"] > 0:
        assert result["verified_miss_km"] > 0


def test_collision_probability_realistic_tool(tools):
    """The realistic Pc tool returns both analytic and realism-adjusted Pc."""
    result = tools.collision_probability_realistic(1, realism_factor=2.0)
    assert "pc_analytic" in result
    assert "pc_realistic" in result
    assert result["realism_factor"] == 2.0
    assert 0.0 <= result["pc_analytic"] <= 1.0
    assert 0.0 <= result["pc_realistic"] <= 1.0


def test_generate_cdm_message_tool(tools):
    """The CDM generation tool returns a CCSDS-compliant message."""
    result = tools.generate_cdm_message(1)
    assert result["format"] == "CCSDS_CDM_V1.0_KVN"
    assert "CCSDS_CDM_VERS = 1.0" in result["cdm"]
    assert "MISS_DISTANCE =" in result["cdm"]
    assert "COLLISION_PROBABILITY =" in result["cdm"]


def test_dispatch_new_tools(tools):
    """The new tools are routable via dispatch."""
    r1 = tools.dispatch("fuel_optimal_maneuver", {"event_id": 1, "target_miss_km": 10.0})
    assert "dv_total_ms" in r1
    r2 = tools.dispatch("collision_probability_realistic", {"event_id": 1})
    assert "pc_realistic" in r2
    r3 = tools.dispatch("generate_cdm_message", {"event_id": 1})
    assert "cdm" in r3


def test_query_knowledge_base_tool(tools):
    """The RAG tool retrieves relevant, cited knowledge."""
    result = tools.query_knowledge_base("How is collision probability computed?", k=3)
    assert "context" in result
    assert "citations" in result
    assert result["count"] >= 1
    # Should surface collision-probability knowledge
    topics = {c["topic"] for c in result["citations"]}
    assert "collision-probability" in topics


def test_query_knowledge_base_dispatch(tools):
    """The RAG tool is routable via dispatch."""
    result = tools.dispatch("query_knowledge_base", {"query": "avoidance maneuver propellant", "k": 2})
    assert "context" in result
    assert result["count"] >= 1


def test_tool_and_schema_counts_match(tools):
    """TOOL_NAMES and TOOL_SCHEMAS must stay in sync (19 tools now)."""
    from agent.tools import TOOL_SCHEMAS, AgentTools

    assert len(AgentTools.TOOL_NAMES) == len(TOOL_SCHEMAS)
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert schema_names == set(AgentTools.TOOL_NAMES)


# --- Phase A: live data tools (graceful — pass whether or not APIs are up) ---

def test_get_near_earth_objects_tool(tools):
    result = tools.get_near_earth_objects(days=3)
    assert "count" in result
    assert "objects" in result
    assert result["source"] == "NASA NEO Feed"
    # If NEOs were returned, they must be well-formed.
    for obj in result["objects"]:
        assert "name" in obj
        assert "hazardous" in obj


def test_get_earth_imagery_tool(tools):
    result = tools.get_earth_imagery()
    assert "available" in result
    if result["available"]:
        assert "latest" in result
        assert "image_url" in result["latest"]


def test_get_astronomy_picture_tool(tools):
    result = tools.get_astronomy_picture()
    assert "available" in result
    if result["available"]:
        assert "title" in result
        assert result["media_type"] in ("image", "video")


def test_get_iss_position_tool(tools):
    result = tools.get_iss_position()
    assert "available" in result
    if result["available"]:
        assert -90 <= result["latitude"] <= 90
        assert -180 <= result["longitude"] <= 180
        assert result["source"] in ("open-notify", "tle-computed")


def test_get_astronauts_tool(tools):
    result = tools.get_astronauts()
    assert "number" in result
    assert isinstance(result["number"], int)
    assert result["number"] >= 0


def test_get_catalog_statistics_tool(tools):
    result = tools.get_catalog_statistics(top_n=5)
    assert "available" in result
    if result["available"]:
        assert "top_countries" in result
        assert len(result["top_countries"]) <= 5
        for c in result["top_countries"]:
            assert "country" in c
            assert "orbital_payloads" in c


def test_get_recent_reentries_tool(tools):
    result = tools.get_recent_reentries(limit=5)
    assert "available" in result
    if result["available"]:
        assert "events" in result
        for e in result["events"]:
            assert "norad_id" in e


def test_search_literature_tool(tools):
    """Without an ADS key, this degrades gracefully to available=False."""
    result = tools.search_literature("collision probability", rows=3)
    assert "available" in result
    assert "count" in result


# --- Phase B: space-weather deepening tools (graceful) ---

def test_get_space_weather_detailed_tool(tools):
    result = tools.get_space_weather_detailed()
    assert "composite" in result
    assert "score" in result["composite"]
    assert "level" in result["composite"]
    assert "solar_wind" in result
    assert "xray" in result
    assert "protons" in result
    # Composite score must be in [0, 100].
    assert 0 <= result["composite"]["score"] <= 100


def test_get_space_weather_alerts_tool(tools):
    result = tools.get_space_weather_alerts(days=7)
    assert "total" in result
    assert "by_type" in result
    assert "active_storm" in result
    assert "storm_building" in result
    assert isinstance(result["active_storm"], bool)


def test_get_drag_uncertainty_tool(tools):
    result = tools.get_drag_uncertainty(1)
    assert "available" in result
    if result["available"]:
        assert "quiet_miss_km" in result
        assert "storm_miss_km" in result
        assert "band_km" in result
        assert "recommendation" in result
        assert result["band_km"] >= 0.0
