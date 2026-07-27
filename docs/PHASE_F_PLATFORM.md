# Phase F — A Real, Operable Platform (Implemented)

> Phase F of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): turn the
> backend's capabilities into a **real, operable platform** — fully wired,
> deployed, monitored, and scheduled. Not a demo: a system that runs unattended,
> degrades gracefully, and reports its own health.
>
> **Implemented and deployed (2026-07-27).** Live at a public URL.

---

## What "real" means here

The earlier phases built real capabilities (validated physics, live data
integrations, an AI judgment layer). Phase F makes them a **platform someone can
operate**:

| Before Phase F | After Phase F |
|----------------|---------------|
| 9 of 29 tools exposed via API | **All 29 tools** exposed as REST endpoints (31 routes) |
| Frontend showed only conjunctions | **6-panel space-situation platform** (Mission Control, Space Weather, Earth Observation, Discovery, Solar System, System Health) |
| Manual one-off batch | **Scheduled service** that survives failures |
| No visibility into system state | **Operational health monitoring** (per-source freshness, overall status) |
| Runs locally | **Deployed** at a public URL, serving live data |
| `print` debugging | **Structured logging** (per-request, per-pipeline-stage) |

---

## What was built

### 1. Full API surface (`api/main.py`)
All 29 agent tools exposed as REST endpoints, organized by capability:
- **Core screening**: `/api/events`, `/api/events/{id}`, `/api/events/{id}/maneuvers`
- **Advanced astrodynamics**: `/api/events/{id}/fuel-optimal`, `/api/events/{id}/collision-probability`, `/api/events/{id}/cdm`, `/api/events/{id}/drag-uncertainty`
- **Space weather**: `/api/space-weather`, `/api/space-weather/detailed`, `/api/space-weather/alerts`
- **Earth observation**: `/api/ground-track`, `/api/imagery`, `/api/disaster`
- **Precision ephemerides**: `/api/planet/{body}`
- **Astronomy & discovery**: `/api/transients`, `/api/exoplanets`, `/api/stars`
- **NASA / catalog / engagement**: `/api/neo`, `/api/earth-image`, `/api/apod`, `/api/iss`, `/api/astronauts`, `/api/catalog-stats`, `/api/reentries`, `/api/literature`
- **Knowledge base**: `/api/knowledge`
- **Analyst**: `/api/chat`, `/api/chat/events` (SSE)

### 2. Operational health monitoring (`api/health.py`)
`/api/health/full` reports the real operational state:
- **Database**: present, populated, last-run freshness.
- **Every external data source**: ok / stale / unknown, based on cache freshness.
- **Overall status**: ok / degraded.

This is what makes the platform operable — an operator sees at a glance what's
healthy and what's degraded, rather than discovering failures silently.

### 3. Space-situation dashboard (`web/src`)
A tabbed platform surfacing the entire backend:
- **Mission Control** — conjunction board, event detail (RSW geometry, Pc, risk), avoidance options, analyst chat.
- **Space Weather** — composite storm-risk score + all signals (Kp, Bt, Bz, solar wind, X-ray, protons).
- **Earth Observation** — ground-track map (SVG, antimeridian-aware), Sentinel-2 imagery under the satellite, NEO watch.
- **Discovery** — ZTF transients, exoplanet counter, Gaia star field.
- **Solar System** — planet positions (Horizons), live ISS, astronauts in space.
- **System Health** — operational status of every data source.

Each panel fetches its own data and degrades gracefully ("unavailable" rather
than broken).

### 4. Scheduled batch service (`batch/nightly.py`)
- `--schedule` mode runs the screening as a **recurring service** (default every 24 h).
- **Survives failures** — a failed run logs an error and retries next interval; never crashes unattended.
- **Structured logging** — one line per pipeline stage.

### 5. Deployment
- API + frontend exposed publicly via the codespace.
- **Live URL** serving real data (verified: Mars at 2.02 AU via the public API).
- `docs/OPERATIONS.md` — the operations runbook (how to run, monitor, and deploy).

---

## Verified live (2026-07-27)

```
Public API:     https://sturdy-space-journey-4g5qw4rvpx27wwq-8000.app.github.dev  (HTTP 200)
Public frontend: https://sturdy-space-journey-4g5qw4rvpx27wwq-5173.app.github.dev  (HTTP 200)

/api/health/full:          overall=degraded, db=ok, 12 ok / 4 stale / 1 unknown
/api/space-weather/detailed: composite 28.6/100 (unsettled), Kp=5.33, Bz=-2.0 nT
/api/ground-track:         ISS, 91 points, now at (-45.4, 142.8)
/api/exoplanets:           2,229 confirmed since 2020
/api/planet/mars:          2.0176 AU
```

(The "degraded" status is honest — some sources were stale at check time. The
platform reports this rather than hiding it.)

---

## The point

This is no longer a collection of scripts to be run by hand and shown once. It is
a **service**: it has a full API, a frontend that surfaces everything, a scheduled
batch that keeps the data fresh, health monitoring that reports its own state,
structured logging, graceful degradation, and a public deployment. Someone else
could operate it from the runbook without me.

That is the difference between a demo and a real project.

---

*Implemented and deployed 2026-07-27. See `docs/OPERATIONS.md` for how to run it.*
