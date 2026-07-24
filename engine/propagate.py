"""SGP4 propagation — the deterministic physics core.

Wraps the C-accelerated `sgp4` library with:
- vectorized grid propagation (`sgp4_tsince`) — ~10k time points per satellite
  in one call, the workhorse of the coarse scan
- NaN masking at propagation errors (decayed objects, deep-space edge cases)
  so downstream distance math treats bad points as non-candidates
- datetime <-> tsince conversion against each TLE's own epoch

All positions are TEME (True Equator Mean Equinox) km, velocities km/s.
For conjunction screening we never leave TEME: both objects share the frame,
so relative distances are exact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from sgp4.api import Satrec

from engine.models import TLEData

MINUTES_PER_DAY = 1440.0


@lru_cache(maxsize=65536)
def make_satrec(norad_id: int, line1: str, line2: str) -> Satrec:
    """Build (and cache) a Satrec from TLE lines. Cached by (id, lines)."""
    sat = Satrec.twoline2rv(line1, line2)
    if sat.error != 0:
        raise ValueError(f"SGP4 init failed for NORAD {norad_id}: error code {sat.error}")
    return sat


def satrec_from_tle(tle: TLEData) -> Satrec:
    return make_satrec(tle.norad_id, tle.line1, tle.line2)


def tsince_minutes(when: datetime, tle: TLEData) -> float:
    """Minutes elapsed from the TLE epoch to `when` (both UTC-aware)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when - tle.epoch).total_seconds() / 60.0


def propagate_grid(
    satrec: Satrec, tsince_min: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate over a grid of minutes-from-epoch.

    Returns (positions [N,3] km, velocities [N,3] km/s) in TEME. Rows where
    SGP4 reports an error are NaN — callers mask them out.

    Uses the vectorized `sgp4_array` C entry point: the epoch-anchored jd/fr
    split keeps full float64 precision across the whole 7-day window.
    """
    tsince_min = np.asarray(tsince_min, dtype=np.float64)
    epoch_jd = satrec.jdsatepoch + satrec.jdsatepochF
    total_jd = epoch_jd + tsince_min / MINUTES_PER_DAY
    jd = np.floor(total_jd)
    fr = total_jd - jd
    errors, positions, velocities = satrec.sgp4_array(jd, fr)

    positions = np.asarray(positions, dtype=np.float64)
    velocities = np.asarray(velocities, dtype=np.float64)
    bad = np.asarray(errors) != 0
    if bad.any():
        positions[bad] = np.nan
        velocities[bad] = np.nan
    return positions, velocities


def propagate_at(satrec: Satrec, when: datetime, epoch: datetime) -> tuple[np.ndarray, np.ndarray]:
    """Propagate to a single UTC instant. Returns (position [3], velocity [3])."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    tsince = (when - epoch).total_seconds() / 60.0
    positions, velocities = propagate_grid(satrec, np.array([tsince]))
    return positions[0], velocities[0]
