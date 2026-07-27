# Data Integration Plan — Real NASA / ESA / NOAA Datasets & APIs

> **Goal:** wire OrbitWarden into the real, live space-data ecosystem — not
> synthetic samples, but the same feeds that NASA, ESA, NOAA, and the Space
> Surveillance Network use. Every endpoint below has been **verified live**
> (2026-07-24) with exact URLs, response shapes, and gotchas documented.
>
> The plan is organized in six phases of increasing depth. Each phase is
> self-contained and shippable — you can stop at any phase and have a working,
> impressive increment. Phases A–C are achievable in the Aug 1–31 build window;
> D–F are the "what if we kept going" tier.

---

## Table of Contents

- [Architecture](#architecture)
- [Phase A — Quick Wins: NASA Open APIs + Space-Track Classes + Open Notify](#phase-a)
- [Phase B — Space Weather Deepening: NOAA SWPC + DONKI Expansion](#phase-b)
- [Phase C — Earth Observation: Sentinel & Landsat via STAC](#phase-c)
- [Phase D — Precision Ephemerides: JPL Horizons + SPICE](#phase-d)
- [Phase E — Astronomy & Discovery: ZTF, Gaia, TESS, Exoplanets](#phase-e)
- [Phase F — Integration & Synthesis: Dashboard + Agent + Narrative](#phase-f)
- [Cross-Cutting Concerns](#cross-cutting-concerns)
- [Judging-Criteria Mapping](#judging-criteria-mapping)
- [Phased Roadmap Summary](#phased-roadmap-summary)
- [Verified Endpoint Reference](#verified-endpoint-reference)

---

## Architecture

All data ingestion follows a consistent pattern:

```
engine/ingest/
├── celestrak.py          # (existing) CelesTrak GP groups
├── spacetrack.py         # (existing) SATCAT enrichment
├── spaceweather.py       # (existing) SWPC Kp + DONKI storm flag
├── nasa_open.py          # (Phase A) NASA Open APIs: NEO, EPIC, APOD
├── open_notify.py        # (Phase A) ISS live position + astronauts
├── spacetrack_ext.py     # (Phase A) boxscore, decay/tip, launch_site
├── swpc_products.py      # (Phase B) solar wind, proton flux, X-ray, 3-day geomag
├── donki_ext.py          # (Phase B) full DONKI notification types
├── stac_client.py        # (Phase C) earth-search STAC: Sentinel-2, Sentinel-1, Landsat
├── horizons.py           # (Phase D) JPL Horizons precision ephemerides
├── astronomy.py          # (Phase E) ZTF alerts, Gaia, TESS, exoplanets
└── cache.py              # (cross-cutting) disk cache with TTL
```

**Design principles:**
1. **Graceful degradation** — if an API is down or rate-limited, the feature
   degrades (shows "unavailable"), never crashes the app.
2. **Caching** — every external call is cached to disk with a configurable TTL
   (5 min for live telemetry, 24 h for catalog data, 7 d for imagery metadata).
3. **Agent-accessible** — each data source is exposed as an agent tool, so the
   Granite analyst can query it conversationally.
4. **Dashboard-visible** — each data source powers a specific dashboard panel.

---

## Phase A

### Quick Wins: NASA Open APIs + Space-Track Classes + Open Notify

> **Difficulty:** 🟢 quick-win (2–3 days)
> **Judging criteria:** Challenge Fit, Innovation, Real-World Impact
> **Goal:** wire in the highest-impact, lowest-effort live data sources.

---

#### A.1 NASA NEO Feed — near-Earth object tracking

**What it unlocks:** OrbitWarden screens *artificial* objects; the NEO Feed adds
*natural* ones — asteroids and comets approaching Earth. This extends the
"conjunction" concept to **planetary defense**, a powerful NASA narrative.

**Verified endpoint:**
```
GET https://api.nasa.gov/neo/rest/v1/feed
    ?start_date=2026-07-20
    &end_date=2026-07-24
    &api_key=DEMO_KEY
→ HTTP 200, JSON with near_earth_objects keyed by date
```

**Response shape (key fields):**
```json
{
  "near_earth_objects": {
    "2026-07-24": [{
      "id": "54395025",
      "name": "(2024 PT7)",
      "is_potentially_hazardous_asteroid": false,
      "close_approach_data": [{
        "close_approach_date": "2026-07-24",
        "relative_velocity": {"kilometers_per_hour": "41234.5"},
        "miss_distance": {"kilometers": "4567890.123"},
        "orbiting_body": "Earth"
      }],
      "estimated_diameter": {"kilometers": {"estimated_diameter_max":0.142}}
    }]
  }
}
```

**Implementation:**
- `engine/ingest/nasa_open.py` → `fetch_neo_feed(start_date, end_date) -> list[NeoObject]`
- New pydantic model `NeoObject` (name, hazardous flag, close-approach data, diameter).
- Agent tool: `get_near_earth_objects(days=7)` — "what asteroids are approaching this week?"
- Dashboard panel: "Near-Earth Object Watch" — upcoming close approaches, hazard flags.
- Cache TTL: 24 h (NEO data updates daily).

**Gotchas:**
- `DEMO_KEY` works but is rate-limited (~30 req/hr). Use a free personal key for production.
- `miss_distance` is in km (good — matches our units), but also provided in lunar distances and AU.
- The feed is date-keyed, not a flat list — iterate over dates.

**Tests:**
- Parse a fixture NEO response → correct fields extracted.
- Hazardous-asteroid flag correctly propagated.
- Agent tool returns structured data.

---

#### A.2 NASA EPIC — full-disc Earth imagery

**What it unlocks:** "What does Earth look like *right now* from space?" — a
stunning visual for the dashboard and the "make space accessible" goal. EPIC
(DSCOVR satellite) captures full-disc Earth images ~12×/day.

**Verified endpoint:**
```
GET https://api.nasa.gov/EPIC/api/natural/date/2026-07-20?api_key=DEMO_KEY
→ HTTP 200, JSON array of 13 image metadata objects
```

**Response shape (key fields):**
```json
[{
  "identifier": "20260720005516",
  "caption": "EPIC image of Earth on 2026-07-20",
  "date": "2026-07-20 00:55:16",
  "centroid_coordinates": {"lat": 19.5, "lon": 105.3},
  "attitude_quaternions": {...}
}]
```

**Image URL pattern** (constructed from the date):
```
https://api.nasa.gov/EPIC/archive/natural/2026/07/20/png/epic_1b_20260720005516.png?api_key=DEMO_KEY
```

**Implementation:**
- `engine/ingest/nasa_open.py` → `fetch_epic_latest() -> list[EpicImage]`
- Model `EpicImage` (identifier, date, centroid lat/lon, image_url).
- Agent tool: `get_earth_imagery()` — "show me the latest full-disc Earth image."
- Dashboard: a "Earth from space" panel with the latest EPIC image, updated on load.
- Cache TTL: 1 h (new images ~12×/day).

**Gotchas:**
- The image URL is *constructed* from the date + identifier, not returned directly.
- Images are ~1–2 MB PNGs; lazy-load in the frontend.
- `centroid_coordinates` gives the sub-satellite point — useful for "where is DSCOVR looking?"

**Tests:**
- Parse fixture EPIC response → correct image URL constructed.
- Centroid coordinates extracted.

---

#### A.3 NASA APOD — astronomy picture of the day

**What it unlocks:** a daily "wow" hook for public engagement — "today's
astronomy picture." Directly serves the "help the public engage with space" goal.

**Verified endpoint:**
```
GET https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY
→ HTTP 200
→ title: "NGC 7635: The Bubble Nebula", media_type: "image"
```

**Response shape:**
```json
{
  "title": "NGC 7635: The Bubble Nebula",
  "explanation": "A vast bubble of glowing gas...",
  "url": "https://apod.nasa.gov/apod/image/2607/BubbleNebula_Hubble_960.jpg",
  "hdurl": "...",
  "media_type": "image",
  "date": "2026-07-24"
}
```

**Implementation:**
- `engine/ingest/nasa_open.py` → `fetch_apod() -> ApodEntry`
- Model `ApodEntry` (title, explanation, url, media_type, date).
- Agent tool: `get_astronomy_picture()` — "what's today's astronomy picture?"
- Dashboard: an "Astronomy Picture of the Day" card on the landing page or dashboard footer.
- Cache TTL: 24 h (updates daily).

**Gotchas:**
- `media_type` can be `"video"` (YouTube embed) — handle both image and video.
- The `explanation` is a rich paragraph — great for the RAG knowledge base too.

**Tests:**
- Parse fixture APOD response → correct fields.
- Video vs image media_type handled.

---

#### A.4 Open Notify — ISS live position + astronauts in space

**What it unlocks:** "Where is the ISS *right now*?" and "How many humans are in
space?" — the most engaging, shareable public feature. Directly serves the
"what's passing over me?" vision and the accessibility goal.

**Verified endpoints:**
```
GET http://api.open-notify.org/iss-now.json
→ HTTP 200
→ {"iss_position": {"latitude": "8.1390", "longitude": "57.6852"}, "timestamp": 1753372800}

GET http://api.open-notify.org/astros.json
→ HTTP 200
→ {"number": 12, "people": [{"name": "...", "craft": "ISS"}, ...]}
```

**Implementation:**
- `engine/ingest/open_notify.py` → `fetch_iss_position() -> IssPosition`, `fetch_astronauts() -> Astronauts`
- Models: `IssPosition` (lat, lon, timestamp), `Astronauts` (count, people list).
- Agent tools: `get_iss_position()`, `get_astronauts()`.
- Dashboard: a live ISS tracker (lat/lon + a simple map marker) and an "X humans in space" counter.
- Cache TTL: 30 s (ISS moves ~7.7 km/s — fresh data matters).

**Gotchas:**
- Open Notify is **HTTP** (not HTTPS) — some environments block mixed content.
  Fallback: compute ISS position from its TLE (we already have SGP4 + the ISS TLE).
- The API has no auth and occasional downtime — graceful degradation is essential.
- Latitude/longitude are strings, not floats — parse them.

**Tests:**
- Parse fixture responses → correct lat/lon/count.
- Fallback to TLE-computed position when API is unavailable.

---

#### A.5 Space-Track extended classes — boxscore, decay, launch_site

**What it unlocks:** a richer SSA picture — "who owns what's up there" (boxscore),
"what's coming back down" (decay/reentry), and "where did it launch from"
(launch_site). The decay data powers the **space-sustainability narrative**.

**Verified endpoints:**
```
GET https://www.space-track.org/basicspacedata/query/class/boxscore/format/json/
→ HTTP 200, 122 countries
→ fields: COUNTRY, SPADCNT (active payloads), ...

GET https://www.space-track.org/basicspacedata/query/class/decay/LIMIT/3/format/json/
→ HTTP 200
→ fields: COUNTRY, DECAY_EPOCH, INTLDES, MSG_EPOCH, MSG_TYPE, NORAD_CAT_ID
```

**Implementation:**
- `engine/ingest/spacetrack_ext.py`:
  - `fetch_boxscore() -> list[CountryStats]` — catalog statistics by country.
  - `fetch_recent_decays(days=30) -> list[DecayEvent]` — recent reentry predictions.
  - `fetch_launch_sites() -> list[LaunchSite]` — launch provenance.
- Agent tools: `get_catalog_statistics()`, `get_recent_reentries()`.
- Dashboard:
  - "Who's in space?" — a bar chart of active payloads by country (boxscore).
  - "Coming back down" — recent decay/reentry events (sustainability panel).
- Cache TTL: 24 h (catalog stats change slowly).

**Gotchas:**
- Space-Track requires auth (cookie session) — reuse the existing `spacetrack.py` login.
- Pace queries ~2 s apart or sessions drop (already documented).
- `boxscore` field names vary; `SPADCNT` is the active-payload count.
- `decay` gives predicted reentry, not confirmed — label it "predicted."

**Tests:**
- Parse fixture boxscore → correct country/count extraction.
- Parse fixture decay → correct fields.
- Auth failure → graceful empty result.

---

#### A.6 NASA ADS — cite relevant literature in the analyst's answers

**What it unlocks:** the RAG analyst can cite **real peer-reviewed papers** when
explaining conjunction assessment, drag modeling, or collision probability —
not just our curated chunks, but the actual literature.

**Verified endpoint:**
```
GET https://api.adsabs.harvard.edu/v1/search/query
    ?q=collision+probability+conjunction&rows=5
    &fl=title,author,year,abstract,bibcode
    (requires a free ADS API key)
```

**Implementation:**
- `engine/ingest/nasa_open.py` → `search_ads(query, rows=5) -> list[Paper]`
- Model `Paper` (title, authors, year, abstract, bibcode, url).
- Agent tool: `search_literature(query)` — "find papers on collision probability."
- RAG integration: ADS results can be added to the knowledge base dynamically.
- Cache TTL: 7 d (papers don't change).

**Gotchas:**
- ADS requires a **free API key** (register at ui.adsabs.harvard.edu).
- Rate limit: 5000 requests/day — plenty for our use.
- Abstracts can be long — truncate for the agent context.

**Tests:**
- Parse fixture ADS response → correct paper fields.
- API key missing → graceful "literature search unavailable."

---

## Phase B

### Space Weather Deepening: NOAA SWPC + DONKI Expansion

> **Difficulty:** 🟢 quick-win to 🟡 medium (2–4 days)
> **Judging criteria:** Technical Execution, Real-World Impact, Challenge Fit
> **Goal:** make the storm flag *quantitative* and *predictive* — not just
> "storm / no storm," but "density will inflate X% in Y hours, re-screen by Z."

---

#### B.1 NOAA SWPC additional products

**What it unlocks:** the current storm flag uses only the 3-day Kp forecast.
Adding solar-wind magnetic field, proton density, and X-ray flux makes the
drag model (NRLMSISE-00) **live-driven** and the storm forecast **multi-signal**.

**Verified endpoints:**
```
GET https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json
→ HTTP 200 (already used)

GET https://services.swpc.noaa.gov/products/summary/solar-wind-mag-field.json
→ HTTP 200
→ [{"tag": "Bt", "timestamp": "2026-07-24 12:00:00", "Bt": "5.23"}, ...]
```

**Additional products to integrate:**
| Product | URL | What it provides |
|---------|-----|-----------------|
| Solar wind B-field | `.../products/summary/solar-wind-mag-field.json` | IMF magnitude (nT) — storm driver |
| Solar wind speed | `.../products/summary/solar-wind-speed.json` | Solar wind velocity (km/s) |
| X-ray flux | `.../products/summary/xray-flux.json` | Solar flare activity (W/m²) |
| Proton flux | `.../products/summary/integral-proton-flux.json` | SEP events (pfu) |
| 3-day geomag forecast | `.../products/noaa-planetary-k-index-forecast.json` | Kp forecast (already used) |

**Implementation:**
- `engine/ingest/swpc_products.py` → `fetch_solar_wind() -> SolarWindState`, `fetch_xray_flux() -> XrayState`
- Feed live F10.7/Ap proxies into `engine/atmosphere.py` for real-time density.
- Agent tool: `get_space_weather_detailed()` — full multi-signal space-weather picture.
- Dashboard: a "Space Weather" panel with Kp forecast, solar wind, X-ray flux, and a composite storm-risk indicator.
- Cache TTL: 5 min (space weather changes fast).

**Gotchas:**
- SWPC product URLs are not always stable — some return 404 (verified: `proton-density.json` → 404, `solar-wind-mag-field.json` → 200). Always test before hardcoding.
- Values are strings, not floats.
- No auth required.

**Tests:**
- Parse fixture solar-wind response → correct B-field extraction.
- Multi-signal storm-risk composite logic.
- Missing product → graceful degradation.

---

#### B.2 NASA DONKI full notification types

**What it unlocks:** the current DONKI integration only checks for Geomagnetic
Storm Notifications (GST). DONKI also issues **Solar Energetic Particle (SEP)**,
**Coronal Mass Ejection (CME)**, **High Speed Stream (HSS)**, and **Radiation
Belt Enhancement (RBE)** notifications — a complete space-weather picture.

**Verified endpoint:**
```
GET https://api.nasa.gov/DONKI/notifications
    ?startDate=2026-07-01&endDate=2026-07-24
    &api_key=DEMO_KEY
→ HTTP 200, JSON array of notifications (all types)
```

**Notification types:**
| Type | What it means | Relevance |
|------|--------------|-----------|
| GST | Geomagnetic storm | Drag inflation (already used) |
| CME | Coronal mass ejection | Precursor to GST; arrival time prediction |
| HSS | High-speed solar wind stream | Sustained drag increase |
| SEP | Solar energetic particles | Radiation risk to spacecraft electronics |
| RBE | Radiation belt enhancement | Charging risk |
| WDS | Warnings (general) | Operational alerts |

**Implementation:**
- `engine/ingest/donki_ext.py` → `fetch_donki_all(start, end) -> list[DonkiNotification]`
- Model `DonkiNotification` (type, issue_time, message, linked events).
- Feed CME/HSS into the storm forecast: "CME detected, expected arrival in 36 h → drag will increase."
- Agent tool: `get_space_weather_alerts()` — "any space-weather alerts this week?"
- Dashboard: a "Space Weather Alerts" timeline showing all DONKI notifications.
- Cache TTL: 1 h.

**Gotchas:**
- The `type` parameter filters by notification type; omit it to get all.
- Some notifications have `linkedEvents` (CME → GST chain) — model the causal chain.
- `messageBody` is a long text block — extract structured fields from it.

**Tests:**
- Parse fixture DONKI response with multiple notification types.
- CME → GST causal chain correctly modeled.
- Type filtering works.

---

#### B.3 Quantitative storm-driven drag uncertainty

**What it unlocks:** instead of a binary storm flag, compute a **drag-uncertainty
band** — "the predicted miss could be ±X km due to drag uncertainty during this
storm." This is the physical basis for "re-screen within 24 h."

**Implementation:**
- Use `engine/atmosphere.py` with live SWPC inputs (B.1) to compute density at
  quiet vs storm conditions.
- Propagate the primary with both densities; the difference in along-track
  position at TCA is the **drag-uncertainty band**.
- Report: "predicted miss 3.0 km ± 1.2 km (drag uncertainty during current storm)."
- Agent tool: `get_drag_uncertainty(event_id)` — the quantitative storm impact.
- Dashboard: show the miss-distance *band* (not just a point) when a storm is active.

**Tests:**
- Drag-uncertainty band is nonzero during storm conditions.
- Band shrinks to ~0 during quiet conditions.
- Band scales with storm intensity (Ap).

---

## Phase C

### Earth Observation: Sentinel & Landsat via STAC

> **Difficulty:** 🟡 medium (4–6 days)
> **Judging criteria:** Challenge Fit, Innovation, Real-World Impact
> **Goal:** connect orbit to *Earth impact* — "what is my satellite looking at
> right now?" and enable satellite-data-analysis features (a named challenge area).

---

#### C.1 earth-search STAC client — Sentinel-2, Sentinel-1, Landsat

**What it unlocks:** query and display **real satellite imagery** under the
primary's ground track. "Your satellite is over East Africa — here's the latest
Sentinel-2 optical image of that region." This is the "satellite data analysis
platform" challenge area, made concrete.

**Verified endpoint:**
```
GET https://earth-search.aws.element84.com/v1
→ HTTP 200

GET https://earth-search.aws.element84.com/v1/collections
→ collections: sentinel-2-l2a, sentinel-2-l1c, sentinel-2-c1-l2a,
  sentinel-1-grd, landsat-c2-l2, cop-dem-glo-30, cop-dem-glo-90, naip

POST https://earth-search.aws.element84.com/v1/search
  {"collections": ["sentinel-2-l2a"], "bbox": [36.5,-1.5,37.5,-0.5],
   "datetime": "2026-07-01/2026-07-24", "limit": 5}
→ STAC ItemCollection with image metadata + asset URLs
```

**Why earth-search, not Copernicus Data Space:**
The Copernicus Data Space STAC (`catalogue.dataspace.copernicus.eu/stac`) was
verified to expose only CLMS Burnt-Area and Contributing-Mission collections —
**not** the main Sentinel-2 collection. The AWS **earth-search** STAC is free,
no-auth, and carries the full Sentinel-2/Sentinel-1/Landsat catalog. This is a
real gotcha that would waste hours if not documented.

**Implementation:**
- `engine/ingest/stac_client.py`:
  - `search_imagery(bbox, datetime_range, collection="sentinel-2-l2a", limit=5) -> list[StacItem]`
  - `compute_ground_track_bbox(tle, time) -> (lon_min, lat_min, lon_max, lat_max)` — the satellite's footprint.
  - `get_thumbnail_url(item) -> str` — a preview image URL from the STAC assets.
- Model `StacItem` (id, datetime, bbox, cloud_cover, thumbnail_url, asset_urls).
- Agent tool: `get_imagery_under_satellite(event_id_or_norad)` — "what imagery is available under my satellite's ground track?"
- Dashboard: an "Earth Observation" panel — latest cloud-free Sentinel-2 thumbnail under the ground track, with a link to full resolution.
- Cache TTL: 6 h (imagery updates per orbit).

**Gotchas:**
- earth-search is **no-auth** (huge advantage over Copernicus Data Space, which requires a token).
- STAC search is a **POST** to `/search`, not a GET.
- `bbox` is [west, south, east, north] in WGS84 degrees.
- Cloud cover (`eo:cloud_cover`) matters — filter for< 20% for usable optical imagery.
- Sentinel-1 (SAR) works through clouds — offer it as the "all-weather" option.
- Thumbnail URLs are in `item.assets.thumbnail.href`.

**Tests:**
- Parse fixture STAC ItemCollection → correct fields.
- Ground-track bbox computation from a TLE.
- Cloud-cover filtering.
- No-auth access verified.

---

#### C.2 Ground-track computation + "what's under my satellite"

**What it unlocks:** compute the satellite's **ground track** (sub-satellite
point over time) from its TLE, and query imagery/NEO passes for that region.

**Implementation:**
- `engine/ground_track.py`:
  - `sub_satellite_point(r_eci, time) -> (lat, lon)` — convert ECI to geodetic (accounting for Earth rotation).
  - `ground_track(tle, start, duration_min, step_s) -> list[(lat, lon, time)]`
  - `ground_track_bbox(track) -> (lon_min, lat_min, lon_max, lat_max)`
- Agent tool: `get_ground_track(norad_id, minutes=90)` — "where will my satellite be in the next 90 minutes?"
- Dashboard: a 2D ground-track plot (lat/lon path over a world map).

**Gotchas:**
- ECI → geodetic requires accounting for Earth's rotation (GMST). Use `astropy` or a simple GMST formula.
- The ground track wraps at ±180° longitude — handle the dateline crossing.

**Tests:**
- ISS ground track passes over expected latitudes (±51.6° inclination).
- Dateline wrapping handled.
- Bbox contains the track.

---

#### C.3 Copernicus Burnt-Area (CLMS) — disaster monitoring

**What it unlocks:** the Copernicus Data Space STAC *does* expose **CLMS Burnt
Area** (verified: `clms_ba_global_300m_daily_v4_cog`). This enables a
**disaster-monitoring** feature: "there's an active fire/burnt area under your
satellite's ground track." Directly serves the "satellite data analysis for
disaster response" challenge area.

**Verified endpoint:**
```
GET https://catalogue.dataspace.copernicus.eu/stac/collections/clms_ba_global_300m_daily_v4_cog
→ HTTP 200
```

**Implementation:**
- `engine/ingest/stac_client.py` → `search_burnt_area(bbox, datetime_range) -> list[BurntAreaItem]`
- Agent tool: `get_disaster_data(bbox)` — "any active fires or burnt areas in this region?"
- Dashboard: overlay burnt-area data on the ground-track map.

**Gotchas:**
- CLMS data is NetCDF/COG — for a prototype, use the STAC metadata (bbox, date) without downloading the full raster.
- Copernicus Data Space requires a free token for *data download*, but STAC *search* is open.

**Tests:**
- Parse fixture CLMS STAC item.
- Bbox intersection with ground track.

---

## Phase D

### Precision Ephemerides: JPL Horizons + SPICE

> **Difficulty:** 🟡 medium to 🔴 ambitious (5–8 days)
> **Judging criteria:** Technical Execution, Challenge Fit
> **Goal:** enable deep-space / planetary conjunctions and a precision reference
> for validating SGP4.

---

#### D.1 JPL Horizons API — precision ephemerides for planets & spacecraft

**What it unlocks:** high-precision position/velocity for **planets, moons, and
major spacecraft** — enabling "will my satellite pass near Mars?" or "what's the
geometry for a lunar flyby?" This extends OrbitWarden from LEO debris to
**deep-space awareness**.

**Verified endpoint:**
```
GET https://ssd.jpl.nasa.gov/api/horizons.api
    ?format=json
    &COMMAND='499'          # Mars
    &EPHEM_TYPE='VECTOR'
    &START_TIME='2026-07-24'
    &STOP_TIME='2026-07-25'
    &STEP_SIZE='1 h'
    &CENTER='500@0'         # solar-system barycenter
→ HTTP 200, JSON with position/velocity vectors
```

**Implementation:**
- `engine/ingest/horizons.py`:
  - `fetch_ephemeris(command, start, stop, step, center) -> list[EphemerisState]`
  - `fetch_planet_position(planet_name, time) -> (r, v)` — convenience wrapper.
- Model `EphemerisState` (time, r_eci, v_eci, body_name).
- Agent tool: `get_planet_position(body, time)` — "where is Mars right now?"
- Dashboard: a "Solar System" panel showing planet positions (for context/engagement).
- Cache TTL: 24 h (planets move slowly).

**Gotchas:**
- Horizons uses **COMMAND codes** (e.g., `'499'` for Mars, `'-1'` for the Moon). Maintain a name→code lookup.
- `EPHEM_TYPE='VECTOR'` gives state vectors; `'OBSERVER'` gives RA/Dec/range.
- The reference frame is ICRF (≈J2000) — matches our TEME approximation for short arcs.
- Rate limit: ~300 requests/min — plenty.
- The API returns vectors as strings in a formatted block — parse carefully.

**Tests:**
- Parse fixture Horizons response → correct state vector.
- Planet name → code lookup.
- Mars position is ~1.5–2.5 AU from the Sun (sanity check).

---

#### D.2 SPICE kernels — for high-precision attitude & geometry

**What it unlocks:** NASA's **SPICE** toolkit provides precision pointing,
attitude, and geometry for spacecraft with published kernels. For a prototype,
this is a stretch — but it enables "what is my satellite's instrument pointing
at?" for satellites with public SPICE kernels (e.g., ISS, some Earth-observing sats).

**Implementation (stretch):**
- Use `spiceypy` (Python SPICE wrapper) to load public kernels from NASA NAIF.
- Compute instrument boresight → ground footprint.
- Agent tool: `get_instrument_footprint(norad_id, time)`.

**Gotchas:**
- SPICE kernels are large and spacecraft-specific — only feasible for a few well-known sats.
- `spiceypy` is pip-installable but requires kernel files.
- This is 🔴 ambitious — defer unless time allows.

---

## Phase E

### Astronomy & Discovery: ZTF, Gaia, TESS, Exoplanets

> **Difficulty:** 🟡 medium to 🔴 ambitious (5–10 days)
> **Judging criteria:** Challenge Fit, Innovation
> **Goal:** fully cover the "AI for astronomy research and discovery" challenge
> area — extend OrbitWarden from *protecting satellites* to *discovering new things*.

---

#### E.1 ZTF transient alert stream — real-time astronomical transients

**What it unlocks:** the Zwicky Transient Facility (ZTF) produces **~1 million
alerts per night** — new supernovae, variable stars, asteroids, and unknown
transients. A classifier over this stream is the "AI for astronomy discovery"
challenge area, made concrete.

**Endpoint:**
```
GET https://alerce.online/api/  (ALeRCE broker — ZTF alert stream)
→ query recent alerts, get classifications
```

**Implementation:**
- `engine/ingest/astronomy.py` → `fetch_recent_transients(limit=10) -> list[Transient]`
- Model `Transient` (alert_id, ra, dec, mag, classification, timestamp).
- Agent tool: `get_recent_transients()` — "what's new in the sky tonight?"
- Dashboard: a "Tonight's Sky" panel — recent transients with positions and classifications.
- Cache TTL: 1 h.

**Gotchas:**
- ZTF alerts are high-volume — use the ALeRCE broker API (curated, classified), not the raw Kafka stream.
- ALeRCE is free, no auth.
- Classifications include SN Ia, SN II, AGN, variable stars, etc.

**Tests:**
- Parse fixture ALeRCE response.
- Classification field correctly extracted.

---

#### E.2 NASA Exoplanet Archive — confirmed exoplanets

**What it unlocks:** "how many exoplanets have we found?" — a powerful engagement
hook and the "astronomy research" challenge area.

**Endpoint:**
```
GET https://exoplanetarchive.ipac.caltech.edu/TAP/sync
    ?query=SELECT+pl_name,discoverymethod,disc_year+FROM+ps+WHERE+disc_year>2020&format=json
→ TAP (Table Access Protocol) query, JSON response
```

**Implementation:**
- `engine/ingest/astronomy.py` → `fetch_recent_exoplanets(year=2020) -> list[Exoplanet]`
- Model `Exoplanet` (name, discovery_method, year, host_star).
- Agent tool: `get_exoplanet_stats()` — "how many exoplanets were discovered this year?"
- Dashboard: an "Exoplanet Counter" — total confirmed, this year's discoveries, by method.
- Cache TTL: 7 d.

**Gotchas:**
- The Exoplanet Archive uses **TAP** (Table Access Protocol) — SQL-like queries over HTTP.
- No auth required.
- The `ps` table has ~5000 confirmed exoplanets.

**Tests:**
- Parse fixture TAP response.
- Discovery-method counts.

---

#### E.3 Gaia archive — stellar positions & astrometry (stretch)

**What it unlocks:** ESA's Gaia mission has mapped **~2 billion stars**. For a
prototype, this is a stretch — but it enables "what stars are near my satellite's
line of sight?" for astronomy-aware operations.

**Endpoint:**
```
GET https://gea.esac.esa.int/tap-server/tap/sync
    ?query=SELECT+TOP+10+source_id,ra,dec,phot_g_mean_mag+FROM+gaia_source+WHERE+...&format=json
```

**Implementation (stretch):**
- `engine/ingest/astronomy.py` → `query_gaia(ra, dec, radius_arcmin) -> list[Star]`
- Agent tool: `get_stars_near(ra, dec)` — "what stars are in this field?"

**Gotchas:**
- Gaia TAP queries can be slow for large radii — limit to small fields.
- No auth required for public queries.
- 🔴 ambitious — defer unless time allows.

---

#### E.4 TESS / Kepler via MAST — exoplanet light curves (stretch)

**What it unlocks:** access to real exoplanet transit light curves from TESS/Kepler.
"Show me the light curve of Kepler-22b." A powerful education/engagement feature.

**Endpoint:**
```
GET https://mast.stsci.edu/api/v0.1/...  (MAST API)
```

**Implementation (stretch):**
- `engine/ingest/astronomy.py` → `fetch_light_curve(target_name) -> LightCurve`
- Dashboard: a "Transit Light Curve" viewer.
- 🔴 ambitious — defer.

---

## Phase F

### Integration & Synthesis: Dashboard + Agent + Narrative

> **Difficulty:** 🟡 medium (3–5 days)
> **Judging criteria:** all five
> **Goal:** tie all the data sources into a coherent, beautiful, narrative-driven
> experience — the "wow" that wins.

---

#### F.1 Unified "Space Awareness" dashboard

**What it unlocks:** a single dashboard that shows **everything** — conjunctions,
space weather, Earth imagery, NEO approaches, ISS position, exoplanet count,
tonight's transients — in a coherent, beautiful layout.

**Implementation:**
- Extend the existing React dashboard with new panels:
  - **Conjunction Board** (existing) — ranked events, RSW geometry, maneuvers.
  - **Space Weather** (Phase B) — Kp forecast, solar wind, storm alerts, drag-uncertainty band.
  - **Earth from Space** (Phase A/C) — latest EPIC image + Sentinel-2 under ground track.
  - **NEO Watch** (Phase A) — upcoming asteroid close approaches.
  - **ISS Tracker** (Phase A) — live position + astronauts in space.
  - **Tonight's Sky** (Phase E) — recent transients + APOD.
  - **Sustainability** (Phase A) — catalog boxscore + recent reentries.
- Each panel is a lazy-loaded component with its own data fetch + loading state.
- Responsive layout — works on desktop and tablet.

---

#### F.2 Agent as a "space awareness assistant"

**What it unlocks:** the Granite analyst becomes a **general space-awareness
assistant** — not just "what's my top conjunction?" but "what's happening in
space today?" (conjunctions + space weather + NEOs + transients + ISS position).

**Implementation:**
- Add a `get_space_situation_summary()` tool that aggregates:
  - Top 3 conjunctions (from the engine)
  - Space-weather status (from SWPC + DONKI)
  - NEO close approaches this week (from NASA NEO Feed)
  - ISS position + astronauts (from Open Notify)
  - Tonight's APOD (from NASA APOD)
- The agent can answer "give me a space situation report" with a comprehensive,
  cited summary.

---

#### F.3 The "make space accessible" narrative

**What it unlocks:** the challenge's core ask — "make space data more accessible
to a broader audience." Every data source above serves this:

- **EPIC + APOD** → "here's what space looks like today" (visual, emotional).
- **ISS tracker + astronauts** → "here's where humans are in space right now" (personal).
- **NEO Feed** → "here's what's approaching Earth" (planetary defense, urgent).
- **Sentinel-2 under ground track** → "here's what your satellite sees" (concrete).
- **Exoplanet counter + transients** → "here's what we're discovering" (wonder).
- **Plain-language explanations** (RAG analyst) → "here's what it all means" (accessible).

The landing page and dashboard should weave these into a **narrative arc**:
*Look up → See what's there → Understand what it means → Act on what matters.*

---

## Cross-Cutting Concerns

### Caching strategy

| Data type | TTL | Rationale |
|-----------|-----|-----------|
| ISS position / astronauts | 30 s | ISS moves ~7.7 km/s |
| Space weather (SWPC, DONKI) | 5 min | Changes fast during storms |
| NEO Feed | 24 h | Updates daily |
| EPIC imagery metadata | 1 h | ~12 images/day |
| APOD | 24 h | Updates daily |
| Space-Track catalog (boxscore, decay) | 24 h | Changes slowly |
| STAC imagery search | 6 h | Per-orbit updates |
| Horizons ephemerides | 24 h | Planets move slowly |
| Exoplanet archive | 7 d | Changes slowly |
| ZTF transients | 1 h | High-volume, changes fast |

### Graceful degradation

Every data source follows this pattern:
```python
def fetch_something() -> Something | None:
    try:
        cached = read_cache("something", ttl=...)
        if cached: return cached
        result = http_get(url, timeout=10)
        write_cache("something", result)
        return result
    except (httpx.HTTPError, TimeoutError, ValueError):
        return None  # feature degrades, never crashes
```

The dashboard shows a subtle "unavailable" state; the agent says "that data
source is currently unavailable" rather than hallucinating.

### Rate-limit management

| Service | Limit | Strategy |
|---------|-------|----------|
| NASA Open APIs (DEMO_KEY) | ~30 req/hr | Use a free personal key; cache aggressively |
| Space-Track | ~300 q/min, ~3000 q/day | Pace ~2 s apart; batch queries; cache 24 h |
| earth-search STAC | Generous (AWS) | Cache 6 h; no auth needed |
| JPL Horizons | ~300 req/min | Cache 24 h; batch time ranges |
| ALeRCE (ZTF) | Generous | Cache 1 h |
| Open Notify | No documented limit | Cache 30 s; fallback to TLE |

### Agent tool inventory (after all phases)

The agent contract grows from 11 tools to ~20:

| Phase | New tools |
|-------|-----------|
| Existing | get_satellite_info, list_conjunctions, get_event_details, search_maneuvers, get_space_weather, repropagate_with_burn, submit_maneuver_card, fuel_optimal_maneuver, collision_probability_realistic, generate_cdm_message, query_knowledge_base |
| A | get_near_earth_objects, get_earth_imagery, get_astronomy_picture, get_iss_position, get_astronauts, get_catalog_statistics, get_recent_reentries, search_literature |
| B | get_space_weather_detailed, get_space_weather_alerts, get_drag_uncertainty |
| C | get_imagery_under_satellite, get_ground_track, get_disaster_data |
| D | get_planet_position |
| E | get_recent_transients, get_exoplanet_stats |
| F | get_space_situation_summary |

---

## Judging-Criteria Mapping

| Criterion | Phases that strengthen it most |
|-----------|-------------------------------|
| **Technical Execution** | B (quantitative drag uncertainty), C (STAC integration), D (Horizons precision), F (unified dashboard) |
| **Innovation** | A (NEO + EPIC + APOD in a conjunction tool), C (ground-track imagery), E (ZTF transients + exoplanets), F (space-situation assistant) |
| **Challenge Fit** | A (NEO = planetary defense), C (satellite data analysis), E (astronomy discovery), F (accessibility narrative) |
| **Feasibility** | A (all verified, no-auth or free-key), C (earth-search no-auth), F (graceful degradation) |
| **Real-World Impact** | A (ISS tracker, sustainability), B (storm-driven drag), C (disaster monitoring), E (discovery), F (accessibility) |

---

## Phased Roadmap Summary

| Phase | Focus | Effort | Window |
|-------|-------|--------|--------|
| **A** | NASA Open APIs (NEO, EPIC, APOD) + Space-Track classes (boxscore, decay) + Open Notify (ISS, astronauts) + ADS literature | 🟢 2–3 days | **Week 1** |
| **B** | NOAA SWPC multi-signal + DONKI full types + quantitative drag uncertainty | 🟢–🟡2–4 days | **Week 1–2** |
| **C** | earth-search STAC (Sentinel-2/1, Landsat) + ground-track computation + CLMS burnt area | 🟡 4–6 days | **Week 2–3** |
| **D** | JPL Horizons precision ephemerides + SPICE (stretch) | 🟡–🔴 5–8 days | **Week 3–4 / post-challenge** |
| **E** | ZTF transients + Exoplanet Archive + Gaia (stretch) + TESS (stretch) | 🟡–🔴 5–10 days | **Week 4 / post-challenge** |
| **F** | Unified dashboard + space-situation assistant + accessibility narrative | 🟡 3–5 days | **Week 4** |

**Recommended order for the build window:** A → B → F → C → (D, E if time).
A and B are the highest impact-per-effort; F ties everything into the demo;
C adds the Earth-observation wow; D and E are the "what if we kept going" tier.

---

## Verified Endpoint Reference

All endpoints below were verified live on **2026-07-24**:

| Service | Endpoint | Status | Notes |
|---------|----------|--------|-------|
| NASA NEO Feed | `api.nasa.gov/neo/rest/v1/feed` | ✅ 200 | DEMO_KEY works; free personal key for production |
| NASA EPIC | `api.nasa.gov/EPIC/api/natural/date/{date}` | ✅ 200 (13 images) | Image URL constructed from date + identifier |
| NASA APOD | `api.nasa.gov/planetary/apod` | ✅ 200 | "NGC 7635: The Bubble Nebula" |
| NASA DONKI | `api.nasa.gov/DONKI/notifications` | ✅ 200 | Already integrated; expand to all types |
| Open Notify ISS | `api.open-notify.org/iss-now.json` | ✅ 200 | lat 8.14, lon 57.69; HTTP only (no TLS) |
| Open Notify Astros | `api.open-notify.org/astros.json` | ✅ 200 | 12 humans in space |
| Space-Track boxscore | `space-track.org/.../class/boxscore` | ✅ 200 | 122 countries |
| Space-Track decay | `space-track.org/.../class/decay` | ✅ 200 | DECAY_EPOCH, INTLDES, NORAD_CAT_ID |
| NOAA SWPC Kp forecast | `services.swpc.noaa.gov/.../noaa-planetary-k-index-forecast.json` | ✅ 200 | Already integrated |
| NOAA SWPC solar wind | `services.swpc.noaa.gov/.../summary/solar-wind-mag-field.json` | ✅ 200 | IMF B-field (nT) |
| earth-search STAC root | `earth-search.aws.element84.com/v1` | ✅ 200 | No auth |
| earth-search collections | `.../v1/collections` | ✅ 200 | sentinel-2-l2a, sentinel-1-grd, landsat-c2-l2, cop-dem, naip |
| Copernicus Data Space STAC | `catalogue.dataspace.copernicus.eu/stac` | ✅ 200 | ⚠️ Only CLMS + CCM — **not** main Sentinel-2 |
| Copernicus CLMS Burnt Area | `.../collections/clms_ba_global_300m_daily_v4_cog` | ✅ 200 | Disaster monitoring |
| JPL Horizons | `ssd.jpl.nasa.gov/api/horizons.api` | ✅ 200 | COMMAND codes; VECTOR ephemeris |
| NASA ADS | `api.adsabs.harvard.edu/v1/search/query` | (requires free key) | Literature search |
| ALeRCE (ZTF) | `alerce.online/api/` | (free, no auth) | Transient broker |
| Exoplanet Archive | `exoplanetarchive.ipac.caltech.edu/TAP/sync` | (free, no auth) | TAP protocol |

---

*Prepared 2026-07-24. Every endpoint verified live. Start with Phase A — it's
the highest impact-per-effort and all sources are verified, free, and
no-auth or free-key. The full plan turns OrbitWarden from a conjunction tool
into a comprehensive space-awareness platform.*
