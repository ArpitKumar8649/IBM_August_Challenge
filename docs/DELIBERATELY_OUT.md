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
- CesiumJS 3D globe — **stretch goal only**, unlocked if everything else ships by Aug 25; 2D Recharts plots are the shipping visualization

**Positioning:** decision support and education — never autonomous operations.
