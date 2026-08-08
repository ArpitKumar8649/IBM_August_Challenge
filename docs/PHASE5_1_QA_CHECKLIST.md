# Phase 5.1 — 3D Globe: Manual QA Checklist

> Manual verification checklist for the CesiumJS 3D conjunction globe (the
> "3D View" tab), recorded for the operator / partner to sign off. The dev
> workspace has **no browser installed**, so this is the human-in-the-loop
> gate for what automated gates cannot see (rendering, animation, camera,
> fullscreen). Automated gates already cover: `npm test` (18 vitest specs on
> the CZML fetch client) and `npm run build` (tsc strict + vite) in the `web`
> CI job, plus 46 backend pytest specs for the CZML composer/endpoint.
>
> Companion docs: [`PHASE5_1_GLOBE_PLAN.md`](PHASE5_1_GLOBE_PLAN.md) (design +
> delivery notes), [`VISUALIZATION_PLAN.md`](VISUALIZATION_PLAN.md) §5.1
> (feature spec), [`OPERATIONS.md`](OPERATIONS.md) (how to run the stack).

---

## 0. Prerequisites & environment

```bash
# Terminal 1 — API (the globe's only source of numbers)
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend dev server (proxies /api -> :8000)
cd web && npm run dev          # http://localhost:5173
```

- [ ] Backend up: `curl http://localhost:8000/api/health` returns 200
- [ ] A screening run exists (the event board is populated — the globe
      derives its event selector from the board)
- [ ] Test environment: `_______` · Browser/version: `_______` · Date: `_______`

**State to verify:** the 3D scene requires the **live engine** — a fabricated
orbit is deliberately impossible (project principle: no fake numbers in the
globe). Every scenario below assumes the API is running unless the step says
"kill the backend".

---

## 1. Tab & lazy loading (DoD: "lazy-loads the globe only when opened")

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 1.1 | Load the dashboard | No globe/network work for the globe until the tab is used | |
| 1.2 | Hover (or focus) the **3D View** tab, then click it | Opens quickly; a themed spinner shows briefly, then the globe | |
| 1.3 | Network tab (DevTools), first open | A `GlobePanel` chunk (~12–14 kB) loads on hover/open; **no `Cesium.js` in any JS bundle** — the Cesium runtime is served as static assets under `dist/cesium/` only when the globe mounts | |
| 1.4 | Switch away from the tab, switch back | Same scene restored fast (cache); no duplicate viewers, no console errors | |

## 2. Scene contents at TCA (DoD: "two real orbits … TCA points, miss line, velocity arrow")

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 2.1 | Open the tab with an event selected | Two orbits render: primary (accent color) and secondary; both animate along the timeline | |
| 2.2 | At TCA | Primary and secondary **points**, the **miss line** between them, and the **relative-velocity arrow** are visible | |
| 2.3 | Legend | Lists exactly the entities drawn (primary/secondary orbit, TCA, miss line, velocity, covariance, maneuver track when shown) with the engine's palette swatches | |
| 2.4 | Footer | Shows secondary name/NORAD, TCA timestamp, window width, and the engine attribution | |

## 3. Timeline, clock, camera (DoD: "timeline scrubs; TCA jump + re-center")

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 3.1 | Timeline scrub | Orbits scrub smoothly; the **⏱ TCA** button jumps the clock to TCA and re-centers the camera on the encounter | |
| 3.2 | Play/pause | Toggle animates/pauses the clock; the button state never desyncs from the animation (even across scene reloads) | |
| 3.3 | Switch events | Camera re-frames the new encounter; maneuver-kind toggles do **not** move the camera | |
| 3.4 | Reduce motion (OS setting on) | Globe opens **paused** at the TCA frame; camera jumps instead of flying; spinner/pulse animations off; explicit play still animates | |
| 3.5 | Switch browser tab away and back | Clock pauses on hide; resumes only if it was playing before | |
| 3.6 | Toggle OS reduced-motion mid-session | Globe pauses immediately; does not auto-resume | |

