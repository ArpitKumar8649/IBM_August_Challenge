# Advanced Astrodynamics & Conjunction-Assessment Science

> OrbitWarden's physics, deepened to be credible to a flight-dynamics engineer.
> This document covers the five advanced modules added on top of the validated
> SGP4 screening engine, the physics behind each, and the honest assumptions.

---

## Overview

The base engine (Phases 1–2) uses **SGP4** for catalog-wide screening — fast,
analytic, validated to <1 mm against the reference implementation, and shown to
reproduce real CDMs to ~1.07× miss ratio. SGP4 is the right tool for screening
18,000 objects quickly.

These advanced modules add **high-fidelity physics where it matters** — for the
conjunctions that rise to the top, and for the maneuvers that protect the
spacecraft:

| Module | File | What it adds |
|--------|------|--------------|
| Atmospheric density & drag | `engine/atmosphere.py` | NRLMSISE-00 density, space-weather-driven drag |
| Precision propagation | `engine/precision.py` | Numerical propagation with J2, drag, SRP |
| Realistic collision probability | `engine/covariance.py` | General 2-D Pc + covariance realism factor |
| Fuel-optimal maneuvers | `engine/fuel_optimal.py` | Minimum-Δv burn for a target miss (CW-optimized, numerically verified) |
| CDM/ODM standards | `engine/standards.py` | CCSDS-standard Conjunction & Orbit Data Messages |

---

## 1. Atmospheric Density & Drag — NRLMSISE-00

**File:** `engine/atmosphere.py`

### The physics
Atmospheric drag is the **dominant non-gravitational perturbation in LEO** and
the main reason TLEs go stale. The drag acceleration is:

```
a_drag = −½ · (Cd·A/m) · ρ · |v_rel| · v_rel
```

where `Cd·A/m` is the **ballistic coefficient** and `ρ` is the atmospheric mass
density. Density in the thermosphere varies by *orders of magnitude* with
altitude, solar activity (F10.7), and geomagnetic activity (Kp/Ap).

### The model
We use **NRLMSISE-00** (Picone et al. 2002), NASA's empirical thermosphere
model, via the `pymsis` wrapper. It takes altitude, location, and space-weather
indices (F10.7, F10.7a, Ap) and returns the total mass density.

**Verified behavior:**
- Density at 400 km: ~3.6×10⁻¹² kg/m³ (correct order of magnitude)
- Monotonic decrease with altitude (200→800 km spans ~4 orders of magnitude)
- **Storm inflation:** Ap=200 (storm) inflates 400 km density by ~1.7× vs Ap=4 (quiet)
- Solar-activity dependence: higher F10.7 → higher density

### Why it matters
This makes the **storm flag quantitative**: instead of a binary "storm / no
storm," the predicted miss *band* widens with geomagnetic activity, because the
density (and thus drag uncertainty) genuinely increases. It's the physical basis
for "re-screen within 24 h of TCA during a storm."

---

## 2. Precision Numerical Propagation — J2 + Drag + SRP

**File:** `engine/precision.py`

### The physics
For the conjunctions that matter, we propagate with a high-fidelity numerical
integrator (scipy DOP853, tolerances 1e-11) including:

- **J2 (and optional J3) geopotential** — Earth's equatorial bulge, the largest
  perturbation for LEO. Causes nodal regression and perigee precession.
  ```
  a_J2 = −(3/2)·J2·(μ·R_E²/r⁵)·[x(1−5z²/r²), y(1−5z²/r²), z(3−5z²/r²)]
  ```
  with J2 = 1.08262668×10⁻³.

- **Atmospheric drag** — from NRLMSISE-00 (above), space-weather-driven.

- **Solar radiation pressure (SRP)** — cannonball model:
  ```
  a_SRP = −P·Cr·(A/m)·ŝ_sun,   P ≈ 4.56×10⁻⁶ N/m² at 1 AU
  ```

### Verified behavior
- **Two-body energy conservation:** with perturbations off, energy conserved to
  ~1e-8 and the orbit closes to <10 m after one period.
