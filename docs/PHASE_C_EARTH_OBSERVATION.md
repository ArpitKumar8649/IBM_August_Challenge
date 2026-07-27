# Phase C — Earth Observation (Implemented)

> Phase C of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): connect orbit
> to *Earth impact* — "what is my satellite looking at right now?" and enable
> satellite-data-analysis features (a named challenge area). **Implemented and
> tested.**
>
> **28 new tests; 300 passing.** The agent contract grows 22 → **25 tools**.
> All integrations verified live (2026-07-27).

---

## What was built

| Module | Role |
|--------|------|
| `engine/ground_track.py` | **Ground-track computation** — the satellite's sub-satellite point (lat/lon) over time, from its TLE via SGP4, accounting for Earth's rotation (GMST). Bounding box + center, with **antimeridian (±180°) crossing handled**. |
| `engine/ingest/stac_client.py` | **STAC client** — earth-search (AWS, free, no auth) for Sentinel-2 (optical), Sentinel-1 (SAR, all-weather), Landsat; plus Copernicus CLMS burnt-area (disaster monitoring). Cloud filtering + thumbnails. |

### New models (`engine/models.py`)
`GroundTrackPoint` · `StacItem` · `BurntAreaItem`

### 3 new agent tools (`agent/tools.py`)
| Tool | Returns |
|------|---------|
| `get_ground_track(norad_id, minutes)` | The satellite's lat/lon path over the next N minutes + bbox + center |
| `get_imagery_under_satellite(norad_id, collection, max_cloud)` | Latest cloud-filtered scene under the satellite's current position |
| `get_disaster_data(w, s, e, n, days)` | Copernicus CLMS burnt-area observations in a region |

---

## The two capabilities, in detail

### C.1/C.2 Ground track + "what's under my satellite"

Compute the satellite's **ground track** (sub-satellite point over time):
1. Propagate the TLE with SGP4 over the window (vectorized grid).
2. Convert each ECI position to geodetic lat/lon via **GMST** (Earth-rotation
   correction), reusing the astronomy helpers from `open_notify.py`.
3. Compute the bounding box and center; handle the **antimeridian crossing**
   (normalize longitudes to [0, 360) when the track crosses ±180°, producing a
   valid STAC/GeoJSON antimeridian bbox where west > east).

Then query imagery for the region under the satellite:
- Compute the sub-satellite point → a small bbox around it.
- Query earth-search STAC for the latest cloud-filtered scene.
- **Sentinel-2** (optical, cloud-sensitive) by default; **Sentinel-1** (SAR) as
  the all-weather option (sees through clouds — the cloud filter is skipped for it).

### C.3 Copernicus CLMS burnt-area (disaster monitoring)

The Copernicus Data Space STAC exposes **CLMS Burnt-Area** (verified:
`clms_ba_global_300m_daily_v4_cog`). This enables a disaster-monitoring feature:
"there's an active fire / burnt area under your satellite's ground track." We
return the STAC metadata (bbox, date) — the full raster download needs a free
Copernicus token, but **STAC search is open**.

---

## Why earth-search, not Copernicus Data Space (documented gotcha)

The Copernicus Data Space STAC (`catalogue.dataspace.copernicus.eu/stac`) was
verified to expose only **CLMS Burnt-Area and Contributing-Mission** collections —
**not** the main Sentinel-2 collection. The AWS **earth-search** STAC
(`earth-search.aws.element84.com/v1`) is free, **no-auth**, and carries the full
Sentinel-2 / Sentinel-1 / Landsat catalog. This is a real gotcha that would waste
hours if not documented — so we use earth-search for imagery and Copernicus for
CLMS, each for what it's good at.

---

## Verified live results (2026-07-27)

```
ISS ground track (90 min):  91 points; current lat=48.93, lon=33.23, alt=412 km
                            bbox [W,S,E,N] spans the orbit; center lat=-1.0, lon=11.2
Sentinel-2 under ISS:       S2B_36UVV_20260727_0_L2A, 2026-07-27T08:56, cloud=31.7%
                            thumbnail: https://sentinel-cogs.s3.us-west-2.amazonaws.com/...
earth-search collections:   sentinel-2-l2a, sentinel-1-grd, landsat-c2-l2, cop-dem, naip
Copernicus CLMS:            clms_ba_global_300m_daily_v4_cog (HTTP 200)
```

---

## Honest scope & assumptions (documented, not hidden)

- **Geocentric latitude** is used (differs from geodetic by ≤ ~0.2°) — fine for
  ground-track display and imagery-region queries; not survey-grade.
- **Imagery is metadata + thumbnails** — we surface the scene and a preview URL,
  not the full multi-GB raster (which would need download + processing). Full-res
  assets are linked for the operator to fetch.
- **CLMS is metadata-only** — STAC search is open; raster download needs a free
  Copernicus Data Space token.
- **Cloud filtering** uses `eo:cloud_cover` (Sentinel-2/Landsat); SAR has no cloud
  cover, so the filter is skipped for Sentinel-1.
- **earth-search data is current** (latest scenes are days old) but a specific
  bbox may have tile gaps — the tool reports "no scenes" gracefully and suggests
  the all-weather SAR option.

---

## Tests (28 new)

- **ground_track:** sub-satellite point (equator/pole/altitude), point count, ISS
  latitude bounds (±inclination), longitude validity, altitude range, bbox
  containment, center = mean, antimeridian detection + crossing bbox (west > east).
- **stac_client:** item parsing (fields/thumbnail/assets/defaults), collections
  defined, cloud filtering (mocked search), recent-first sort, SAR skips cloud
  filter, graceful empty on failure.
- **agent tools:** get_ground_track (live + unknown-NORAD), get_imagery_under_satellite,
  get_disaster_data — all graceful.

---

## Next (from the plan)

- **Phase D** — JPL Horizons precision ephemerides (feeds accurate SRP Sun direction;
  a precision reference for validating SGP4).
- **Phase E** — astronomy streams (ZTF transients via ALeRCE, Exoplanet Archive,
  Gaia, TESS).
- **Phase F** — synthesis: unified dashboard (ground-track map, imagery panel,
  disaster overlay) + space-situation assistant + accessibility narrative.

The frontend Earth-observation panel (2D ground-track over a world map + latest
Sentinel-2 thumbnail under the satellite) is the natural next step to make this
visible.

---

*Implemented 2026-07-27. Run: `pytest tests/test_ground_track.py
tests/test_stac_client.py tests/test_agent_tools.py`.*
