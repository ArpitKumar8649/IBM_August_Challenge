# Visualization, UX & Making Space Accessible — Detailed Implementation Plan

> A detailed, in-depth implementation plan for **Section 5** of
> [`ENHANCEMENTS.md`](ENHANCEMENTS.md) — *Visualization, UX & Making Space
> Accessible*. Organized as **Phases 5–7**.
>
> **Framing:** this is a real project, not a demo. Every visualization here is
> *functional* — driven by real data from the engine, genuinely interactive, and
> accessible. Nothing is a mockup. The goal is to make OrbitWarden's real
> capabilities *visible and understandable* to operators, students, educators,
> journalists, and the public.
>
> The challenge *explicitly* wants to "make space data more accessible to a broader
> audience" and "help the public engage with space." This plan is how we deliver
> that — and score on **Challenge Fit**, **Real-World Impact**, and **Innovation**.

---

## 0. Goals & principles

**The accessibility problem:** OrbitWarden computes a rich space situation —
conjunctions, collision probabilities, maneuvers, space weather, transients,
exoplanets. But raw numbers (a Pc of 6.69e-13, an RSW miss vector, a B-plane
covariance) are meaningless to anyone but a specialist. The challenge is to make
this *understandable* without dumbing it down.

**Principles:**

1. **Real, not mocked.** Every visualization renders real data from the engine.
   The 3D globe shows real orbits from real TLEs. The B-plane plot is generated
   from the actual covariance. "What's passing over me" computes real passes.
2. **Layered depth.** Every view works at two levels: a plain-language surface
   ("a satellite will pass overhead at 9:42 PM, look northwest") and a technical
   depth ("TCA 02:14:33 UTC, miss 3.04 km, Pc 6.7e-13, radial-dominated geometry").
   The user chooses their depth.
3. **Accessible by design.** Keyboard-navigable, screen-reader-friendly,
   color-blind-safe (we already have a validated palette), and — via sonification
   (5.5) — usable by visually-impaired users. Accessibility is a feature, not an
   afterthought.
4. **The visualization serves the insight.** We don't add 3D because it's flashy;
   we add it because a 3D conjunction is *viscerally understandable* in a way a
   table never is. Every visual earns its place.

---

## 1. Current state (what exists)

| Exists | Notes |
|--------|-------|
| SVG ground-track map | `EarthObservationPanel.tsx` — equirectangular ground track, antimeridian-aware |
| Tabbed dashboard | 7 tabs (Mission Control, 3D View, Space Weather, Earth Obs, Discovery, Solar System, Health) |
| RSW geometry bars | In the event detail (radial/in-track/cross-track) |
| Validated color palette | Color-blind-safe (dataviz skill) |
| RAG knowledge base | 18 space-domain chunks — these ARE the explainers for 5.4 |
| All 30 tools as API endpoints | The data layer is complete (`get_bplane` added by 5.2) |

**What's missing (this plan):** the public "what's over me" feature (5.3) and
immersive/sonification (5.5). **Delivered:** 5.1 (CesiumJS 3D globe —
`PHASE5_1_GLOBE_PLAN.md`, phases A–G), 5.2 (B-plane diagram), 5.4 (plain-language
education).

---

# Phase 5 — Technical Visualization (the professional view)

> **Goal:** render OrbitWarden's analysis the way professionals see it — a 3D
> orbital view (5.1) and the canonical B-plane conjunction diagram (5.2). These
> signal real domain mastery and make the analysis viscerally understandable.
>
> **Effort:** 🟡 medium-large (CesiumJS is the biggest lift).

---

### 5.1 CesiumJS 3D globe with live orbits & conjunctions ✅ SHIPPED

> **Status:** delivered in full — backend CZML composer + `GET /api/events/{id}/czml`
> endpoint (46 backend tests), lazy "3D View" tab (Cesium never enters the page's
> critical path), covariance/maneuver toggles, honest offline/error states,
> reduced-motion + keyboard a11y, a CI `web` job, and a manual QA checklist. See
> [`docs/PHASE5_1_GLOBE_PLAN.md`](PHASE5_1_GLOBE_PLAN.md) (phases A–G, all
> delivered) and [`docs/PHASE5_1_QA_CHECKLIST.md`](PHASE5_1_QA_CHECKLIST.md).

