"""FastAPI application — exposes the screening engine and the Granite agent.

Endpoints:
  GET  /api/health
  GET  /api/satellite                    primary satellite info
  GET  /api/satellites/{norad_id}        catalog object info
  GET  /api/events?limit=N               ranked conjunctions
  GET  /api/events/{event_id}            event detail (RSW geometry, Pc, risk)
  GET  /api/events/{event_id}/maneuvers  avoidance-maneuver options
  GET  /api/space-weather                geomagnetic conditions
  POST /api/chat                         agent conversation (validated)
  GET  /api/chat/events?message=...      SSE stream of the agent's reasoning

`create_app(ctx)` injects a ToolContext (used by tests); `create_app_from_db()`
loads the latest screening run from the store (production / demo).
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.session import AgentLoop, OrbitWardenAgent, WatsonxClient
from agent.tools import AgentTools, ToolContext
from agent.validator import Validator


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

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "primary": ctx.primary.name,
            "primary_norad": ctx.primary.norad_id,
            "events": len(ctx.events),
        }

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
