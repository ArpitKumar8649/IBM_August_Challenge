# Phase 5.1 — CesiumJS 3D Globe: Frontend Completion & Phase-Wise Final Polish

> Status: **COMPLETE — all phases A–G delivered (Aug 8, 2026).** Backend
> (engine/viz/czml.py, the `/api/events/{id}/czml` endpoint, 46 passing tests)
> plus the full frontend — lazy "3D View" tab, CZML scene renderer, panel state
> machine, hardening (reduced-motion, a11y), the `web` CI job, a manual QA
> checklist, and the Phase G polish sweep. The one open gate is the
> **human-run manual QA checklist** (`docs/PHASE5_1_QA_CHECKLIST.md`) — the dev
> workspace has no browser.
>
> Companion docs: [`VISUALIZATION_PLAN.md`](VISUALIZATION_PLAN.md) §5.1 (feature
> spec + acceptance criteria), [`ENHANCEMENTS.md`](ENHANCEMENTS.md) §5.1.

---

## 0. North-star principles (non-negotiable)

1. **The engine is the only source of numbers — including in 3D.** CZML stays
   server-composed (`GET /api/events/{id}/czml`). The frontend *feeds* that
   document to Cesium and *never computes, re-derives, or fabricates* orbit
   geometry. Concretely: the React layer treats the CZML `document` field as
   **opaque JSON** — it reads the response *envelope* (`tca`, `maneuver_kind`,
   `secondary_norad`) for UI, and hands the document to `CzmlDataSource` whole.
   No coordinate parsing, no client-side orbit math, ever.
2. **No fake data in the globe.** Unlike the 2D panels, there is **no sample
   CZML fallback**: a fabricated orbit would be a fake number, which the
   project's validation philosophy forbids. Offline ⇒ an honest, beautiful
   empty state with a retry, never a mocked scene.
3. **Content toggles refetch; presentation toggles are client-side.** Changing
   *what is computed* (maneuver kind, window width) ⇒ refetch CZML from the
   engine. Changing *what is shown* (covariance ellipsoid on/off) ⇒ flip
   `entity.show` in the loaded data source. This keeps the engine authoritative
   and toggles instant.
4. **Never blank, never console-only.** Every failure mode has a visible,
   readable state (loading / error / offline / empty) with an action (retry).
5. **Cesium stays out of the critical path.** The globe is lazy-loaded on both
   axes: `React.lazy` for the panel (the project currently has **zero**
   `React.lazy`/`Suspense` usage — this introduces the pattern) and dynamic
   `import('cesium')` inside `Globe3D` (already the existing pattern). The
   `~3 MB` Cesium chunk must never ship to users who never open the tab.
6. **Accessible and consistent.** Keyboard-focusable toolbar, ARIA labels, the
   project's validated color-blind-safe palette (reuse the rgba constants the
   backend emits in CZML for the legend swatches), and the existing panel CSS
   conventions (`panel`, `eyebrow`, `mono`, chips).

---

## 1. Current-state audit (verified this session)

| Layer | File | State |
|-------|------|-------|
| CZML generator (orbits, TCA points/miss-line/vel-arrow, covariance ellipsoid, maneuver track, clock) | `engine/viz/czml.py` | ✅ complete |
| Scene composer | `agent/tools.py::get_conjunction_czml` | ✅ complete |
| Endpoint `GET /api/events/{id}/czml?maneuver_kind=&window_min=` | `api/main.py` | ✅ complete |
| Unit + endpoint tests | `tests/test_czml.py`, `tests/test_api.py` | ✅ **46 passed** |
| deps `cesium@1.143` + `vite-plugin-cesium` | `web/package.json` | ✅ |
| Vite plugin | `web/vite.config.ts` | ✅ |
| Cesium widgets CSS | `web/src/main.tsx` | ✅ |
| `Globe3D.tsx` Viewer wrapper (Ion token / OSM no-token fallback, `requestRenderMode`) | `web/src/viz/Globe3D.tsx` | 🔶 **renders an empty globe only — no CZML loading, no props beyond `loading`** |
| CZML fetch + types | `web/src/lib/api.ts`, `web/src/types.ts` | ❌ none (`types.ts` has no CZML type) |
| `GlobePanel.tsx` ("3D View" tab) | — | ❌ missing |
| Tab wiring / lazy-load | `web/src/pages/Dashboard.tsx` | ❌ missing — `Globe3D` is imported nowhere (dead code; the 242 kB production bundle contains no Cesium chunk) |
| Maneuver toggle, covariance toggle, scrub-to-TCA UI | — | ❌ missing |