**What:** a 3D Earth (CesiumJS) showing the primary's orbit, nearby catalog
objects, conjunction geometry, and the TCA moment — time-dynamic via CZML, with a
timeline slider to scrub to the moment of closest approach.

**Why it matters:** CesiumJS powers NASA Eyes (Eyes on the Earth/Solar System) and
is the standard for space visualization. A 3D conjunction — watching two orbits
converge, then the AI's burn pull them apart — is understandable in a way a table
never is. → **Innovation, Challenge Fit, Technical Execution.**

**Technical design:**

- **Library:** `cesium` (npm, v1.143). CesiumJS needs imagery/terrain:
  - **Decision point:** Cesium Ion (free token, default globe imagery/terrain) vs.
    open imagery (Natural Earth tiles, no token). Ion is easier and higher quality;
    open imagery avoids the token dependency. **Recommend Ion** (free tier is ample)
    with a documented fallback.
- **CZML (Cesium's time-dynamic format):** the key to time-dynamic orbits. A CZML
  document describes entities (satellites) with position sampled over time; Cesium
  interpolates and animates along the timeline.
- **Components:**
  - `web/src/viz/Globe3D.tsx` — a React component wrapping Cesium's `Viewer`.
    Initializes the globe, loads CZML, wires the clock/timeline.
  - `web/src/viz/czml.ts` — a CZML generator: converts orbits (from the ground-track
    / propagation) into CZML entities with sampled positions, orbit paths, and
    conjunction markers.
- **Backend endpoint:** `GET /api/orbits/czml?norad_id=&event_id=` — emits a CZML
  document for the primary + the conjunction secondary over the screening window,
  with the TCA marked. (Alternatively, generate CZML on the frontend from the
  ground-track data; backend is cleaner and reusable.)
- **Conjunction visualization:** at TCA, show both objects, the miss-distance line
  between them, the relative-velocity vector, and a label with the miss/Pc.
- **Maneuver visualization:** show the pre-burn and post-burn orbits diverging;
  the burn vector as an arrow at the burn epoch. "Watch the burn pull them apart."
- **Covariance ellipsoid glyph:** at TCA, render the projected covariance as a
  translucent ellipsoid around the secondary (ties to 5.2).

**Files to create/modify:**
- `web/src/viz/Globe3D.tsx` (new)
- `web/src/viz/czml.ts` (new)
- `web/src/panels/GlobePanel.tsx` (new — a "3D View" tab)
- `api/main.py` — add `/api/orbits/czml`
- `engine/viz/czml.py` (new — backend CZML generation)
- `web/package.json` — add `cesium`
- `web/vite.config.ts` — configure Cesium's static assets (Cesium copies static
  files; Vite needs `vite-plugin-cesium` or manual asset config)

**Implementation steps (all done):**
- [x] Add `cesium` + `vite-plugin-cesium`; get a minimal globe rendering (verify the
  Ion token / imagery works).
- [x] Build `engine/viz/czml.py`: convert a TLE → sampled positions → CZML entity
  with a path. Verify a single orbit animates.
- [x] Add the conjunction secondary + TCA marker. Verify two orbits + the TCA marker.
- [x] Add the `GET /api/events/{id}/czml` endpoint; wire the `GlobePanel` tab
  (the endpoint landed as `/api/events/{id}/czml` — per-event, matching the
  B-plane and maneuver endpoints, rather than the planned `/api/orbits/czml`).
- [x] Add the maneuver visualization (pre/post-burn orbits, with kind-substitution
  transparency).
- [x] Add the covariance ellipsoid glyph (client-side `entity.show` toggle).
- [x] Add the timeline scrubbing to TCA (+ reduced-motion paused-clock default).

**Testing:**
- CZML generation: a TLE produces valid CZML with the expected sample count.
- The globe renders without console errors (manual / Playwright if available).
- The CZML endpoint returns valid CZML (JSON-parseable, has the expected entities).

**Acceptance criteria:**
- [ ] A 3D globe renders the primary's orbit, animating over time.
- [ ] The conjunction secondary and TCA marker are shown.
- [ ] The timeline slider scrubs to TCA.
- [ ] The maneuver visualization shows pre/post-burn orbits diverging.
- [ ] No Ion-token hard dependency (documented fallback works).

