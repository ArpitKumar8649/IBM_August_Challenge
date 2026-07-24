# OrbitWarden 🛰️

> **AI collision-avoidance analyst for smallsat operators.** Screens your satellite against every tracked object in orbit, triages conjunctions with explained risk, designs propellant-aware avoidance maneuvers, and writes the maneuver card — giving a two-person university CubeSat team the collision-avoidance desk of a major operator.
>
> Built for the **IBM AI Builders Challenge — August 2026: Advance Space Exploration with AI**.
> Core design principle: ***physics computes, AI judges*** — a deterministic astrodynamics engine produces every number; an IBM Granite agent judges via strict tool-calling; a validation layer guarantees no AI-invented figure ever reaches the UI.

⚠️ **Status: Phase 2 (complete screening engine) done.** TCA refinement, collision probability, SATCAT enrichment, storm flag, scoring, and persistence — validated against CelesTrak SOCRATES and the SGP4 reference suite. See [`docs/PHASE1_RESULTS.md`](docs/PHASE1_RESULTS.md) and [`docs/PHASE2_RESULTS.md`](docs/PHASE2_RESULTS.md). Build window: Aug 1–31, 2026.

## Problem statement

<!-- Phase 5: fill from ORBITWARDEN_IMPLEMENTATION_PLAN.md §"Problem" -->

## Solution

<!-- Phase 5: fill — screening → triage → maneuvers → maneuver card; human in the loop -->

## AI approach and architecture

<!-- Phase 5: fill — the three planes + validation layer; see ORBITWARDEN_IMPLEMENTATION_PLAN.md §"Architecture" -->

## Selected challenge theme

**August Challenge — Advance Space Exploration with AI.** OrbitWarden targets *mission safety and reliability* and *better decision-making in complex environments*: it turns the raw data of conjunction screening (miss distances, TCA timestamps, covariance) into explained, actionable decisions for the operators who can least afford a mistake.

## How IBM Bob was used

<!-- Phase 5: fill from docs/BOB_LOG.md with concrete examples -->

## Docs

- [`ORBITWARDEN_IMPLEMENTATION_PLAN.md`](ORBITWARDEN_IMPLEMENTATION_PLAN.md) — full engineering blueprint (phases, algorithms, schemas, tool contract)
- [`CHALLENGE_PLAN.md`](CHALLENGE_PLAN.md) — challenge requirements, judged concept rankings, weekly plan
- [`PHASE0_CHECKLIST.md`](PHASE0_CHECKLIST.md) — prep-window tracker
- [`docs/READING_LIST.md`](docs/READING_LIST.md) — domain reading with inline summaries
- [`docs/DELIBERATELY_OUT.md`](docs/DELIBERATELY_OUT.md) — the scope fence
- [`docs/BOB_LOG.md`](docs/BOB_LOG.md) — running log of IBM Bob usage

## License

MIT — see [LICENSE](LICENSE).