**Frontend build today:** `tsc && vite build` passes, but only 55 modules /
242 kB — the globe is verifiably dead code until wired.

---

## 2. Architecture & data flow

```
Dashboard (tab 'globe')
  └─ <GlobePanel events={events} />            // new panel, React.lazy-wrapped
       ├─ state: selectedEventId, maneuverKind ('none'|kind), showCovariance, windowMin, status
       ├─ fetchConjunctionCzml(eventId, kind, windowMin)   // api.ts, cached + AbortController
       ├─ <Globe3D czml={doc} tca={iso} … />   // imperative Cesium wrapper
       │    ├─ viewer.dataSources.load(CzmlDataSource.load(doc))
       │    ├─ clock ← document clock (currentTime already = TCA), timeline enabled
       │    ├─ jump-to-TCA: clock.currentTime = JulianDate.fromIso8601(tca); flyToBoundingSphere(tca points)
       │    └─ covariance toggle: entities.getById('covariance-ellipsoid').show = …
       └─ toolbar: event select · kind chips · covariance switch · window slider · TCA button · fullscreen
```

**CZML response envelope (already returned by the backend — the frontend's only
parsed surface):**

```ts
interface ConjunctionCzmlResponse {
  available: boolean
  event_id: number
  primary: string
  secondary: string
  secondary_norad: number
  tca: string                    // ISO with Z — the only field the UI needs for clock/camera
  maneuver_kind: string | null   // may differ from requested (curated kinds collide)
  note?: string
  document: Record<string, unknown>[]   // opaque; handed to Cesium whole
}
```

**Known entity ids in the document** (from `engine/viz/czml.py`) — the only
ids the frontend ever references for show/hide:
`orbit-primary`, `orbit-secondary`, `tca-primary`, `tca-secondary`,
`tca-miss-line`, `tca-vel-vector`, `covariance-ellipsoid`, `maneuver-track`.

**Cache key:** `"${eventId}|${kind}|${windowMin}"` → `{ doc, tca, usedKind }`.
A small `Map` in `api.ts` (module-scope) + `AbortController` per request +
a monotonically increasing request id to discard stale resolutions (a fast
toggle sequence must not let an old response clobber a new one).

---

## 3. The plan, phase by phase

### Phase A — Plumbing: types + API client (0.5 d) ✅ DELIVERED

**`web/src/types.ts`** — add (under a `// 5.1 CZML — 3D globe` section):

```ts
export interface ConjunctionCzml {
  available: boolean
  event_id: number
  primary: string
  secondary: string
  secondary_norad: number
  tca: string
  maneuver_kind: string | null
  note?: string
  document: Array<Record<string, unknown>>
}
export type ManeuverKind = 'cheapest-safe' | 'nominal' | 'conservative'
```

**`web/src/lib/api.ts`** — add:

```ts
export async function fetchConjunctionCzml(
  eventId: number,
  opts?: { maneuverKind?: ManeuverKind | 'none'; windowMin?: number },
): Promise<ConjunctionCzml | null>   // null ⇒ backend unavailable (offline state)
```

- Uses `fetchRaw`-style timeout (8 s default; the CZML endpoint can take ~1–3 s
  computing the maneuver track) with a **module-scope cache** keyed as above,
  plus `AbortSignal` plumbing so the panel can cancel stale requests.
- **No sample fallback** (principle 2). `null` → offline empty state.
- `ManeuverKind | 'none'` maps to the query param (omit when `'none'`).**Exit:** `tsc` clean; a tiny vitest unit test (see Phase F) pins the URL builder + cache behavior with a stubbed `fetch`.

**Delivered** (`web/src/types.ts`, `web/src/lib/api.ts`, `web/vitest.config.ts`,
`web/src/lib/api.czml.test.ts`, `web/package.json` + `npm i -D vitest`):

- `ConjunctionCzml` + `ManeuverKind` types (document field typed opaque — the
  UI only ever reads the envelope).
- `fetchConjunctionCzml(eventId, { maneuverKind, windowMin }, signal)` —
  URL built via `URLSearchParams` (engine contract `maneuver_kind` / `window_min`,
  `'none'` omitted), 8 s timeout composed with the caller's abort signal,
  already-aborted callers short-circuit without touching the network, and
  failures are never cached so Retry always re-hits the engine.
