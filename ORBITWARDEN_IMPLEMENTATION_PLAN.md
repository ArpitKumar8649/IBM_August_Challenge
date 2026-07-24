# OrbitWarden — Detailed Implementation Plan

> **IBM AI Builders Challenge · August 2026 · "Advance Space Exploration with AI"**
> One-liner: an AI mission-ops analyst that screens a smallsat against every tracked object in orbit, triages conjunctions with explained risk, designs propellant-aware avoidance maneuvers, and writes the maneuver card — giving a two-person university CubeSat team the collision-avoidance desk of a major operator.
>
> **Core design principle: "physics computes, AI judges."** A deterministic astrodynamics engine is the sole source of every number. The Granite agent does judgment (triage, selection, explanation, what-ifs) via strict tool-calling. A validation layer guarantees no AI-invented figure ever reaches the UI.

---

## 0. Phase map at a glance

| Phase | Dates | Goal | Exit gate (must pass to proceed) |
|-------|-------|------|----------------------------------|
| **0 — Prep** | Jul 24–31 | Accounts, learning, team, domain knowledge | Bob trial works; SkillsBuild cert saved; Space-Track account requested; team roles assigned |
| **1 — Physics core** | Aug 1–7 | Ingestion + SGP4 + coarse screening for ONE satellite | ISS screened vs ~2–3k LEO subset; miss-distance list matches CelesTrak SOCRATES within tolerance |
| **2 — Screening engine** | Aug 8–14 | Full scoring, TCA refinement, Pc, storm flags, nightly batch | Top-20 ranked events with all scores, auto-refreshing nightly cache in Postgres |
| **3 — Judgment layer** ⚠️ make-or-break | Aug 15–21 | Maneuver search + Granite agent + validation layer + API | One real event flows end-to-end: engine → agent → **validated** maneuver card, via API |
| **4 — Product** | Aug 22–28 | Dashboard, CDM validation report, deployment, design partner | Live demo URL on Code Engine; one-page validation report; partner verdict captured |
| **5 — Submission** | Aug29–31 | README, ≤3-min video, project page, compliance | Submitted by **Aug 30** (Aug 31 = buffer only) |