**Effort:** ~4-5 days (CesiumJS integration + CZML + the visualizations).

**Risks & mitigations:**
- **Cesium bundle size / Vite asset config** — Cesium is large and needs static
  asset handling. Mitigation: `vite-plugin-cesium`; lazy-load the globe panel.
- **Ion token dependency** — mitigate with open-imagery fallback.
- **CZML complexity** — start with a single orbit, add complexity incrementally.

---

### 5.2 B-plane & covariance-ellipsoid plots 🟢

**What:** render the **B-plane** (the encounter plane perpendicular to the relative
velocity at TCA) with the miss vector and **covariance ellipsoids** — the canonical
conjunction-assessment visualization.

**Why it matters:** this is *the* diagram a conjunction analyst looks at. Showing
it correctly — the miss point, the hard-body radius circle, the 1σ/2σ/3σ covariance
ellipses — signals real domain mastery. → **Technical Execution, Innovation.**

**Technical design:**

- **The B-plane:** the plane perpendicular to the relative-velocity vector at TCA.
  The miss vector projects onto it; the combined covariance projects to a 2D ellipse.
- **We have what we need:** the RSW miss components (`miss_r`, `miss_s`, `miss_w`)
  and the fixed covariance (`engine/covariance.py`). We compute the B-plane basis
  (already in `engine/pc.py` — `_b_plane_basis`) and project the miss + covariance.
- **Component:** `web/src/viz/BPlanePlot.tsx` — an SVG/canvas plot showing:
  - The B-plane axes (ξ, ζ).
  - The origin (nominal predicted miss).
  - The miss point (the actual miss vector projection).
  - The hard-body radius circle (HBR — the "collision" circle).
  - The covariance ellipses (1σ, 2σ, 3σ) — the uncertainty.
  - A label: miss distance, Pc, whether the miss point is inside the HBR.
- **Backend endpoint:** `GET /api/events/{id}/bplane` — returns the B-plane
  projection data: miss point (ξ, ζ), covariance ellipse parameters (eigenvalues,
  eigenvectors), HBR, Pc.

**Files to create/modify:**
- `web/src/viz/BPlanePlot.tsx` (new)
- `engine/viz/bplane.py` (new — B-plane projection computation)
- `api/main.py` — add `/api/events/{id}/bplane`
- `web/src/pages/Dashboard.tsx` — add the B-plane plot to the event detail

**Implementation steps:**
1. `engine/viz/bplane.py`: project the RSW miss + covariance onto the B-plane;
   compute the ellipse eigenvalues/eigenvectors. Test against a known case.
2. `/api/events/{id}/bplane` endpoint.
3. `BPlanePlot.tsx`: render the axes, miss point, HBR circle, covariance ellipses.
4. Wire into the event detail (next to the RSW bars).

**Testing:**
- B-plane projection: a known miss vector projects to the expected (ξ, ζ).
- Covariance ellipse: eigenvalues/eigenvectors are correct for a known covariance.
- The plot renders the miss point inside/outside the HBR correctly.

**Acceptance criteria:**
- [x] The B-plane plot shows the miss point, HBR circle, and 1σ/2σ/3σ ellipses.
- [x] The plot is generated from the real engine covariance (not hardcoded).
- [x] It correctly indicates whether the miss is inside the HBR.

**Delivered** (`engine/viz/bplane.py`, `api/main.py`, `web/src/viz/BPlanePlot.tsx`,
wired at `web/src/pages/Dashboard.tsx`), beyond the plan above:

- **The figure and the number cannot disagree.** `engine/viz/bplane.py` imports the
  sigmas from `engine.pc` rather than restating them, and recomputes Pc *from the
  projected quantities it draws*. Tests pin that recomputation to
  `engine.pc.collision_probability` and
  `engine.covariance.collision_probability_general` at rel=1e-12, so a drawing that
  disagreed with the probability beside it would fail the suite.
- **Covariance realism** (Foster/Hall `Σ_real = k·Σ`, default k=2) as a second
  contour and a second Pc — `?realism_factor=` on the endpoint.
