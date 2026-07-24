"""Conjunction screening — Phase 1 (coarse scan).

Pipeline:
  1. Altitude-band pre-filter — perigee/apogee overlap test, no SGP4 needed;
     cuts the catalog from ~16k to a few thousand LEO objects.
  2. Coarse scan — propagate the primary once over a 60 s grid across the
     window; propagate candidates in vectorized chunks; detect local distance
     minima below the miss threshold; refine each with a parabolic fit.

Phase 2 replaces the parabolic fit with golden-section TCA refinement and adds
RSW geometry, object metadata, Pc, and the composite risk score.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import Satrec

from engine.frames import relative_state_rsw
from engine.models import (
    ConjunctionCandidate,
    ObjectInfo,
    ScoredConjunction,
    ScreeningConfig,
    ScreeningRun,
    SpaceWeatherState,
    TLEData,
)
from engine.pc import DEFAULT_HBR_KM, collision_probability
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes
from engine.scoring import geometry_class, is_maneuverable, risk_score
from engine.ingest.spaceweather import storm_flag_for_event
from engine.tca import refine_tca

# Objects co-located with the primary (docked modules, formation-flying, or
# catalog duplicates) have near-zero relative velocity. A genuine conjunction is
# a crossing encounter with vrel of order km/s. Filtering on vrel — not miss
# distance — correctly drops co-located objects while keeping the most dangerous
# (meter-scale, high-vrel) conjunctions.
CO_LOCATION_VREL_KMS = 0.1


def altitude_band_filter(
    catalog: list[TLEData], primary: TLEData, margin_km: float
) -> list[TLEData]:
    """Keep objects whose [perigee−margin, apogee+margin] band overlaps the primary's."""
    lo = primary.perigee_alt_km - margin_km
    hi = primary.apogee_alt_km + margin_km
    return [
        obj
        for obj in catalog
        if obj.norad_id != primary.norad_id and obj.apogee_alt_km >= lo and obj.perigee_alt_km <= hi
    ]


def _find_local_minima(distances: np.ndarray, threshold: float) -> np.ndarray:
    """Indices of strict local minima below threshold (NaN-safe)."""
    d = np.asarray(distances, dtype=np.float64)
    finite = np.isfinite(d)
    below = finite & (d< threshold)
    left_ok = np.empty_like(below)
    right_ok = np.empty_like(below)
    left_ok[0] = True
    left_ok[1:] = d[:-1] >= d[1:]
    right_ok[-1] = True
    right_ok[:-1] = d[1:] >= d[:-1]
    return np.nonzero(below & left_ok & right_ok)[0]


def _parabolic_refine(
    distances: np.ndarray, idx: int, step_s: float
) -> tuple[float, float]:
    """Parabolic fit through grid points (idx-1, idx, idx+1).

    Returns (refined_offset_s, refined_distance_km). Falls back to the grid
    value at window edges or degenerate cases.
    """
    if idx == 0 or idx >= len(distances) - 1:
        return 0.0, float(distances[idx])
    y0, y1, y2 = distances[idx - 1], distances[idx], distances[idx + 1]
    denom = y0 - 2.0 * y1 + y2
    if denom <= 0:
        return 0.0, float(y1)
    offset = 0.5 * (y0 - y2) / denom  # in grid steps, clamped to [-1, 1]
    offset = float(np.clip(offset, -1.0, 1.0))
    refined = y1 - 0.25 * (y0 - y2) * offset
    return offset * step_s, float(refined)


