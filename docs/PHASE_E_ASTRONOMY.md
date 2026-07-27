# Phase E — Astronomy & Discovery (Implemented)

> Phase E of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): extend
> OrbitWarden from *protecting satellites* to *discovering new things* — the
> "AI for astronomy research and discovery" challenge area. **Implemented and
> tested (E.1, E.2, E.3).**
>
> **22 new tests; 349 total passing.** The agent contract grows 26 → **29 tools**.
> Verified live (2026-07-27). E.4 (TESS light curves) is documented as future work.

---

## What was built

| Module | Role |
|--------|------|
| `engine/ingest/astronomy.py` | **Astronomy client** — ZTF transients (ALeRCE broker), confirmed exoplanets (NASA Exoplanet Archive TAP), and Gaia DR3 stars (TAP cone search). Plus a **robust TAP response normalizer** that handles all common TAP JSON formats. |

### New models (`engine/models.py`)
`Transient` (ZTF) · `Exoplanet` (NASA) · `Star` (Gaia)

### 3 new agent tools (`agent/tools.py`)
| Tool | Returns |
|------|---------|
| `get_recent_transients(limit)` | Recent ZTF transients — supernovae, variables, AGN, unclassified — most-recent-first |
| `get_exoplanet_stats(since_year, limit)` | Confirmed-exoplanet count + recent discoveries by detection method |
| `get_stars_near(ra, dec, radius_arcmin)` | Gaia DR3 stars in a field, brightest-first |

---

## The three integrations, in detail

### E.1 ZTF transients (ALeRCE broker)

The Zwicky Transient Facility produces ~1 million alerts per night. We use the
**ALeRCE broker** (curated, classified) rather than the raw Kafka stream —
`get_recent_transients` returns the most recently observed objects with their
positions and classifications (SN Ia, SN II, AGN, variable stars, or unclassified).

### E.2 NASA Exoplanet Archive (TAP)

"How many exoplanets have we found?" — a powerful engagement hook. We query the
**NASA Exoplanet Archive** via TAP (Table Access Protocol):
- `exoplanet_count(since_year)` — total confirmed since a year.
- `fetch_recent_exoplanets(since_year, limit)` — recent discoveries with detection
  method (Transit, Radial Velocity, Microlensing, …) and host star.

### E.3 Gaia DR3 stars (TAP cone search)

"What stars are in this field?" — a **cone search** of ESA's Gaia DR3 catalog
(~2 billion stars) for stars near a sky position, sorted brightest-first by G
magnitude. Useful for astronomy-aware operations and engagement.

### Robust TAP response normalization (the key engineering point)

TAP servers return JSON in **different shapes**, which would break a naive parser:
1. **Top-level list of row dicts** — NASA Exoplanet Archive.
2. **Dict with `metadata` + `data`**, where `data` rows are either:
   - dicts (keyed), or
   - **positional lists** matching the `metadata` column order — the standard IVOA
     TAP serialization, used by **ESA Gaia**.

`_normalize_tap_rows` handles all three, returning a uniform list of
`{column: value}` dicts. This is verified against all three formats plus edge
cases (length mismatch, missing columns, garbage input).

---

## Verified live results (2026-07-27)

```
ZTF transients (ALeRCE):  ZTF19abfzjvg (ra=331.4, dec=6.8), ZTF19abdqjyv, …
Exoplanets since 2020:    2,229 confirmed
Recent discoveries:       KMT-2023-BLG-1896L b (2025, Microlensing),
                          TOI-3464 b (2025, Transit), GJ 3512 c (2020, Radial Velocity)
Gaia cone search:         stars near Galactic center (266.4, -28.9), brightest-first
TAP normalization:        all 3 response formats + edge cases ✓
```

---

## Gotchas (documented, handled)

These are real, time-costly traps — documented so no one re-discovers them:

- **ALeRCE's main domain (`alerce.online`) is CloudFront-blocked (403)** — use
  `api.alerce.online`. Its list endpoint is **slow (~30-60 s)** and its `count`
  query param is **broken** (a Flask-RESTx version bug: `module 'flask_restx.reqparse'
  has no attribute 'ArgumentTypeError'`), so we omit `count` and use a trailing
  slash on the objects endpoint (the non-slash form 308-redirects).
- **Gaia TAP requires** `REQUEST=doQuery` & `LANG=ADQL`, and the **fully-qualified
  table name** `gaiadr3.gaia_source` (bare `gaia_source` is unresolved).
- **Gaia uses UPPERCASE TAP params** (`QUERY`/`FORMAT`/`REQUEST`/`LANG`) — unlike
  the Exoplanet Archive's lowercase — and HTTP params are case-sensitive.
- **Gaia rate-limits** repeated queries (HTTP 000) — the client degrades gracefully
  (returns empty), and results are cached 24 h.

---

## Honest scope & assumptions

- **Transients are "recently observed,"** not strictly "new tonight" — ALeRCE's
  list endpoint returns the most recently detected objects; a true novelty filter
  (first-detection-only) would need the alert stream.
- **Exoplanet counts** use `default_flag = 1` (the canonical confirmed set) to
  avoid double-counting.
- **Gaia cone search** is limited to small fields (large radii are slow); we
  default to a 5-arcmin radius.
- **E.4 TESS light curves** (deferred, below) would add real transit photometry.

---

## E.4 TESS / Kepler light curves — future work (🔴 ambitious, deferred)

The plan flags TESS as a stretch. It would enable "show me the light curve of
Kepler-22b" — a powerful education feature — via the MAST API. Deferred because:
- MAST's API is more involved (product search + FITS download + light-curve extraction).
- It requires parsing FITS files (an `astropy` dependency) and extracting the
  transit signal.
- Lower marginal value than the other phases for a collision-avoidance tool.

**Path to add it later:** query MAST for a target's TESS/Kepler light-curve product,
download the FITS, extract the PDCSAP flux vs time, and expose
`get_light_curve(target_name)`. The architecture (thin ingest adapter + agent tool)
is established by Phases A–E, so this is a well-scoped addition.

---

## Tests (22 new)

- **mjd_to_iso:** J2000 epoch, zero, overflow.
- **_parse_transient:** fields, unclassified default, missing-field defaults, model
  validation.
- **_normalize_tap_rows:** all 3 TAP formats (list-of-dicts, dict-data-dicts,
  dict-data-positional), length-mismatch skip, edge cases ({}, garbage, None,
  no-columns).
- **models:** Exoplanet, Star validation.
- **live (graceful):** transients, exoplanet count, recent exoplanets, Gaia cone
  search — all degrade gracefully.
- **agent tools:** get_recent_transients, get_exoplanet_stats, get_stars_near.

---

## Next (from the plan)

- **Phase F** — synthesis: unified dashboard (Tonight's Sky transients panel,
  exoplanet counter, Gaia field viewer, solar-system panel, ground-track map,
  imagery, space weather) + space-situation assistant + accessibility narrative.

The data-integration plan (Phases A–E) is now **complete** — OrbitWarden ingests
live data from NASA, ESA, NOAA, the Space Surveillance Network, ZTF, the Exoplanet
Archive, and Gaia. Phase F makes it all visible.

---

*Implemented 2026-07-27. Run: `pytest tests/test_astronomy.py tests/test_agent_tools.py`.*
