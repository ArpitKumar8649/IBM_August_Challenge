# Phase D — Precision Ephemerides: JPL Horizons (Implemented)

> Phase D of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): enable
> deep-space awareness and a precision reference, and feed the **real Sun
> direction** into the SRP model. **Implemented and tested (D.1).**
>
> **27 new tests; 327 passing.** The agent contract grows 25 → **26 tools**.
> Verified live (2026-07-27). D.2 (SPICE) is documented as future work below.

---

## What was built

| Module | Role |
|--------|------|
| `engine/ingest/horizons.py` | **JPL Horizons client** — precision VECTOR ephemerides (ICRF/J2000) for planets, the Moon, and the Sun. Body name→code lookup, `$$SOE..$$EOE` block parsing, **geocentric Sun direction**, and an **Earth-shadow (eclipse) test**. |
| `engine/precision.py` (extended) | The SRP model now uses the **real Sun direction** (from Horizons) and **zeroes SRP in Earth's shadow** (eclipse) — physically correct, not a constant push. |

### New model (`engine/models.py`)
`EphemerisState` (body, time, JD, ICRF position + velocity)

### 1 new agent tool (`agent/tools.py`)
| Tool | Returns |
|------|---------|
| `get_planet_position(body, days)` | Precision geocentric ICRF/J2000 state vector + distance (km and AU) for any solar-system body |

---

## The two integrations, in detail

### D.1 JPL Horizons precision ephemerides

Horizons returns high-precision state vectors for solar-system bodies. The API
returns a JSON object whose `result` field is a **formatted text block**; the
ephemeris is the section between `$$SOE` and `$$EOE`, with `X/Y/Z` (km) and
`VX/VY/VZ` (km/s) in ICRF/J2000. We parse it with regex.

- **Body lookup:** name → COMMAND code (`sun`→`10`, `mars`→`499`, `moon`→`301`,
  `earth`→`399`, … all major bodies). Raw codes pass through.
- **Geocentric Sun direction:** fetch the Sun's geocentric position (`CENTER='500@399'`)
  and normalize → the unit vector from Earth toward the Sun.
- **Earth-shadow test:** cylindrical shadow model — a satellite is in shadow if
  it's on the night side (opposite the Sun) *and* its perpendicular distance from
  the Earth-Sun line is less than Earth's radius. Accurate for LEO (penumbra small
  relative to umbra).

### Feeding the real Sun direction into SRP (the key value-add)

Previously the SRP model used a default Sun direction `[1,0,0]` (equinox
approximation) and pushed constantly. Now:

1. `precision_propagate` resolves the **real geocentric Sun direction** from
   Horizons **once** (outside the integrator — no repeated API calls), falling
   back to the default if Horizons is unavailable.
2. `srp_acceleration` uses that real direction, and with `check_shadow=True`
   **returns zero when the satellite is in Earth's shadow** (eclipse).

This makes SRP physically correct: the force points away from the *real* Sun and
vanishes during the ~35 min/orbit a LEO satellite spends in eclipse.

---

## Verified live results (2026-07-27)

```
Body lookup:    sun→10, mars→499, moon→301, earth→399, jupiter→599
Mars ephemeris: geocentric distance 2.02 AU (sane for 2026)
Sun direction:  [-0.554, 0.833, 0.000] (unit vector, norm 1.0)
Sun distance:   ~1.0 AU (parse test within 2%)
Shadow check:   day-side → not in shadow; night-side → in shadow ✓
SRP integration: day-side accel 5.9e-11 km/s²; night-side (eclipse) → 0.0 ✓
```

---

## Honest scope & assumptions (documented, not hidden)

- **Frame:** Horizons vectors are ICRF/J2000; our engine uses TEME≈J2000. For the
  Sun direction this is fine — the Sun is ~1 AU away, so the TEME/J2000 frame
  difference (equinox precession, ~tens of arcsec) is negligible for SRP.
- **Shadow model:** cylindrical (umbra) approximation — accurate for LEO; a full
  conical penumbra model would matter only for high-altitude orbits.
- **Sun direction is fetched once per propagation** (not per integrator step) —
  the Sun moves negligibly over a LEO arc, and this avoids hammering the API.
- **Horizons rate limit** ~300 req/min — ample; results cached 24 h.

---

## D.2 SPICE kernels — future work (🔴 ambitious, deferred)

The plan flags SPICE as a stretch: "defer unless time allows." SPICE (via
`spiceypy`) would enable **instrument pointing → ground footprint** for satellites
with public kernels (e.g., some Earth-observing sats). It's deferred because:

- SPICE kernels are large and **spacecraft-specific** — only feasible for a few
  well-known satellites.
- It requires downloading and managing kernel files (meta-kernels, CK, SPK, FK).
- The marginal value for a collision-avoidance tool is lower than the other phases.

**Path to add it later:** `spiceypy` is pip-installable; load a satellite's public
kernels from NASA NAIF, compute the instrument boresight → ground footprint, and
expose `get_instrument_footprint(norad_id, time)`. The architecture (a thin ingest
adapter + an agent tool) is already established by Phases A–D, so this would be a
small, well-scoped addition.

---

## Tests (27 new)

- **horizons:** body lookup (known/case-insensitive/raw/unknown), `$$SOE` block +
  state-line regex, ephemeris parsing (position/velocity/JD/time/body name), Sun
  distance ≈ 1 AU, model validation, no-block → empty.
- **shadow:** day-side false, night-side true, off-axis night-side false, arbitrary
  Sun direction.
- **SRP integration:** zero in shadow, nonzero in sunlight, nonzero without shadow
  check, anti-sunward direction.
- **agent tool:** get_planet_position (Mars distance 0.3–3 AU, Sun ~1 AU, unknown
  body → unavailable).

---

## Next (from the plan)

- **Phase E** — astronomy streams (ZTF transients via ALeRCE, Exoplanet Archive,
  Gaia, TESS) — the discovery angle.
- **Phase F** — synthesis: unified dashboard (solar-system panel, ground-track map,
  imagery, space weather) + space-situation assistant + accessibility narrative.

---

*Implemented 2026-07-27. Run: `pytest tests/test_horizons.py tests/test_agent_tools.py`.*