- Module-scope cache keyed by the exact URL, capped at 12 entries with
  oldest-first eviction; `clearConjunctionCzmlCache()` exported for refresh UX
  and tests.
- **18 vitest specs green** (URL shape ×5, response handling ×5, cache
  semantics ×5, abort plumbing ×3) — stubbed fetch, node environment,
  separate `vitest.config.ts` so tests never load the Cesium plugin.
  Review-driven hardening: abort short-circuit precedes the cache read (uniform
  semantics), eviction test derives from the exported `CZML_CACHE_MAX`, and
  non-JSON-body / cached-but-aborted specs added.
- Verified: `npm test` 18/18 · `npm run build` (tsc strict + vite) clean.

### Phase B — Globe3D: real CZML loading (1.5 d) ✅ DELIVERED

Rework `web/src/viz/Globe3D.tsx` from "empty viewer" to "scene renderer".
New props (replacing the cosmetic `loading`):

```ts
export interface Globe3DProps {
  czml: Array<Record<string, unknown>> | null   // null ⇒ render nothing
  tca: string | null                            // ISO — clock anchor + camera target
  showCovariance: boolean
  onReady?: (info: { tcaEntities: number }) => void
  onError?: (message: string) => void
  onLoadingChange?: (loading: boolean) => void
}
```

Behaviour (all inside the existing single `useEffect` lifecycle):

1. **Viewer init** — keep the current init exactly (Ion token → Bing + terrain;
   no token → OSM tiles, flat globe; `requestRenderMode: true`; timeline on;
   chrome off).
2. **CZML load** — `viewer.dataSources.add(await CzmlDataSource.load(czml))`,
   keeping a ref to the returned data source for show/hide + cleanup.
   **On failure:** call `onError`, remove the partially loaded source,
   `viewer.entities.removeAll()` — never leave a half-scene.
3. **Clock** — CZML carries its own clock (`interval`, `currentTime = TCA`,
   `multiplier = 60`, `LOOP_STOP`). Configure `viewer.clock` from the loaded
   document (Cesium does this automatically on load; verify and override
   `shouldAnimate = true`, `multiplier = 60`).
4. **Jump to TCA** — expose an imperative handle (`useImperativeHandle`):
   - `viewer.clock.currentTime = JulianDate.fromIso8601(tca)`
   - compute the bounding sphere from the `tca-primary` / `tca-secondary`
     entity positions at TCA (`entity.position.getValue(clock.currentTime)`),
     `viewer.camera.flyToBoundingSphere(sphere, { offset })` so the encounter
     fills the frame.
5. **Covariance toggle** — effect on `showCovariance`: set
   `dataSource.entities.getById('covariance-ellipsoid').show` (no refetch).
6. **Cleanup** — on unmount / prop change: abort in-flight loads (via a
   per-load cancellation token), `viewer.dataSources.remove(dataSource)`,
   then `viewer.destroy()`. Guard every async continuation with a `cancelled`
   flag (existing pattern) so a fast tab-switch never touches a dead viewer.
7. **Resize** — a `ResizeObserver` on the container calling
   `viewer.resize()` (Cesium in a resizable flex/grid container otherwise
   renders off-size).

**Exit:** with the API running, a manually mounted `Globe3D` (dev-only harness
route or the Phase C panel) renders two animated orbits, the TCA markers,
miss line, velocity arrow, and ellipsoid; console has zero errors.

**Delivered** (`web/src/viz/Globe3D.tsx`, `web/src/styles/dashboard.css`):

- Viewer lifecycle: created once per mount (dynamic `import('cesium')`),
  themed to the dashboard (`#05070f` space, sun-lit globe, `requestRenderMode`),
  Ion token → Bing + terrain / no token → OSM (unchanged, verified).
- CZML scene load/swap via `CzmlDataSource.load`, guarded by a monotonic load
  token + `active`/`destroyed` flags so superseded loads and unmount races are
  dropped silently; `viewer.dataSources.remove(prev, true)` tears down the old
  scene (CzmlDataSource has no typed `destroy` in 1.143 — removal is the path).
- Clock anchored from the document's `DataSourceClock` (start/stop/current/
  multiplier clamped 1–600/`clockRange`) with a `tca`-prop fallback; the viewer
  clock's `clockRange` (not `range` — verified against Cesium 1.143 d.ts) is
  copied from the scene.
