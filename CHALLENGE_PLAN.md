# IBM AI Builders Challenge — August 2026: Full Breakdown & Build Plan

> Theme: **Advance Space Exploration with AI** · Platform: AI Builders Challenge with IBM Bob (BeMyApp)
> Prepared 2026-07-24 from the official challenge brief. Analysis produced by a 26-agent workflow: 6 concepts (one per official solution angle) × 3 judges (IBM-technical, innovation/impact, feasibility-skeptic) scored against the 5 official criteria, then a build plan for the winner.

---

## 1. What the challenge is

Build an **AI-powered solution that advances space exploration** — turning space from data-heavy to insight-driven: smarter missions, better decisions, more accessible space data. Example areas from the brief: mission-planning assistants, predictive spacecraft monitoring/anomaly detection, debris tracking & collision avoidance, space-data translation tools, astronomy research aids, satellite data analysis, ops decision-support, space education/engagement.

Two hard rules define eligibility:
1. **IBM Bob must be the primary development tool.**
2. **AI must be a core functional component** of the solution (not a bolt-on).

Each team may submit **one project per month** to either the August Challenge or the Wildcard Challenge.

## 2. What you must deliver (submission requirements)

All due by **Monday, August 31, 2026, 11:59 PM ET**, via a published project page on the challenge platform:

| # | Artifact | Details |
|---|----------|---------|
| 1 | Working prototype / PoC | Built with IBM Bob as primary dev tool |
| 2 | IBM SkillsBuild learning activity | Completed (certificate is evidence) |
| 3 | Public GitHub repo | README must include: problem statement · solution description · AI approach & architecture · selected challenge theme · how IBM Bob was used |
| 4 | Published project page | Project + team details · GitHub link · **publicly accessible demo video, max 3 minutes** |

⚠️ Repo and video must be **publicly accessible** — judges review and score from them.

## 3. Judging criteria (what wins)

| Criterion | Meaning |
|-----------|---------|
| **Technical Execution** | Quality of implementation; effective use of AI and IBM technologies |
| **Innovation** | Creativity, originality, uniqueness |
| **Challenge Fit** | Alignment with the space-exploration theme |
| **Feasibility** | Practicality and real-world implementation potential |
| **Real-World Impact** | Meaningful value addressing real needs |

## 4. Timeline (from today,2026-07-24)

| Date | Event |
|------|-------|
| **Now → Jul 31** | Prep window (no project code yet): IBM Bob trial, SkillsBuild activity, Discord, API accounts, team scouting, domain reading |
| **Aug 1 (Sat)** | Challenge launches; project creation opens; GitHub Learning Lab opens |
| **Aug 3 (Mon) 10 AM ET** | Kickoff webinar |
| **Aug 5 (Wed) 10 AM ET** | Team formation webinar |
| TBA | IBM technical workshop |
| **Aug 31 (Mon) 11:59 PM ET** | **Submission deadline** |
| Sep 1–11 | Judging (August Challenge + Overall Grand Prize from July+August finalists) |
| Sep 16 | IBM Bob Virtual Conference — winners announced |

## 5. Encouraged technology

IBM Granite · watsonx · LangChain/LangFlow · space-related APIs · vector databases · open-source AI tools · Python, Node.js, React, Next.js. Additional tech welcome.

## 6. Project concepts — judged & ranked

Six concepts were generated (one per official solution angle) and scored by three judges on the five official criteria (max 50 each):

| Rank | Concept | Angle | Avg | Judge totals |
|------|---------|-------|-----|--------------|
| 🥇 1 | **OrbitWarden** — AI collision-avoidance analyst for smallsat operators | Debris tracking / mission ops | **39.0** | 37 · 40 · 40 |
| 🥈 2 | **DragCast** — storm-aware conjunction screening (which alerts are geomagnetic-storm noise?) | Debris tracking | 36.0 | 37 · 35 · 36 |
| 🥉 3 | **FloodSight** — AI SAR flood mapping + population exposure for disaster response | Satellite data analysis | 35.0 | 36 · 36 · 33 |
| 4 | **AuroraDesk** — AI space-weather newsroom: telemetry → plain-English aurora forecast | Data accessibility | 34.7 | 33 · 37 · 34 |
| 5 | **OrbitPulse** — orbital decay prediction & anomaly detection over LEO constellations | Anomaly detection | 34.3 | 39 · 28 · 36 |
| 6 | **TransientTriage** — real-time classification of ZTF's million-alerts/night transient firehose | Astronomy research | 33.3 | 33 · 35 · 32 |

**Why OrbitWarden won:** the cleanest AI-core architecture in the field — *"physics computes, AI judges."* A deterministic astrodynamics engine produces every number; the Granite agent does genuine judgment work (triage, constraint-aware maneuver selection, maneuver-card drafting, what-if reasoning) via strict tool-calling; a validation layer re-checks every figure before display. This turns the classic hackathon weakness (LLMs fabricating math) into the central design principle. All data is public/free, there's no hardware and no ML-research risk, and the wedge is vivid: a two-person university CubeSat team gets the collision-avoidance desk of a major operator.

---

## 7. Recommended build: OrbitWarden

