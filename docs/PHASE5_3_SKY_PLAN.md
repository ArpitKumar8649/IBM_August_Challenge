# 5.3 — "What's passing over me?" (Tonight's Sky) — plan of record

> **Status: ✅ COMPLETE** — engine, API, agent tool, dashboard tab, tests, and docs all delivered (phases A–F). The only remaining gate is the human-run manual QA checklist (§QA), as this workspace has no browser.

The one 5.x feature that serves the challenge's **accessibility** criterion ("help the public engage with space") — the public counterpart to the operator-facing 5.1 globe and 5.2 B-plane. A non-specialist can look up, learn *what* that bright dot is, and *when* to be outside to see it.

---

## 1. What we built

Enter a location (preset cities — Bengaluru, Delhi, Mumbai, New York, London, Tokyo — browser geolocation, or manual coordinates) and see which **famous satellites** (ISS, Tiangong, Hubble, and the bright Earth-observation fleet) pass overhead **tonight**: start/apex/end times, compass directions, brightness estimate, and a plain-language *"Look northwest (312°) at 9:42 PM — the ISS will pass high overhead."* drawn on a polar sky chart.

**Design decisions (pinned by the operator, not guessed):**
- **Bright & famous catalog only** — a curated 15-object allow-list, not the 40 k-object catalog. Every row is a "wow, look up now" moment; compute is trivial.
- **Fresh TLEs, no fallback** — the endpoint always fetches current CelesTrak elements (24 h disk cache). If CelesTrak is unreachable it answers `available: false` with an honest note. Predicting "look up at 9:42 PM" from week-old TLEs would send a family outside at the wrong hour — worse than "try again later."
- **Agent tool: yes** — `get_visible_passes` is exposed to the analyst (unlike the deliberately-withheld CZML tool), so the chat answers "when can I see the ISS from Bengaluru tonight?" with engine-computed times.
- **The engine is the only source of numbers** — the frontend renders the response verbatim; the sample mirror is clearly labelled SAMPLE.

## 2. The physics

A satellite is *visually* visible only when **all three** hold at once:

1. **Above the horizon** — elevation > 10° (default threshold).
2. **The observer is dark** — the Sun is more than 6° below the observer's horizon (nautical twilight, the standard satellite-watching threshold).
3. **The satellite is sunlit** — it's in sunlight while the ground is dark (cylindrical Earth-shadow test, mirroring `engine/ingest/horizons.py::in_earth_shadow`). This is the key "satellite flare" geometry.

Per pass we also derive: max elevation, azimuth at start/apex/end (16-point compass), range at apex, and a **brightness estimate** from the standard satellite-magnitude formula — a physical Lambertian-sphere phase function `M = M0 − 15.75 + 2.5·log10(r²) − 2.5·log10((1+cosβ)/2)` with published per-object standard magnitudes (ISS ≈ −1.8 → typically the brightest thing in the sky after the Moon and Venus). Every estimate is labelled as such in the UI.

The night window comes from an analytical Sun position (Astronomical Almanac/NOAA low-precision, ~0.01°, no network); the per-sample condition checks do the rest.

## 3. Reuse

| Asset | Where | Role |
|---|---|---|
| Vectorized SGP4 (`sgp4_array`, NaN-masked) + cached `Satrec` | `engine/propagate.py` | propagate the curated set over the night in ~0.5 s |
| TEME→ECEF rotation (`_julian_date`, `_gmst_rad`, `teme_to_latlon`) | `engine/ingest/open_notify.py` | the frame flip the topocentric math needs |
| Cylindrical Earth-shadow test (concept) | `engine/ingest/horizons.py` | the "satellite is lit" condition |
| TLE catalog with 24 h disk cache (`fetch_groups`) | `engine/ingest/celestrak.py` | fresh TLEs |
| Tool/envelope conventions (`{available, note}`, `ToolContext`) | `agent/tools.py` | the API shape |
| UI kit: `Explainer`/glossary, chips, lazy tabs, `fetchRaw` + sample fallback, honest-error convention | `web/src/*` | the panel inherits 5.4's plain-language + the 5.1 error-honesty |

## 4. Files

