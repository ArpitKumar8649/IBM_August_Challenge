# Phase A — Real NASA / ESA / NOAA Data Integration (Implemented)

> Phase A of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): wire OrbitWarden
> into the live space-data ecosystem with the highest-impact, lowest-effort sources.
> **All endpoints verified live on 2026-07-27.**50 new tests; 233 total passing.
> The agent contract grows from 11 → **19 tools**.

---

## What was built

### Shared infrastructure

| Module | Role |
|--------|------|
| `engine/ingest/cache.py` | **TTL disk cache** keyed by (source, params). Every external call goes through it — fast repeats, works from cache when an API is down, per-source freshness. Never raises on miss/corrupt/disk error; `get_or_set` falls back to a *stale* entry if the fresh fetch fails. |

### Data source adapters

| Module | Sources | Verified live |
|--------|---------|---------------|
| `engine/ingest/nasa_open.py` | NASA NEO Feed, EPIC Earth imagery, APOD, ADS literature | ✅ 17 NEOs (incl. hazardous 2013 OD4), 22 EPIC images, APOD "NGC 7635" |
| `engine/ingest/open_notify.py` | Live ISS position + astronauts (with **TLE-computed fallback**) | ✅ ISS lat/lon,12 humans in space |
| `engine/ingest/spacetrack_ext.py` | boxscore, decay, launch_site | ✅ 122 countries (US: 13,454 payloads), 44 launch sites, reentries |

### New pydantic models (`engine/models.py`)
`NeoObject` + `NeoCloseApproach`, `EpicImage`, `ApodEntry`, `IssPosition`,
`Astronaut` + `Astronauts`, `CountryStats`, `DecayEvent`, `LaunchSite`, `Paper`.

### 8 new agent tools (`agent/tools.py`)
`get_near_earth_objects`, `get_earth_imagery`, `get_astronomy_picture`,
`get_iss_position`, `get_astronauts`, `get_catalog_statistics`,
`get_recent_reentries`, `search_literature` — each with a JSON schema so the
Granite analyst can call them conversationally.

---

## Capabilities unlocked

| Source | Feature | Judging criteria |
|--------|---------|------------------|
| **NEO Feed** | Planetary defense — asteroids/comets approaching Earth, with hazard flags | Challenge Fit, Innovation, Impact |
| **EPIC** | "Earth from space right now" — full-disc imagery (stunning visual) | Challenge Fit, Innovation |
| **APOD** | Daily astronomy engagement hook | Challenge Fit, Impact |
| **Open Notify ISS** | Live ISS tracker (with SGP4 fallback so it never breaks) | Challenge Fit, Impact, Feasibility |
| **Open Notify astronauts** | "X humans in space" counter | Challenge Fit, Impact |
| **boxscore** | "Who owns orbit" — payloads/debris by country | Challenge Fit, Impact |
| **decay** | "What's coming back down" — reentry predictions (sustainability) | Impact, Challenge Fit |
| **ADS** | Analyst cites real peer-reviewed literature | Innovation, Technical Execution |

---

## Robustness design (the difference between a demo and a product)

1. **Graceful degradation everywhere.** Every fetch returns empty/`available: False`
   on any failure — the app never crashes because an API is down or rate-limited.
2. **Caching with sensible TTLs.** NEO/APOD 24 h · EPIC 1 h · ISS 30 s · astronauts
   1 h · boxscore/decay 24 h · ADS 7 d. Repeated calls are fast and cheap.
3. **Stale-on-error fallback.** If a fresh fetch fails, `get_or_set` serves the last
   good cached value rather than nothing.
4. **ISS position has a physics fallback.** Open Notify is HTTP-only and occasionally
   down; if it fails, we compute the ISS position from its TLE via SGP4 (TEME →
   geodetic lat/lon), so the live tracker *always* works.
5. **Rate-limit respect.** Space-Track queries paced ~2 s apart (sessions drop under
   rapid fire); NASA `DEMO_KEY` is rate-limited — use a free personal key for production.

---

## Verified live results (2026-07-27)

```
NASA NEO Feed:   17 NEOs over 3 days; first: (2013 OD4), HAZARDOUS, Ø0.368 km
NASA EPIC:       22 full-disc Earth images; latest 20260724002713, centroid (11.7, -175.6)
NASA APOD:       "NGC 7635: The Bubble Nebula" (image)
Open Notify ISS: lat -14.05, lon -129.67 (source: open-notify)
Open Notify:     12 humans in space
Space-Track boxscore: 122 countries/orgs
   UNITED STATES: 13,454 payloads · 3,906 debris · 18,146 orbital · 10,612 decayed
   CIS:           1,612 payloads · 3,902 debris · 6,599 orbital · 18,629 decayed
   PRC:           1,272 payloads · 4,188 debris · 6,042 orbital · 3,161 decayed
   ALL: 19,085 payloads · 12,501 debris · 34,737 orbital · 35,385 decayed
Space-Track decay: NORAD 46171 (2020-057BG, US) decay 2026-07-27; …
Space-Track launch sites: 44 (AFETR, Baikonur/Tyuratam, Andoya, …)
```

---

## Configuration

Add to `.env` (all optional — every source degrades gracefully without keys):

```
NASA_API_KEY=...     # free at api.nasa.gov (DEMO_KEY works but is rate-limited)
ADS_API_KEY=...      # free at ui.adsabs.harvard.edu (for literature search)
# SPACETRACK_USERNAME / SPACETRACK_PASSWORD already used for boxscore/decay
```

---

## Tests (50 new, 233 total)

- `tests/test_cache.py` — TTL, expiry, corrupt-file safety, stale-on-error fallback, fetcher-once.
- `tests/test_nasa_open.py` — NEO/EPIC/APOD/ADS parsing from recorded fixtures (offline).
- `tests/test_open_notify.py` — TEME→lat/lon math (equator/pole/range), TLE fallback, graceful failure.
- `tests/test_spacetrack_ext.py` — boxscore/decay/launch_site parsing from recorded fixtures.
- `tests/test_agent_tools.py` — 8 new tools (graceful whether or not APIs are up).

---

## Honest scope & gotchas (documented, not hidden)

- **NASA `DEMO_KEY`** is rate-limited (~30 req/hr); a free personal key is needed for
  sustained use. Every NASA call degrades to empty without one.
- **ADS requires a free API key**; `search_literature` returns `available: False` without it.
- **Open Notify is HTTP-only** (no TLS) — the SGP4 TLE fallback covers environments
  that block mixed content.
- **Space-Track `boxscore`** field names are non-obvious (`ORBITAL_PAYLOAD_COUNT`,
  `ORBITAL_DEBRIS_COUNT`, …); we map them to a clean `CountryStats` model. The `ALL`
  row is the global aggregate, separated from individual countries.
- **`decay` is predicted, not confirmed** reentry — labeled as such in the tool output.

---

## Next (from the plan)

- **Phase B** — space-weather deepening (NOAA solar wind, DONKI full types, quantitative
  storm-driven drag uncertainty band).
- **Phase C** — Earth observation (earth-search STAC: Sentinel-2/1, Landsat) + ground track.
- **Phase D** — JPL Horizons precision ephemerides (feeds accurate SRP).
- **Phase E** — astronomy streams (ZTF/Gaia/TESS).
- **Phase F** — synthesis: unified dashboard + space-situation assistant + accessibility narrative.

---

*Implemented 2026-07-27. Phase A of the data-integration roadmap is complete and
live-verified. The frontend panels for these sources are the natural next step
(see Phase F), but the data layer, agent tools, and tests are all in place.*