### Problem
LEO is crowded and getting worse: the tracked-object catalog exceeds ~35,000 and Starlink alone executes thousands of collision-avoidance maneuvers per year. The operators who can least afford a mistake — university CubeSat teams, early-stage smallsat startups — receive cryptic close-approach data but lack the analysts, tooling, and time to triage weekly conjunctions and design fuel-efficient avoidance burns. Commercial conjunction-assessment services are expensive and built for large constellations. Small operators either over-maneuver (burning scarce propellant, shortening mission life) or under-react (risking the satellite). **The judgment layer is exactly where expertise is scarce and no affordable answer exists.**

### Solution
A web-based mission-ops decision-support tool. Given a satellite (NORAD ID or TLE):
- A **Python astrodynamics engine** propagates the spacecraft and the CelesTrak/Space-Track catalog with SGP4, pre-filters by altitude band, finds close approaches over a 7-day window (coarse scan + golden-section TCA refinement), and scores events on miss distance, relative velocity, approach geometry, and object size/type.
- A **numeric maneuver search** applies candidate impulsive burns inside the propagator and scores them by post-burn miss distance per gram of propellant → 2–3 options.
- A **Granite agent on watsonx.ai** (strict tool/function-calling) does the analyst's job: triages and ranks events with plain-English rationale, selects a maneuver against natural-language operator constraints ("50 g fuel margin, no burns during Tuesday's downlink"), drafts a standard-format maneuver card (burn epoch, Δv, propellant cost, verified post-burn miss distance, rollback plan), and answers what-ifs by re-invoking physics tools.
- A **NOAA SWPC / NASA DONKI feed** flags events whose prediction window straddles a geomagnetic storm (TLE uncertainty inflation → re-screen).
- The human stays in the loop. The AI recommends and explains; it never executes.

### What the AI actually does (why it's core, not a wrapper)
1. **Multi-factor triage & risk ranking** with written rationale — judgment, not arithmetic.
2. **Constraint-aware maneuver selection** from engine-generated options.
3. **Operational product generation** — maneuver cards and operator bulletins.
4. **Interactive what-if reasoning** — "what if we delay the burn 3 hours?" re-invokes propagation tools.
Without the AI the product is a table of miss distances; with it, a decision-support analyst.

### Data sources (all public, free)
- **CelesTrak NORAD GP catalog** (active, stations/debris, Starlink, OneWeb, GEO) — no auth
- **Space-Track.org** (free account) — SATCAT object metadata + **CDM_PUBLIC** to validate the engine against real historical conjunctions
- **NOAA SWPC** 3-day forecast + **NASA DONKI** — storm flags
- **ISS TLEs** — ready-made recognizable demo scenario

### Architecture: three planes + a trust layer
1. **Deterministic physics plane (Python):** the sole source of every number — SGP4 propagation, band pre-filtering, TCA refinement, event scoring, documented fixed-covariance Pc (assumption stated in UI), shoot-and-score maneuver grid. Nightly cached batch + on-demand single-satellite re-propagation.
2. **AI judgment plane:** Granite on watsonx.ai as a strict tool-calling agent (LangChain/LangGraph). Never computes an orbit. Fallback model endpoint configured.
3. **Presentation plane:** React + TypeScript dashboard — ranked event list, 2D TCA-geometry and maneuver-tradeoff plots (Recharts, v1), maneuver-card view, ask-the-analyst panel. **CesiumJS 3D globe = stretch goal only.**
4. **Output-validation layer (between 2 and 3):** deterministic pydantic/regex checker re-verifies every figure in any AI product against engine output; blocks display on mismatch; logs all checks → the demo's "provably computed" claim.

**Infra:** Postgres + pgvector (screening results, event history, agent transcripts → similar-encounter retrieval) · FastAPI · IBM Cloud Code Engine (serverless API + nightly batch) · IBM Bob as primary pair-programmer across all planes, usage logged for the README.

### Demo video plan (≤3 min)
Hook (catalog >35k objects, CubeSat teams decide alone) → live dashboard: pick a real satellite, ranked 7-day events with AI one-liners → deep dive on top event (TCA geometry, SATCAT object card, storm-flag banner) → the decision: operator states constraints, AI returns 3 verified maneuver options + maneuver card, answers a live what-if → architecture card ("physics computes, AI judges," built with IBM Bob) → impact. The what-if segment is pre-recorded as a golden-path fallback.

---

## 8. Execution plan

### Prep: now → July 31 (no project code — creation opens Aug 1)
- [ ] Create & verify an **IBM Bob trial account** in your editor
- [ ] Complete the required **IBM SkillsBuild learning activity**; save the certificate
- [ ] Join the challenge **Discord**; watch #august-challenge-and-learning
- [ ] Register a free **Space-Track.org** account now (approval can lag; ~3,000 queries/day limit)
- [ ] Get a **NASA API key** (DONKI, free/instant); verify CelesTrak + SWPC endpoints reachable
- [] Create an **IBM Cloud** free-tier account; confirm watsonx.ai (Granite) + Code Engine access; do a throwaway "hello Granite" tool-calling tutorial (practice only)
- [ ] Plan for the **Aug 5 team webinar**: recruit 2–4 people, pre-agree roles (engine lead, agent/backend lead, frontend lead, demo/README/validation owner)
- [ ] Domain reading: SGP4/TLE basics, short-term collision probability & covariance caveats, CCSDS CDM format, CelesTrak SOCRATES (the free incumbent to differentiate from), Starlink maneuver statistics
- [ ] Team logistics: branching model, license (MIT/Apache-2.0), shared demo-assets folder