| Change | File |
|---|---|
| **NEW** — the pass engine | `engine/viz/passes.py` |
| Passes models (`VisiblePass`, `PassesResponse`) | `engine/models.py` |
| `get_visible_passes` tool (+ `TOOL_NAMES` + `TOOL_SCHEMAS`) | `agent/tools.py` |
| `GET /api/passes` | `api/main.py` |
| **NEW** — tests (ENU math, sunlit, magnitude, segmentation, dark span, deterministic ISS pass, honesty guards) | `tests/test_passes.py` |
| API tests (envelope, fetch-failure honesty, bad lat) | `tests/test_api.py` |
| Types + client (`fetchPasses`) + sample mirror (`samplePasses`) | `web/src/types.ts`, `web/src/lib/api.ts`, `web/src/data/sample.ts` |
| **NEW** — polar sky chart + Tonight's Sky tab | `web/src/viz/SkyChart.tsx`, `web/src/panels/SkyViewPanel.tsx` |
| Tab wiring + 5 glossary explainers + styles | `web/src/pages/Dashboard.tsx`, `web/src/data/glossary.ts`, `web/src/styles/dashboard.css` |
| **NEW** — vitest specs (9) | `web/src/lib/api.sky.test.tsx` |
| Docs sweep | this plan, `docs/VISUALIZATION_PLAN.md`, `README.md`, `docs/BOB_LOG.md` |

## 5. Phases delivered

- **A — Engine & models:** topocentric ENU (elevation/azimuth/range), analytical Sun, sunlit mask, pass segmentation with sub-minute gap merging, brightness formula + plain-language bands, dark-span (night-window) computation, curated famous catalog, `compute_passes_for_location` with honesty guards (date outside reliable window → `available: false` + note). Tests: **40/40** (pure-math + a *deterministic* ISS-pass construction — the spec's headline test that doesn't flake).
- **B — API & agent:** `get_visible_passes` (fresh fetch, no fallback) + `GET /api/passes` + analyst tool registration.
- **C — Frontend:** `SkyChart` (polar, shape-distinct markers, `role="img"`), `SkyViewPanel` (location controls, summary strip, pass list, chart, explainers, honest error/empty/SAMPLE states), Dashboard tab.
- **D — Hardening:** layered honesty (reachable-engine `available:false` shown verbatim, only unreachable → sample), geolocation error handling, a11y (labels, aria-pressed, keyboard inputs), responsive grid.
- **E — Tests & gates:** 9 vitest specs; vitest include widened to `.tsx`; Cesium-asset build gate still green.
- **F — Docs:** this plan, VISUALIZATION_PLAN §5.3 ✅ SHIPPED + acceptance criteria ticked, README bullet, BOB_LOG entry.

## 6. Definition of Done

- [x] `GET /api/passes?lat&lon&date&limit` returns tonight's visible passes for a location.
- [x] The ISS produces a visible pass for a constructed known geometry (deterministic test).
- [x] A pass in full daylight is excluded; a dark-sky sunlit pass is included.
- [x] Brightness is an estimate, labelled as such; magnitude ordering is sane (ISS brightest).
- [x] No stale-TLE fallback: CelesTrak failure answers honestly.
- [x] Sky chart renders the pass arc; markers are shape-distinct (not colour-only).
- [x] Geolocation + manual coordinates + presets all work.
- [x] Explainers on every technical term; plain language throughout.
- [x] Backend 40/40 (passes + API), vitest 28/28 (19 + 9), `tsc`+vite build clean, Cesium gate green.

## 7. Manual QA checklist (human, with a browser)

| # | Check | Pass |
|---|---|---|
| 1 | Open **Tonight's Sky** → Bengaluru preselects; LIVE chip when the API is up | ☐ |
| 2 | A pass list appears: times, directions, brightness, "look" instruction | ☐ |
| 3 | The ISS row is flagged **brightest**; its blurb reads correctly | ☐ |
| 4 | Click a pass → the sky chart draws its arc with start/apex/end markers | ☐ |
| 5 | Click **Delhi / New York / London / Tokyo** → refetches for that location | ☐ |
| 6 | **Use my location** → prompts for permission; grant/deny both behave | ☐ |
| 7 | Manual lat/lon + **check the sky**; a bogus value shows the validation note | ☐ |
| 8 | Kill the backend → SAMPLE chip appears with sample passes (clearly labelled) | ☐ |
| 9 | Restart backend, click a preset → back to LIVE | ☐ |
| 10 | Restart backend with no network (CelesTrak down) → honest error card with the engine's note + try-again | ☐ |
| 11 | A location with no passes (e.g. polar summer) → "The sky is quiet tonight" | ☐ |
| 12 | Keyboard: tab through presets/inputs; chart has an accessible label | ☐ |
| 13 | Narrow the window (<900 px) → list and chart stack | ☐ |
| 14 | Every `?` explainer (pass, elevation, azimuth, magnitude, twilight) opens | ☐ |

## 8. Traceability

- Spec: `docs/VISUALIZATION_PLAN.md` §5.3 (acceptance criteria ticked).
- Physics: three-condition visibility + Lambertian magnitude, documented in `engine/viz/passes.py`.
- The one genuinely subtle design finding: a 400 km satellite's horizon is only ~21° of arc from its sub-point — "observer 25° away" is below the horizon, so real visible passes are low passes near the terminator with a sunlit satellite over a dark sub-point. The deterministic test encodes exactly that geometry.
