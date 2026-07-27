<div align="center">

# 🛰️ OrbitWarden

### *The collision-avoidance desk for satellites that can't afford one.*

**An AI mission-ops analyst that screens your spacecraft against every tracked object in orbit, explains which conjunctions actually matter, and drafts propellant-aware avoidance maneuvers — with every number provably computed by physics, never invented by a model.**

Built for the **IBM AI Builders Challenge — August 2026 · Advance Space Exploration with AI**

[![Python](https://img.shields.io/badge/Python-3.12-2a78d6?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-18-61dafb?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![IBM Granite](https://img.shields.io/badge/IBM%20Granite-4-0f62fe?logo=ibm&logoColor=white)](https://github.com/ibm-granite-community)
[![Tests](https://img.shields.io/badge/tests-113%20passing-4cd6a4)](#validation--evidence)
[![License](https://img.shields.io/badge/license-MIT-6c7896)](LICENSE)

</div>

---

## The core principle

> **Physics computes. The AI judges. The human decides.**

Most "AI for space" demos bolt a chatbot onto a dataset. OrbitWarden is built the other way around: a **deterministic astrodynamics engine** is the sole source of every number, and an **IBM Granite agent** does the judgment — triage, maneuver selection, explanation — through a strict tool-calling contract. A **validation layer** guarantees that no figure the model invents ever reaches the operator. The maneuver card is **server-composed**: the agent chooses a burn, and the engine fills in the numbers.

This isn't a slogan — it's the architecture, and it's enforced in code and in tests.

---

## Table of Contents

- [Problem Statement](#-problem-statement)
- [Solution](#-solution)
- [Features](#-features)
- [Architecture & AI Approach](#-architecture--ai-approach)
- [Selected Challenge Theme](#-selected-challenge-theme)
- [How IBM Bob Was Used](#-how-ibm-bob-was-used)
- [Quick Start](#-quick-start)
- [Validation & Evidence](#-validation--evidence)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [Tech Stack](#-tech-stack)
- [Roadmap](#-roadmap)
- [License & Acknowledgments](#-license--acknowledgments)

---

## 🎯 Problem Statement

Space exploration operates in one of the most data-rich, high-stakes environments imaginable — and **Low Earth Orbit is getting dangerously crowded.**

- The tracked-object catalog has passed **35,000 objects** and is climbing fast with mega-constellations. Starlink alone executes **thousands of collision-avoidance maneuvers every year.**
- Conjunction alerts are exploding — but the operators who can *least* afford a mistake are the ones with the fewest resources to handle them. **University CubeSat teams and early-stage smallsat startups** receive cryptic close-approach data (miss distances, TCA timestamps) and are expected to decide alone — no experienced analysts, no professional tooling, no time.
- Commercial conjunction-assessment services (COMSPOC, LeoLabs, Slingshot) are **expensive, opaque, and built for large constellations** — inaccessible to a two-person team.

The result is a lose-lose: small operators either **over-maneuver** (burning scarce propellant and shortening mission life) or **under-react** (risking the satellite). The judgment layer — deciding *which* conjunctions are real threats and *how* to respond within tight fuel and mission constraints — is exactly where human expertise is scarce and where the industry has **no affordable answer.**

Despite vast amounts of telemetry, extracting *actionable insight* from it remains hard. **OrbitWarden turns space from data-heavy to insight-driven** — giving a smallsat team the collision-avoidance desk of a major operator.

---

## 💡 Solution

OrbitWarden is a web-based mission-ops decision-support tool. Give it a satellite (by NORAD ID or TLE), and it:

1. **Screens** your spacecraft against the full tracked catalog over the next 7 days, finding every close approach.
2. **Triages** the conjunctions — ranking them by geometry, relative velocity, and *who can maneuver* — with a plain-English rationale for each.
3. **Plans** propellant-aware avoidance maneuvers that meet your constraints (fuel margin, required miss distance, burn blackout windows).
4. **Explains** it all through a conversational Granite analyst you can ask in plain language — *"what's my most urgent conjunction?"*, *"plan a burn, I have 100 g margin and want a 90 km miss."*
5. **Hands you a maneuver card** for approval — with the burn epoch, Δv, propellant cost, predicted post-burn miss, assumptions, and verification guidance.

**The operator stays in the loop.** OrbitWarden recommends and explains; it never executes.

### What makes it different

| | Free tools (SOCRATES) | Commercial SSA | **OrbitWarden** |
|---|---|---|---|
| Screening | ✅ a table of miss distances | ✅ | ✅ |
| Explained triage | ❌ | partial | ✅ plain-English rationale |
| Maneuver planning | ❌ | ✅ (expensive) | ✅ propellant-aware, constraint-driven |
| Conversational analyst | ❌ | ❌ | ✅ Granite, tool-grounded |
| Provably-computed numbers | n/a | n/a | ✅ validation layer + server-composed cards |
| Accessible to a 2-person team | ✅ | ❌ | ✅ free & open-source |

---

## ✨ Features

- **Catalog-wide screening** — altitude-band pre-filter + vectorized SGP4 propagation screens ~18,000 objects in ~2 minutes (SGP4 validated to **< 1 mm** against the reference implementation).
- **Golden-section TCA refinement** — coarse 60 s grid refined to **0.01 s** precision.
- **Collision probability** — Alfriend–Foster short-term encounter model with a B-plane projection and a documented fixed covariance.
- **RSW geometry classification** — in-track / radial / cross-track, with maneuverability awareness (debris and rocket bodies can't move — *you* must).
- **Storm-aware re-screening** — NOAA SWPC + NASA DONKI feed a flag when geomagnetic activity inflates TLE uncertainty near a conjunction's TCA.
- **Avoidance-maneuver search** — shoot-and-score over a grid of burns, using **numerical two-body propagation** (not linearized approximations), with rocket-equation propellant costing and three curated options (cheapest-safe / nominal / conservative).
- **Granite judgment agent** — an 11-tool strict contract; the model's *only* way to touch numbers.
- **Retrieval-augmented analyst (RAG)** — a vector-database memory of space-domain knowledge (conjunction assessment, CDM/ODM standards, collision probability, maneuver planning, drag, validation, operator runbook, sustainability). The analyst answers with **grounded, cited expertise**, not generic prose — see [`docs/RAG_ANALYST.md`](docs/RAG_ANALYST.md).
- **Output-validation layer** — every number the model writes in prose is checked against the engine's outputs; inventions are flagged. Maneuver cards are server-composed.
- **Mission-control dashboard** — live conjunction board with ticking TCA countdowns, RSW geometry, maneuver options, and the analyst chat.
- **Validated against ground truth** — replayed against CelesTrak SOCRATES and real Space Surveillance Network CDMs (see [Validation](#-validation--evidence)).

### 🔬 Advanced astrodynamics (NASA-level physics)

Beyond SGP4 screening, OrbitWarden adds high-fidelity physics where it matters — see [`docs/ADVANCED_ASTRODYNAMICS.md`](docs/ADVANCED_ASTRODYNAMICS.md):

- **NRLMSISE-00 atmospheric drag** (`engine/atmosphere.py`) — NASA's empirical thermosphere model (via `pymsis`), space-weather-driven; makes the storm flag *quantitative* (density inflates ~1.7× during a geomagnetic storm).
- **Precision numerical propagation** (`engine/precision.py`) — J2 geopotential + drag + solar radiation pressure (scipy DOP853, 1e-11 tolerances). **Two-tier fidelity:** SGP4 screens the many; numerical propagation confirms the few that matter — exactly how operational centers work.
- **Realistic collision probability** (`engine/covariance.py`) — the *general* 2-D Alfriend–Foster formula for arbitrary (correlated) covariance, plus a documented **covariance realism factor** (Foster/Hall). Correctly captures the non-monotonic Pc-vs-covariance behavior for off-center misses.
- **Fuel-optimal maneuvers** (`engine/fuel_optimal.py`) — the **minimum-Δv** burn for a target miss, optimized via the Clohessy-Wiltshire state-transition matrix and verified numerically. Beats a naive in-track burn.
- **CCSDS CDM/ODM standards** (`engine/standards.py`) — generates standards-compliant Conjunction Data Messages (CCSDS 508.0-B-1) and Orbit Mean-Elements Messages (CCSDS 502.0-B-2) — interoperable with operational SSA tooling.

---

## 🏗️ Architecture & AI Approach

OrbitWarden is three planes with a hard separation of concerns, plus a trust layer between the AI and the operator.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION PLANE (React)                          │
│   Landing page · Mission-control dashboard · Analyst chat (SSE)            │
└───────────────────────────────────────▲──────────────────────────────────┘
                                        │  REST + Server-Sent Events
┌───────────────────────────────────────┴──────────────────────────────────┐
│                          API PLANE (FastAPI)                                │
│   /api/events · /api/events/{id}/maneuvers · /api/chat · /api/space-weather │
└───────────────▲───────────────────────────────────────▲──────────────────┘
                │                                        │
   ┌────────────┴──────────────┐         ┌───────────────┴─────────────────┐
   │   AI JUDGMENT PLANE        │         │   DETERMINISTIC PHYSICS PLANE    │
   │   (IBM Granite on watsonx) │  tools  │   (Python astrodynamics engine)  │
   │                            │────────▶│                                  │
   │  · 7-tool strict contract  │         │  · SGP4 propagation (<1mm)       │
   │  · triage & rationale      │         │  · band filter + coarse scan     │
   │  · maneuver selection      │         │  · golden-section TCA refine     │
   │  · what-if reasoning       │         │  · Alfriend–Foster Pc (B-plane)  │
   │  · server-composed cards   │         │  · RSW geometry + risk scoring   │
   └────────────┬───────────────┘         │  · numerical maneuver search     │
                │                          │  · SATCAT + space-weather ingest │
   ┌────────────┴───────────────┐         └────────────────▲─────────────────┘
   │   OUTPUT-VALIDATION LAYER   │                          │
   │   · numbers never transit   │      every number flows  │
   │     the model               │      from the engine ────┘
   │   · prose numbers verified  │
   │     against tool outputs    │
   │   · audit trail             │
   └─────────────────────────────┘
```

### The AI approach, in detail

**1. The model never computes.** The Granite agent is given seven tools (`list_conjunctions`, `get_event_details`, `search_maneuvers`, `repropagate_with_burn`, `get_space_weather`, `get_satellite_info`, `submit_maneuver_card`). These are its *only* way to touch numbers. It does judgment — triage, selection, explanation, what-ifs — and composes prose. It never propagates an orbit, computes a probability, or designs a burn.

**2. The card is server-composed.** When the agent decides on a maneuver, it calls `submit_maneuver_card` with the *burn parameters it selected*. The **server** computes the post-burn miss distance and propellant from the engine and assembles the card. The model supplies prose; the engine supplies figures. The card's numbers are authoritative regardless of what the model says.

**3. Prose is validated.** For the model's free-form explanations, the validation layer extracts every number it writes and verifies it against the set of values that actually came from tool results (plus the model's own arguments and the operator's stated constraints). Anything invented is flagged inline (`⚠[unverified]`) before it reaches the operator, and logged to an audit trail.

**4. The physics is honest about itself.** Maneuver prediction uses **numerical two-body propagation** (scipy DOP853), not linearized Clohessy-Wiltshire equations — we cross-validated CW against a numerical propagator and found 20–45% linearization error at kilometer-scale separations, so we use the exact method and keep CW only as a documented fast-estimate. The collision probability uses a **documented fixed covariance** (a true Pc needs each object's tracking covariance, which only CDM issuers have) — stated openly in the UI and the card's assumptions.

This is the concrete realization of *"physics computes, AI judges."* It turns the classic hackathon weakness — an LLM fabricating math — into the central design principle.

---

## 🎯 Selected Challenge Theme

**August Challenge — Advance Space Exploration with AI.**

OrbitWarden directly addresses the challenge's call to *"transform space exploration from data-heavy to insight-driven systems, enabling smarter missions and making space more accessible."* It maps to the theme's guiding questions:

- **"How can AI improve mission safety and reliability?"** — by screening every tracked object and triaging the conjunctions that actually threaten the spacecraft.
- **"How can AI support better decision-making in complex environments?"** — by turning raw miss-distance data into explained, ranked, actionable decisions with propellant-aware maneuver options.
- **"How can AI make space data more usable and accessible?"** — by giving a two-person university team, in plain language, the collision-avoidance capability that previously required an expensive commercial service.

AI is a **core functional component**, not a bolt-on: the judgment layer *is* the product. And **IBM Bob is the primary development tool** (see below), with **IBM Granite on watsonx.ai** as the reasoning engine.

---

## 🛠️ How IBM Bob Was Used

**IBM Bob is the primary development tool for OrbitWarden.** As an AI-powered development partner (a standalone IDE + terminal agent), Bob was used across the entire build — and its usage is documented in [`docs/BOB_LOG.md`](docs/BOB_LOG.md) as we go.

> **Note on process:** OrbitWarden's deterministic engine and architecture were designed and validated ahead of the August 1 build window (project creation opens at launch). During the official build window, the implementation is driven through IBM Bob as the primary tool, with usage logged for this section. The patterns below are how Bob is applied to each part of the system.

### Where Bob does the heavy lifting

| Area | How Bob is used |
|------|-----------------|
| **Engine modules** | Generating and iterating `engine/` modules from precise specs and pydantic models — propagation, screening, scoring, maneuvers. |
| **Test generation** | Writing pytest suites from descriptions — e.g. *"test SGP4 against Vallado's reference vectors,"* *"test the validator flags an invented number."* |
| **Debugging loops** | The structured analyze → recommend → apply → validate pattern (the SkillsBuild troubleshooting workflow) for chasing down issues like the CW linearization error and the TLE-vintage sensitivity. |
| **Agent wiring** | Building the tool contract, prompts, and the tool-calling loop. |
| **Frontend** | Generating React components and CSS from the design system. |
| **Refactoring & docs** | Splitting modules, writing docstrings, drafting README sections from the code. |

### What we capture (in `docs/BOB_LOG.md`)

For each significant task: the prompt given to Bob, what Bob produced, what we iterated on, and the time saved. This makes the "primary development tool" claim concrete and auditable — not asserted.

### Bob setup

IBM Bob is a standalone application (not a VS Code extension). See [`docs/IBM_BOB_GUIDE.md`](docs/IBM_BOB_GUIDE.md) for installation, the three modes (Plan / Agent / Ask), and the Bobcoin trial budget strategy.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+, Node20+
- A Space-Track.org account (free) and a NASA API key (free) for live data
- IBM Cloud credentials (watsonx.ai) for the live analyst

### 1. Backend — the engine + API

```bash
# install Python deps
pip install -r requirements.txt

# configure secrets (never committed)
cp .env.example .env   # then fill in SPACETRACK_*, NASA_API_KEY, WATSONX_*

# run a screening pass to populate the database
python -m batch.nightly --norad 25544 --days 7

# start the API (serves the latest screening run)
uvicorn api.main:app --reload --port 8000
```

### 2. Frontend — landing page + mission control

```bash
cd web
npm install
npm run dev          # → http://localhost:5173
```

The dashboard shows a **LIVE API** indicator when the backend is reachable, and falls back to a bundled sample dataset otherwise — so it's always alive.

### 3. One-command screening (CLI)

```bash
python -m engine.cli --norad 25544 --days 7 --top 15 --enrich
```

### 4. Reproduce the validation

```bash
python -m validation.cdm_validate --days 30 --limit 15 --json data/cdm_validation.json
python -m validation.socrates_crosscheck --events 10
```

---

## 🔬 Validation & Evidence

OrbitWarden isn't just built — it's **validated against ground truth.**

### SGP4 accuracy — sub-millimeter

The propagation wrapper reproduces the `sgp4` library's **own official verification suite** (SGP4-VER.TLE / tcppver.out, 33 cases) to **< 1 mm** on every valid case, and correctly masks error cases. This is the strongest possible correctness guarantee: we match the reference implementation's published vectors.

### CelesTrak SOCRATES cross-check — 9/10

Re-screening the top close approaches published by CelesTrak SOCRATES, OrbitWarden independently reproduces **9 of 10** events with **TCA within 1.1 s** and **relative velocity within 0.07%.**

### Real CDM replay — the headline result

Replaying **15 real conjunctions** that the operational Space Surveillance Network flagged (CDM_PUBLIC), using **era-correct TLEs** (the TLE each CDM was based on, via `gp_history`):

| Metric | Result |
|--------|--------|
| **Detection** | **11/15 (73%)** — the 4 misses are all *"no era TLE available"* (debris fragments without history), **not engine failures** |
| **Miss distance** | **median 1.07×** — km-scale conjunctions agree **0.88–1.23×** with the CDM's *precision* propagation |
| **TCA** | **median 0.09 s**, max 3.1 s |

**Honest interpretation:** kilometer-scale conjunctions agree to ~20% with precision propagation; sub-kilometer conjunctions show the expected SGP4-vs-precision spread — but **every one is still detected with sub-second TCA.** We characterize this gap rather than hide it, and it motivates two design choices: ranking on robust quantities (geometry, timing), and the storm/staleness re-screen flag.

📄 Full report: [`docs/CDM_VALIDATION_REPORT.md`](docs/CDM_VALIDATION_REPORT.md) · interactive chart: [`docs/cdm_validation_chart.html`](docs/cdm_validation_chart.html)

### Test suite

**113 tests passing** across the engine, agent, validator, API, and integration (golden-path) tests. CI runs `pytest` on every push.

---

## 📁 Project Structure

```
IBM_August_Challenge/
├── engine/                     # deterministic physics plane
│   ├── ingest/                 # CelesTrak, Space-Track (SATCAT), space weather
│   ├── propagate.py            #   vectorized SGP4 wrapper
│   ├── frames.py               #   RSW frame transforms
│   ├── screen.py               #   band filter → coarse scan → full scored pipeline
│   ├── tca.py                  #   golden-section TCA refinement
│   ├── pc.py                   #   Alfriend–Foster collision probability (B-plane)
│   ├── covariance.py           #   general 2-D Pc + covariance realism factor
│   ├── atmosphere.py           #   NRLMSISE-00 density & drag (pymsis)
│   ├── precision.py            #   numerical propagation: J2 + drag + SRP
│   ├── fuel_optimal.py         #   minimum-Δv maneuver (CW-optimized, verified)
│   ├── standards.py            #   CCSDS CDM/ODM message generation
│   ├── scoring.py              #   geometry classification + risk score
│   ├── maneuvers.py            #   numerical shoot-and-score maneuver search
│   ├── storage.py              #   SQLite persistence (Postgres-ready schema)
│   ├── models.py               #   shared pydantic models
│   └── cli.py                  #   one-command screening
├── agent/                      # AI judgment plane
│   ├── tools.py                #   the 11-tool contract
│   ├── prompts.py              #   system prompt + few-shot
│   ├── session.py              #   Granite tool-calling loop (watsonx REST)
│   ├── validator.py            #   output-validation layer
│   ├── knowledge.py            #   space-domain knowledge base (RAG)
│   ├── embedder.py             #   watsonx embeddings + offline hashing fallback
│   ├── vectorstore.py          #   cosine-similarity vector store (pgvector-ready)
│   └── rag.py                  #   retrieval-augmented generation
├── api/                        # FastAPI layer (REST + SSE)
├── batch/                      # nightly screening orchestration
├── validation/                 # SOCRATES + CDM validation harnesses
├── web/                        # React + Vite + TypeScript frontend
│   └── src/
│       ├── pages/              #   Landing + Dashboard
│       ├── components/         #   OrbitScene, charts, clocks, reveals
│       ├── lib/                #   API client (with sample fallback)
│       └── styles/             #   design system
├── tests/                      # 113 tests
├── docs/                       # results, reports, guides
└── .github/workflows/ci.yml    # CI
```

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Service status + primary satellite |
| `GET` | `/api/satellite` | Primary satellite info |
| `GET` | `/api/satellites/{norad_id}` | Catalog object info |
| `GET` | `/api/events?limit=N` | Ranked conjunctions |
| `GET` | `/api/events/{id}` | Event detail (RSW geometry, Pc, risk) |
| `GET` | `/api/events/{id}/maneuvers` | Avoidance-maneuver options |
| `GET` | `/api/space-weather` | Geomagnetic conditions |
| `POST` | `/api/chat` | Analyst conversation (validated) |
| `GET` | `/api/chat/events?message=…` | Analyst reasoning stream (SSE) |

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI model** | IBM Granite 4 (`ibm/granite-4-h-small`) on **watsonx.ai** |
| **AI dev tool** | **IBM Bob** (primary development tool) |
| **Physics** | `sgp4` (vectorized), `scipy` (DOP853, Brent), `numpy`, `pymsis` (NRLMSISE-00 atmospheric model) |
| **Backend** | Python 3.12, FastAPI, pydantic, SQLite (Postgres-ready) |
| **Frontend** | React 18, TypeScript, Vite |
| **Data** | CelesTrak, Space-Track (SATCAT, CDM_PUBLIC, gp_history), NOAA SWPC, NASA DONKI |
| **Deployment** | IBM Cloud Code Engine (serverless) |
| **Optional** | LangChain / LangGraph (the agent uses the watsonx REST API directly) |

---

## 🗺️ Roadmap

- [ ] Graded storm-uncertainty band (beyond the binary flag)
- [ ] Multi-turn analyst memory across sessions
- [ ] pgvector similar-encounter retrieval ("what did we recommend for a geometry like this?")
- [ ] Design-partner trial with a university CubeSat team
- [ ] Precision-ephemeris option for sub-km conjunctions
- [ ] Mobile / alerting integrations

---

## 📄 License & Acknowledgments

Released under the [MIT License](LICENSE).

Built for the **IBM AI Builders Challenge — August 2026**, on [IBM Bob](https://www.ibm.com/products/bob), [IBM Granite](https://github.com/ibm-granite-community), and [watsonx.ai](https://cloud.ibm.com). Orbital data courtesy of [CelesTrak](https://celestrak.org) and [Space-Track.org](https://www.space-track.org).

<div align="center">

*Physics computes. The AI judges. The human decides.*

</div>
