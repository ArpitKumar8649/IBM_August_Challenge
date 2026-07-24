# Phase 3 Results — AI Judgment Layer (completed 2026-07-24)

Phase 3 is the make-or-break phase: it turns OrbitWarden from a screening table into an **analyst**. The AI judges (triage, maneuver selection, explanation, what-ifs); the physics computes; and a validation layer guarantees no invented number ever reaches the operator.

## What was built

| Module | Role |
|--------|------|
| `engine/maneuvers.py` | **Shoot-and-score avoidance-maneuver search** using numerical two-body propagation (scipy DOP853). Grid of lead times × directions × magnitudes; propellant via the rocket equation; constraint handling (fuel margin, min post-burn miss, blackout windows); three curated options (cheapest-safe / nominal / conservative). |
| `agent/tools.py` | The **7-tool contract** — the AI's only way to touch numbers. `submit_maneuver_card` is **server-composed**: the agent supplies the burn parameters; the server fills every figure from the engine. |
| `agent/validator.py` | The **output-validation layer** — extracts every number the model writes in prose and verifies it against the set of values that came from tool results (plus the model's own arguments and the operator's stated constraints). Invented numbers are flagged inline. |
| `agent/prompts.py` | System prompt + few-shot encoding the "never invent numbers" contract and the human-in-the-loop principle. |
| `agent/session.py` | The **Granite tool-calling loop** on the proven watsonx REST API. Model-agnostic core (testable offline) with a swappable watsonx backend; supports both blocking and SSE-streaming. |
| `api/main.py` | **FastAPI** layer: satellite/events/maneuvers/space-weather endpoints + `POST /api/chat` (validated) + `GET /api/chat/events` (SSE stream of the agent's reasoning). |

## Key engineering decisions (and the investigations behind them)

### 1. Maneuver prediction: numerical, not Clohessy-Wiltshire
We initially implemented the maneuver search with the Clohessy-Wiltshire (Hill) relative-motion equations — the textbook tool for proximity operations. **Cross-validation against an independent numerical two-body propagator revealed 20–45% linearization error** for km-scale separations over 10-minute arcs (the cross-track component matched to 5 decimals, confirming the frames were correct, but the in-plane linearization diverged). Rather than hide this, we **switched the authoritative prediction to exact numerical two-body propagation** (energy conserved to ~1e-9, orbit closes to <1 m), keeping CW as a documented fast-estimate for explaining the linear Δv→miss sensitivity. This is the honest, industry-correct choice.

### 2. The validator's ground truth — and a subtle collision
The validator verifies prose numbers against the set of values the model legitimately received. During testing we found that a fabricated "99999.9 km" was *not* flagged because it fell within 2% of **99998 — the secondary's NORAD id**, which is in the truth set. This exposed a real limitation: 5-digit fabricated numbers can coincidentally match NORAD IDs. The airtight guarantee is therefore the **server-composed maneuver card** (no model numbers at all); prose validation is defense-in-depth that catches the common case. We also learned to seed the truth set with the model's own tool-call arguments and the operator's stated constraints, so restating those isn't falsely flagged.

### 3. The tool contract is the architecture
The agent never computes an orbit, a probability, or a burn. It calls tools to get numbers and composes prose to explain them. `submit_maneuver_card` takes the specific burn the agent chose and composes the card server-side — so the card's numbers are authoritative regardless of what the model says. This is the concrete realization of "physics computes, AI judges."

## Live demonstration (real Granite, not scripted)

The agent, given *"Plan an avoidance burn for my top conjunction. I have 100 g of propellant margin and want at least a 90 km post-burn miss,"* autonomously:
1. Called `search_maneuvers` with the operator's constraints
2. Interpreted the options and selected a burn
3. Called `submit_maneuver_card` with the specific Δv and lead time
4. Presented a complete maneuver card (Δv, propellant, predicted post-burn miss, assumptions, verification guidance, next steps)

with `audit_passed: True` and **zero unverified markers** — every number traceable to the engine.

## Exit gate — the golden-path integration test
`tests/test_golden_path.py` proves the full contract offline:
1. ✅ A realistic operator exchange drives triage → event detail → maneuver search → server-composed card
2. ✅ The card's numbers match the engine exactly (server-composed)
3. ✅ An invented number is flagged and the audit fails
4. ✅ The card is a recommendation requiring human approval — never autonomous

## Test suite
**108 tests passing** (`pytest tests/`): all of Phases 1–2 plus maneuver engine (numerical validation, rocket equation, constraints), the 7-tool contract, the validator (incl. dash normalization, constraint seeding, fabrication blocking), the agent loop (scripted model), the FastAPI endpoints (TestClient), and the golden-path integration test.

## Known limitations (handed to later phases)
- Prose validation is best-effort (NORAD-ID collisions possible); the server-composed card is the authoritative artifact.
- Maneuver propagation is two-body (no drag/J2 over the short burn arc) — documented in every card's assumptions.
- The agent currently operates over a single screening run's context; multi-turn memory across sessions is a stretch.