## 4. Toolbar: content toggles refetch, presentation toggles don't (DoD: maneuver + covariance)

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 4.1 | **Maneuver kind** chips (none / cheapest-safe / nominal / conservative) | Selecting a kind refetches and renders the **pre/post-burn maneuver track**; the chip reflects the kind actually used | |
| 4.2 | Kind substitution | If the engine substitutes (curated kinds collide), a notice appears: "requested X — showing best available (Y)" | |
| 4.3 | Kind → **none** while a scene is loaded | No refetch (instant); the maneuver track disappears (`entity.show` flip); no stuck "refreshing…" state | |
| 4.4 | **Covariance** switch | Ellipsoid toggles **instantly with no network request** (check Network tab) | |
| 4.5 | **Window** slider (10–120 min) | After ~400 ms debounce, a refetch renders a wider/narrower arc; value shown as "± N min" | |
| 4.6 | Rapid-fire toggles | The last selection always wins (stale responses discarded); no console errors | |

## 5. Honest failure states (DoD: "offline / error / loading states are honest, readable, retryable")

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 5.1 | With the globe open, **kill the backend** and toggle a maneuver kind / window / event | A "backend unreachable — last scene shown" chip appears; the last good scene stays visible; a **Retry** control exists | |
| 5.2 | Click **Retry** with the backend still down | Stays in the degraded state (honest, no fake scene) | |
| 5.3 | Restart the backend, click **Retry** | Refetches and restores the live scene | |
| 5.4 | Open the tab with the backend **already down** | An offline card explains the 3D scene needs the live engine, hints `uvicorn api.main:app`, and offers Retry | |
| 5.5 | Force a 404 event (delete the event's screening row, or ask dev for a bad id) | Error card with the backend message + Retry | |
| 5.6 | First-open spinner | Composing-encounter spinner with pulse text; no frozen white frame | |

## 6. Trust layer & context

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 6.1 | Storm-flagged event selected | Storm chip appears in the globe header ("storm-flagged — uncertainty inflated…") with its `?` explainer | |
| 6.2 | Header status chips | LIVE / SAMPLE status reflects the board's data source; a **refetch** shows "refreshing…" + dim, never blanks the scene | |
| 6.3 | Numbers cross-check | Miss distance / Pc on the globe's story agree with the event board and the B-plane figure (same engine rows; "figure agrees with number") | |

## 7. Platform & accessibility

| # | Step | Expected | ✓ |
|---|------|----------|---|
| 7.1 | **Fullscreen** button | The globe stage goes fullscreen; ESC exits cleanly; Cesium's built-in fullscreen button is hidden | |
| 7.2 | Narrow viewport (~360 px) | Toolbar wraps without horizontal overflow; globe height clamps sanely (`clamp(380px, 56vh, 720px)`) | |
| 7.3 | Keyboard: Tab through the toolbar | Every control is focusable with a visible `:focus-visible` outline; toggles announce state (`aria-pressed`, `role="switch"`) | |
| 7.4 | Screen reader on the globe | Offline/error cards read as status/alert; legend is a semantic `<dl>`; images/icons are `aria-hidden` with text labels | |
| 7.5 | **No Ion token** (clear `CESIUM_ION_TOKEN`, hard-refresh) | Globe still renders with open (OSM/Natural Earth) imagery — no token hard-dependency | |
| 7.6 | Console (all scenarios) | Zero errors; no leaked viewers/observers after tab switches | |

## 8. Bundle / architecture verification (production build)

```bash
cd web && npm run build && ls -S dist/assets/ | head -6 && ls dist/cesium
```

- [ ] `GlobePanel` is its own small chunk (~12–14 kB) — no Cesium in any JS bundle
- [ ] `dist/cesium/` exists with `Cesium.js`, `Workers/`, `Widgets/`, `Assets/`
- [ ] Main bundle stays lean (~245 kB)
- [ ] Served over HTTPS in deployment (Cesium Workers are strict about mixed content)

---

## 9. Traceability to Definition of Done (PHASE5_1_GLOBE_PLAN §6)

| DoD item | Verified by |
|----------|-------------|
| Lazy-loads only when opened; bundle lean | §1, §8 |
| Two real orbits animate; TCA points/miss line/velocity arrow | §2 |
| Timeline scrubs; TCA jump + re-center | §3 |
| Maneuver chips refetch + substitution notice | §4.1–4.3 |
| Covariance toggles without refetch | §4.4 |
| Offline/error/loading honest, readable, retryable | §5 |
| `npm run build` + backend pytest green; CI runs both | CI `test` + `web` jobs |
| Manual QA signed off (incl. no-token OSM fallback) | this checklist, §7.5 |
| Docs swept | Phase G |

---

## Sign-off

- [ ] All applicable checks pass (or deviations recorded below)
- [ ] Deviations / notes: `______________________________________________`
- [ ] Signed off by: `______________` · Date: `______________`