- Covariance ellipsoid: `entity.show` client-side toggle, applied at load via a
  ref mirror (`showCovarianceRef`) so a mid-load toggle is never clobbered by a
  stale closure (review-driven fix).
- Camera: `flyToEncounter` frames the TCA via `BoundingSphere.fromPoints` over
  `tca-primary`/`tca-secondary`, minimum 30 km range; flies on the first scene
  and re-flies when the encounter changes (`tca` change resets `flewOnce`),
  so event switches re-frame and maneuver-kind toggles keep the view.
- `Globe3DHandle` (`jumpToTca` / `play` / `pause`) via `useImperativeHandle`;
  `ResizeObserver → viewer.resize()` for flex/grid layouts.
- Beautiful themed overlays (`.globe-overlay` loading spinner + pulse text,
  `.globe-error-card` with `role="alert"`, pointer-events-correct), timeline
  strip tinted to match the panel.
- Verified: `npm run build` (tsc strict + vite) clean · `npm test` 18/18.

### Phase C — GlobePanel: the "3D View" tab (1.5 d) ✅ DELIVERED

New `web/src/panels/GlobePanel.tsx` — the only component `Dashboard` imports
for this feature.

**Props:** `events: ScoredConjunction[]` (already fetched in Dashboard; the
panel derives the selector from it, so the selector and the event board
cannot disagree).

**Layout** (new CSS classes in `web/src/styles/dashboard.css`, Phase D):

```
┌─ globe-head: eyebrow "Conjunction · 3D" ─ status chips (LIVE/SAMPLE, spinner) ─┐
│   toolbar row: [event ▾] [maneuver: none|cheapest-safe|nominal|conservative]  │
│                [☑ covariance] [window 10—120 min ◉──] [⏵ TCA] [⛶]           │
├─ globe-body (fills available height, ~56vh, min 380px) ── Globe3D ────────────┤
└─ globe-foot: legend (palette swatches from engine/viz/czml.py constants) +     ┘
   maneuver-kind notice + engine-attribution note
```

**State machine:** `status: 'idle' | 'loading' | 'ready' | 'error' | 'offline'`.
- `loading` — spinner overlay (`panel-loading` class exists).
- `offline` — `fetchConjunctionCzml` returned `null`: explain that the 3D
  scene requires the live engine, offer **Retry** (and hint
  `uvicorn api.main:app`).
- `error` — backend raised (404 event, no feasible burn): show `message` from
  the response envelope/`note`, Retry button.
- `ready` — globe visible; `maneuver_kind` chip reflects **the kind actually
  used** (backend may substitute the best available option when kinds collide)
  and, when different from the requested kind, a small notice:
  "nominal unavailable — showing best available (cheapest-safe)".

**Behaviour contract:**
- Event change / maneuver-kind change / window change ⇒ **refetch** with cache
  lookup first; window slider is debounced (~400 ms) to avoid refetch storms.
- Maneuver kind `'none'` ⇒ fetch without `maneuver_kind`; toggling a kind off
  keeps the current document and just hides `maneuver-track` (instant) — no
  refetch needed unless a *different* kind is picked.
- Covariance switch ⇒ client-side `show` flip (Phase B.5). No refetch.
- **TCA button** ⇒ jump-to-TCA (Phase B.4); also re-fly the camera ("re-center").
- **Fullscreen** button ⇒ `requestFullscreen()` on the globe container
  (ESC-aware; the Cesium `fullscreenButton` is disabled in the viewer chrome).
- The status chip in the top bar keeps saying `SAMPLE DATA` when the events
  list is sampled — the globe offline state must not imply live orbit data.

**Exit:** every control works against the live API; all states are reachable
by killing the backend mid-session.

**Delivered** (`web/src/panels/GlobePanel.tsx`, `web/src/viz/Globe3D.tsx`,
`web/src/styles/dashboard.css`):

- State machine `idle | loading | ready | offline | error`, with a
  request-id + abort stale guard, a mounted-flag on the fetch resolution, and a
  400 ms debounced window slider.
- Content vs presentation split: kind/window/event refetch (module cache
  first); covariance AND maneuver-track visibility flip `entity.show`
  client-side — a curated kind → "no burn" transition skips the refetch
  entirely when a scene is already loaded (review-driven guard: without a
  scene it refetches, and `fetching` is always cleared).