def screen_satellite(
    primary: TLEData,
    catalog: list[TLEData],
    config: ScreeningConfig | None = None,
    start: datetime | None = None,
) -> tuple[list[ConjunctionCandidate], ScreeningRun]:
    """Screen one satellite against a catalog over the configured window.

    Args:
        primary: The satellite to protect.
        catalog: Candidate objects (pre-filtered or not — filtering happens here).
        config: Screening knobs (defaults from ScreeningConfig).
        start: Window start, UTC (default: now).
    """
    config = config or ScreeningConfig()
    start = start or datetime.now(timezone.utc)
    t0 = time.perf_counter()

    window_s = config.window_days * 86400.0
    n_points = int(window_s // config.time_step_s) + 1
    grid_s = np.arange(n_points) * config.time_step_s
    grid_min = grid_s / 60.0

    # 1. Band pre-filter (no SGP4)
    filtered = altitude_band_filter(catalog, primary, config.band_margin_km)

    # 2. Primary trajectory — computed once
    primary_sat = satrec_from_tle(primary)
    primary_tsince = tsince_minutes(start, primary) + grid_min
    primary_pos, _primary_vel = propagate_grid(primary_sat, primary_tsince)

    # 3. Chunked candidate scan
    candidates: list[ConjunctionCandidate] = []
    for chunk_start in range(0, len(filtered), config.chunk_size):
        chunk = filtered[chunk_start : chunk_start + config.chunk_size]
        satrecs: list[Satrec] = []
        for obj in chunk:
            try:
                satrecs.append(satrec_from_tle(obj))
            except ValueError:
                continue  # invalid TLE — skip
        if not satrecs:
            continue

        n = len(satrecs)
        all_pos = np.empty((n, n_points, 3))
        for i, sat in enumerate(satrecs):
            obj = chunk[i]
            obj_tsince = tsince_minutes(start, obj) + grid_min
            pos, _vel = propagate_grid(sat, obj_tsince)
            all_pos[i] = pos

        # Distances [n, n_points] with NaN where either side errored
        delta = all_pos - primary_pos[None, :, :]
        distances = np.linalg.norm(delta, axis=2)
        primary_bad = ~np.isfinite(primary_pos).any(axis=1)  # [n_points]
        distances[:, primary_bad] = np.nan

        # Relative velocity at each grid point (central difference)
        all_vel = np.empty_like(all_pos)
        all_vel[:, 1:-1] = (all_pos[:, 2:] - all_pos[:, :-2]) / (2.0 * config.time_step_s)
        all_vel[:, 0] = (all_pos[:, 1] - all_pos[:, 0]) / config.time_step_s
        all_vel[:, -1] = (all_pos[:, -1] - all_pos[:, -2]) / config.time_step_s
        primary_vel = np.empty_like(primary_pos)
        primary_vel[1:-1] = (primary_pos[2:] - primary_pos[:-2]) / (2.0 * config.time_step_s)
        primary_vel[0] = (primary_pos[1] - primary_pos[0]) / config.time_step_s
        primary_vel[-1] = (primary_pos[-1] - primary_pos[-2]) / config.time_step_s
        rel_vel = np.linalg.norm(all_vel - primary_vel[None, :, :], axis=2)

        for i, obj in enumerate(chunk[:n]):
            minima = _find_local_minima(distances[i], config.miss_threshold_km)
            for idx in minima:
                offset_s, refined_dist = _parabolic_refine(distances[i], idx, config.time_step_s)
                tca = start + timedelta(seconds=float(grid_s[idx]) + offset_s)
                candidates.append(
                    ConjunctionCandidate(
                        primary_norad=primary.norad_id,
                        secondary_norad=obj.norad_id,
                        secondary_name=obj.name,
                        tca=tca,
                        miss_distance_km=refined_dist,
                        relative_velocity_kms=float(rel_vel[i, idx]),
                        coarse=True,
                    )
                )

    candidates.sort(key=lambda c: c.miss_distance_km)
    run = ScreeningRun(
        primary_norad=primary.norad_id,
        primary_name=primary.name,
        run_at=datetime.now(timezone.utc),
        window_days=config.window_days,
        catalog_size=len(catalog),
        band_filtered_size=len(filtered),
        candidates_found=len(candidates),
        duration_s=time.perf_counter() - t0,
    )
    return candidates, run


def analyze_conjunctions(
    primary: TLEData,
    candidates: list[ConjunctionCandidate],
    catalog_by_id: dict[int, TLEData],
    object_info: dict[int, ObjectInfo] | None = None,
    space_weather: SpaceWeatherState | None = None,
    config: ScreeningConfig | None = None,
    start: datetime | None = None,
    limit: int = 200,
) -> list[ScoredConjunction]:
    """Refine and score coarse candidates into full ScoredConjunctions.

    For each candidate: golden-section TCA refinement -> RSW geometry ->
    collision probability (fixed covariance) -> hard-body radius from SATCAT ->
    maneuverability -> storm flag -> transparent composite risk score.

    Only the `limit` closest candidates are refined (refinement is ~20 SGP4
    evaluations each, so the full coarse list is too expensive to refine whole).
    Self-matches (duplicate catalog entries of the primary) are skipped.
    """
    config = config or ScreeningConfig()
    start = start or datetime.now(timezone.utc)
    object_info = object_info or {}
    primary_sat = satrec_from_tle(primary)
    primary_size = object_info.get(primary.norad_id)
    primary_radius = (primary_size.size_m / 2000.0) if primary_size else DEFAULT_HBR_KM

    # Refine only the closest candidates; drop self-matches and co-located
    # objects (docked modules / catalog duplicates have coarse vrel ~ 0 and flood
    # the candidate list with one entry per grid point). Filtering on coarse vrel
    # before the top-N keeps genuine crossing conjunctions (vrel ~ km/s).
    to_refine = sorted(
        (
            c
            for c in candidates
            if c.secondary_norad != primary.norad_id
            and c.relative_velocity_kms >= CO_LOCATION_VREL_KMS
        ),
        key=lambda c: c.miss_distance_km,
    )[:limit]

    scored: list[ScoredConjunction] = []
    for cand in to_refine:
        secondary = catalog_by_id.get(cand.secondary_norad)
        if secondary is None:
            continue
        try:
            secondary_sat = satrec_from_tle(secondary)
            state = refine_tca(
                primary_sat,
                secondary_sat,
                tsince_minutes(cand.tca, primary),
                tsince_minutes(cand.tca, secondary),
                step_s=config.time_step_s,
            )
        except (ValueError, RuntimeError):
            continue  # unpropagatable object — skip

        tca = cand.tca + timedelta(seconds=state.tca_offset_s)
        miss_rsw, rel_vel_rsw = relative_state_rsw(
            state.r_primary, state.v_primary, state.r_secondary, state.v_secondary
        )
        vrel = float(np.linalg.norm(rel_vel_rsw))

        # Drop co-located objects (docked modules / catalog duplicates): they move
        # with the primary (vrel ~ 0) and are not collision threats.
        if vrel < CO_LOCATION_VREL_KMS:
            continue

        info = object_info.get(cand.secondary_norad)
        obj_type = info.object_type if info else "UNKNOWN"
        secondary_radius = (info.size_m / 2000.0) if info else DEFAULT_HBR_KM
        hbr_km = primary_radius + secondary_radius

        pc = collision_probability(miss_rsw, rel_vel_rsw, hbr_km)
        geometry = geometry_class(miss_rsw)
        maneuverable = is_maneuverable(obj_type)
        storm = (
            storm_flag_for_event(tca, space_weather) if space_weather is not None else False
        )
        score = risk_score(state.miss_distance_km, vrel, geometry, maneuverable)

        scored.append(
            ScoredConjunction(
                primary_norad=primary.norad_id,
                secondary_norad=cand.secondary_norad,
                secondary_name=cand.secondary_name,
                tca=tca,
                miss_distance_km=state.miss_distance_km,
                relative_velocity_kms=vrel,
                miss_r_km=float(miss_rsw[0]),
                miss_s_km=float(miss_rsw[1]),
                miss_w_km=float(miss_rsw[2]),
                geometry=geometry,
                hbr_km=hbr_km,
                pc=pc,
                secondary_type=obj_type,
                secondary_maneuverable=maneuverable,
                storm_flag=storm,
                risk_score=score,
            )
        )

    scored.sort(key=lambda c: c.risk_score, reverse=True)
    return scored


def full_screen(
    primary: TLEData,
    catalog: list[TLEData],
    object_info: dict[int, ObjectInfo] | None = None,
    space_weather: SpaceWeatherState | None = None,
    config: ScreeningConfig | None = None,
    start: datetime | None = None,
) -> tuple[list[ScoredConjunction], ScreeningRun]:
    """Coarse scan + full analysis in one call."""
    config = config or ScreeningConfig()
    start = start or datetime.now(timezone.utc)
    candidates, run = screen_satellite(primary, catalog, config, start=start)
    catalog_by_id = {obj.norad_id: obj for obj in catalog}
    scored = analyze_conjunctions(
        primary, candidates, catalog_by_id, object_info, space_weather, config, start
    )
    return scored, run
