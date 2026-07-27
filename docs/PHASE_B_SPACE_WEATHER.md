# Phase B — Space-Weather Deepening (Implemented)

> Phase B of the [Data Integration Plan](DATA_INTEGRATION_PLAN.md): make the storm
> flag **quantitative and predictive** — not just "storm / no storm," but "density
> will inflate X% in Y hours, re-screen by Z." **Implemented and tested.**
>
> **39 new tests; 272 total passing.** The agent contract grows 19 → **22 tools**.
> All integrations verified live (2026-07-27).

---

## What was built

| Module | Role |
|--------|------|
| `engine/ingest/swpc_products.py` | NOAA SWPC **multi-signal** space weather: solar-wind B-field (Bt, Bz), solar-wind speed, GOES X-ray flux (flare class), energetic proton flux (SEP), and 10.7 cm flux (F10.7 proxy). Plus a **composite storm-risk indicator** (0–100). |
| `engine/ingest/donki_ext.py` | NASA DONKI **full notification types** (GST/CME/FLR/HSS/SEP/RBE/IPS/…), with **causal-chain modeling** — the predictive "storm building" signal. |
| `engine/drag_uncertainty.py` | **Quantitative drag-uncertainty band** — propagates both objects under quiet vs storm drag and reports the miss-distance band. The physical basis for "re-screen within 24 h." |

### New models (`engine/models.py`)
`SolarWindState` · `XrayState` · `ProtonState` · `StormRiskComposite` ·
`DonkiNotification` · `DragUncertainty`

### 3 new agent tools (`agent/tools.py`)
| Tool | Returns |
|------|---------|
| `get_space_weather_detailed()` | Multi-signal picture + composite storm-risk score (0–100) with active drivers |
| `get_space_weather_alerts(days)` | All DONKI alerts by type + active-storm + "storm building" predictive signal |
| `get_drag_uncertainty(event_id)` | "Predicted miss X km ± Y km due to drag uncertainty" + re-screen guidance |

---

## The three upgrades, in detail

### B.1 Multi-signal storm-risk composite

The old storm flag used only the 3-day Kp forecast. Now a **composite indicator**
combines five signals into one 0–100 score with a qualitative level (quiet /
unsettled / active / storm / severe) and the list of **active drivers**:

| Signal | Weight | Driver threshold |
|--------|--------|------------------|
| Kp forecast | up to 40 | Kp ≥ 6 (geomagnetic storm) |
| Southward Bz | up to 25 | Bz ≤ −5 nT (strong southward IMF) |
| Solar-wind speed | up to 15 | ≥ 600 km/s (fast stream / CME arrival) |
| X-ray flare class | up to 10 | M- or X-class flare |
| SEP event | up to 10 | proton flux ≥ 10 pfu |

So the operator sees not just *that* the risk is elevated, but *why*: "Kp forecast
7 (geomagnetic storm), Bz −12 nT southward."

### B.2 DONKI predictive "storm building" signal

DONKI issues many notification types. The key insight: **CME, HSS, and IPS are
precursors** to geomagnetic storms. So we surface a predictive signal:

- `active_storm` = a GST notification is present (a storm is happening now).
- `storm_building` = precursors (CME/HSS/IPS) present but **no active storm yet** —
  "a CME was detected; a geomagnetic storm is expected → drag will increase."

This turns the storm flag from *reactive* into *predictive*.

### B.3 Quantitative drag-uncertainty band (the physics centerpiece)

Instead of a binary flag, compute the actual **miss-distance uncertainty** from
drag:

1. Get both objects' states from their TLEs (SGP4 at "now").
2. Numerically propagate both to TCA under **two** atmospheric scenarios — quiet
   (Ap = 4) and storm (Ap from current Kp via the standard NOAA table).
3. The **band** = |miss_storm − miss_quiet|.

The band is nonzero because the two objects have **different ballistic
coefficients** (Cd·A/m) — a payload and a debris fragment respond differently to
the same density change. Object-type-based BC defaults are used (documented
assumption). The output: *"predicted miss 3.0 km ± 1.2 km (drag uncertainty);
re-screen within 24 h of TCA."*

---

## Verified live results (2026-07-27)

```
Solar wind:      Bt=4.0 nT, Bz=+1.0 nT, speed=371 km/s, F10.7=148 sfu
X-ray flux:      1.05e-06 W/m² (C-class flare)
Proton flux:     0.17 pfu (no SEP event)
Composite risk:  29/100 (unsettled)
DONKI (7 days):  17 notifications — CME:11, RBE:4, IPS:1, Report:1
                 active storm: False · storm building: True  ← predictive signal
Drag band (ISS vs FREGAT DEB, +3h, Kp 7):
                 quiet 6719.609 km · storm 6719.515 km · band 0.094 km
                 density inflation1.73× · "negligible — prediction robust"
```

(The proxy TCA above is +3 h, not a real conjunction — a real close approach over
a longer arc produces a larger, more meaningful band.)

---

## Honest scope & assumptions (documented, not hidden)

- **Ballistic-coefficient defaults** are rough object-type estimates (payload
  100 kg/1 m², debris 1 kg/0.1 m², rocket body 1500 kg/12 m²). The *differential*
  BC between the two objects is what drives the band; exact per-object BC would
  require tracking data we don't have.
- **Geocentric latitude** is used in the drag lookup (≤ ~0.2° from geodetic) —
  negligible for density.
- **Kp→Ap** uses the standard NOAA table with linear interpolation.
- **SWPC product URLs are unstable** — `xray-flux.json` and `proton-density.json`
  404; the working endpoints are the GOES `xrays-6-hour.json` and
  `integral-protons-1-day.json` (verified and used). Every product degrades
  gracefully if its endpoint changes.
- The composite is a **heuristic weighting**, not a physical model — it's a
  triage aid that surfaces *why* the risk is elevated, documented as such.

---

## Tests (39 new)

- **swpc_products:** X-ray class boundaries, risk-level boundaries, composite
  (quiet/storm/southward-Bz/Kp/SEP drivers, cap at 100, None handling, signal
  recording).
- **donki_ext:** notification parsing, header-stripping summary, by-type analysis,
  active-storm, storm-building (precursors without GST), type meanings.
- **drag_uncertainty:** Kp→Ap standard table + interpolation + clamping, BC
  defaults (distinct per type), recommendation escalation, nonzero band for
  different types, zero band for past TCA, band scales with storm intensity.
- **agent tools:** all 3 new tools return well-formed data (graceful).

---

## Next (from the plan)

- **Phase C** — Earth observation (earth-search STAC: Sentinel-2/1, Landsat) +
  ground-track computation + CLMS burnt-area disaster monitoring.
- **Phase D** — JPL Horizons precision ephemerides (feeds accurate SRP Sun direction).
- **Phase E** — astronomy streams (ZTF/Gaia/TESS/Exoplanet Archive).
- **Phase F** — synthesis: unified dashboard (space-weather panel, alerts timeline,
  drag-band visualization) + space-situation assistant.

The frontend space-weather dashboard (Kp dial, solar wind, alerts timeline, drag
band) is the natural next step to make these signals visible.

---

*Implemented 2026-07-27. Run: `pytest tests/test_swpc_products.py
tests/test_donki_ext.py tests/test_drag_uncertainty.py tests/test_agent_tools.py`.*