- **J2 nodal regression:** an inclined orbit does *not* close after one period
  (J2 perturbs it) — the expected behavior.
- **Drag orbital decay:** with drag on, orbital energy and altitude *decrease*
  over 10 orbits — the expected decay.
- **SRP direction:** acceleration is anti-sunward; magnitude ~6×10⁻¹¹ km/s² for
  a small satellite (correct order).
- **Backward propagation** inverts forward propagation (two-body) to <1e-4 km.

### The two-tier fidelity design
This is the key architectural choice: **SGP4 for the many, numerical for the
few.** Screening 18,000 objects with numerical propagation would be too slow;
but the handful of high-risk conjunctions deserve precision. OrbitWarden
triages with SGP4, then *confirms* the top events with full perturbations —
exactly how operational centers work.

---

## 3. Realistic Collision Probability — General 2-D Pc + Covariance Realism

**File:** `engine/covariance.py`

### The physics
The base engine (`engine/pc.py`) uses the Alfriend–Foster short-term encounter
probability with a **fixed diagonal covariance**. This module adds two things:

**(a) The general 2-D formula** for an arbitrary (possibly correlated) combined
covariance projected onto the B-plane:

```
Pc = HBR² / (2·√det Σ_bp) · exp(−½ · m_bpᵀ · Σ_bp⁻¹ · m_bp)
```

This reduces to the fixed-covariance formula when Σ_bp is diagonal, but
correctly handles correlated covariance on an arbitrary B-plane.

**(b) A covariance realism factor** (Foster/Hall methodology). Real Pc needs
each object's tracking covariance, which only CDM issuers possess. The standard,
honest bridge is to inflate the analytic covariance by a factor *k*:

```
Σ_real = k · Σ_analytic,   k ∈ [1.5, 3] typical for LEO TLE screening
```

We use a documented default of **k =2.0**, stated openly in the UI and the
maneuver card — not hidden.

### An important physics subtlety (and why we test it)
A naive intuition says "more uncertainty → lower Pc." **This is only true for a
miss at the origin.** For an *off-center* miss, Pc is **non-monotonic** in
covariance: increasing covariance first *increases* Pc (spreading probability
density toward the hard body) before dilution dominates. Our tests verify this
peak exists rather than assuming monotonic dilution — the kind of correctness a
flight-dynamics engineer would check.

### Verified behavior
- General formula matches the fixed formula for diagonal covariance (k=1).
- At the origin, larger realism factor monotonically reduces Pc (pure dilution).
- For off-center misses, Pc is non-monotonic in covariance (interior peak).
- Correlated (non-diagonal) covariance is handled correctly.

---

## 4. Fuel-Optimal Maneuvers — Minimum-Δv for a Target Miss

**File:** `engine/fuel_optimal.py`

### The physics
The base engine (`engine/maneuvers.py`) does a **shoot-and-score grid search** —
it finds *good* maneuvers. This module finds the **cheapest** one: the minimum-Δv
burn that achieves a target post-burn miss.

Using the **Clohessy-Wiltshire (Hill)** state-transition matrix, the post-burn
miss is a linear function of Δv:

```
m_new = m + Φ_rv · Δv
```

where Φ_rv is the 3×3 velocity-to-position block of the CW STM. The **optimal
burn direction** is the one that maximizes miss-per-Δv — the gradient direction
`Φ_rvᵀ · m̂`. The **optimal magnitude** follows from the target miss via a bounded
scalar optimization. The result is then **verified** with the high-fidelity
numerical propagator (J2 + drag).

### Verified behavior
- The optimal direction is a unit vector that *increases* the miss.
- The fuel-optimal burn achieves the target miss.
- **It beats a naive in-track-only burn** — uses less Δv for the same target
  (it picks the best direction, not just the obvious one).
- No burn is computed if the current miss already exceeds the target.
- Propellant scales with Δv (rocket equation).

