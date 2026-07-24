"""The agent's tool contract — the AI's ONLY way to touch numbers.

Every tool returns engine-computed data. The Granite agent calls these tools to
triage, select maneuvers, and answer what-ifs; it never computes an orbit, a
probability, or a burn itself. `submit_maneuver_card` is *server-composed*: the
agent supplies the event + chosen option + prose, and the server fills every
figure from the engine — the model cannot transcribe a number it never handles.

This module is deliberately framework-agnostic: tools are plain methods returning
JSON-serializable dicts, so they work identically under the watsonx REST agent
loop, the FastAPI layer, and the golden-path tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from engine.frames import relative_state_rsw
from engine.maneuvers import (
    DEFAULT_ISP_S,
    DEFAULT_MASS_KG,
    curated_options,
    mean_motion_from_alt,
    post_burn_miss,
    propellant_g,
    search_maneuvers,
)
from engine.models import (
    ManeuverConstraints,
    ObjectInfo,
    ScoredConjunction,
    ScreeningConfig,
    SpaceWeatherState,
    TLEData,
)
from engine.propagate import satrec_from_tle, tsince_minutes
from engine.tca import refine_tca

R_EARTH_KM = 6378.135


@dataclass
class ToolContext:
    """The screening state the agent operates over."""

    primary: TLEData
    catalog_by_id: dict[int, TLEData]
    events: list[ScoredConjunction]  # ranked, highest risk first
    object_info: dict[int, ObjectInfo] = field(default_factory=dict)
    space_weather: SpaceWeatherState | None = None
    config: ScreeningConfig = field(default_factory=ScreeningConfig)
    start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mass_kg: float = DEFAULT_MASS_KG
    isp_s: float = DEFAULT_ISP_S


class AgentTools:
    """The seven tools. Event ids are 1-based ranks (event #1 = highest risk)."""

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    # -- helpers -------------------------------------------------------------

    def _event(self, event_id: int) -> ScoredConjunction:
        if not 1 <= event_id <= len(self.ctx.events):
            raise ValueError(f"event_id {event_id} out of range (1-{len(self.ctx.events)})")
        return self.ctx.events[event_id - 1]

    def _inertial_state_at_tca(self, event: ScoredConjunction):
        """Re-refine the event to recover the inertial states at TCA (for maneuvers)."""
        secondary = self.ctx.catalog_by_id.get(event.secondary_norad)
        if secondary is None:
            raise ValueError(f"secondary {event.secondary_norad} not in catalog")
        primary_sat = satrec_from_tle(self.ctx.primary)
        secondary_sat = satrec_from_tle(secondary)
        state = refine_tca(
            primary_sat,
            secondary_sat,
            tsince_minutes(event.tca, self.ctx.primary),
            tsince_minutes(event.tca, secondary),
            step_s=self.ctx.config.time_step_s,
        )
        return state  # .r_primary, .v_primary, .r_secondary, .v_secondary

    # -- the seven tools -----------------------------------------------------

    def get_satellite_info(self, norad_id: int | None = None) -> dict:
        """Details for the primary (default) or a catalog object."""
        if norad_id is None or norad_id == self.ctx.primary.norad_id:
            sat = self.ctx.primary
        else:
            sat = self.ctx.catalog_by_id.get(norad_id)
            if sat is None:
                return {"error": f"NORAD {norad_id} not in catalog"}
        info = self.ctx.object_info.get(sat.norad_id)
        alt = (sat.perigee_alt_km + sat.apogee_alt_km) / 2
        return {
            "norad_id": sat.norad_id,
            "name": sat.name,
            "tle_epoch": sat.epoch.isoformat(),
            "tle_age_days": round(sat.age_days, 2),
            "inclination_deg": round(sat.inclination_deg, 2),
            "perigee_alt_km": round(sat.perigee_alt_km, 1),
            "apogee_alt_km": round(sat.apogee_alt_km, 1),
            "object_type": info.object_type if info else "UNKNOWN",
            "rcs_size": info.rcs_size if info else "",
        }

    def list_conjunctions(self, limit: int = 20) -> dict:
        """Ranked conjunctions for the primary (highest risk first)."""
        rows = []
        for i, e in enumerate(self.ctx.events[:limit], 1):
            rows.append(
                {
                    "event_id": i,
                    "secondary_name": e.secondary_name,
                    "secondary_norad": e.secondary_norad,
                    "secondary_type": e.secondary_type,
                    "tca": e.tca.isoformat(),
                    "miss_km": round(e.miss_distance_km, 3),
                    "vrel_kms": round(e.relative_velocity_kms, 3),
                    "geometry": e.geometry,
                    "pc": e.pc,
                    "risk_score": round(e.risk_score, 1),
                    "storm_flag": e.storm_flag,
                    "secondary_maneuverable": e.secondary_maneuverable,
                }
            )
        return {"primary": self.ctx.primary.name, "count": len(rows), "events": rows}

    def get_event_details(self, event_id: int) -> dict:
        """Full geometry + object card for one event."""
        e = self._event(event_id)
        info = self.ctx.object_info.get(e.secondary_norad)
        return {
            "event_id": event_id,
            "secondary_name": e.secondary_name,
            "secondary_norad": e.secondary_norad,
            "secondary_type": e.secondary_type,
            "secondary_country": info.country if info else "",
            "secondary_maneuverable": e.secondary_maneuverable,
            "tca": e.tca.isoformat(),
            "miss_km": round(e.miss_distance_km, 3),
            "vrel_kms": round(e.relative_velocity_kms, 3),
            "miss_rsw_km": {
                "radial": round(e.miss_r_km, 3),
                "in_track": round(e.miss_s_km, 3),
                "cross_track": round(e.miss_w_km, 3),
            },
            "geometry": e.geometry,
            "hbr_km": round(e.hbr_km, 4),
            "pc": e.pc,
            "risk_score": round(e.risk_score, 1),
            "storm_flag": e.storm_flag,
        }

    def search_maneuvers(self, event_id: int, constraints: dict | None = None) -> dict:
        """Propellant-aware avoidance-maneuver options for an event."""
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        cons = ManeuverConstraints(**(constraints or {}))
        options = search_maneuvers(
            e.tca,
            state.r_primary,
            state.v_primary,
            state.r_secondary,
            constraints=cons,
            mass_kg=self.ctx.mass_kg,
            isp_s=self.ctx.isp_s,
        )
        curated = curated_options(options)
        return {
            "event_id": event_id,
            "original_miss_km": round(e.miss_distance_km, 3),
            "mass_kg": self.ctx.mass_kg,
            "isp_s": self.ctx.isp_s,
            "options": [
                {
                    "option_index": options.index(o),
                    "kind": o.kind,
                    "burn_epoch": o.burn_epoch.isoformat(),
                    "lead_time_min": o.lead_time_min,
                    "dv_total_ms": round(o.dv_total_ms, 1),
                    "dv_rsw_ms": {
                        "radial": round(o.dv_r_ms, 1),
                        "in_track": round(o.dv_s_ms, 1),
                        "cross_track": round(o.dv_w_ms, 1),
                    },
                    "propellant_g": round(o.propellant_g, 1),
                    "post_burn_miss_km": round(o.post_burn_miss_km, 3),
                    "satisfies_constraints": o.satisfies_constraints,
                }
                for o in curated
            ],
        }

    def get_space_weather(self) -> dict:
        """Current geomagnetic conditions."""
        sw = self.ctx.space_weather
        if sw is None:
            return {"available": False}
        return {
            "available": True,
            "max_kp_3day": round(sw.max_kp_3day, 2),
            "active_storm": sw.active_storm,
            "fetched_at": sw.fetched_at.isoformat(),
        }

    def repropagate_with_burn(
        self,
        event_id: int,
        dv_r_ms: float = 0.0,
        dv_s_ms: float = 0.0,
        dv_w_ms: float = 0.0,
        lead_time_min: float = 60.0,
    ) -> dict:
        """What-if: predicted miss at TCA after a specific burn."""
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        dv_rsw_kms = [dv_r_ms / 1000.0, dv_s_ms / 1000.0, dv_w_ms / 1000.0]
        new_miss = post_burn_miss(
            state.r_primary, state.v_primary, state.r_secondary,
            dv_rsw_kms, lead_time_min * 60.0,
        )
        return {
            "event_id": event_id,
            "original_miss_km": round(e.miss_distance_km, 3),
            "burn": {"dv_r_ms": dv_r_ms, "dv_s_ms": dv_s_ms, "dv_w_ms": dv_w_ms,
                     "lead_time_min": lead_time_min},
            "post_burn_miss_km": round(new_miss, 3),
            "miss_change_km": round(new_miss - e.miss_distance_km, 3),
        }

    def submit_maneuver_card(
        self,
        event_id: int,
        dv_r_ms: float = 0.0,
        dv_s_ms: float = 0.0,
        dv_w_ms: float = 0.0,
        lead_time_min: float = 60.0,
        notes: str = "",
    ) -> dict:
        """Server-composed maneuver card from specific burn parameters.

        The agent picks a burn (from search_maneuvers) and passes its Δv and lead
        time; the server computes the post-burn miss and propellant from the engine
        and composes the card. Numbers never come from the model.
        """
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        dv_rsw_kms = [dv_r_ms / 1000.0, dv_s_ms / 1000.0, dv_w_ms / 1000.0]
        new_miss = post_burn_miss(
            state.r_primary, state.v_primary, state.r_secondary,
            dv_rsw_kms, lead_time_min * 60.0,
        )
        dv_total_ms = (dv_r_ms**2 + dv_s_ms**2 + dv_w_ms**2) ** 0.5
        grams = propellant_g(dv_total_ms, self.ctx.mass_kg, self.ctx.isp_s)
        burn_epoch = e.tca - timedelta(minutes=lead_time_min)
        return {
            "card_type": "AVOIDANCE_MANEUVER",
            "status": "RECOMMENDATION — human approval required",
            "primary": self.ctx.primary.name,
            "secondary": e.secondary_name,
            "tca": e.tca.isoformat(),
            "original_miss_km": round(e.miss_distance_km, 3),
            "burn_epoch": burn_epoch.isoformat(),
            "lead_time_min": lead_time_min,
            "delta_v": {
                "total_ms": round(dv_total_ms, 1),
                "radial_ms": round(dv_r_ms, 1),
                "in_track_ms": round(dv_s_ms, 1),
                "cross_track_ms": round(dv_w_ms, 1),
            },
            "propellant_g": round(grams, 1),
            "predicted_post_burn_miss_km": round(new_miss, 3),
            "spacecraft": {"mass_kg": self.ctx.mass_kg, "isp_s": self.ctx.isp_s},
            "assumptions": [
                "Impulsive-burn approximation",
                "Two-body propagation for the maneuver (no drag/J2 over the short arc)",
                "User-supplied mass and Isp",
                "Secondary is un-maneuvered",
            ],
            "verification": "Re-screen within 24 h of TCA; confirm post-burn miss before executing.",
            "operator_notes": notes,
        }

    # -- dispatch ------------------------------------------------------------

    TOOL_NAMES = [
        "get_satellite_info",
        "list_conjunctions",
        "get_event_details",
        "search_maneuvers",
        "get_space_weather",
        "repropagate_with_burn",
        "submit_maneuver_card",
    ]

    def dispatch(self, tool_name: str, arguments: dict | None = None) -> dict:
        """Route a model tool call to the right method. Errors are returned, not raised,
        so the agent can recover and explain them to the operator."""
        arguments = arguments or {}
        if tool_name not in self.TOOL_NAMES:
            return {"error": f"unknown tool '{tool_name}'"}
        try:
            method = getattr(self, tool_name)
            return method(**arguments)
        except (ValueError, TypeError, KeyError) as exc:
            return {"error": f"{tool_name} failed: {exc}"}


# OpenAI-style function schemas — what the Granite agent sees.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_satellite_info",
            "description": "Get details for the primary satellite (or a catalog object by NORAD id): orbit, TLE age, object type.",
            "parameters": {
                "type": "object",
                "properties": {"norad_id": {"type": "integer", "description": "NORAD id; omit for the primary"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_conjunctions",
            "description": "List ranked conjunctions for the primary satellite, highest risk first.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "max events to return (default 20)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_details",
            "description": "Get full RSW geometry, object card, and risk for one conjunction event.",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "integer"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_maneuvers",
            "description": "Compute propellant-aware avoidance-maneuver options for an event, given operator constraints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "constraints": {
                        "type": "object",
                        "properties": {
                            "fuel_margin_g": {"type": "number", "description": "propellant to keep in reserve (g)"},
                            "min_post_burn_miss_km": {"type": "number", "description": "required post-burn miss (km)"},
                        },
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_space_weather",
            "description": "Get current geomagnetic conditions (Kp forecast, active storm).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repropagate_with_burn",
            "description": "What-if: predict the miss distance at TCA after applying a specific burn (RSW Δv in m/s, lead time in minutes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "dv_r_ms": {"type": "number"},
                    "dv_s_ms": {"type": "number"},
                    "dv_w_ms": {"type": "number"},
                    "lead_time_min": {"type": "number"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_maneuver_card",
            "description": "Produce the standard-format maneuver card for a chosen burn. Pass the burn's RSW Δv (m/s) and lead time (min) from search_maneuvers; the server composes all numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "dv_r_ms": {"type": "number"},
                    "dv_s_ms": {"type": "number"},
                    "dv_w_ms": {"type": "number"},
                    "lead_time_min": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
]
