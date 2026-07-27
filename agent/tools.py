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

from engine.frames import relative_state_rsw, rsw_rotation
from engine.maneuvers import (
    DEFAULT_ISP_S,
    DEFAULT_MASS_KG,
    curated_options,
    mean_motion_from_alt,
    post_burn_miss,
    propellant_g,
    search_maneuvers,
)
from engine.covariance import collision_probability_both
from engine.fuel_optimal import fuel_optimal_with_verification
from engine.standards import generate_cdm
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

    # -- advanced astrodynamics tools ----------------------------------------

    def fuel_optimal_maneuver(
        self, event_id: int, target_miss_km: float = 10.0, lead_time_min: float = 60.0
    ) -> dict:
        """Minimum-Δv avoidance burn for a target miss, verified numerically.

        Uses the CW state-transition matrix to find the fuel-optimal burn
        direction/magnitude, then verifies the actual post-burn miss with the
        high-fidelity numerical propagator (J2 + drag). Returns both the CW
        estimate and the verified result.
        """
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        # RSW rotation at TCA (for Δv frame)
        rotation = rsw_rotation(state.r_primary, state.v_primary)
        # Mean motion from the primary's orbit
        alt = (self.ctx.primary.perigee_alt_km + self.ctx.primary.apogee_alt_km) / 2
        n = mean_motion_from_alt(alt)
        miss_rsw = [e.miss_r_km, e.miss_s_km, e.miss_w_km]
        vrel_rsw = [
            e.relative_velocity_kms if e.geometry == "in-track" else 0.0,
            e.relative_velocity_kms if e.geometry != "in-track" else e.relative_velocity_kms,
            0.0,
        ]
        # Use the actual relative velocity magnitude in the dominant direction
        vrel_rsw = [0.0, e.relative_velocity_kms, 0.0]

        result = fuel_optimal_with_verification(
            mean_motion=n,
            lead_time_s=lead_time_min * 60.0,
            miss_rsw=miss_rsw,
            rel_vel_rsw=vrel_rsw,
            target_miss_km=target_miss_km,
            r_primary_tca=state.r_primary,
            v_primary_tca=state.v_primary,
            r_secondary_tca=state.r_secondary,
            rsw_rotation=rotation,
            mass_kg=self.ctx.mass_kg,
            isp_s=self.ctx.isp_s,
            include_j2=True,
            include_drag=True,
            include_srp=False,
        )
        dv = result["dv_rsw_ms"]
        return {
            "event_id": event_id,
            "target_miss_km": target_miss_km,
            "dv_total_ms": round(result["dv_total_ms"], 2),
            "dv_rsw_ms": {
                "radial": round(float(dv[0]), 2),
                "in_track": round(float(dv[1]), 2),
                "cross_track": round(float(dv[2]), 2),
            },
            "propellant_g": round(result["propellant_g"], 1),
            "cw_predicted_miss_km": round(result["cw_predicted_miss_km"], 3),
            "verified_miss_km": round(result["verified_miss_km"], 3),
            "satisfies_target": result["satisfies_target"],
            "lead_time_min": lead_time_min,
            "note": result.get("note", "fuel-optimal burn (CW-optimized, numerically verified)"),
        }

    def collision_probability_realistic(self, event_id: int, realism_factor: float = 2.0) -> dict:
        """Both the analytic (fixed) and realism-adjusted collision probability.

        Reports both so the operator sees the effect of the covariance-realism
        assumption. The realism factor inflates the analytic covariance toward
        operational realism (Foster/Hall methodology).
        """
        e = self._event(event_id)
        miss_rsw = [e.miss_r_km, e.miss_s_km, e.miss_w_km]
        vrel_rsw = [0.0, e.relative_velocity_kms, 0.0]
        result = collision_probability_both(miss_rsw, vrel_rsw, e.hbr_km, realism_factor)
        return {
            "event_id": event_id,
            "pc_analytic": result["pc_analytic"],
            "pc_realistic": result["pc_realistic"],
            "realism_factor": result["realism_factor"],
            "note": (
                "pc_realistic uses a documented covariance realism factor "
                f"(k={realism_factor}); see docs/ADVANCED_ASTRODYNAMICS.md."
            ),
        }

    def generate_cdm_message(self, event_id: int) -> dict:
        """Generate a CCSDS-standard Conjunction Data Message (CDM) for an event.

        Produces a standards-compliant CDM (CCSDS 508.0-B-1) that an operator
        could ingest into existing SSA tooling — interoperability with the
        operational community.
        """
        e = self._event(event_id)
        secondary = self.ctx.catalog_by_id.get(e.secondary_norad)
        cdm_text = generate_cdm(e, self.ctx.primary, secondary)
        return {
            "event_id": event_id,
            "format": "CCSDS_CDM_V1.0_KVN",
            "cdm": cdm_text,
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
        "fuel_optimal_maneuver",
        "collision_probability_realistic",
        "generate_cdm_message",
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
    {
        "type": "function",
        "function": {
            "name": "fuel_optimal_maneuver",
            "description": "Compute the minimum-Δv (fuel-optimal) avoidance burn for a target miss distance, verified with high-fidelity numerical propagation (J2 + drag). Returns both the CW estimate and the verified post-burn miss.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "target_miss_km": {"type": "number", "description": "required post-burn miss (km), default 10"},
                    "lead_time_min": {"type": "number", "description": "burn lead time before TCA (min), default 60"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collision_probability_realistic",
            "description": "Compute both the analytic (fixed-covariance) and realism-adjusted collision probability for an event, using a documented covariance realism factor (Foster/Hall).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "realism_factor": {"type": "number", "description": "covariance realism factor k, default 2.0"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cdm_message",
            "description": "Generate a CCSDS-standard Conjunction Data Message (CDM, CCSDS 508.0-B-1) for an event — interoperable with operational SSA tooling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                },
                "required": ["event_id"],
            },
        },
    },
]
