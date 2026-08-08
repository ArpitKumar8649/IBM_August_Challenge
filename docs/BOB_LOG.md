# IBM Bob Usage Log

> Running log of how IBM Bob was used as the primary development tool. Entries feed the README's required "How IBM Bob was used" section — log as you go, not at the end. Capture: what you asked, what Bob produced, what you iterated on, time saved.

| Date | Module | What Bob did | Prompt pattern / notes | Outcome |
|------|--------|--------------|------------------------|---------|
| 2026-07-24 | Planning | (pre-launch — planning done with Claude; project code will be built with Bob from Aug 1) | — | — |
| 2026-08-08 | 5.1 plan | Produced `docs/PHASE5_1_GLOBE_PLAN.md` — audited the globe as backend-done / frontend-empty (dead-code Viewer skeleton), then laid out a 7-phase (A–G) plan with non-negotiable principles: engine-only numbers, no fake CZML, content-vs-presentation toggles, Cesium out of the critical path. | "create complete detailed deep robust implementation plan for 5.1 frontend" | Single source of truth for the whole 5.1 build; risks table + Definition of Done gates |
| 2026-08-08 | 5.1 frontend | Phases A–D: CZML fetch client with cache/abort + 19 vitest specs; `Globe3D` CZML scene renderer (TCA clock, fly-to-encounter camera, covariance toggle); `GlobePanel` state machine + toolbar; lazy "3D View" tab with hover-prefetch. Verified the production bundle: main ~245 kB with **zero Cesium in any JS bundle** (static `dist/cesium/` only). | "go with phase X deeply" | Globe works end-to-end; `npm test` 19/19, `tsc`+vite clean; each phase reviewed and hardened (stale-closure race, stuck-refresh state, pause desync) |
| 2026-08-08 | 5.1 hardening | Phase E: reduced-motion (paused clock, instant camera), hidden-tab pause, keyboard `:focus-visible`, semantic `<dl>` legend. Phase F: new `web` CI job (`npm ci`/test/build on node 22), manual QA checklist — and the QA gate caught a real bug: the client swallowed 404s, so a reachable backend rendered the misleading "offline" card. Fixed with a typed `ConjunctionCzmlError` that surfaces the engine's `detail`. | "start phase F now deeply" | CI now guards the frontend; error states honest ("event 999 not found" shows, not "engine offline") |
| 2026-08-08 | 5.1 polish | Phase G: B-plane → globe "view in 3D" link with event preselection, globe explainers (3D view / covariance ellipsoid / maneuver track), a post-build Cesium-asset gate, and the all-phase docs sweep (VISUALIZATION_PLAN, DELIBERATELY_OUT, challenge plans, README, BOB_LOG, OPERATIONS). 5.3 "what's over me" decision recorded. | "start phase G, precisely deep implementation" | 5.1 signed off end-to-end; only the human-run manual QA checklist remains open |

## Patterns worth documenting for the README

- **Module generation:** e.g. "generate `engine/ingest/celestrak.py` from this spec + pydantic model" → review → iterate
- **Test generation:** "write pytest cases for SGP4 propagation against Vallado's reference TLEs"
- **Debugging loops:** the SkillsBuild troubleshooting pattern (analyze → recommend → apply → validate)
- **Refactoring:** "split screen.py into coarse/fine stages"
- **Docs:** docstrings, README drafts from code
