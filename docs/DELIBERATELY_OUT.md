# Deliberately Out of Scope

> Pinned from Week 1. New ideas go to a "roadmap" slide, not the codebase. Stretch goals unlock only after the Week-4 checkpoint passes.

**Not building (MVP):**

- Full-covariance CDM-grade collision probability (we use a documented fixed covariance; ranking is driven by miss + Vrel + geometry)
- Numerical propagation with drag and high-order gravity (SGP4 analytic propagation only)
- Finite-duration burns and full attitude modeling (impulsive-burn approximation)
- Multi-satellite fleet scheduling (one satellite at a time)
- Regulatory coordination filings
- Autonomous execution — **human in the loop, always**; the tool recommends and explains, never acts
- ML trained on historical CDM archives
- Mobile apps / alerting integrations (email/SMS/push)

**Shipped since pinning:** the CesiumJS 3D globe — the one stretch goal that
unlocked early (5.1, Aug 2026) and is now the signature view, replacing the
"2D Recharts only" assumption above. See
[`docs/PHASE5_1_GLOBE_PLAN.md`](PHASE5_1_GLOBE_PLAN.md). Everything else in this
list remains deliberately out.

**Positioning:** decision support and education — never autonomous operations.