### Why it matters
Operators care about **grams of propellant** — it's mission lifetime. A
provably fuel-optimal recommendation ("the cheapest burn that keeps you safe")
is materially better than "here's a burn that works."

---

## 5. CDM/ODM Standards — CCSDS Interoperability

**File:** `engine/standards.py`

### The physics
OrbitWarden speaks the operational community's language:

- **CDM (Conjunction Data Message)** — CCSDS 508.0-B-1. We generate a
  standards-compliant CDM for any scored event: TCA, miss distance (meters),
  relative speed, relative position (RSW, meters), collision probability with
  method tag, object identifiers, and emergency-reportable flag. An operator
  could feed this into existing SSA tooling.

- **OMM (Orbit Mean-Elements Message)** — CCSDS 502.0-B-2. We convert a TLE to
  the modern standard mean-element form (semi-major axis, eccentricity,
  inclination, etc.) for sharing orbit data.

### Verified behavior
- CDM contains all CCSDS-required fields; miss distance and relative position
  are correctly in **meters** (the standard unit).
- Emergency-reportable flag is set correctly from the risk score.
- CDM round-trips through the parser.
- OMM inclination matches the TLE; semi-major axis is correct for ISS (~6794 km).

### Why it matters
**Interoperability is credibility.** A tool that emits the same message format
the 18th Space Defense Squadron uses is not a toy — it's drop-in compatible with
real SSA workflows.

---

## Integration

These modules are exposed to the Granite analyst as three new tools (the agent's
contract grows from 7 to 10 tools):

- **`fuel_optimal_maneuver(event_id, target_miss_km, lead_time_min)`** — the
  minimum-Δv burn, CW-optimized and numerically verified.
- **`collision_probability_realistic(event_id, realism_factor)`** — both the
  analytic and realism-adjusted Pc, for transparency.
- **`generate_cdm_message(event_id)`** — a CCSDS-standard CDM for the event.

The agent never computes these itself — it calls the tools, and the engine
computes. *Physics computes. The AI judges. The human decides.*

---

## Honest Assumptions (stated, not hidden)

1. **Covariance realism factor k=2.0** is a documented default, not a calibrated
   value. CDM_PUBLIC's `PC` field is null (no public covariances to calibrate
   against), so we use a literature-based factor and state it explicitly.
   Calibrating *k* against a proprietary covariance source is future work.

2. **Drag uses NRLMSISE-00 with default spacecraft parameters** (Cd=2.2,
   A=0.04 m², m=4 kg) unless overridden. Real drag depends on attitude and
   geometry we don't know for arbitrary catalog objects.

3. **SRP uses a cannonball model** with a default Sun direction; precision work
   should pass the true Sun direction.

4. **Precision propagation is two-body + J2 + drag + SRP** — it does not include
   higher-order geopotential (J4+), third-body (Sun/Moon gravity), or Earth
   tides. These matter for high-precision work over long arcs.

5. **The CW fuel-optimal solution is a linear approximation**, verified against
   the numerical propagator. For very large burns or long lead times, the
   verification step catches any divergence.

---

## References

- Picone et al. (2002), "NRLMSISE-00 empirical model of the atmosphere" — `pymsis`
- Vallado, *Fundamentals of Astrodynamics and Applications* — J2, SRP, Pc
- Montenbruck & Gill, *Satellite Orbits: Models, Methods, Applications*
- Alfriend & Akella (2000), "Collision Probability for Spacecraft" — general 2-D Pc
- Foster (1992), short-term encounter probability
- Hall & Do, "Covariance Realism"
- Clohessy & Wiltshire (1960), "Terminal Guidance System for Satellite Rendezvous"
- CCSDS 508.0-B-1 (Conjunction Data Message)
- CCSDS 502.0-B-2 (Orbit Data Messages)

---

*Added 2026-07-24. 45 dedicated tests for these modules; 162 total across the
whole system. Run: `pytest tests/test_atmosphere.py tests/test_precision.py
tests/test_covariance.py tests/test_fuel_optimal.py tests/test_standards.py`.*