- Toolbar: event selector, segmented burn control, covariance switch
  (`role="switch"`), window slider, TCA / play-pause / fullscreen buttons.
  `playing` is ref-mirrored and re-asserted after every scene load so the
  pause button and the animation never disagree.
- Honest states: loading spinner card, offline card (with `uvicorn` hint),
  error card — all only when no scene exists; a stale-dim + "refreshing…"
  chip during refetch; a "backend unreachable — last scene shown" chip +
  toolbar retry when a refetch fails over a live scene (review-driven).
- Trust layer: substitution notice ("requested nominal — showing best
  available"), storm-flag chip with explainer, engine-palette legend that
  lists only what is drawn, and a footer with secondary/TCA/window provenance.
- Verified: `npm run build` (tsc strict + vite) clean · `npm test` 18/18.

### Phase D — Wiring & styling (0.5 d) ✅ DELIVERED

**`web/src/pages/Dashboard.tsx`:**
- `type Tab` gains `'globe'`; `TABS` gains `{ id: 'globe', label: '3D View' }`
  (after "Mission Control" — the signature view).
- `const GlobePanel = lazy(() => import('../panels/GlobePanel'))` +
  `<Suspense fallback={<div className="panel-loading">loading 3D view…</div>}>`.
- `{tab === 'globe' && <div className="tab-pad globe-pad"><GlobePanel events={events} /></div>}`
- Pass `events` (not just `selected`) so the panel owns its selector.

**`web/src/styles/dashboard.css`** (follow existing conventions —
`.tab-pad`, `.panel`, `.eyebrow`, `.mono`, `.chip`, `--line/--ink-*` vars):
`.globe-pad`, `.globe-panel`, `.globe-head`, `.globe-toolbar`, `.globe-btn`,
`.globe-chip` (segmented kind selector with `.active`), `.globe-slider`
(styled range), `.globe-body` (`height: clamp(380px, 56vh, 720px)`),
`.globe-foot`, `.globe-legend` + `.swatch`, plus the offline/error card
reusing `panel-empty`. Dark-theme Cesium chrome: a `.cesium-viewer-bottom` /
widget-override block so the timeline matches the palette.

**Exit:** `npm run build` green; tab appears, lazy chunk is separate and only
requested on tab open (verify in Network tab of devtools).

**Delivered** (`web/src/pages/Dashboard.tsx`, `web/src/styles/dashboard.css`):

- New `'globe'` tab in the `Tab` union + `TABS` ("3D View", right after Mission
  Control); `GlobePanel` rendered inside `<Suspense>` with a themed spinner
  fallback, passing `events` and `live`.
- `lazy(() => import('../panels/GlobePanel'))` with a shared `preloadGlobe()`
  prefetch (`.catch`-guarded) wired to the tab's `onMouseEnter` and `onFocus` —
  the panel chunk is ready by the time the user opens the tab, while the heavy
  Cesium runtime still only loads on actual globe mount.
- Verified in the production build: `GlobePanel` splits into its own 12.5 kB
  chunk; `vite-plugin-cesium` copies the Cesium runtime to `dist/cesium/` static
  assets (`Cesium.js`, `Workers/`, `Widgets/`, `Assets/`, `ThirdParty/`) so no
  Cesium lands in any JS bundle (main bundle stays ~245 kB).

### Phase E — Interactions & robustness hardening (1 d) ✅ DELIVERED

- **Stale-response guard:** request-id counter (Phase A) — verify by hammering
  the kind chips: the selected kind's scene must always win.
- **Window slider edge cases:** clamp 10–120; keep camera; refetch only after
  debounce; if a refetch fails, keep showing the last good scene and surface a
  toast/notice rather than blanking.
- **Maneuver collision notice** (Phase C) — engine fallback transparency is a
  *feature*: it shows the analyst layer is honest about substitutions.
- **Storm flag tie-in (small):** if the selected event has `storm_flag`,
  render a chip in `globe-head` ("storm-flagged — uncertainty inflated; TLEs
  re-screened ≤24 h before TCA") reusing the `storm-flag` styling.
- **Reduced-motion:** respect `prefers-reduced-motion` by defaulting the clock
  to paused with the TCA frame shown (orbits only animate on explicit play).
- **Accessibility:** toolbar buttons focusable + `aria-pressed` for toggles;
  legend doubles as a `<dl>`; the offline/error cards carry `role="status"`.
- **Performance:** `requestRenderMode` already set; add `scene.inertia`-friendly
  camera; cap the CZML window default at 45 min (backend default) so documents
  stay ~<1 MB; note the fetch is the only network cost (no per-frame network).

**Exit:** scripted QA pass (below) all green.

**Delivered** (`web/src/lib/media.ts`, `web/src/viz/Globe3D.tsx`,
`web/src/panels/GlobePanel.tsx`, `web/src/styles/dashboard.css`):

- **Reduced motion (WCAG 2.3.3):** a shared `usePrefersReducedMotion` hook
  (matchMedia + change listener). The globe defaults to a paused clock showing
  the TCA frame — orbits animate only on explicit play — and the camera jumps
  (`duration: 0`) instead of flying. The mirror ref is kept fresh *before* any
  load effect reads it (review-driven ordering), and a mid-session preference
  flip pauses the globe (review-driven; no auto-resume). CSS kills the spinner
  / pulse / transition animations under the same query.
- **Hidden-tab pause:** `visibilitychange` pauses the clock and resumes only if
  the analyst had it playing.
- **Accessibility:** keyboard `:focus-visible` outlines on all globe controls
  (matching the B-plane figure), the legend is now a semantic `<dl>` (swatch as
  `aria-hidden` dt, label as dd), offline/error cards carry `role="status"` /
  `role="alert"`.
- Already in place from Phase C (confirmed, no rework): stale-response request
  id + load-token guards, window clamp 10–120 + 400 ms debounce + keep-last-
  scene on failed refetch, maneuver-substitution notice, storm chip,
  `requestRenderMode`, 45 min default window.
- Verified: `npm run build` (tsc strict + vite) clean · `npm test` 18/18.

### Phase F — Testing & validation gates (0.5 d) ✅ DELIVERED

- **Backend:** unchanged — `pytest tests/test_czml.py tests/test_api.py`
  (46 tests) must stay green; any backend tweak (e.g. adding `note` to the
  response) gets a matching test.
- **Frontend static:** `npm run build` (tsc strict + vite) — the required gate.
- **Frontend unit (new, minimal):** add `vitest` (devDependency) with one spec
  for `fetchConjunctionCzml` (URL shape, param mapping, cache hit/miss,
  abort-on-stale) using a stubbed global fetch. Keep it to pure helpers only —
  no DOM/Cesium tests (Cesium is not headless-friendly).
- **CI (new):** extend `.github/workflows/ci.yml` with a `web` job:
  `npm ci && npm run build` (catches frontend regressions — today CI runs
  pytest only).
- **Manual QA checklist** (no Chrome in this workspace — record for the
  operator/partner): tab opens → spinner → two orbits animate · TCA markers,
  miss line, velocity arrow at TCA · scrub timeline, jump-TCA · toggle each
  maneuver kind (notice appears when substituted) · covariance on/off ·
  window 10→120 refetches · kill backend → offline state + retry · narrow
  viewport (responsive, no overflow) · keyboard-tab through toolbar ·
  fullscreen in/out.

**Exit:** build + backend tests green in CI; manual checklist signed off.

**Delivered** (`.github/workflows/ci.yml`, `docs/PHASE5_1_QA_CHECKLIST.md`):

- **New `web` CI job** (runs in parallel with pytest on every push/PR):
  `setup-node@v4` with `node-version: 22` (cesium@1.143 requires node ≥ 22),
  npm cache keyed on `web/package-lock.json`, `working-directory: web`, then
  `npm ci` → `npm test` (vitest) → `npm run build` (tsc strict + vite).
  Previously CI ran pytest only — a frontend regression (e.g. a broken lazy
  chunk) could now never ship unnoticed.
- **`docs/PHASE5_1_QA_CHECKLIST.md`** — the operator/partner manual gate,
  organized as 9 sections + sign-off block: tab/lazy-loading, scene contents,
  timeline/camera, toolbar toggles (content-vs-presentation split), honest
  failure states (incl. kill-the-backend scenarios), trust layer, platform &
  a11y (fullscreen, responsive, keyboard, reduced-motion, no-token OSM),
  bundle/architecture verification, and a traceability table mapping every
  check to the §6 Definition of Done items.

- The vitest harness itself was already delivered in Phase A (18 specs — URL
  contract, response handling, cache semantics, abort plumbing).
- **Review-driven hardening (the QA gate found a real gap):** the client used
  to collapse *every* failure to `null`, so a reachable backend answering 404
  ("event 999 not found", "no feasible maneuver option…") rendered the
  misleading "live engine offline" card. The client now throws a typed
  `ConjunctionCzmlError` carrying the engine's `detail`/`note`, and the panel
  maps it to the honest `error` state (or the "compose error — last scene
  shown" chip when a scene is still on screen). Spec suite updated to pin the
  new contract — now **19 vitest specs** (added 404-detail, envelope-note, and
  HTTP-status-fallback coverage).

### Phase G — Final polish, all phases (1.5 d)

**5.1 itself (this plan's completion):** acceptance criteria from
`VISUALIZATION_PLAN.md` §5.1 — globe renders primary orbit animating; secondary
+ TCA marker shown; timeline scrubs to TCA; maneuver pre/post-burn divergence
visible; no Ion-token hard dependency (OSM fallback verified). Update
`docs/VISUALIZATION_PLAN.md` checkboxes; remove the "CesiumJS globe — stretch /
out" language from `docs/DELIBERATELY_OUT.md`, `CHALLENGE_PLAN.md` and
`ORBITWARDEN_IMPLEMENTATION_PLAN.md` (it has shipped).

**5.2 B-plane:** already delivered. Polish: link the event detail's
`BPlanePlot` to the globe — a "view in 3D" button that switches to the globe
tab with that event preselected (the two diagrams then tell the same story);
align legend swatches with the CZML palette.

**5.3 "What's passing over me?":** still unbuilt. Decision to record: build it
next (it completes Phase 6 and is a judged "accessibility" criterion), or
explicitly defer to the roadmap. This plan does not block on it.

**5.4 Plain-language education:** shipped. Polish: add glossary/explainer
entries for the new UI vocabulary ("3D view", "covariance ellipsoid",
"maneuver track") so the globe is self-explaining; wire the same `Explainer`
component into the globe legend.

**5.5 Sonification/AR:** keep deferred (stretch; not in the build window).

**Phase A–E (feature phases):** no code-blocking items; only documentation
sweeps — verify each `docs/PHASE_*` file's "delivered" section is current.

**Phase F (platform):** Code Engine deployment must include the Cesium static
assets produced by `vite-plugin-cesium` (verify `dist` contains
`cesium/` + `Workers/`; add a build-time check); keep `requestRenderMode` and
lazy chunking so the deployed bundle stays lean; confirm the live URL serves
the globe over HTTPS (Cesium Workers are strict about mixed content).

**Phase G (submission):** README §"AI approach & architecture" gains the globe
(one paragraph + the architecture's *"engine computes the scene, the browser
renders it"* line); the demo beat-sheet in `ORBITWARDEN_IMPLEMENTATION_PLAN.md`
adds the 3D convergence as the hook moment (~0:15 and the maneuver pull-apart
in the decision segment); `docs/BOB_LOG.md` gains entries for this plan and its
implementation; one screenshot of the globe goes into the README/project page.

**Cross-cutting polish:**
- **Consistency:** the globe, B-plane figure, and event card all derive from
  the same engine rows — a "figure agrees with number" note mirrors the B-plane
  test discipline (already pinned at rel=1e-12 there).
- **Perf budget:** monitor the lazy chunk size; if > ~6 MB gzip, sample the
  CZML at `step_s=180` and note it in the UI.
- **Accessibility sweep** of the new tab per the existing dataviz procedure
  (contrast, `forced-colors`, keyboard) — same bar as the B-plane figure.

**Delivered** (`.github` docs, `web/`, `README.md`, `CHALLENGE_PLAN.md`,
`ORBITWARDEN_IMPLEMENTATION_PLAN.md`, `docs/*`):

- **B-plane → globe link:** a "view in 3D →" button under the B-plane figure
  switches to the 3D View tab with that event preselected
  (`Dashboard.openGlobe` + `GlobePanel.preselectEventId`/
  `onPreselectConsumed` — one-shot, consumed so the panel's own selection is
  never clobbered). The two diagrams now tell the same story.
- **Globe explainers (5.4 polish):** new glossary terms `globe_3d`,
  `covariance_ellipsoid`, `maneuver_track`; wired into the globe header and the
  legend (`?` on "encounter uncertainty" and "pre/post-burn track").
- **Cesium-asset build gate (Phase F platform):** `web/scripts/check-cesium-assets.mjs`
  runs at the end of `npm run build` and fails if `dist/cesium/` lacks
  `Cesium.js`/`Workers/`/`Widgets/`/`Assets/`/`ThirdParty/` — enforced in CI's
  `web` job. HTTPS requirement documented in OPERATIONS.
- **Docs sweep:** VISUALIZATION_PLAN §5.1 marked shipped + steps ticked;
  DELIBERATELY_OUT, CHALLENGE_PLAN and ORBITWARDEN_IMPLEMENTATION_PLAN updated
  ("stretch only" language replaced — the globe shipped); the ORBITWARDEN demo
  beat-sheet gained the 3D convergence hook (~0:15) and the maneuver pull-apart
  in the decision segment (~2:20); README gained a globe feature bullet, an
  architecture point ("the engine computes the scene, the browser renders it"),
  the `/api/events/{id}/czml` API row, and the 7-tab panel count; BOB_LOG gained
  the 5.1 plan/implementation rows; OPERATIONS gained the deployment notes.
- **Phase A–E doc sweep:** `docs/PHASE_*` delivered sections verified current
  (no stale 5.1 claims outside this plan doc).
- **Perf check (cross-cutting):** lazy chunk ~13.6 kB gz 4.9 kB — far under the
  6 MB trigger for CZML step-sampling; no action.

**5.3 decision (recorded):** "What's passing over me?" remains unbuilt. This
plan does not block on it — but it is the recommended next build: it completes
Phase 6 of the roadmap and is a judged accessibility criterion (making space
accessible to the public). If time remains before submission, build it next;
otherwise it ships on the roadmap slide.

---

## 4. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Cesium bundle bloat | React.lazy panel + dynamic `import('cesium')`; verify a separate chunk; monitor size |
| CZML refetch storms from toggles | cache Map + debounced window slider + abort-on-stale request ids |
| Ion token dependency | OSM no-token fallback already implemented; keep it exercised in QA |
| Cesium in a flex container renders off-size | `ResizeObserver → viewer.resize()` |
| Viewer lifecycle races (fast tab switching) | per-load cancellation token; `cancelled`/destroyed guards; data-source remove before destroy |
| Stale scene after failed refetch | keep last good scene; surface notice; never blank on refetch failure |
| Maneuver-kind substitution confuses demo | explicit "requested X → showing Y" notice (transparency as a feature) |
| Offline demo shows nothing in the globe | by design (principle 2) — offline card explains and offers retry; demo runs with the API up |
| Frontend regressions silently pass CI | new `web` CI job runs `npm run build` on every push/PR |

## 5. Effort & order

| Phase | Work | Est. |
|-------|------|------|
| A | types + `fetchConjunctionCzml` + cache/abort | 0.5 d |
| B | Globe3D CZML load, clock, fly-to-TCA, toggles, cleanup, resize | 1.5 d |
| C | GlobePanel UI + state machine + toolbar | 1.5 d |
| D | Dashboard lazy tab + CSS | 0.5 d |
| E | hardening, storm chip, a11y, reduced-motion | 1.0 d |
| F | vitest helper spec + CI web job + QA checklist | 0.5 d |
| G | docs sweep, README/demo/BOB_LOG, DELIBERATELY_OUT, deployment check | 1.5 d |
| **Total** | | **~7 d** |

**Recommended order:** A → B → C → D (a working globe tab), then E → F, then G
(interleaved with the 5.3 decision).

## 6. Definition of Done (5.1 frontend)

- [x] "3D View" tab lazy-loads the globe only when opened; bundle stays lean.
- [x] Two real orbits animate; TCA points, miss line, velocity arrow appear at TCA.
- [x] Timeline scrubs; TCA jump + re-center work.
- [x] Maneuver chips refetch and render the pre/post-burn track; substitution notice works.
- [x] Covariance ellipsoid toggles without refetch.
- [x] Offline / error / loading states are honest, readable, retryable.
- [x] `npm run build` and backend pytest green; CI runs both (new `web` job, Phase F).
- [ ] Manual QA checklist signed off (incl. no-token OSM fallback) — human gate, `docs/PHASE5_1_QA_CHECKLIST.md`.
- [x] Docs swept: VISUALIZATION_PLAN checkboxes, DELIBERATELY_OUT, README, demo beat sheet, BOB_LOG (Phase G).