- **Honest dynamic range.** The quantities span 2–3 orders of magnitude in both
  directions, so the figure never rescales a feature to look bigger than it is.
  Instead: a scale toggle offered *only* when the first framing genuinely crushes a
  feature, direction-aware (`zoom σ` when the miss dwarfs the covariance, `zoom HBR`
  when the covariance dwarfs the cross-section); three unresolvable contours
  collapsed into one labelled region; an HBR circle drawn only when it is larger
  than the marks it contains, and annotated otherwise; a contour that encloses the
  whole frame dropped from the figure *and* the legend rather than drawn invisibly;
  and an off-scale miss shown as a bearing chevron with a corner callout instead of
  a marker clamped to the edge (which would misreport its position).
- **Accessibility, per the dataviz procedure.** Validated ordinal ramp
  (`#9ec5f4/#5598e7/#256abf` — ALL CHECKS PASS under
  `validate_palette.js --ordinal --mode dark`); a legend always present, listing only
  what is actually drawn; direct labels on scrim+halo so they survive crossing a
  contour; every mark focusable with an ARIA label carrying the same numbers hover
  shows; `<title>`/`<desc>` summarising the encounter in prose; a
  `forced-colors: active` fallback that re-encodes the σ levels as dash patterns,
  because high-contrast mode collapses every hue to one system colour; and a
  **table view** with every quantity, so no value is reachable only by pointer.
- **Verified by rasterizing.** `web/scripts/render-bplane.tsx` (dev-only) SSRs the
  figure to standalone SVG for five payload shapes — far, far/zoom σ, close, HBR
  collision, HBR/zoom — which is how the label collisions, the crescent artifact at
  the origin, and the misleading edge marker were found and fixed.

**Effort:** ~2 days.

**Risks & mitigations:**
- **Ellipse rendering math** — the covariance ellipse from eigenvalues/eigenvectors
  is standard but fiddly. Mitigation: test against a known covariance first.

---

# Phase 6 — Public Accessibility & Engagement

> **Goal:** make OrbitWarden accessible to the *public* — "what's passing over me?"
> (5.3) and plain-language education (5.4). This is the heart of "make space
> accessible to a broader audience."
>
> **Effort:** 🟡 medium.

---

### 5.3 "What's passing over me?" public engagement feature 🟢

**What:** a public-facing feature: enter your location (or geolocate), see
satellites passing overhead *tonight*, with plain-language explanations. "That
bright dot at 9:42 PM, moving northwest — that's the ISS."

**Why it matters:** this directly serves "help the public engage with space." It's
accessible, delightful, and shareable — the feature that makes a non-specialist
*care*. → **Challenge Fit, Real-World Impact.**

**Technical design:**

- **Visible-pass computation:** for each catalog object, propagate over the night
  and find when it's:
  - Above the observer's horizon (elevation > ~10° for practical visibility).
  - **Lit by the Sun while the observer is in darkness** (a satellite is visually
    visible when it's in sunlight but the ground is dark — the geometry of a
    "satellite flare"). This is the key physics: compute the satellite's
  sun-angle and the observer's local solar time.
- **Backend endpoint:** `GET /api/passes?lat=&lon=&date=&limit=` — computes visible
  passes for a location: each pass has start/max/end times, direction (azimuth),
  max elevation, magnitude (brightness estimate), and the object name.
- **Component:** `web/src/panels/SkyViewPanel.tsx` — a "Tonight's Sky" view:
  - Location input (manual lat/lon or browser geolocation).
  - A list of tonight's visible passes: time, direction, brightness, name.
  - A simple sky chart (polar plot: horizon circle, N/S/E/W, the pass arc).
  - Plain-language: "Look northwest at 9:42 PM — the ISS will cross overhead."
- **Reuse:** the SGP4 ground-track computation (`engine/ground_track.py`) + the
  sub-satellite-point math. Add the observer-horizon + sun-angle computation.

**Files to create/modify:**
- `engine/viz/passes.py` (new — visible-pass computation)
- `api/main.py` — add `/api/passes`
- `web/src/panels/SkyViewPanel.tsx` (new — a "Tonight's Sky" tab)
- `web/src/viz/SkyChart.tsx` (new — polar sky chart)