### Week 1 (Aug 1–7) — foundation + thin end-to-end skeleton
Repo scaffolded (license, CI, DELIBERATELY-OUT list pinned in README) · CelesTrak ingestion + SGP4 module tested against reference orbits · coarse screening of one real satellite (ISS or public CubeSat) against a curated ~2–3k LEO subset · IBM Bob workflow + usage log started · team finalized Aug 5.

### Week 2 (Aug 8–14) — complete the screening engine
Band pre-filtering, vectorized SGP4, golden-section TCA refinement, event scoring (miss distance, Vrel, geometry, hard-body radius, documented fixed-covariance Pc) · top-20 ranked events for a real satellite · nightly cached batch in Postgres · SWPC/DONKI storm flags · Space-Track SATCAT enrichment (CelesTrak-only fallback).

### Week 3 (Aug 15–21) — the AI judgment layer (make-or-break)
Shoot-and-score maneuver grid (2–3 options, Δv + grams burned from user-supplied mass/Isp, verified post-burn miss distance) · Granite tool-calling agent: triage rationale, constraint-aware selection, maneuver-card drafting, what-if re-runs · output-validation layer with audit log · **by Aug 21: one event flows end-to-end from engine to validated maneuver card.**

### Week 4 (Aug 22–28) — dashboard, validation, deployment
React dashboard (event list + rationales, 2D plots, storm banners, maneuver card, analyst panel) · **CDM_PUBLIC validation report**: replay 3–5 documented historical conjunctions, show OrbitWarden re-discovering each (one-page precision/recall-style report — converts "simplified Pc" from liability to measured claim) · Code Engine deployment with live demo URL · design-partner verdict from a real university CubeSat team. CesiumJS globe only if everything above is done by Aug 25.

### Final days (Aug 29–31) — packaging only, no new features after Aug 28
Final README (problem, solution, AI approach/architecture, theme, how IBM Bob was used) · ≤3-min demo video recorded/hosted · project page published · compliance check · **submit by Aug 30** so Aug 31 is pure buffer.

### Top risks & mitigations
| Risk | Mitigation |
|------|------------|
| Over-scoping (all 3 judges' #1 concern) | Week 1 ships a thin slice (one satellite, ~2–3k-object subset, one maneuver card); 2D plots ship, 3D globe is stretch; Friday go/no-go cuts anything off the frozen MVP list |
| Simplified collision probability mis-ranking | Rank on miss distance + Vrel + geometry; show Pc only from a documented fixed covariance with the assumption in the UI; CDM_PUBLIC replay as a measured accuracy claim |
| LLM fabricating numbers on camera | Strict tool-calling contract + validation layer re-checking every figure; fallback model endpoint; pre-recorded what-if golden path |
| Demo fragility | All live interactions run on cached events + fast single-satellite re-propagation; golden-path recording swappable instantly |
| Space-Track approval delay | CelesTrak (no auth) is primary; SATCAT enrichment degrades gracefully |
| Differentiation vs. free SOCRATES / commercial SSA | The judgment layer IS the product: CDM validation report + named design partner + maneuver cards no screening table provides; positioned as decision support/education, never autonomous ops |
| Scope creep | DELIBERATELY-OUT list pinned in README from Week 1 (no full covariance CDMs, no numerical propagation, no finite burns, no fleet mode, no autonomous execution) |

### Submission checklist
- [ ] Public GitHub repo, clean Aug 1–31 commit history, license file
- [ ] README with all 5 required sections incl. concrete "How IBM Bob was used" examples
- [ ] Demo video ≤3 min (hosted link + copy in repo)
- [ ] Published project page with video + repo link + team details
- [ ] SkillsBuild completion evidence
- [ ] Working IBM stack: Granite on watsonx.ai, Code Engine hosting (live demo URL recommended, cached data for speed)
- [ ] CDM_PUBLIC validation report in repo
- [ ] Repo + video verified PUBLIC on Aug 30; submit with a day of buffer

### Pivot options (if dependencies stall)
- **DragCast (36/50)** — its storm-physics angle is already folded into OrbitWarden as the SWPC/DONKI flag; pivot fully if maneuver search proves intractable in Week 3.
- **FloodSight (35/50)** — simpler data story (open Sentinel-1 SAR, IBM/NASA Prithvi-EO-2.0 segmentation) but harder CV workload; fallback if space-data dependencies block.

## 9. Open questions the brief doesn't answer
Verify on Discord / FAQ guide: **prize amounts**, eligibility rules (age/country/student status), **team size limits**, judging-criteria weights, IP/licensing terms, whether all code must be written inside the Aug 1–31 window, and the exact submission-platform mechanics.
