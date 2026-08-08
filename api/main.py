"""FastAPI application — exposes the full OrbitWarden platform.

The API surfaces all 29 agent tools as REST endpoints, organized by capability:

  Core screening (Phase 1-2):
    GET  /api/health · /api/satellite · /api/satellites/{id} · /api/events
    GET  /api/events/{id} · /api/events/{id}/maneuvers
  Advanced astrodynamics:
    GET  /api/events/{id}/fuel-optimal · /api/events/{id}/collision-probability
    GET  /api/events/{id}/cdm · /api/events/{id}/drag-uncertainty
    GET  /api/events/{id}/bplane
  Space weather (Phase B):
    GET  /api/space-weather · /api/space-weather/detailed · /api/space-weather/alerts
  Public engagement (Phase 5.3):
    GET  /api/passes
  Earth observation (Phase C):
    GET  /api/ground-track · /api/imagery · /api/disaster
  Precision ephemerides (Phase D):
    GET  /api/planet/{body}
  Astronomy & discovery (Phase E):
    GET  /api/transients · /api/exoplanets · /api/stars
  NASA / catalog / engagement (Phase A):
    GET  /api/neo · /api/earth-image · /api/apod · /api/iss · /api/astronauts
    GET  /api/catalog-stats · /api/reentries · /api/literature
  Knowledge base (RAG):
    GET  /api/knowledge
  Analyst (Granite agent):
    POST /api/chat · GET /api/chat/events (SSE stream of the agent's reasoning)

`create_app(ctx)` injects a ToolContext (used by tests); `create_app_from_db()`
loads the latest screening run from the store (production).
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.session import AgentLoop, OrbitWardenAgent, WatsonxClient
from agent.tools import AgentTools, ToolContext
from agent.validator import Validator
from api.health import system_health

# Structured logging — one line per request, with method/path/status/latency.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("orbitwarden.api")


class ChatRequest(BaseModel):
    message: str
    max_iterations: int = 8


def create_app(ctx: ToolContext, client: WatsonxClient | None = None) -> FastAPI:
    app = FastAPI(title="OrbitWarden API", version="1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    tools = AgentTools(ctx)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        latency_ms = (time.time() - start) * 1000
        logger.info(
            "%s %s -> %d (%.0f ms)",
            request.method, request.url.path, response.status_code, latency_ms,
        )
        return response

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "primary": ctx.primary.name,
            "primary_norad": ctx.primary.norad_id,
            "events": len(ctx.events),
        }

    @app.get("/api/health/full")
    def health_full():
        """Detailed operational health: database + every external data source."""
        return system_health()


    @app.get("/api/satellite")
    def primary_satellite():
        return tools.get_satellite_info()

    @app.get("/api/satellites/{norad_id}")
    def satellite(norad_id: int):
        result = tools.get_satellite_info(norad_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    @app.get("/api/events")
    def events(limit: int = 20):
        return tools.list_conjunctions(limit)

    @app.get("/api/events/{event_id}")
    def event_detail(event_id: int):
        try:
            return tools.get_event_details(event_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/events/{event_id}/maneuvers")
    def maneuvers(
        event_id: int,
        fuel_margin_g: float | None = None,
        min_post_burn_miss_km: float = 0.0,
    ):
        constraints: dict = {}
        if fuel_margin_g is not None:
            constraints["fuel_margin_g"] = fuel_margin_g
        if min_post_burn_miss_km:
            constraints["min_post_burn_miss_km"] = min_post_burn_miss_km
        try:
            return tools.search_maneuvers(event_id, constraints or None)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/space-weather")
    def space_weather():
        return tools.get_space_weather()

    # -- Phase B: space-weather deepening ------------------------------------

    @app.get("/api/space-weather/detailed")
    def space_weather_detailed():
        return tools.get_space_weather_detailed()

    @app.get("/api/space-weather/alerts")
    def space_weather_alerts(days: int = 7):
        return tools.get_space_weather_alerts(days)

    @app.get("/api/events/{event_id}/drag-uncertainty")
    def drag_uncertainty(event_id: int):
        try:
            return tools.get_drag_uncertainty(event_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # -- Phase C: Earth observation ------------------------------------------

    @app.get("/api/ground-track")
    def ground_track(norad_id: int | None = None, minutes: int = 90):
        return tools.get_ground_track(norad_id, minutes)

    @app.get("/api/imagery")
    def imagery(norad_id: int | None = None, collection: str = "sentinel-2", max_cloud: float = 30.0):
        return tools.get_imagery_under_satellite(norad_id, collection, max_cloud)

    @app.get("/api/disaster")
    def disaster(west: float, south: float, east: float, north: float, days: int = 30):
        return tools.get_disaster_data(west, south, east, north, days)

    # -- Phase D: precision ephemerides --------------------------------------

    @app.get("/api/planet/{body}")
    def planet_position(body: str, days: int = 1):
        return tools.get_planet_position(body, days)

    # -- Phase E: astronomy & discovery --------------------------------------

    @app.get("/api/transients")
    def transients(limit: int = 10):
        return tools.get_recent_transients(limit)

    @app.get("/api/exoplanets")
    def exoplanets(since_year: int = 2020, limit: int = 10):
        return tools.get_exoplanet_stats(since_year, limit)

    @app.get("/api/stars")
    def stars(ra: float, dec: float, radius_arcmin: float = 5.0, limit: int = 10):
        return tools.get_stars_near(ra, dec, radius_arcmin, limit)

    # -- Phase A: NASA / catalog / engagement --------------------------------

    @app.get("/api/neo")
    def near_earth_objects(days: int = 7):
        return tools.get_near_earth_objects(days)

    @app.get("/api/earth-image")
    def earth_image():
        return tools.get_earth_imagery()

    @app.get("/api/apod")
    def apod():
        return tools.get_astronomy_picture()

    @app.get("/api/iss")
    def iss_position():
        return tools.get_iss_position()

    @app.get("/api/astronauts")
    def astronauts():
        return tools.get_astronauts()

    @app.get("/api/catalog-stats")
    def catalog_stats(top_n: int = 10):
        return tools.get_catalog_statistics(top_n)

    @app.get("/api/reentries")
    def reentries(limit: int = 10):
        return tools.get_recent_reentries(limit)

    @app.get("/api/literature")
    def literature(query: str, rows: int = 5):
        return tools.search_literature(query, rows)

    # -- knowledge base (RAG) ------------------------------------------------

    @app.get("/api/knowledge")
    def knowledge(query: str, k: int = 3):
        return tools.query_knowledge_base(query, k)

    @app.get("/api/knowledge/learn")
    def knowledge_learn(query: str, k: int = 3):
        """Full chunks (plain + technical) for the Learn tab — same KB the analyst cites."""
        return tools.query_knowledge_chunks(query, k)

    # -- advanced astrodynamics ----------------------------------------------

    @app.get("/api/events/{event_id}/fuel-optimal")
    def fuel_optimal(event_id: int, target_miss_km: float = 10.0, lead_time_min: float = 60.0):
        try:
            return tools.fuel_optimal_maneuver(event_id, target_miss_km, lead_time_min)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/events/{event_id}/collision-probability")
    def collision_probability(event_id: int, realism_factor: float = 2.0):
        try:
            return tools.collision_probability_realistic(event_id, realism_factor)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/events/{event_id}/bplane")
    def bplane(event_id: int, realism_factor: float = 2.0):
        try:
            return tools.get_bplane(event_id, realism_factor)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/events/{event_id}/czml")
    def event_czml(
        event_id: int,
        maneuver_kind: str | None = None,
        window_min: float = 45.0,
    ):
        """CZML document for the 3D conjunction globe (5.1) — the full scene.

        Both orbits over ±window_min around TCA, the TCA moment (points, miss
        line, relative-velocity arrow), the covariance ellipsoid, and optionally
        the pre/post-burn maneuver track (maneuver_kind = cheapest-safe |
        nominal | conservative). Consumed by web/src/viz/Globe3D.tsx.
        """
        try:
            return tools.get_conjunction_czml(event_id, maneuver_kind, window_min)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # -- Phase 5.3: what's passing over me? ----------------------------------

    @app.get("/api/passes")
    def visible_passes(
        lat: float,
        lon: float,
        date: str | None = None,
        limit: int = 12,
        min_elevation: float = 10.0,
    ):
        """Tonight's naked-eye satellite passes for a location (5.3).

        The public-facing "what's passing over me?" — enter a location, see which
        famous satellites (ISS, Tiangong, Hubble…) pass overhead tonight, with
        times, compass directions, brightness, and plain-language instructions.
        Always uses fresh CelesTrak elements (no stale-TLE fallback); answers
        available:false with a note when the catalog is unreachable.
        """
        try:
            return tools.get_visible_passes(lat, lon, date, limit, min_elevation)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/events/{event_id}/cdm")
    def cdm_message(event_id: int):
        try:
            return tools.generate_cdm_message(event_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        agent = OrbitWardenAgent(ctx, client)
        resp = agent.chat(req.message, max_iterations=req.max_iterations)
        return {
            "content": resp.content,
            "tool_calls_made": resp.tool_calls_made,
            "audit_passed": resp.audit_passed,
        }

    @app.get("/api/chat/events")
    def chat_stream(message: str):
        validator = Validator()
        backend = client or WatsonxClient()
        loop = AgentLoop(tools, validator, backend.complete)

        def gen():
            for event in loop.run_stream(message):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def create_app_from_db(db_path: str = "data/orbitwarden.db") -> FastAPI:
    """Build the app from the latest screening run persisted by the nightly batch."""
    from engine.ingest.spaceweather import fetch_space_weather
    from engine.storage import ScreeningStore

    store = ScreeningStore(db_path)
    try:
        # Find the most recent run.
        row = store.conn.execute(
            "SELECT id, primary_norad FROM screening_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("no screening runs found — run `python -m batch.nightly` first")
        run_id, primary_norad = row["id"], row["primary_norad"]
        context = store.load_context(run_id)
        if context is None:
            raise RuntimeError(f"run #{run_id} has no persisted context")
    finally:
        store.close()

    catalog = context["catalog"]
    primary = catalog[primary_norad]
    try:
        space_weather = fetch_space_weather()
    except Exception:  # noqa: BLE001 — degrade gracefully
        space_weather = None

    ctx = ToolContext(
        primary=primary,
        catalog_by_id=catalog,
        events=context["events"],
        object_info=context["object_info"],
        space_weather=space_weather,
    )
    return create_app(ctx)


# Lazy module-level app (PEP 562) so importing `create_app` has no side effects,
# while `uvicorn api.main:app` still resolves the production app on first access.
def __getattr__(name: str):
    if name == "app":
        return create_app_from_db()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