**Implementation steps:**
1. `engine/viz/passes.py`: compute observer horizon + satellite elevation over time;
   find passes above the elevation threshold; compute sun-angle for visibility.
   Test: the ISS produces visible passes for a known location.
2. `/api/passes` endpoint.
3. `SkyViewPanel.tsx`: location input + pass list.
4. `SkyChart.tsx`: polar sky chart with the pass arc.
5. Plain-language labels.

**Testing:**
- Visible-pass computation: the ISS produces passes for a known location/night.
- Sun-angle visibility: a pass in full daylight is excluded; a twilight pass included.
- The sky chart renders the pass arc correctly.

**Acceptance criteria:**
- [ ] Enter a location → see tonight's visible satellites with times/directions.
- [ ] The ISS appears with a plain-language "look here" instruction.
- [ ] The sky chart shows the pass arc.
- [ ] Geolocation works (browser API).

**Effort:** ~3 days.

**Risks & mitigations:**
- **Visibility physics** (sun-angle, twilight) is subtle. Mitigation: start with
  "above horizon" passes, add sun-angle visibility as a refinement.
- **Magnitude estimation** is approximate. Mitigation: label as "estimated
  brightness."

---

### 5.4 Plain-language data storytelling & education modules 🟢

**What:** layer **plain-language explanations** and **education modules** over every
technical output. "What is a conjunction, and why should I care?" Contextual
explainers, a "Learn" tab, glossary tooltips, an educator's guide.

**Why it matters:** "translate complex space data into clear insights" is a core
challenge goal. This makes OrbitWarden usable by students, educators, and
journalists — "a PhD's tool that a 10th-grader can understand." → **Challenge Fit,
Real-World Impact.**

**Technical design:**

- **Key insight:** we already built the explainers — the **RAG knowledge base**
  (`agent/knowledge.py`, 18 chunks) covers conjunction assessment, CDM/ODM,
  collision probability, drag, etc. Wire these into contextual help.
- **Components:**
  - `web/src/components/Explainer.tsx` — a tooltip/popover that, given a technical
    term (e.g. "collision probability"), shows a plain-language explanation (from
    the knowledge base). Attach to technical terms throughout the UI.
  - `web/src/panels/LearnPanel.tsx` — a "Learn" tab with education modules:
    "What is a conjunction?", "Why does space weather matter?", "What is a collision
    probability?", "What is the Kessler syndrome?". Each module: plain-language
    explanation + a relevant visualization.
  - **Glossary tooltips** — hover any technical term (TCA, Pc, RSW, B-plane, Kp) for
    a definition.
  - **Educator's guide** — a printable guide for teachers (a markdown/PDF page).
- **Backend endpoint:** `GET /api/knowledge?query=` already exists (the RAG tool).
  Add `GET /api/glossary` for term definitions (or serve from a static glossary).
- **Pattern:** every technical output gets a "?" that opens the relevant explainer.
  The user can always go deeper.

