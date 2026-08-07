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
from engine.covariance import collision_probability_both
from engine.fuel_optimal import fuel_optimal_with_verification
from engine.standards import generate_cdm
from engine.ingest.nasa_open import fetch_apod, fetch_epic_latest, fetch_neo_feed, search_ads
from engine.ingest.open_notify import fetch_astronauts, fetch_iss_position
from engine.ingest.spacetrack_ext import fetch_boxscore, fetch_recent_decays
from engine.ingest.swpc_products import (
    fetch_proton_flux,
    fetch_solar_wind,
    fetch_xray_flux,
    storm_risk_composite,
)
from engine.ingest.donki_ext import analyze_donki, fetch_donki_all
from engine.ingest.stac_client import search_burnt_area, search_imagery
from engine.ingest.horizons import fetch_body_state, sun_direction_geocentric
from engine.ingest.astronomy import (
    exoplanet_count,
    fetch_recent_exoplanets,
    fetch_recent_transients,
    query_gaia,
)
from engine.drag_uncertainty import drag_uncertainty_band
from engine.ground_track import ground_track, ground_track_bbox, ground_track_center
from agent.rag import get_retriever
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
        """Minimum-Δv avoidance burn for a target miss, numerically verified.

        Plans the burn with the exact closed-form minimum-|Δv| solution on the
        Clohessy-Wiltshire map, then propagates BOTH objects with truth
        dynamics (J2 + drag) and re-screens the post-burn trajectories. The
        relative state is re-derived as a full vector at TCA, and the
        verification derives its own burn-epoch RSW frame internally.

        Returns the CW plan alongside the verified result — including
        ``closest_approach_km``, the re-screened post-burn closest approach,
        which is the quantity that actually protects the spacecraft.
        """
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        # True relative state at TCA (full vector) in the primary's RSW frame
        miss_rsw, rel_vel_rsw = relative_state_rsw(
            state.r_primary, state.v_primary, state.r_secondary, state.v_secondary
        )
        # Mean motion from the primary's orbit
        alt = (self.ctx.primary.perigee_alt_km + self.ctx.primary.apogee_alt_km) / 2
        n = mean_motion_from_alt(alt)

        result = fuel_optimal_with_verification(
            mean_motion=n,
            lead_time_s=lead_time_min * 60.0,
            miss_rsw=miss_rsw,
            rel_vel_rsw=rel_vel_rsw,
            target_miss_km=target_miss_km,
            r_primary_tca=state.r_primary,
            v_primary_tca=state.v_primary,
            r_secondary_tca=state.r_secondary,
            v_secondary_tca=state.v_secondary,
            mass_kg=self.ctx.mass_kg,
            isp_s=self.ctx.isp_s,
            epoch_tca=e.tca,
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
            "closest_approach_km": round(result["closest_approach_km"], 3),
            "satisfies_target": result["satisfies_target"],
            "lead_time_min": lead_time_min,
            "note": result.get(
                "note", "fuel-optimal burn (exact CW plan, numerically verified, re-screened)"
            ),
        }

    def collision_probability_realistic(self, event_id: int, realism_factor: float = 2.0) -> dict:
        """Both the analytic (fixed) and realism-adjusted collision probability.

        Reports both so the operator sees the effect of the covariance-realism
        assumption. The realism factor inflates the analytic covariance toward
        operational realism (Foster/Hall methodology).

        The relative velocity is re-derived as a full vector at TCA, because the
        B-plane orientation — and therefore Pc — depends on its *direction*, not
        just its magnitude. Assuming a purely in-track velocity picks the wrong
        encounter plane and can shift Pc by orders of magnitude on radial- or
        cross-track-dominated conjunctions.
        """
        e = self._event(event_id)
        state = self._inertial_state_at_tca(e)
        miss_rsw, vrel_rsw = relative_state_rsw(
            state.r_primary, state.v_primary, state.r_secondary, state.v_secondary
        )
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

    def get_bplane(self, event_id: int, realism_factor: float = 2.0) -> dict:
        """B-plane plot data for a conjunction — the canonical conjunction diagram.

        Re-derives the full relative state at TCA (the B-plane basis needs the
        complete relative-velocity vector, not just its magnitude), projects the
        miss vector and covariance onto the B-plane, and returns everything needed
        to render the diagram: the miss point (ξ, ζ), the hard-body-radius circle,
        the 1σ/2σ/3σ covariance contours, and how many sigmas out the miss sits.

        The returned ``pc`` is recomputed from this exact projection, so the plot
        and the collision probability can never disagree. ``realism`` carries the
        same geometry under the documented covariance-realism factor (Foster/Hall),
        letting the plot show the inflated uncertainty alongside the analytic one.
        """
        e = self._event(event_id)
        # Re-derive the full inertial state at TCA to get the true relative velocity.
        state = self._inertial_state_at_tca(e)
        miss_rsw, rel_vel_rsw = relative_state_rsw(
            state.r_primary, state.v_primary, state.r_secondary, state.v_secondary
        )
        from engine.viz.bplane import bplane_data

        data = bplane_data(
            miss_rsw, rel_vel_rsw, hbr_km=e.hbr_km, realism_factor=realism_factor
        )
        if data is None:
            return {
                "available": False,
                "event_id": event_id,
                "note": "B-plane undefined (near-zero relative velocity).",
            }
        return {
            "available": True,
            "event_id": event_id,
            "secondary_name": e.secondary_name,
            "secondary_norad": e.secondary_norad,
            "tca": e.tca.isoformat().replace("+00:00", "Z"),
            "miss_bp": {"xi": data["miss_bp"][0], "zeta": data["miss_bp"][1]},
            "miss_norm_km": data["miss_norm_km"],
            "miss_3d_km": e.miss_distance_km,
            "vrel_kms": e.relative_velocity_kms,
            "hbr_km": data["hbr_km"],
            "miss_inside_hbr": data["miss_inside_hbr"],
            "ellipse": data["ellipse"],
            "sigma_levels": data["sigma_levels"],
            "mahalanobis_sigma": data["mahalanobis_sigma"],
            "sigma_contour_containing_miss": data["sigma_contour_containing_miss"],
            "axes_rsw": data["axes_rsw"],
            "pc": data["pc"],
            "realism": data["realism"],
            "note": (
                "Covariance is the documented fixed diagonal RSW assumption "
                "(engine/pc.py); realism.pc inflates it by k for operational "
                "realism (Foster/Hall). See docs/ADVANCED_ASTRODYNAMICS.md."
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

    def query_knowledge_base(self, query: str, k: int = 3) -> dict:
        """Retrieve relevant space-domain knowledge for a question (RAG).

        Searches the analyst's knowledge base (conjunction assessment, CDM/ODM
        standards, collision probability, maneuver planning, atmospheric drag,
        validation results, operator runbook, sustainability) and returns the
        most relevant chunks with citations. Use this to ground answers in
        domain expertise and cite sources.
        """
        retriever = get_retriever()
        return retriever.retrieve_and_format(query, k=k)

    def query_knowledge_chunks(self, query: str, k: int = 3) -> dict:
        """Retrieve knowledge chunks in full — for the Learn tab (not an agent tool).

        Same retrieval as ``query_knowledge_base``, but returns each chunk's complete
        content (plain-language summary + technical body) so the education UI can
        render it directly. Explanations come from the same knowledge base the
        analyst cites — never hardcoded UI text.
        """
        retriever = get_retriever()
        results = retriever.retrieve(query, k=k)
        return {
            "query": query,
            "chunks": [
                {
                    "chunk_id": r.chunk.chunk_id,
                    "title": r.chunk.title,
                    "topic": r.chunk.topic,
                    "plain": r.chunk.plain,
                    "body": r.chunk.body,
                    "score": round(r.score, 3),
                }
                for r in results
            ],
            "count": len(results),
        }

    # -- Phase A: live NASA / Space-Track / Open Notify data tools -----------

    def get_near_earth_objects(self, days: int = 7) -> dict:
        """Near-Earth objects approaching Earth over the next N days (NASA NEO Feed).

        Extends OrbitWarden from artificial-object conjunctions to natural ones —
        planetary defense. Returns upcoming close approaches with hazard flags.
        """
        from datetime import date, timedelta

        end = date.today() + timedelta(days=days)
        neos = fetch_neo_feed(date.today(), end)
        rows = []
        for n in neos:
            approaches = [
                {
                    "date": ca.date,
                    "miss_km": round(ca.miss_distance_km, 1),
                    "miss_lunar": round(ca.miss_distance_lunar, 2),
                    "velocity_kmh": round(ca.relative_velocity_kmh, 1),
                }
                for ca in n.close_approaches
            ]
            rows.append(
                {
                    "name": n.name,
                    "hazardous": n.is_potentially_hazardous,
                    "diameter_km": round(n.estimated_diameter_km, 3),
                    "approaches": approaches,
                }
            )
        hazardous_count = sum(1 for n in neos if n.is_potentially_hazardous)
        return {
            "days": days,
            "count": len(neos),
            "hazardous_count": hazardous_count,
            "objects": rows,
            "source": "NASA NEO Feed",
        }

    def get_earth_imagery(self) -> dict:
        """Latest full-disc Earth imagery from NASA EPIC (DSCOVR satellite)."""
        images = fetch_epic_latest()
        if not images:
            return {"available": False, "note": "EPIC imagery unavailable (API down or rate-limited)"}
        latest = images[0]
        return {
            "available": True,
            "count": len(images),
            "latest": {
                "identifier": latest.identifier,
                "date": latest.date,
                "caption": latest.caption,
                "centroid_lat": round(latest.centroid_lat, 2),
                "centroid_lon": round(latest.centroid_lon, 2),
                "image_url": latest.image_url,
            },
            "source": "NASA EPIC (DSCOVR)",
        }

    def get_astronomy_picture(self) -> dict:
        """NASA Astronomy Picture of the Day (public engagement)."""
        apod = fetch_apod()
        if apod is None:
            return {"available": False, "note": "APOD unavailable"}
        return {
            "available": True,
            "title": apod.title,
            "media_type": apod.media_type,
            "date": apod.date,
            "url": apod.url,
            "explanation": apod.explanation[:600] + ("..." if len(apod.explanation) > 600 else ""),
            "source": "NASA APOD",
        }

    def get_iss_position(self) -> dict:
        """Live ISS position (Open Notify, with TLE-computed fallback)."""
        iss = fetch_iss_position()
        if iss is None:
            return {"available": False, "note": "ISS position unavailable"}
        return {
            "available": True,
            "latitude": round(iss.latitude, 3),
            "longitude": round(iss.longitude, 3),
            "source": iss.source,
            "note": "Live ground-track position of the International Space Station.",
        }

    def get_astronauts(self) -> dict:
        """Humans currently in space (Open Notify)."""
        astros = fetch_astronauts()
        return {
            "number": astros.number,
            "people": [{"name": p.name, "craft": p.craft} for p in astros.people],
            "source": "Open Notify",
        }

    def get_catalog_statistics(self, top_n: int =10) -> dict:
        """Who owns what's in orbit — catalog statistics by country (Space-Track boxscore).

        Returns the top spacefaring nations by active payloads, plus orbital debris
        and decayed-object counts. Powers the 'who's in space' and sustainability views.
        """
        stats = fetch_boxscore()
        if not stats:
            return {"available": False, "note": "boxscore unavailable (auth or rate limit)"}
        # Separate the global 'ALL' row from individual countries.
        global_row = next((s for s in stats if s.country.upper() == "ALL"), None)
        countries = [s for s in stats if s.country.upper() != "ALL"]
        top = sorted(countries, key=lambda s: s.orbital_payloads, reverse=True)[:top_n]
        return {
            "available": True,
            "global": {
                "orbital_payloads": global_row.orbital_payloads if global_row else 0,
                "orbital_debris": global_row.orbital_debris if global_row else 0,
                "orbital_total": global_row.orbital_total if global_row else 0,
                "decayed_total": global_row.decayed_total if global_row else 0,
            } if global_row else {},
            "top_countries": [
                {
                    "country": s.country,
                    "orbital_payloads": s.orbital_payloads,
                    "orbital_debris": s.orbital_debris,
                    "orbital_total": s.orbital_total,
                    "decayed_total": s.decayed_total,
                }
                for s in top
            ],
            "source": "Space-Track boxscore",
        }

    def get_recent_reentries(self, limit: int = 10) -> dict:
        """Recent predicted reentry/decay events (Space-Track decay class).

        Powers the space-sustainability narrative — what's coming back down.
        """
        decays = fetch_recent_decays(limit=limit)
        if not decays:
            return {"available": False, "note": "decay data unavailable"}
        return {
            "available": True,
            "count": len(decays),
            "events": [
                {
                    "norad_id": d.norad_id,
                    "intl_des": d.intl_des,
                    "country": d.country,
                    "decay_epoch": d.decay_epoch,
                    "msg_type": d.msg_type,
                }
                for d in decays
            ],
            "note": "Predicted reentries (not confirmed). Powers deorbit/sustainability tracking.",
            "source": "Space-Track decay",
        }

    def search_literature(self, query: str, rows: int = 5) -> dict:
        """Search NASA ADS for peer-reviewed papers (needs a free ADS_API_KEY).

        Lets the analyst cite real literature on conjunction assessment, drag
        modeling, collision probability, etc. Returns [] if no key is configured.
        """
        papers = search_ads(query, rows=rows)
        if not papers:
            return {
                "available": False,
                "count": 0,
                "note": "Literature search unavailable (set ADS_API_KEY in .env for NASA ADS).",
            }
        return {
            "available": True,
            "count": len(papers),
            "papers": [
                {
                    "title": p.title,
                    "authors": p.authors[:3],
                    "year": p.year,
                    "bibcode": p.bibcode,
                    "url": p.url,
                    "abstract": p.abstract[:300] + ("..." if len(p.abstract) > 300 else ""),
                }
                for p in papers
            ],
            "source": "NASA ADS",
        }

    # -- Phase B: space-weather deepening tools ------------------------------

    def get_space_weather_detailed(self) -> dict:
        """Full multi-signal space-weather picture with a composite storm-risk score.

        Combines the Kp forecast, solar-wind magnetic field (Bt, Bz), solar-wind
        speed, X-ray flare class, and energetic proton flux into one storm-risk
        indicator (0-100) with a qualitative level and the list of active drivers.
        This is the quantitative upgrade to the binary storm flag.
        """
        sw = fetch_solar_wind()
        xr = fetch_xray_flux()
        pr = fetch_proton_flux()
        # Get the Kp forecast max from the existing space-weather source.
        from engine.ingest.spaceweather import fetch_space_weather

        base = fetch_space_weather()
        kp_max = base.max_kp_3day if base else 0.0

        comp = storm_risk_composite(kp_max_3day=kp_max, solar_wind=sw, xray=xr, proton=pr)
        return {
            "composite": {
                "score": comp.score,
                "level": comp.level,
                "drivers": comp.drivers,
            },
            "kp_max_3day": kp_max,
            "solar_wind": {
                "bt_nt": sw.bt_nt,
                "bz_gsm_nt": sw.bz_gsm_nt,
                "speed_kms": sw.speed_kms,
                "f107_sfu": sw.f107_sfu,
            },
            "xray": {"flux_w_m2": xr.flux_w_m2, "flare_class": xr.flare_class},
            "protons": {"flux_pfu": pr.flux_pfu, "sep_active": pr.sep_active},
            "source": "NOAA SWPC (multi-signal)",
        }

    def get_space_weather_alerts(self, days: int = 7) -> dict:
        """All NASA DONKI space-weather alerts over the last N days.

        Returns counts by notification type (GST/CME/FLR/HSS/SEP/RBE/…), whether a
        geomagnetic storm is active, and the predictive 'storm building' signal
        (precursors like CME/HSS present but no active storm yet).
        """
        from datetime import date, timedelta

        notifs = fetch_donki_all(date.today() - timedelta(days=days), date.today())
        analysis = analyze_donki(notifs)
        return {
            "days": days,
            "total": analysis["total"],
            "by_type": analysis["by_type"],
            "active_storm": analysis["active_storm"],
            "storm_precursors": analysis["storm_precursors"],
            "storm_building": analysis["storm_building"],
            "type_meanings": analysis["type_meanings"],
            "recent": [
                {"type": n.message_type, "issue_time": n.issue_time, "summary": n.summary}
                for n in notifs[:5]
            ],
            "source": "NASA DONKI",
        }

    def get_drag_uncertainty(self, event_id: int) -> dict:
        """Quantitative storm-driven drag-uncertainty band for a conjunction.

        Propagates both objects under quiet vs current-storm drag and reports the
        miss-distance band — 'predicted miss X km ± Y km due to drag uncertainty.'
        This is the physical basis for 're-screen within 24 h of TCA.'
        """
        e = self._event(event_id)
        primary_tle = self.ctx.primary
        secondary_tle = self.ctx.catalog_by_id.get(e.secondary_norad)
        if secondary_tle is None:
            return {"available": False, "note": f"secondary {e.secondary_norad} TLE not in catalog"}

        # Current Kp from the space-weather source.
        from engine.ingest.spaceweather import fetch_space_weather

        base = fetch_space_weather()
        kp_current = base.max_kp_3day if base else 4.0

        band = drag_uncertainty_band(
            primary_tle,
            secondary_tle,
            e.tca,
            event_id=event_id,
            primary_type="PAYLOAD",
            secondary_type=e.secondary_type,
            kp_current=kp_current,
        )
        return {
            "available": True,
            "event_id": event_id,
            "quiet_miss_km": band.quiet_miss_km,
            "storm_miss_km": band.storm_miss_km,
            "band_km": band.band_km,
            "ap_quiet": band.ap_quiet,
            "ap_storm": band.ap_storm,
            "density_inflation_ratio": band.inflation_ratio,
            "recommendation": band.recommendation,
            "note": (
                "Band = |miss under storm drag − miss under quiet drag|. Nonzero because "
                "the two objects have different ballistic coefficients."
            ),
            "source": "NRLMSISE-00 + numerical propagation",
        }

    # -- Phase C: Earth observation tools ------------------------------------

    def get_ground_track(self, norad_id: int | None = None, minutes: int = 90) -> dict:
        """The satellite's ground track (sub-satellite lat/lon path) over the next N minutes.

        Answers "where will my satellite be?" — computed from the TLE via SGP4,
        accounting for Earth's rotation. Returns the track points, bounding box,
        and center (for imagery queries).
        """
        if norad_id is None or norad_id == self.ctx.primary.norad_id:
            tle = self.ctx.primary
        else:
            tle = self.ctx.catalog_by_id.get(norad_id)
            if tle is None:
                return {"available": False, "note": f"NORAD {norad_id} not in catalog"}

        try:
            track = ground_track(tle, duration_min=minutes, step_s=60.0)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "note": f"ground-track computation failed: {exc}"}
        if not track:
            return {"available": False, "note": "empty ground track (propagation error)"}

        bbox = ground_track_bbox(track)
        center = ground_track_center(track)
        return {
            "available": True,
            "satellite": tle.name,
            "norad_id": tle.norad_id,
            "minutes": minutes,
            "num_points": len(track),
            "current": {"latitude": track[0].latitude, "longitude": track[0].longitude,
                        "altitude_km": track[0].altitude_km},
            "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
            "center": {"latitude": center[0], "longitude": center[1]},
            "track": [{"lat": p.latitude, "lon": p.longitude, "time": p.time} for p in track[::5]],
            "source": "SGP4 ground-track",
        }

    def get_imagery_under_satellite(
        self, norad_id: int | None = None, collection: str = "sentinel-2", max_cloud: float = 30.0
    ) -> dict:
        """Satellite imagery under the satellite's current ground-track position.

        Computes the sub-satellite point, then queries earth-search STAC for the
        latest cloud-filtered scene (Sentinel-2 optical by default; Sentinel-1 SAR
        for all-weather). Answers "what is my satellite looking at right now?"
        """
        if norad_id is None or norad_id == self.ctx.primary.norad_id:
            tle = self.ctx.primary
        else:
            tle = self.ctx.catalog_by_id.get(norad_id)
            if tle is None:
                return {"available": False, "note": f"NORAD {norad_id} not in catalog"}

        try:
            track = ground_track(tle, duration_min=5, step_s=60.0)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "note": f"ground-track failed: {exc}"}
        if not track:
            return {"available": False, "note": "empty ground track"}

        lat, lon = track[0].latitude, track[0].longitude
        bbox = (lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5)
        items = search_imagery(bbox, collection=collection, max_cloud_cover=max_cloud, limit=3)
        if not items:
            return {
                "available": False,
                "note": f"No {collection} scenes under the satellite (try collection='sentinel-1' for all-weather SAR).",
                "position": {"latitude": lat, "longitude": lon},
            }
        return {
            "available": True,
            "satellite": tle.name,
            "position": {"latitude": round(lat, 3), "longitude": round(lon, 3)},
            "collection": collection,
            "scenes": [
                {
                    "id": it.item_id,
                    "datetime": it.datetime,
                    "cloud_cover": round(it.cloud_cover, 1),
                    "platform": it.platform,
                    "thumbnail_url": it.thumbnail_url,
                }
                for it in items
            ],
            "source": "AWS earth-search STAC",
        }

    def get_disaster_data(
        self, west: float, south: float, east: float, north: float, days: int = 30
    ) -> dict:
        """Copernicus CLMS burnt-area observations in a region (disaster monitoring).

        Answers "any active fires / burnt areas in this region?" Queries the
        Copernicus Data Space STAC (open search; data download needs a free token).
        """
        from datetime import date, timedelta

        bbox = (west, south, east, north)
        end = date.today()
        start = end - timedelta(days=days)
        dt_range = f"{start.isoformat()}/{end.isoformat()}"
        items = search_burnt_area(bbox, datetime_range=dt_range, limit=10)
        return {
            "available": len(items) > 0,
            "bbox": {"west": west, "south": south, "east": east, "north": north},
            "days": days,
            "count": len(items),
            "burnt_areas": [
                {"id": it.item_id, "datetime": it.datetime, "bbox": it.bbox} for it in items
            ],
            "note": "CLMS burnt-area metadata (STAC search is open; raster download needs a Copernicus token).",
            "source": "Copernicus CLMS (Data Space STAC)",
        }

    # -- Phase D: precision ephemerides tools --------------------------------

    def get_planet_position(self, body: str, days: int = 1) -> dict:
        """Precision position/velocity of a solar-system body from JPL Horizons.

        Answers "where is Mars right now?" — high-precision ephemeris (ICRF/J2000,
        geocentric) for planets, the Moon, and the Sun. Enables deep-space awareness
        and feeds the SRP model with the real Sun direction.

        Args:
            body: a body name (sun, mercury, venus, earth, moon, mars, jupiter,
                saturn, uranus, neptune, pluto) or a raw Horizons COMMAND code.
            days: ephemeris window (days from today).
        """
        from datetime import date, timedelta

        start = date.today()
        stop = start + timedelta(days=max(days, 1))
        states = fetch_body_state(body, start.isoformat(), stop.isoformat(), "1 d")
        if not states:
            return {
                "available": False,
                "note": f"Could not fetch ephemeris for '{body}' (unknown body or Horizons unavailable).",
            }
        s = states[0]
        r = s.r_eci
        v = s.v_eci
        distance_km = (r[0] ** 2 + r[1] ** 2 + r[2] ** 2) ** 0.5
        return {
            "available": True,
            "body": body,
            "time": s.time,
            "position_eci_km": {"x": round(r[0], 3), "y": round(r[1], 3), "z": round(r[2], 3)},
            "velocity_eci_kms": {"vx": round(v[0], 6), "vy": round(v[1], 6), "vz": round(v[2], 6)},
            "distance_from_earth_km": round(distance_km, 1),
            "distance_from_earth_au": round(distance_km / 1.495978707e8, 4),
            "frame": "ICRF/J2000, geocentric",
            "source": "JPL Horizons",
        }

    # -- Phase E: astronomy & discovery tools --------------------------------

    def get_recent_transients(self, limit: int = 10) -> dict:
        """Recent astronomical transients from the ZTF survey (via the ALeRCE broker).

        Answers "what's new in the sky tonight?" — supernovae, variable stars, AGN,
        and unclassified transients, most-recent-first. The discovery angle of the
        challenge.
        """
        transients = fetch_recent_transients(limit=limit)
        if not transients:
            return {
                "available": False,
                "count": 0,
                "note": "ALeRCE broker unavailable or slow (it can take ~30-60 s). Try again shortly.",
            }
        classified = sum(1 for t in transients if t.classification != "unclassified")
        return {
            "available": True,
            "count": len(transients),
            "classified": classified,
            "transients": [
                {
                    "oid": t.oid,
                    "ra": round(t.ra, 4),
                    "dec": round(t.dec, 4),
                    "classification": t.classification,
                    "last_observed": t.last_observed[:10],
                    "n_detections": t.n_detections,
                }
                for t in transients
            ],
            "source": "ZTF via ALeRCE broker",
        }

    def get_exoplanet_stats(self, since_year: int = 2020, limit: int = 10) -> dict:
        """Confirmed-exoplanet statistics from the NASA Exoplanet Archive.

        Answers "how many exoplanets have we found?" — total confirmed since a given
        year, plus recent discoveries with their detection method. An engagement hook
        and the astronomy-research angle.
        """
        count = exoplanet_count(since_year=since_year)
        recent = fetch_recent_exoplanets(since_year=since_year, limit=limit)
        if count == 0 and not recent:
            return {"available": False, "note": "NASA Exoplanet Archive unavailable."}
        # Tally discovery methods among the recent sample.
        methods: dict[str, int] = {}
        for e in recent:
            methods[e.discovery_method] = methods.get(e.discovery_method, 0) + 1
        return {
            "available": True,
            "confirmed_since": since_year,
            "count": count,
            "recent": [
                {
                    "name": e.name,
                    "discovery_method": e.discovery_method,
                    "year": e.discovery_year,
                    "host_star": e.host_star,
                }
                for e in recent
            ],
            "methods_in_sample": methods,
            "source": "NASA Exoplanet Archive",
        }

    def get_stars_near(self, ra: float, dec: float, radius_arcmin: float = 5.0, limit: int = 10) -> dict:
        """Stars near a sky position from the Gaia DR3 catalog (cone search).

        Answers "what stars are in this field?" — useful for astronomy-aware
        operations and engagement. Returns stars sorted brightest-first.
        """
        stars = query_gaia(ra=ra, dec=dec, radius_arcmin=radius_arcmin, limit=limit)
        if not stars:
            return {
                "available": False,
                "count": 0,
                "note": "Gaia query returned no stars (field may be empty, or Gaia is rate-limited).",
            }
        return {
            "available": True,
            "center": {"ra": ra, "dec": dec},
            "radius_arcmin": radius_arcmin,
            "count": len(stars),
            "stars": [
                {
                    "source_id": s.source_id,
                    "ra": round(s.ra, 5),
                    "dec": round(s.dec, 5),
                    "g_mag": round(s.g_mag, 2),
                }
                for s in stars
            ],
            "source": "ESA Gaia DR3",
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
        "get_bplane",
        "generate_cdm_message",
        "query_knowledge_base",
        "get_near_earth_objects",
        "get_earth_imagery",
        "get_astronomy_picture",
        "get_iss_position",
        "get_astronauts",
        "get_catalog_statistics",
        "get_recent_reentries",
        "search_literature",
        "get_space_weather_detailed",
        "get_space_weather_alerts",
        "get_drag_uncertainty",
        "get_ground_track",
        "get_imagery_under_satellite",
        "get_disaster_data",
        "get_planet_position",
        "get_recent_transients",
        "get_exoplanet_stats",
        "get_stars_near",
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
            "name": "get_bplane",
            "description": "Get the B-plane plot data for a conjunction — the canonical conjunction-assessment diagram. Returns the miss point (ξ, ζ), the in-plane miss distance, the hard-body-radius circle, the 1σ/2σ/3σ covariance contours, how many sigmas out the miss sits (mahalanobis_sigma), the Pc recomputed from that exact projection, and the same geometry under the covariance-realism factor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "realism_factor": {
                        "type": "number",
                        "description": "Covariance-realism factor k (Σ_real = k·Σ_analytic); default 2.0.",
                    },
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
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Search the analyst's space-domain knowledge base (conjunction assessment, CDM/ODM standards, collision probability, maneuver planning, drag, validation results, operator runbook, sustainability) and return the most relevant chunks with citations. Use this to ground your answers in domain expertise and cite sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "the question or topic to search for"},
                    "k": {"type": "integer", "description": "number of chunks to retrieve (default 3)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_near_earth_objects",
            "description": "Get near-Earth objects (asteroids/comets) approaching Earth over the next N days from the NASA NEO Feed — planetary defense. Returns close approaches with hazard flags, miss distances, and velocities.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "look-ahead window in days (default 7)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_earth_imagery",
            "description": "Get the latest full-disc Earth imagery from NASA EPIC (DSCOVR satellite) — 'what does Earth look like from space right now?'",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_astronomy_picture",
            "description": "Get NASA's Astronomy Picture of the Day (APOD) — a daily astronomy engagement hook.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_iss_position",
            "description": "Get the live position (latitude/longitude) of the International Space Station.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_astronauts",
            "description": "Get the humans currently in space (count and names/craft).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_catalog_statistics",
            "description": "Get catalog statistics by country (Space-Track boxscore) — who owns what's in orbit: active payloads, debris, and decayed-object counts per nation.",
            "parameters": {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "description": "number of top countries to return (default 10)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_reentries",
            "description": "Get recent predicted reentry/decay events (Space-Track decay class) — what's coming back down (space sustainability).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "number of events (default 10)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_literature",
            "description": "Search NASA ADS for peer-reviewed papers on a topic (e.g. 'collision probability', 'atmospheric drag'). Cite real literature. Requires ADS_API_KEY in .env.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "search query"},
                    "rows": {"type": "integer", "description": "number of papers (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_space_weather_detailed",
            "description": "Get the full multi-signal space-weather picture: Kp forecast, solar-wind B-field (Bt/Bz) and speed, X-ray flare class, energetic proton flux, and a composite storm-risk score (0-100) with active drivers. The quantitative upgrade to the binary storm flag.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_space_weather_alerts",
            "description": "Get all NASA DONKI space-weather alerts over the last N days: counts by type (GST/CME/FLR/HSS/SEP/RBE), whether a geomagnetic storm is active, and the predictive 'storm building' signal (precursors present, no active storm yet).",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "look-back window in days (default 7)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_drag_uncertainty",
            "description": "Get the quantitative storm-driven drag-uncertainty band for a conjunction: 'predicted miss X km ± Y km due to drag uncertainty.' Propagates both objects under quiet vs current-storm drag. The physical basis for 're-screen within 24 h of TCA.'",
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
            "name": "get_ground_track",
            "description": "Get the satellite's ground track (sub-satellite lat/lon path) over the next N minutes — 'where will my satellite be?' Computed from the TLE via SGP4, accounting for Earth's rotation. Returns track points, bounding box, and center.",
            "parameters": {
                "type": "object",
                "properties": {
                    "norad_id": {"type": "integer", "description": "satellite NORAD id (default: primary)"},
                    "minutes": {"type": "integer", "description": "track duration in minutes (default 90)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_imagery_under_satellite",
            "description": "Get satellite imagery under the satellite's current ground-track position — 'what is my satellite looking at right now?' Queries earth-search STAC for the latest cloud-filtered scene. collection: 'sentinel-2' (optical, default), 'sentinel-1' (SAR, all-weather), or 'landsat'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "norad_id": {"type": "integer", "description": "satellite NORAD id (default: primary)"},
                    "collection": {"type": "string", "description": "sentinel-2 / sentinel-1 / landsat"},
                    "max_cloud": {"type": "number", "description": "max cloud cover % (default 30)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_disaster_data",
            "description": "Get Copernicus CLMS burnt-area observations in a region (disaster monitoring) — 'any active fires / burnt areas here?' Provide a bounding box (west, south, east, north in degrees).",
            "parameters": {
                "type": "object",
                "properties": {
                    "west": {"type": "number"},
                    "south": {"type": "number"},
                    "east": {"type": "number"},
                    "north": {"type": "number"},
                    "days": {"type": "integer", "description": "look-back window in days (default 30)"},
                },
                "required": ["west", "south", "east", "north"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_planet_position",
            "description": "Get the precision position/velocity of a solar-system body from JPL Horizons — 'where is Mars right now?' Returns geocentric ICRF/J2000 state vector and distance (km and AU). Bodies: sun, mercury, venus, earth, moon, mars, jupiter, saturn, uranus, neptune, pluto (or a raw Horizons code).",
            "parameters": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "body name or Horizons code"},
                    "days": {"type": "integer", "description": "ephemeris window in days (default 1)"},
                },
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_transients",
            "description": "Get recent astronomical transients from the ZTF survey (via the ALeRCE broker) — 'what's new in the sky tonight?' Returns supernovae, variable stars, AGN, and unclassified transients, most-recent-first, with positions and classifications.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "number of transients (default 10)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exoplanet_stats",
            "description": "Get confirmed-exoplanet statistics from the NASA Exoplanet Archive — 'how many exoplanets have we found?' Returns the count since a given year plus recent discoveries with their detection method.",
            "parameters": {
                "type": "object",
                "properties": {
                    "since_year": {"type": "integer", "description": "count discoveries since this year (default 2020)"},
                    "limit": {"type": "integer", "description": "number of recent exoplanets to list (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stars_near",
            "description": "Get stars near a sky position from the Gaia DR3 catalog (cone search) — 'what stars are in this field?' Returns stars sorted brightest-first (by G magnitude).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ra": {"type": "number", "description": "right ascension (deg)"},
                    "dec": {"type": "number", "description": "declination (deg)"},
                    "radius_arcmin": {"type": "number", "description": "search radius (arcmin, default 5)"},
                    "limit": {"type": "integer", "description": "max stars (default 10)"},
                },
                "required": ["ra", "dec"],
            },
        },
    },
]