**Pivot gate (Aug 21):** if the maneuver card is not working end-to-end, cut maneuvers and ship the triage/storm-aware analyst only (still a strong entry — it's essentially DragCast, the #2-ranked concept). Do not let a half-built maneuver search sink the whole project.

---

## 1. Repository layout

All project code lives in this repo (`IBM_August_Challenge`). **Scaffold on Aug 1** (project creation opens then — do not commit project code before that).

```
IBM_August_Challenge/
├── README.md                     # required sections: problem, solution, AI approach &
│                                 # architecture, theme, how IBM Bob was used
├── LICENSE                       # MIT or Apache-2.0
├── docs/
│   ├── ARCHITECTURE.md           # the three planes + validation layer diagram
│   ├── ASSUMPTIONS.md            # fixed-covariance Pc, TEME≈J2000, TLE fidelity — disclosed
│   ├── DELIBERATELY_OUT.md       # pinned scope fence (see §9)
│ ├── BOB_LOG.md                # running log of how IBM Bob was used (prompts, iterations)
│   ├── DEMO_SCRIPT.md            # beat sheet + golden-path recording checklist
│   └── VALIDATION_REPORT.md      # generated from validation/ output
├── engine/                       # DETERMINISTIC PHYSICS PLANE (Python)
│   ├── ingest/
│   │   ├── celestrak.py          # GP catalog fetch (groups: active, stations, starlink, oneweb, geo)
│   │   ├── spacetrack.py         # SATCAT enrichment + CDM_PUBLIC (free account)
│   │   ├── spaceweather.py       # NOAA SWPC 3-day forecast + NASA DONKI
│   │   └── cache.py              # raw-data snapshots → IBM Cloud Object Storage / local disk
│   ├── frames.py                 # TEME↔RSW transforms, B-plane projection
│   ├── propagate.py              # sgp4 wrapper: vectorized sgp4_tsince over time grids
│   ├── screen.py                 # band pre-filter → coarse scan → candidate windows
│   ├── tca.py                    # golden-section/Brent TCA refinement
│   ├── scoring.py                # miss/Vrel/geometry/HBR/Pc + composite rank
│   ├── pc.py                     # Alfriend–Foster short-term Pc (documented fixed covariance)
│   ├── maneuvers.py              # shoot-and-score impulsive burn grid
│   └── models.py                 # pydantic data models (Event, ManeuverOption, ObjectInfo…)
├── agent/                        # AI JUDGMENT PLANE
│   ├── tools.py                  # the 7 tools (strict contract, §6)
│   ├── prompts.py                # system prompt + few-shot examples
│   ├── validator.py              # OUTPUT-VALIDATION LAYER (§7)
│   └── session.py                # LangGraph tool agent over ChatWatsonx (Granite)
├── api/                          # FastAPI
│   ├── main.py
│   ├── routes/                   # satellites, events, maneuvers, chat (SSE), space-weather
│   └── schemas.py
├── batch/
│   └── nightly.py                # APScheduler / Code Engine cron: ingest → screen → persist
├── web/                          # React + TypeScript dashboard
│ └── src/
│       ├── components/           # SatellitePicker, EventList, EventDetail, ManeuverPanel,
│       │                         # AnalystChat, StormBanner, GeometryPlot, ManeuverCard
│       └── pages/
├── validation/
│   ├── cdm_replay.py             # replay CDM_PUBLIC events through the engine
│   └── report.py                 # one-page precision/recall-style report
├── tests/
│   ├── fixtures/                 # Vallado SGP4 test TLEs + expected outputs; golden events
│   ├── test_propagate.py
│   ├── test_screen.py            # cross-check vs SOCRATES published list
│   ├── test_pc.py                # formula vs published examples
│   ├── test_maneuvers.py
│   ├── test_validator.py
│   └── test_agent_golden.py      # golden-path Q&A: tools called, numbers match engine
├── infra/
│   ├── code-engine/              # api.yaml, web.yaml, batch-cron.yaml
│   └── github-actions/ci.yml
└── data/
    └── golden/                   # committed demo snapshot (screening results for demo sats)
```

---

## 2. Phase 0 — Prep (Jul 24–31)

**No project code.** Project creation opens Aug 1; anything before that is setup and learning.

| # | Task | Detail | Owner |
|---|------|--------|-------|
| 0.1 | IBM Bob trial | Create account, verify it works in VS Code; learn its chat/edit/agent modes. If trial/Bobcoins run out later, the FAQ guide documents a fresh trial account. | All |
| 0.2 | SkillsBuild activity | Complete the required learning activity ("Troubleshoot Your Code Using IBM Bob" and/or "How IBM Bob and AI Tools Are Changing the Way Solutions Are Built"). **Save the completion certificate** — submission artifact. | All |
| 0.3 | Discord | Join the challenge Discord; watch `#august-challenge-and-learning` for rules clarifications, the submission platform mechanics, webinar links. | All |
| 0.4 | Space-Track account | Register at space-track.org **now** — approval can lag. Needed for SATCAT (object size/type) and CDM_PUBLIC (validation). Note rate limits (~300 q/min, ~3,000 q/day). | Engine lead |
| 0.5 | NASA API key | Free key at api.nasa.gov (DONKI). Verify CelesTrak GP endpoints + NOAA SWPC 3-day forecast reachable from your machine (no auth). | Engine lead |
| 0.6 | IBM Cloud | Free-tier account; confirm **watsonx.ai** access (Granite models) and **Code Engine**. Do a throwaway "hello Granite" tool-calling tutorial (LangChain `ChatWatsonx.bind_tools`) — practice only, no project code. | Agent lead |
| 0.7 | Team | Attend Aug 5 team-formation webinar; target 2–4 people. Pre-assign: **engine lead**, **agent/backend lead**, **frontend lead**, **demo/README/validation owner** (overlap fine for small teams). | All |
| 0.8 | Domain reading | SGP4/TLE basics (Vallado), short-term collision probability and its covariance caveats (Alfriend–Foster/Foster), CCSDS CDM format, CelesTrak SOCRATES (the free incumbent — know what you differentiate from), Starlink's published maneuver statistics (demo hook). | Engine + agent leads |
| 0.9 | Logistics | Branching model (trunk + short-lived feature branches), commit conventions, license choice, shared folder for demo assets, a `docs/BOB_LOG.md` habit from day one. | All |
| 0.10 | Design-partner outreach | **Start early — needs lead time.** DM/email 3–5 university CubeSat teams (find via Discord, university space-grant programs, public team pages) offering a 30-min trial in Week 4 in exchange for a one-paragraph verdict. | Demo owner |

---

## 3. Phase 1 — Physics core (Aug 1–7)

**Goal:** prove the hardest, riskiest part first — data in, orbits out, a crude but real screening pass for one satellite.

### 3.1 Tasks

| # | Task | Detail | Est. |
|---|------|--------|------|
| 1.1 | Repo scaffold | License, CI (lint + pytest on push), `docs/DELIBERATELY_OUT.md` pinned, README skeleton with the 5 required sections as empty headers, `BOB_LOG.md` started. | 0.5 d |
| 1.2 | `ingest/celestrak.py` | Fetch GP groups (JSON/GP format) for `active`, `stations` (debris), `starlink`, `oneweb`, `geo`. Parse to `(norad_id, name, tle_line1, tle_line2, epoch)`. Polite caching (once/day). | 0.5 d |
| 1.3 | `propagate.py` | Wrap `sgp4` (C-accelerated). `propagate_grid(satrec, ts_minutes) -> positions[N,3], velocities[N,3]` using vectorized `Satrec.sgp4_tsince`. Error handling for decayed objects (error codes). | 0.5 d |
| 1.4 | `frames.py` | RSW (radial/along-track/cross-track) rotation from primary r,v; relative-state → RSW; B-plane projection (plane ⊥ relative velocity). TEME used throughout internally (both objects same frame — distances exact). | 0.5 d |
| 1.5 | `screen.py` v1 | **Band pre-filter:** from each TLE derive perigee/apogee radii (mean motion → semi-major axis; `a(1±e)`); keep objects whose `[rp−M, ra+M]` overlaps the primary's band (M = 150 km default, widened during storms — §4.5). Cuts ~28k → ~2–5k. **Coarse scan:** 7-day window at 60 s steps; primary positions computed once (10,080 points); candidates propagated in chunks of 500 (memory ≈ chunk×10k×3×8 B ≈ 120 MB); find local distance minima < 100 km threshold. | 1.5 d |
| 1.6 | `models.py` | Pydantic models: `CatalogObject`, `Event`, `ManeuverOption`, `ScreeningRun`, `SpaceWeatherState`. Single source of truth shared by engine/API/agent. | 0.5 d |
| 1.7 | Tests + reference validation | Vallado SGP4 test TLEs (fixture with published expected positions at given tsince) — assert < 1 m agreement. Screen ISS against a curated ~2–3k LEO subset; **cross-check top events against CelesTrak SOCRATES' published close-approach list** (same physics family — should broadly agree). | 1 d |

**Performance budget (validated in 1.5):** 3k candidates × 10,080 grid points ≈ 30 M SGP4 evaluations; C-accelerated vectorized ≈ 1–2 min per satellite in chunks. Fine for nightly batch; on-demand "re-screen now" shows a progress bar; **demo always uses cached results.**

### 3.2 Exit gate
- [ ] `pytest` green: SGP4 matches Vallado references; SOCRATES cross-check shows the same close approaches in the top-N (order-of-magnitude miss-distance agreement).
- [ ] One command screens the ISS (or a public CubeSat) against the LEO subset and prints a ranked miss-distance list.
- [ ] Team finalized (Aug 5), roles assigned.

---

## 4. Phase 2 — Screening engine complete (Aug 8–14)

**Goal:** every number the judges will see exists by end of this phase.

### 4.1 Tasks

| # | Task | Detail | Est. |
|---|------|--------|------|
| 2.1 | `tca.py` | For each candidate window: golden-section (or Brent) minimization of `|Δr(t)|` over `[t₀−60 s, t₀+60 s]`, tol 0.01 s (~20 evaluations). Output: precise TCA, miss vector, relative velocity vector. | 0.5 d |
| 2.2 | `scoring.py` | Per event: miss distance (km); relative velocity (km/s); **approach geometry** — miss vector decomposed in RSW (in-track–dominant = more predictable; radial-dominant = harder, flag it); object type from SATCAT (active payload vs derelict rocket body/debris — *unmaneuverable object ⇒ you must move*); composite rank. | 1 d |
| 2.3 | `pc.py` | Short-term 2-D encounter probability (Alfriend–Foster), see formula below. **Fixed, documented combined covariance** (MVP assumption, stated in UI and `ASSUMPTIONS.md`). Pc is a *display* quantity; ranking is driven by miss + Vrel + geometry. | 0.5 d |
| 2.4 | `ingest/spacetrack.py` | SATCAT enrichment (size/RCS/object type/country) with graceful CelesTrak-only fallback if approval stalls. Batch + cache all queries (rate-limited). | 1 d |
| 2.5 | `ingest/spaceweather.py` + storm flags | SWPC 3-day Kp forecast + NASA DONKI geomagnetic-storm notifications. Flag any event whose `[now, TCA]` window straddles a predicted storm (Kp ≥ 6 or active DONKI GST): "TLE uncertainty inflated — re-screen ≤ 24 h before TCA." Optionally widen the band margin M for the next screening run. | 0.5 d |
| 2.6 | Storage | Postgres schema (below); persist runs, objects, events. **pgvector column added now, used later (stretch).** Primary = IBM Cloud Databases for PostgreSQL (trial); fallback = SQLite + JSON snapshots so nothing blocks on cloud signup. | 1 d |
| 2.7 | `batch/nightly.py` | Ingest → upsert catalog → screen each watched satellite (MVP: ISS + 1–2 public CubeSats + demo satellites) → persist top events + storm flags. APScheduler locally; Code Engine cron in Phase 4. | 1 d |

**The Pc formula (Alfriend–Foster short-term encounter):**

```
Pc ≈ (HBR² / (2·σx·σy)) · exp( −xm²/(2σx²) − ym²/(2σy²) )
```

- `(xm, ym)` = miss vector projected onto the **B-plane** (⊥ relative velocity)
- `HBR` = hard-body radius = (size₁ + size₂)/2 from SATCAT, default 50 m when unknown
- `σx, σy` = projected combined position covariance — **MVP: fixed diagonal in RSW, σ_in-track = 1.0 km, σ_radial = σ_cross-track = 0.5 km**, disclosed in the UI ("simplified covariance — see assumptions") and validated empirically against real CDMs in Phase 4

**Database schema (Postgres):**

```sql
objects(norad_id PK, name, object_type, country, size_m, rcs_m2, tle_l1, tle_l2, tle_epoch, updated_at)
screening_runs(id PK, primary_norad, run_at, window_days, catalog_size, margin_km, status, duration_s)
events(id PK, run_id FK, secondary_norad FK, tca, miss_km, vrel_kms,
       miss_r_km, miss_i_km, miss_c_km, hbr_m, pc, storm_flag BOOL, rank INT)
maneuver_options(id PK, event_id FK, burn_epoch, dv_r_ms, dv_i_ms, dv_c_ms,
                 dv_total_ms, propellant_g, post_burn_miss_km, kind TEXT)  -- cheap|nominal|conservative
agent_sessions(id PK, created_at, satellite_norad, transcript JSONB)
validation_log(id PK, session_id FK, artifact_type, referenced_ids JSONB,
               checks JSONB, passed BOOL, created_at)
event_features(id PK, event_id FK, embedding vector(384))  -- pgvector, stretch: similar-encounter retrieval
```

### 4.2 Exit gate
- [ ] Top-20 ranked events for a real satellite with miss, Vrel, RSW geometry, HBR, Pc, storm flag — all persisted, auto-refreshing nightly.
- [ ] `test_pc.py` matches published Pc examples within tolerance; storm flag fires on a constructed storm-window case.

---

## 5. Phase 3 — Judgment layer (Aug 15–21) ⚠️ make-or-break

**Goal:** the AI half of "physics computes, AI judges." **By Aug 21 a single real event must flow: engine → Granite agent → validated maneuver card, served by the API.** If this gate fails on Aug 21, execute the pivot (§10).

### 5.1 Tasks

| # | Task | Detail | Est. |
|---|------|--------|------|
| 3.1 | `maneuvers.py` | Shoot-and-score grid (below). Returns all candidates + a curated 2–3 options (cheapest-safe / nominal / conservative). | 1.5 d |
| 3.2 | `agent/tools.py` | The 7 tools (§6) as pure functions over engine + DB. Every tool returns engine-computed numbers only. | 1 d |
| 3.3 | `agent/session.py` | LangGraph (or LangChain) tool-calling agent over `ChatWatsonx` (**`ibm/granite-4-h-small`** — verified 2026-07-24 in us-south with function-calling; `granite-3-3-8b-instruct` was withdrawn 2026-03-31). Use the `/ml/v1/text/chat` endpoint. Streaming responses. Fallback model endpoint configured. | 1 d |
| 3.4 | `agent/prompts.py` | System prompt (§6.2) + 3–4 few-shot exchanges demonstrating: cite tool outputs, never invent numbers, keep human in loop, flag storms, state assumptions. | 0.5 d |
| 3.5 | `agent/validator.py` | Output-validation layer (§7). | 1 d |
| 3.6 | `api/` | FastAPI routes (§8) incl. `POST /api/chat` with SSE streaming through the validator. | 1.5 d |
| 3.7 | `test_agent_golden.py` | Golden-path script: 6–8 canned operator exchanges; assert correct tools called, card numbers == engine numbers, validator blocks an injected bad number. | 0.5 d |

### 5.2 Maneuver search — shoot-and-score

No analytic optimization; propagate and measure. Robust, simple, fast.

```
For event with TCA t*, user-supplied mass m (kg) and Isp (s):
  burn epochs  : t* − {12 h, 6 h, 3 h, 90 min, 45 min}
  directions   : +in-track, −in-track, +radial, −radial, +normal   (RSW unit vectors)
  magnitudes   : {0.01, 0.05, 0.1, 0.25, 0.5, 1.0} m/s
  → 150 candidates. For each:
      state(t_burn) ← SGP4(primary, t_burn);  v += Δv·direction
      re-propagate (SGP4 with patched state — acceptable for short arcs; note assumption)
      measure post-burn miss distance at original TCA
  propellant:  Δm = m·(1 − exp(−Δv/(g₀·Isp)))   [g₀ = 9.80665 m/s²]
  score:       post_burn_miss_km per gram burned
Select: cheapest option with post-burn miss ≥ max(2×HBR + 1 km, operator min);
        nominal (balanced); conservative (largest margin). 
```

**Constraints the agent can pass through:** `fuel_margin_g` (exclude options burning past reserve), `blackout_windows` (exclude burn epochs inside e.g. a downlink pass), `min_post_burn_miss_km`.

### 5.3 Exit gate
- [ ] `POST /api/chat`: operator question → tool calls → answer with engine numbers; `submit_maneuver_card` returns a card whose every number traces to `maneuver_options`/`events` rows; validator log shows all checks passed.
- [ ] What-if works: "what if we delay the burn 3 hours?" → `repropagate_with_burn` → explained tradeoff.
- [ ] Injected-number test: a doctored transcript with a wrong number is blocked/flagged by the validator.

---

## 6. Agent design

### 6.1 Tool contract (the AI's only way to touch numbers)

| Tool | Inputs | Returns (all from engine/DB) |
|------|--------|------------------------------|
| `get_satellite_info` | `norad_id` | name, object type, TLE epoch/age, orbit summary |
| `list_conjunctions` | `norad_id`, `days=7`, `limit=20` | ranked events: rank, secondary name/type, TCA, miss, Vrel, geometry class, Pc, storm flag |
| `get_event_details` | `event_id` | full RSW miss geometry, object card (SATCAT), storm annotation, similar past events (stretch) |
| `search_maneuvers` | `event_id`, `constraints{}` | 2–3 options: burn epoch, Δv vector & total, grams burned, verified post-burn miss, kind |
| `get_space_weather` | — | current Kp, 3-day forecast, active DONKI warnings |
| `repropagate_with_burn` | `norad_id`, `burn_epoch`, `dv_vector` | new miss at TCA (what-ifs) |
| `submit_maneuver_card` | `event_id`, `option_id`, `operator_constraints`, `notes` | **server-composed** standard card: burn epoch, Δv, propellant cost, predicted post-burn miss, verification pass suggestion, rollback plan, assumptions block — numbers filled server-side from the referenced rows, never transcribed by the model |

### 6.2 System prompt skeleton

```
You are OrbitWarden's conjunction analyst, assisting a smallsat operator.
RULES (non-negotiable):
1. You NEVER compute orbits, probabilities, or burn parameters yourself. Every number
   you state must come verbatim from a tool result. If you don't have a tool result
   for a number, you don't state the number.
2. You JUDGE: triage and rank events with plain-English rationale, select maneuvers
   against the operator's stated constraints, explain tradeoffs, answer what-ifs by
   re-invoking tools.
3. The human decides. You recommend and explain; you never execute or urge urgency
   beyond what the data supports.
4. When a storm flag is present, say so and recommend re-screening ≤ 24 h before TCA.
5. State assumptions when relevant (simplified covariance, user-supplied mass/Isp).
6. To produce a maneuver card, call submit_maneuver_card with event_id + option_id.
   Do not write card numbers in prose.
```

---

## 7. Output-validation layer (the trust guarantee)

This is the architectural move judges will remember. Design it airtight:

1. **Numbers never travel through the model.** All numeric UI content comes from API/engine rows. The maneuver card is *server-composed*: the agent supplies `event_id` + `option_id` + prose; the server fills every figure from the DB. The model cannot transcribe what it never handles.
2. **Prose is scanned.** Any number the model writes in rationale/notes is regex-extracted and matched (with tolerance) against the referenced event/option data. Mismatch → the figure is flagged/stripped and the response annotated "⚠ unverified figure removed."
3. **Every artifact is logged** to `validation_log` (artifact, referenced rows, checks run, passed). The demo's "provably computed" claim is literally demonstrable from this table.
4. **Fallback model endpoint** configured; if Granite is unavailable the agent degrades, the engine never does.

---

## 8. API surface (FastAPI)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/satellites?q=` | search watched + catalog objects |
| `GET /api/satellites/{id}/events?days=7` | ranked events (from cache — instant) |
| `GET /api/events/{id}` | event detail + object card + storm flag |
| `GET /api/events/{id}/maneuvers?fuel_margin_g=&min_post_burn_miss_km=` | 2–3 options |
| `POST /api/chat` | agent session, SSE-streamed, through validator |
| `POST /api/screenings` | on-demand single-satellite re-screen (progress via SSE; demo uses cache) |
| `GET /api/space-weather` | Kp + forecast + warnings |
| `GET /api/runs/latest`, `GET /api/health` | ops |

---

## 9. Deliberately-out list (pin in README Week 1)

Full-covariance CDM-grade Pc · numerical propagation with drag/high-order gravity · finite-duration burns & attitude modeling · multi-satellite fleet scheduling · regulatory coordination filings · autonomous execution (human-in-the-loop only) · ML trained on CDM archives · mobile/alerting · CesiumJS 3D globe **until the Week-4 checkpoint passes** (2D Recharts plots are the shipping visualization).

New ideas go to a "roadmap" slide, not the codebase.

---

## 10. Phase 4 — Product (Aug 22–28)

| # | Task | Detail | Est. |
|---|------|--------|------|
| 4.1 | Dashboard | `SatellitePicker` (NORAD ID / name) · `EventList` (rank, object + type badge, TCA countdown, miss, Vrel, risk chip, one-line AI rationale, storm badge) · `EventDetail` (2D Recharts TCA geometry — miss vector in RSW plane + relative trajectory; object card; rationale panel) · `ManeuverPanel` (natural-language constraints box + structured fallback; option cards; selected maneuver-card view with assumptions block) · `AnalystChat` (SSE streaming) · `StormBanner`. | 4 d |
| 4.2 | CDM validation harness | Pull CDM_PUBLIC (last 30–90 days; ISS + public CubeSats). For each CDM: fetch historical TLEs via `gp_history` from around CDM creation, run the engine, compare: detected? rank? predicted miss vs CDM-stated miss; maneuver options vs what the operator actually did (where inferable). Output `VALIDATION_REPORT.md` + one-page chart: N replayed, detection rate, miss-distance error distribution. **This converts the simplified-Pc liability into a measured, defensible accuracy claim — the single biggest credibility artifact.** | 2 d |
| 4.3 | Deployment | IBM Cloud Code Engine: `api` service, `web` static build, `batch` cron job (nightly). Postgres via IBM Cloud Databases (trial). CI on push; one-command demo env seeded from `data/golden/` so the live URL is fast and network-independent. | 1.5 d |
| 4.4 | Design partner | The university CubeSat team (outreach started Phase 0) runs the tool for a few days; capture their verdict + one requested change for the demo. | 0.5 d |
| 4.5 | Golden path | Freeze a demo dataset (one screening night for ISS + a CubeSat, incl. one storm-flagged event and one replayed CDM). Pre-record the what-if segment against cached tool outputs — the demo's most failure-prone 55 s gets a guaranteed fallback. | 0.5 d |

**Exit gate:** live URL works from a clean browser; validation report shows measured detection rate; partner verdict in hand; golden path recorded. CesiumJS globe only if all of the above shipped by Aug 25.

---

## 11. Phase 5 — Submission packaging (Aug 29–31)

**No new features after Aug 28.**

| Day | Work |
|-----|------|
| Aug 29 | Final README (5 required sections — skeleton below); record demo video against the beat sheet; host video publicly (YouTube unlisted or similar) + copy in repo. |
| Aug 30 | Publish project page (team details, GitHub link, video link); final compliance pass; **submit today**. |
| Aug 31 | Buffer only — contingency for platform issues. |

**README skeleton (required sections):**
1. **Problem statement** — LEO congestion; small operators lack the analyst desk; over-maneuver vs under-react.
2. **Solution** — OrbitWarden: screening → triage → maneuvers → card; human in the loop.
3. **AI approach & architecture** — "physics computes, AI judges" diagram; Granite tool-calling; validation layer; why this makes AI *core* and *trustworthy*.
4. **Selected challenge theme** — August Challenge: Advance Space Exploration with AI; mapping to "improve mission safety and reliability" + "better decision-making in complex environments."
5. **How IBM Bob was used** — concrete examples from `BOB_LOG.md`: which modules Bob generated/iterated (engine, agent wiring, UI, tests), prompting patterns, iteration loops, time saved.

**Demo video beat sheet (≤ 3:00):**
`0:00` hook — catalog > 35 k objects, Starlink's thousands of burns/yr, a CubeSat team decides alone · `0:20` live dashboard — pick a real satellite, ranked 7-day events with AI one-liners · `0:50` deep dive — TCA geometry, SATCAT object card, storm-flag banner ("re-screen 24 h before TCA") · `1:30` the decision — operator states constraints, three verified options, maneuver card, live what-if ("delay 3 h?") · `2:25` architecture card — physics computes / AI judges / validated / built with IBM Bob · `2:45` impact — design-partner verdict, who this is for.

---

## 12. Testing strategy (continuous, from Phase 1)

| Layer | What | How |
|-------|------|-----|
| Physics | SGP4 correctness | Vallado reference TLEs + published positions, < 1 m |
| Physics | Screening correctness | Cross-check vs CelesTrak SOCRATES published close approaches |
| Physics | Pc formula | Published short-term Pc examples, tolerance check |
| Physics | Maneuver sanity | Anti-parallel-to-miss burn must increase miss distance; propellant vs Δv monotonic |
| Integration | CDM replay | Real historical conjunctions re-discovered; measured miss-distance error |
| Agent | Golden path | 6–8 scripted exchanges; correct tools called; card numbers == engine rows |
| Validator | Negative test | Inject wrong number into transcript → blocked/flagged |
| Demo | Rehearsal | Full timed run-through ×3 before recording; golden-path swap drill |

---

## 13. Effort budget & staffing

| Module | Person-days |
|--------|-------------|
| Ingestion (CelesTrak/Space-Track/SWPC/DONKI) | 2.0 |
| Propagation + frames + tests | 2.0 |
| Screening (filter → scan → TCA) | 2.5 |
| Scoring + Pc | 1.5 |
| Maneuver search | 1.5 |
| Storm flags | 0.5 |
| Storage + nightly batch | 2.0 |
| Agent (tools, prompts, session) | 2.5 |
| Validation layer | 1.0 |
| FastAPI | 1.5 |
| Frontend | 4.5 |
| CDM harness + report | 2.0 |
| Deployment | 1.5 |
| Demo / README / video | 3.0 |
| **Total** | **≈ 28 person-days** |

- **Solo:** tight but achievable — IBM Bob-assisted development realistically buys 1.5–2×; cut Cesium entirely, keep CDM report (cheap, high-credibility).
- **2 people:** comfortable — engine lead (Phases 1–2 + harness) / agent+frontend lead (Phases 3–4), swap as needed.
- **3–4 people:** parallel as the role split suggests; integration exercised from Week 3, never the final week.

---

## 14. Risk register (top items)

| Risk | Mitigation |
|------|------------|
| Over-scoping (all judges' #1 concern) | Thin slice Week 1; 2D plots ship, 3D is stretch; Friday go/no-go cuts anything off the frozen list; DELIBERATELY_OUT pinned |
| Simplified Pc mis-ranks events | Rank on miss + Vrel + geometry; Pc displayed with stated assumption; CDM replay = measured accuracy claim |
| LLM fabricates a number on camera | Numbers never transit the model (§7); server-composed cards; validator + audit log; pre-recorded what-if fallback |
| Maneuver search intractable by Aug 21 | **Pivot gate:** ship triage/storm-aware analyst only (DragCast-shaped) — still top-tier |
| Demo fragility | Everything live runs on cached events + fast single-satellite re-prop; golden-path recording swappable instantly; local run script as last resort |
| Space-Track approval delay | CelesTrak (no auth) is primary; SATCAT degrades gracefully; account requested in July |
| Differentiation vs SOCRATES / COMSPOC / LeoLabs | The judgment layer is the product: CDM validation + named design partner + maneuver cards no screening table gives; positioned as decision support/education |
| watsonx.ai quota / outage | Granite 8B is cheap on the free tier; fallback model endpoint; engine + demo work with agent offline |
| Team-formation risk (solo after Aug 5) | Design keeps each module independently testable; Bob accelerates the solo path |

---

## 15. Open items to verify on Discord / FAQ guide

Prize amounts · eligibility (age/country/student) · team-size limits · judging-criteria weights · IP/licensing terms · whether all code must be written inside the Aug 1–31 window · exact submission-platform mechanics. Diff every item in this plan against the official rules the moment clarifications publish.