**Files to create/modify:**
- `web/src/components/Explainer.tsx` (new)
- `web/src/panels/LearnPanel.tsx` (new — a "Learn" tab)
- `web/src/data/glossary.ts` (new — term definitions)
- `docs/EDUCATOR_GUIDE.md` (new — printable educator's guide)
- `web/src/pages/Dashboard.tsx` — add the Learn tab + Explainer tooltips

**Implementation steps:**
1. `glossary.ts`: define the key terms (TCA, Pc, RSW, B-plane, Kp, conjunction,
   CDM, etc.) in plain language.
2. `Explainer.tsx`: a reusable tooltip that shows a glossary definition.
3. Attach Explainers to technical terms throughout the dashboard.
4. `LearnPanel.tsx`: education modules (reuse the knowledge-base content).
5. `EDUCATOR_GUIDE.md`: a printable guide for teachers.

**Testing:**
- Glossary terms render correctly.
- Explainer tooltips open on hover/click.
- The Learn tab renders all modules.

**Acceptance criteria:**
- [x] Every technical term in the UI has a plain-language explainer. *(glossary.ts + Explainer.tsx, wired through Dashboard + BPlanePlot)*
- [x] A "Learn" tab with education modules exists. *(LearnPanel.tsx — 5 modules, plain-first with "go deeper" toggle)*
- [x] An educator's guide is available. *(docs/EDUCATOR_GUIDE.md — concepts, 3 classroom activities, glossary)*
- [x] The explanations come from the real knowledge base (not hardcoded). *(every KB chunk now carries a `plain` summary; `GET /api/knowledge/learn` serves plain+body from the same retriever the analyst uses; offline fallback mirrors the KB; a pytest gate fails the build if any chunk lacks a plain summary)*

**Effort:** ~2-3 days.

**Risks & mitigations:**
- **Content quality** — the plain-language explanations must be accurate *and*
  accessible. Mitigation: reuse the knowledge base (already written and reviewed);
  have a non-specialist review.

---

# Phase 7 — Immersive & Accessibility Polish

> **Goal:** the stretch/immersive layer (5.5 sonification/AR) plus a full
> accessibility (a11y) audit and visual polish. This makes OrbitWarden accessible
> to *everyone*, including visually-impaired users.
>
> **Effort:** 🟡 medium (sonification/AR are optional stretch).

---

### 5.5 Sonification / AR / immersive (stretch) 🔴

**What:** explore **sonification** (hear the orbits) and **AR/VR** (walk around the
conjunction). Sonification maps orbital parameters to sound; AR overlays where to
look to see a satellite.

**Why it matters:** novel, memorable, and **accessibility-forward** — sonification
makes OrbitWarden usable by visually-impaired users (you can *hear* a conjunction
approaching). → **Innovation, Challenge Fit, Accessibility.**

**Technical design:**

- **Sonification (the accessible, high-value part):**
  - Map orbital parameters to sound: pitch = altitude, rhythm/tempo = orbital
    period, a rising "ping" as a conjunction approaches (pitch rises as miss
    distance decreases), a chord at TCA.
  - Use the **Web Audio API** (no library needed) — oscillators + gain envelopes.
  - Component: `web/src/viz/Sonification.tsx` — a "listen to this conjunction"
    button that sonifies the approach.
  - **Accessibility value:** a visually-impaired user can hear the conjunction
    approaching (pitch rising) and the maneuver (the pitch dropping as the miss
    increases). This is a genuine accessibility feature, not a gimmick.
- **AR (stretch, mobile):** an AR overlay (WebXR or a mobile framework) showing
  where to look to see a satellite passing overhead. Ties to 5.3 ("what's over
  me"). High effort, mobile-only.
- **VR (stretch):** a WebXR scene where you "stand" in orbit and watch the
  conjunction. High effort.

**Files to create/modify:**
- `web/src/viz/Sonification.tsx` (new — Web Audio sonification)
- `web/src/pages/Dashboard.tsx` — add a "listen" button to the event detail
- (stretch) `web/src/viz/ARView.tsx`, `web/src/viz/VRScene.tsx`

**Implementation steps:**
1. `Sonification.tsx`: Web Audio API — map miss-distance-over-time to pitch.
   Test: a conjunction produces a rising-then-falling pitch.
2. Add a "listen" button to the event detail.
3. (stretch) AR overlay for "what's over me."
4. (stretch) VR scene.

**Testing:**
- Sonification: a conjunction produces the expected pitch contour (manual / unit
  test the mapping function).
- (stretch) AR/VR render without errors.

**Acceptance criteria:**
- [ ] A conjunction can be sonified (rising pitch as it approaches).
- [ ] The sonification is usable by a visually-impaired user (tested with a screen
  reader / eyes closed).
- [ ] (stretch) AR/VR render.

**Effort:** ~2 days (sonification) + ~3-5 days (AR/VR, stretch).

**Risks & mitigations:**
- **Sonification design** — mapping data to sound is a design challenge. Mitigation:
  start simple (pitch = miss distance), iterate. Reference NASA's sonification
  projects.
- **AR/VR effort** — these are high-effort stretches. Mitigation: sonification first
  (high value, low effort); AR/VR only if time allows.

---

### 7.x Accessibility (a11y) audit & visual polish

**What:** a full accessibility pass — keyboard navigation, screen-reader support,
ARIA labels, color-blind safety, and visual polish across all panels.

**Why it matters:** "making space accessible" includes accessibility for disabled
users. A real product is accessible. → **Real-World Impact, Challenge Fit.**

**Technical design:**
- **Keyboard navigation:** every interactive element is keyboard-reachable; the
  globe, charts, and tabs are operable without a mouse.
- **Screen-reader support:** ARIA labels on all charts/visualizations ("B-plane
  plot: miss 3.04 km, outside the hard-body radius"); the sonification (5.5) as an
  alternative to visual charts.
- **Color-blind safety:** we already have a validated palette; audit all charts use
  it (no red/green-only encoding).
- **Visual polish:** consistent spacing, typography (Great Vibes script for
  headings, Space Grotesk for UI, JetBrains Mono for data), loading/empty states.

**Files to modify:** all panels + components (audit pass).

**Implementation steps:**
1. Keyboard navigation audit (tab through every panel).
2. ARIA labels on all visualizations.
3. Color-blind audit (verify the palette is used everywhere).
4. Loading/empty states for every panel.
5. Visual polish pass.

**Testing:**
- Keyboard navigation: tab through every panel without a mouse.
- Screen reader: a screen reader announces all visualizations.
- Color-blind: a color-blind simulator shows no information loss.

**Acceptance criteria:**
- [ ] Every panel is keyboard-navigable.
- [ ] All visualizations have ARIA labels / text alternatives.
- [ ] No information is conveyed by color alone.
- [ ] Every panel has loading/empty states.

**Effort:** ~2-3 days.

---

# 8. Cross-cutting concerns

### Design system
- **Typography:** Great Vibes (script headings), Space Grotesk (UI), JetBrains Mono
  (data). Already established.
- **Color:** the validated color-blind-safe palette. Use consistently.
- **Components:** reusable `Panel`, `Explainer`, chart components. Consistent
  spacing, borders, loading/empty states.

### Accessibility standards
- **WCAG 2.1 AA** as the target: keyboard, screen reader, color contrast, color-blind.
- **Sonification** as a first-class alternative to visual charts.

### Data flow
- All visualizations consume the existing API endpoints (30 tools). New endpoints
  (`/api/orbits/czml`, `/api/events/{id}/bplane` ✅, `/api/passes`, `/api/glossary`)
  follow the same pattern.
- The RAG knowledge base feeds the education/explainer content (5.4).

---

# 9. Roadmap & effort summary

| Phase | Contents | Effort | Priority |
|-------|----------|--------|----------|
| **Phase 5** | 5.1 CesiumJS 3D globe + 5.2 B-plane plots | ~6-7 days | High (the professional view) |
| **Phase 6** | 5.3 "What's over me?" + 5.4 education | ~5-6 days | High (public accessibility) |
| **Phase 7** | 5.5 sonification/AR (stretch) + a11y audit + polish | ~4-8 days | Medium (immersive + accessibility) |

**Recommended order:** Phase 5 (the technical visualizations that make the analysis
visible) → Phase 6 (the public accessibility that makes it matter) → Phase 7
(immersive + accessibility polish).

**Quick wins within these phases** (do first):
- 5.2 B-plane plot (~2 days) — the professional diagram, generated from the real engine.
- 5.4 Explainers + glossary (~2 days) — reuse the knowledge base.
- 5.5 Sonification (~2 days) — high value, low effort, accessibility-forward.

---

# 10. Decision points

1. **Cesium Ion token vs. open imagery** (5.1) — recommend Ion (free tier) with
   open-imagery fallback.
2. **AR/VR scope** (5.5) — sonification first (high value); AR/VR only if time allows.
3. **Education content review** (5.4) — have a non-specialist review the
   plain-language explanations.

---

## The point

This plan makes OrbitWarden's real capabilities *visible and understandable* — to
operators (the 3D globe, the B-plane diagram), to the public ("what's passing over
me?"), to students and educators (the Learn tab, the explainers), and to everyone
(sonification, accessibility). Every visualization is functional, driven by real
data, and accessible. That is how you make space accessible — not with a mockup,
but with a real tool that anyone can use and understand.

---

*Prepared 2026-07-27. This is the detailed implementation plan for Section 5 of
ENHANCEMENTS.md, organized as Phases 5–7.*
