"""Quantitative storm-driven drag-uncertainty band.

Instead of a binary storm flag, this computes the **drag-uncertainty band** —
"the predicted miss could be ±X km due to drag uncertainty during this storm."
This is the physical basis for "re-screen within 24 h of TCA."

Method:
  1. Get the primary and secondary states from their TLEs (SGP4 at "now").
  2. Numerically propagate both to TCA under two atmospheric scenarios:
     · Quiet: Ap = 4 (geomagnetically quiet)
     · Storm: Ap = current (derived from the latest Kp via the standard table)
  3. Compute the miss distance at TCA in each scenario.
  4. The band = |miss_storm − miss_quiet| — the drag-driven miss uncertainty.

The band is nonzero because the two objects have different ballistic coefficients
(Cd·A/m), so they respond differently to the density change. Object-type-based
BC defaults are used (documented assumption).

This is the quantitative upgrade to the binary storm flag: it tells the operator
*how much* the prediction could shift, not just *that* it might.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from engine.atmosphere import DEFAULT_CD
from engine.models import DragUncertainty, TLEData
from engine.precision import precision_propagate
from engine.propagate import propagate_at, satrec_from_tle

# Standard Kp → Ap conversion table (NOAA).
KP_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
AP_VALUES = [0, 4, 7, 15, 27, 48, 80, 140, 240, 400]

# Object-type-based ballistic-coefficient defaults (mass kg, area m²).
# These are rough but reasonable; the *differential* BC between the two objects
# is what drives the miss-uncertainty band.
BC_DEFAULTS = {
    "PAYLOAD": (100.0, 1.0),       # typical small satellite
    "ROCKET BODY": (1500.0, 12.0), # spent upper stage
    "DEBRIS": (1.0, 0.1),          # small fragment
    "UNKNOWN": (10.0, 0.5),        # conservative default
}


def kp_to_ap(kp: float) -> float:
    """Convert Kp index to Ap index using the standard NOAA table (interpolated)."""
    kp = max(0.0, min(9.0, kp))
    # Linear interpolation between table entries.
    for i in range(len(KP_VALUES) - 1):
        if kp <= KP_VALUES[i + 1]:
            frac = (kp - KP_VALUES[i]) / (KP_VALUES[i + 1] - KP_VALUES[i])
            return AP_VALUES[i] + frac * (AP_VALUES[i + 1] - AP_VALUES[i])
    return float(AP_VALUES[-1])


def _bc_for_type(object_type: str) -> tuple[float, float]:
    """Return (mass_kg, area_m²) defaults for an object type."""
    return BC_DEFAULTS.get((object_type or "UNKNOWN").upper(), BC_DEFAULTS["UNKNOWN"])


def _propagate_to_tca(
    tle: TLEData,
    tca: datetime,
    ap: float,
    f107: float,
    mass_kg: float,
    area_m2: float,
    cd: float = DEFAULT_CD,
) -> np.ndarray | None:
    """Propagate a TLE to TCA under given drag conditions. Returns position at TCA."""
    try:
        sat = satrec_from_tle(tle)
        now = datetime.now(timezone.utc)
        r0, v0 = propagate_at(sat, now, tle.epoch)
        dt_s = (tca - now).total_seconds()
        if dt_s <= 0:
            return None  # TCA in the past — can't forward-propagate
        r_tca, _ = precision_propagate(
            r0, v0, dt_s,
            include_j2=True, include_drag=True, include_srp=False,
            mass_kg=mass_kg, area_m2=area_m2, cd=cd,
            f107=f107, f107a=f107, ap=ap, start_time=now,
        )
        return r_tca
    except Exception:  # noqa: BLE001 — propagation edge cases
        return None


def _recommendation(band_km: float) -> str:
    """Re-screen guidance based on the drag-uncertainty band."""
    if band_km < 0.1:
        return "Drag uncertainty negligible — prediction is robust."
    if band_km < 1.0:
        return "Minor drag uncertainty — prediction is reliable."
    if band_km < 5.0:
        return "Moderate drag uncertainty — re-screen within 24 h of TCA."
    return "Significant drag uncertainty — re-screen as close to TCA as possible; treat the predicted miss with caution."


def drag_uncertainty_band(
    primary_tle: TLEData,
    secondary_tle: TLEData,
    tca: datetime,
    event_id: int = 0,
    primary_type: str = "PAYLOAD",
    secondary_type: str = "UNKNOWN",
    ap_quiet: float = 4.0,
    kp_current: float = 4.0,
    f107: float = 150.0,
) -> DragUncertainty:
    """Compute the drag-uncertainty band for a conjunction.

    Args:
        primary_tle, secondary_tle: TLEs for the two objects.
        tca: time of closest approach (UTC).
        event_id: for labeling.
        primary_type, secondary_type: object types (for BC defaults).
        ap_quiet: Ap for the quiet scenario (default 4).
        kp_current: current Kp (converted to Ap for the storm scenario).
        f107: current F10.7 (sfu).

    Returns:
        DragUncertainty with quiet/storm miss, band, and recommendation.
    """
    ap_storm = kp_to_ap(kp_current)
    p_mass, p_area = _bc_for_type(primary_type)
    s_mass, s_area = _bc_for_type(secondary_type)

    # Propagate both objects under quiet and storm drag.
    r1_quiet = _propagate_to_tca(primary_tle, tca, ap_quiet, f107, p_mass, p_area)
    r2_quiet = _propagate_to_tca(secondary_tle, tca, ap_quiet, f107, s_mass, s_area)
    r1_storm = _propagate_to_tca(primary_tle, tca, ap_storm, f107, p_mass, p_area)
    r2_storm = _propagate_to_tca(secondary_tle, tca, ap_storm, f107, s_mass, s_area)

    # If any propagation failed (e.g., TCA in the past), return a zero band.
    if any(r is None for r in [r1_quiet, r2_quiet, r1_storm, r2_storm]):
        return DragUncertainty(
            event_id=event_id,
            quiet_miss_km=0.0,
            storm_miss_km=0.0,
            band_km=0.0,
            ap_quiet=ap_quiet,
            ap_storm=ap_storm,
            inflation_ratio=1.0,
            recommendation="Unable to compute band (TCA in the past or propagation failed).",
        )

    miss_quiet = float(np.linalg.norm(r1_quiet - r2_quiet))
    miss_storm = float(np.linalg.norm(r1_storm - r2_storm))
    band = abs(miss_storm - miss_quiet)

    # Density inflation ratio (for context).
    from engine.atmosphere import atmospheric_density

    alt = np.linalg.norm(r1_quiet) - 6378.137
    rho_quiet = atmospheric_density(alt, f107=f107, f107a=f107, ap=ap_quiet)
    rho_storm = atmospheric_density(alt, f107=f107, f107a=f107, ap=ap_storm)
    inflation = rho_storm / rho_quiet if rho_quiet > 0 else 1.0

    return DragUncertainty(
        event_id=event_id,
        quiet_miss_km=round(miss_quiet, 3),
        storm_miss_km=round(miss_storm, 3),
        band_km=round(band, 3),
        ap_quiet=ap_quiet,
        ap_storm=round(ap_storm, 1),
        inflation_ratio=round(inflation, 2),
        recommendation=_recommendation(band),
    )
