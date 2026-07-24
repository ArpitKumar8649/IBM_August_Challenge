"""Conjunction scoring — geometry classification, maneuverability, composite risk.

The composite risk score is deliberately transparent and documented: a weighted
sum of normalized closeness, relative velocity, geometry, and who-can-maneuver.
It is a triage aid for ranking — not a physical probability. `pc.py` provides the
physical collision probability; this module provides the operator-facing ranking.
"""

from __future__ import annotations

import numpy as np

# Object types that cannot maneuver — if the secondary is one of these and a
# conjunction is threatening, the primary is the only one who can move.
UNMANEUVERABLE_TYPES = {"DEBRIS", "ROCKET BODY", "UNKNOWN"}


def geometry_class(miss_rsw: np.ndarray) -> str:
    """Classify approach geometry by the dominant RSW component of the miss vector.

    in-track-dominated approaches are the common, more predictable kind;
    radial-dominated ones are rarer and harder to predict.
    """
    r, s, w = np.abs(np.asarray(miss_rsw, float))
    if s >= r and s >= w:
        return "in-track"
    if r >= w:
        return "radial"
    return "cross-track"


def is_maneuverable(object_type: str | None) -> bool:
    """A secondary is maneuverable only if it's a known active payload.

    Unknown/missing type is treated conservatively as unmaneuverable — if we
    can't confirm it's a controllable payload, assume the primary must move.
    """
    if not object_type:
        return False
    return object_type.upper() not in UNMANEUVERABLE_TYPES


def risk_score(
    miss_km: float,
    vrel_kms: float,
    geometry: str,
    secondary_maneuverable: bool,
) -> float:
    """Transparent composite triage score in [0, 100]; higher = more urgent.

    Documented weights:
      closeness : 60 · exp(−miss_km / 5)   — proximity dominates the urgency
      velocity  : 20 · min(vrel/15, 1)     — faster = less reaction time
      geometry  : +10 radial, +5 cross-track, 0 in-track (predictability)
      maneuver  : +10 if the secondary cannot maneuver (you must move)
    """
    closeness = 60.0 * float(np.exp(-miss_km / 5.0))
    velocity = 20.0 * min(vrel_kms / 15.0, 1.0)
    geo = {"radial": 10.0, "cross-track": 5.0, "in-track": 0.0}.get(geometry, 0.0)
    maneu = 0.0 if secondary_maneuverable else 10.0
    return float(min(closeness + velocity + geo + maneu, 100.0))
