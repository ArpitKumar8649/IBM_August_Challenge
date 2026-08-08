# OrbitWarden — Operations Runbook

> How to run OrbitWarden as a real, operable platform — not a one-off script.
> Three services: the **screening batch** (scheduled), the **API**, and the
> **frontend**. Each is independently runnable and monitored.

---

## Architecture (runtime)

```
┌─────────────────────┐ scheduled    ┌──────────────────┐
│  batch.nightly      │ ─────────────▶ │  SQLite store    │
│  (every 24 h)       │   screen +     │  data/orbitwarden│
│  CelesTrak/Space-   │   persist      │  .db             │
│  Track → screen     │                └────────┬─────────┘
└─────────────────────┘                         │ reads
                                                ▼
┌─────────────────────┐   /api/*       ┌──────────────────┐
│  frontend (Vite)    │ ◀───────────── │  FastAPI (uvicorn│
│  :5173              │   proxies      │  :8000)          │
└─────────────────────┘                └──────────────────┘
```

The batch writes the latest screening run to SQLite; the API reads it and serves
all 31 tools as REST endpoints; the frontend proxies to the API.

---

## Prerequisites

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SPACETRACK_*, NASA_API_KEY, WATSONX_*
cd web && npm install && cd ..
```

---

## Running the services

### 1. Screening batch (scheduled service)

```bash
# One-pass (screen once, exit):
python -m batch.nightly

# Scheduled service (recurring, survives failures):
python -m batch.nightly --schedule --interval-hours 24

# Screen specific satellites:
python -m batch.nightly --norad 25544 63210 --schedule
```

The scheduled service logs each run and **keeps running through failures** — if a
data source is down, it logs an error and retries at the next interval. It never
crashes unattended.

### 2. API

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The API loads the latest screening run from SQLite on startup. It serves all 29
tools as REST endpoints (see `api/main.py` for the full list).

### 3. Frontend

```bash
cd web && npm run dev    # dev server on :5173, proxies /api → :8000
# or for production:
cd web && npm run build  # builds to web/dist (serve with any static server)
```

---

## Monitoring

### Health endpoint

```bash
curl http://localhost:8000/api/health/full
```

Returns the operational state: database status + every external data source's
freshness (ok / stale / unknown) + an overall status (ok / degraded). The
frontend's **System Health** tab shows this visually.

### Structured logs

Both the API and batch emit structured logs:
- API: one line per request — `method path -> status (latency ms)`
- Batch: one line per pipeline stage — catalog fetch, screening, enrichment, persistence

---

## Graceful degradation

Every external data source degrades gracefully:
- If a source is down, the API returns `available: false` for that capability.
- The frontend shows "unavailable" for that panel rather than breaking.
- The screening batch falls back from CelesTrak to Space-Track if CelesTrak
  rate-limits.
- The ISS position falls back to TLE-computed if Open Notify is down.

The platform is designed to be **partially degraded and still useful** — a single
data-source outage never takes down the whole system.

---

## Deployment (IBM Cloud Code Engine)

For a permanent public deployment:

1. **API**: containerize (`uvicorn api.main:app`) → Code Engine service, public.
2. **Frontend**: `npm run build` → serve `web/dist` as a static Code Engine service
   (or any static host), with `/api` routed to the API service.
3. **Batch**: Code Engine **job** on a cron schedule (`0 0 * * *` for nightly).

The codespace can also expose the running services publicly via `gh codespace
ports visibility <port>:public` for a live URL during development.

**3D globe deployment notes (5.1):**

- The build **fails if the Cesium runtime is missing** — `npm run build` runs a
  post-build gate (`web/scripts/check-cesium-assets.mjs`) asserting `dist/cesium/`
  contains `Cesium.js`, `Workers/`, `Widgets/`, `Assets/`, `ThirdParty/` (the
  `vite-plugin-cesium` copy). Ship the whole `web/dist` tree, not just the JS
  bundles, or the globe breaks while the rest of the app still works.
- Serve the globe over **HTTPS**: Cesium's web workers are strict about mixed
  content, so the public URL must be `https://` (Code Engine serves TLS by
  default — the failure mode to watch for is a plain-http custom domain or a
  dev-tunnel port).

---

## Operational checklist

- [ ] `.env` populated (Space-Track, NASA, watsonx credentials)
- [ ] Batch scheduled (`--schedule`) and producing runs (check `data/orbitwarden.db`)
- [ ] API serving (`/api/health` returns 200)
- [ ] Frontend reachable (`:5173`)
- [ ] `/api/health/full` shows database `ok` and most sources `ok`
- [ ] Logs reviewed for errors

---

*This runbook treats OrbitWarden as a service to be operated, not a demo to be
shown. The goal is a system that runs unattended, degrades gracefully, and reports
its own health.*
