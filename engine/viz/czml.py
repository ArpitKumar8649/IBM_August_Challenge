"""CZML generation for OrbitWarden's 3D conjunction globe (Phase 5.1).

Produces Cesium Language CZML documents from the screening engine's TEME
trajectories. The pipeline is:

  TLE ──[SGP4 propagate_grid]──▶ TEME positions (km)
       ──[GMST rotation]───────▶ ECEF Cartesian positions (km → m for Cesium)

All entities use ``referenceFrame: "FIXED"`` (Earth-fixed ECEF). TEME is
approximated to ECEF via the GMST z-rotation — good to ~0.01° for visualization;
disclosed in the assumptions docs.

Maneuver tracks join SGP4 (pre-burn) and two-body DOP853 (post-burn) at the burn
epoch so the plotted maneuver stays consistent with the engine's own model.
``event_czml_document`` assembles the complete scene for one conjunction — both
orbits, the TCA moment, the covariance ellipsoid, and an optional maneuver track.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from engine.models import ManeuverOption, ScoredConjunction, TLEData
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes
from engine.tca import TCAState

# Reuse the astronomy helpers from the open-notify ground-track code (GMST, JD).
from engine.ingest.open_notify import _gmst_rad, _julian_date

# ── constants ────────────────────────────────────────────────────────────────

MU_EARTH = 398600.8  # km³/s², for two-body
R_EARTH_KM = 6378.137
VISUAL_COV_SCALE = 10.0  # scale km→km for visibility; labeled explicitly in CZML
KM_TO_M = 1000.0
DEFAULT_STEP_S = 120.0  # seconds between CZML samples — balances size vs smoothness
DEFAULT_WINDOW_MIN = 45.0  # ± half-window around TCA

# CZML color palette
COLOR_PRIMARY = [0, 128, 255, 255]    # blue
COLOR_SECONDARY = [255, 64, 64, 255]  # red
COLOR_MISS_LINE = [255, 220, 0, 128]  # yellow, semi-transparent
COLOR_VEL_VECTOR = [0, 255, 128, 192] # green, semi-transparent
COLOR_MANEUVER = [255, 128, 0, 255]   # orange
COLOR_COVARIANCE = [128, 255, 128, 80]  # green, very translucent
COLOR_TCA_POINT = [255, 255, 255, 255]  # white
COLOR_BURN_POINT = [255, 255, 0, 255]   # yellow


# ── helpers ──────────────────────────────────────────────────────────────────

def _iso(dt: datetime) -> str:
    """ISO 8601 with 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_interval(start: datetime, end: datetime) -> str:
    return f"{_iso(start)}/{_iso(end)}"


def teme_to_ecef(r_teme: np.ndarray, dt: datetime) -> np.ndarray:
    """Rotate a TEME position (km) to Earth-fixed ECEF (km) via GMST.

    This is the 3-D version of ``engine.ingest.open_notify.teme_to_latlon`` without
    the lat/lon reduction. The GMST rotation is approximate for TEME→ECEF
    (treats TEME as pseudo-ECI) — sufficient for visualization, not for
    milliarcsecond astrometry.
    """
    r = np.asarray(r_teme, dtype=np.float64)
    gmst = _gmst_rad(_julian_date(dt))
    c, s = math.cos(gmst), math.sin(gmst)
    x_ecef = r[0] * c + r[1] * s
    y_ecef = -r[0] * s + r[1] * c
    return np.array([x_ecef, y_ecef, r[2]], dtype=np.float64)


def _propagate_two_body_grid(
    r0: np.ndarray, v0: np.ndarray, duration_s: float, step_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Two-body trajectory sampled every step_s over [0, duration_s].

    Uses the same DOP853 integrator as ``engine.maneuvers``, but with dense output so the
    full sampled arc costs one integration call.

    Returns:
        positions [N,3] km TEME, velocities [N,3] km/s TEME, times_s [N] (seconds from r0 epoch).
    """
    from scipy.integrate import solve_ivp

    def _rhs(_t: float, y: np.ndarray) -> np.ndarray:
        return np.concatenate([y[3:], -MU_EARTH * y[:3] / np.linalg.norm(y[:3])**3])

    n = int(abs(duration_s) / step_s) + 1
    t_eval = np.linspace(0.0, duration_s, n)

    y0 = np.concatenate([np.asarray(r0, float), np.asarray(v0, float)])
    sol = solve_ivp(
        _rhs, (0.0, duration_s), y0, method="DOP853",
        rtol=1e-11, atol=1e-11, t_eval=t_eval, dense_output=False,
    )
    return sol.y[:3].T.copy(), sol.y[3:].T.copy(), t_eval.copy()


def _positions_czml_array(
    times_utc: list[datetime], positions_ecef_m: np.ndarray,
) -> list[float]:
    """Flatten ECEF positions (m) into a CZML ``cartesian`` array.

    Each sample contributes [x, y, z]. Returns a flat list of floats.
    The caller sets ``epoch`` and interpolation metadata.
    """
    out: list[float] = []
    for i in range(positions_ecef_m.shape[0]):
        out.extend([positions_ecef_m[i, 0], positions_ecef_m[i, 1], positions_ecef_m[i, 2]])
    return out


def _as_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime (naive datetimes are assumed UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── orbit CZML ───────────────────────────────────────────────────────────────

def orbit_czml(
    tle: TLEData,
    label: str,
    color_rgba: list[int],
    start: datetime,
    duration_min: float,
    step_s: float = DEFAULT_STEP_S,
    entity_id: str | None = None,
) -> dict | None:
    """Generate a CZML ``path`` entity for a satellite's SGP4-propagated orbit.

    Returns None if the object fails to propagate (all NaN).
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    n_points = int(duration_min * 60.0 / step_s) + 1
    offsets_s = np.arange(n_points) * step_s
    offsets_min = offsets_s / 60.0

    sat = satrec_from_tle(tle)
    t0_min = tsince_minutes(start, tle)
    positions_teme, _ = propagate_grid(sat, t0_min + offsets_min)

    # Convert TEME → ECEF per sample, drop NaN
    times: list[datetime] = []
    positions_ecef_km: list[np.ndarray] = []
    for i, offset_s in enumerate(offsets_s):
        r = positions_teme[i]
        if not np.isfinite(r).all():
            continue
        dt = start + timedelta(seconds=float(offset_s))
        r_ecef = teme_to_ecef(r, dt)
        times.append(dt)
        positions_ecef_km.append(r_ecef)

    if len(times) < 2:
        return None

    pos_arr = np.array(positions_ecef_km) * KM_TO_M  # km → m for Cesium
    cartesian = _positions_czml_array(times, pos_arr)

    eid = entity_id or f"orbit-{tle.norad_id}"
    return {
        "id": eid,
        "name": label,
        "availability": _iso_interval(times[0], times[-1]),
        "path": {
            "material": {"solidColor": {"color": {"rgba": color_rgba}}},
            "width": 3 if entity_id else 2,
            "leadTime": 0,
            "trailTime": 0,
            "resolution": step_s,
        },
        "position": {
            "epoch": _iso(times[0]),
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 5,
            "referenceFrame": "FIXED",
            "cartesian": cartesian,
        },
    }


# ── conjunction entities ─────────────────────────────────────────────────────

def conjunction_entities(
    state: TCAState,
    tca: datetime,
    primary_label: str,
    secondary_label: str,
) -> list[dict]:
    """Entities for the TCA moment: points, miss line, relative-velocity arrow.

    All entities have availability bounded to ±5 s around TCA so Cesium only
    shows them at that moment (not across the full timeline).
    """
    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)

    half = timedelta(seconds=5)
    avail = _iso_interval(tca - half, tca + half)

    # Positions in ECEF (m)
    p_ecef = teme_to_ecef(state.r_primary, tca) * KM_TO_M
    s_ecef = teme_to_ecef(state.r_secondary, tca) * KM_TO_M

    # Relative velocity vector (TEME → ECEF)
    v_rel_teme = np.asarray(state.v_secondary, float) - np.asarray(state.v_primary, float)
    # For the arrow, approximate the velocity direction in ECEF at TCA (the GMST
    # rotation of a velocity vector is not rigorous for a rotating frame, but the
    # *direction* is close enough for a visualization arrow).
    v_rel_ecef = teme_to_ecef(v_rel_teme * 100.0, tca)  # scale for visibility
    v_rel_end = s_ecef + v_rel_ecef * KM_TO_M  # arrow tip

    entities: list[dict] = []

    # Primary point at TCA
    entities.append({
        "id": "tca-primary",
        "availability": avail,
        "position": {"referenceFrame": "FIXED", "cartesian": list(p_ecef)},
        "point": {
            "pixelSize": 10,
            "color": {"rgba": COLOR_PRIMARY},
            "outlineColor": {"rgba": COLOR_TCA_POINT},
            "outlineWidth": 2,
        },
        "label": {"text": primary_label, "pixelOffset": {"cartesian2": [0, -16]}},
    })

    # Secondary point at TCA
    entities.append({
        "id": "tca-secondary",
        "availability": avail,
        "position": {"referenceFrame": "FIXED", "cartesian": list(s_ecef)},
        "point": {
            "pixelSize": 10,
            "color": {"rgba": COLOR_SECONDARY},
            "outlineColor": {"rgba": COLOR_TCA_POINT},
            "outlineWidth": 2,
        },
        "label": {"text": secondary_label, "pixelOffset": {"cartesian2": [0, -16]}},
    })

    # Miss-distance line
    entities.append({
        "id": "tca-miss-line",
        "availability": avail,
        "polyline": {
            "positions": {
                "referenceFrame": "FIXED",
                "cartesian": list(p_ecef) + list(s_ecef),
            },
            "material": {"solidColor": {"color": {"rgba": COLOR_MISS_LINE}}},
            "width": 2,
        },
    })

    # Relative-velocity arrow (line from secondary in the velocity direction)
    entities.append({
        "id": "tca-vel-vector",
        "availability": avail,
        "polyline": {
            "positions": {
                "referenceFrame": "FIXED",
                "cartesian": list(s_ecef) + list(v_rel_end),
            },
            "material": {"polylineArrow": {"color": {"rgba": COLOR_VEL_VECTOR}}},
            "width": 2,
        },
    })

    return entities


# ── maneuver track ────────────────────────────────────────────────────────────

def maneuver_track_czml(
    tle: TLEData,
    state: TCAState,
    option: ManeuverOption,
    entity_id: str = "maneuver-track",
) -> dict | None:
    """CZML path showing pre-burn (SGP4) + post-burn (two-body) trajectories.

    The two tracks join at the burn epoch without a gap so Cesium draws a
    continuous path. The post-burn segment uses the same two-body DOP853
    integrator as ``engine.maneuvers.search_maneuvers``, so the plotted track
    and the card numbers are from the same dynamical model.
    """
    from engine.frames import rsw_rotation
    from engine.maneuvers import propagate_two_body

    burn_epoch = option.burn_epoch
    if burn_epoch.tzinfo is None:
        burn_epoch = burn_epoch.replace(tzinfo=timezone.utc)

    # Pre-burn: SGP4 from 60 min before the burn to the burn epoch (inclusive).
    # The last sample lands exactly on the burn epoch, so the two tracks join
    # there. (The models differ — SGP4 vs two-body — so the seam can shift by a
    # fraction of a km; invisible at globe scale.)
    pre_times: list[datetime] = []
    pre_positions: list[np.ndarray] = []

    sat = satrec_from_tle(tle)

    pre_duration_s = 60.0 * 60.0
    n_pre = int(round(pre_duration_s / DEFAULT_STEP_S)) + 1
    offsets_s = np.linspace(0.0, pre_duration_s, n_pre)
    offsets_min = offsets_s / 60.0
    t0_min = tsince_minutes(burn_epoch - timedelta(seconds=pre_duration_s), tle)
    pos_teme, _ = propagate_grid(sat, t0_min + offsets_min)

    for i, offset_s in enumerate(offsets_s):
        r = pos_teme[i]
        if not np.isfinite(r).all():
            continue
        dt = burn_epoch - timedelta(seconds=pre_duration_s) + timedelta(seconds=float(offset_s))
        r_ecef = teme_to_ecef(r, dt)
        pre_times.append(dt)
        pre_positions.append(r_ecef)

    # Post-burn: two-body from burn epoch forward
    # Recover the primary state at the burn epoch
    lead_s = option.lead_time_min * 60.0
    r_p_burn, v_p_burn = propagate_two_body(state.r_primary, state.v_primary, -lead_s)

    # Apply Δv in RSW at burn epoch
    rotation = rsw_rotation(r_p_burn, v_p_burn)
    dv_rsw_kms = np.array([option.dv_r_ms, option.dv_s_ms, option.dv_w_ms]) / 1000.0
    dv_inertial = rotation.T @ dv_rsw_kms
    v_post_burn = v_p_burn + dv_inertial

    # Propagate two-body from burn epoch to TCA + 15 min (past the encounter)
    post_duration_s = lead_s + 15.0 * 60.0  # burn→TCA + 15 min buffer
    post_pos_teme, post_vel_teme, post_t_s = _propagate_two_body_grid(
        r_p_burn, v_post_burn, post_duration_s, DEFAULT_STEP_S,
    )

    post_times: list[datetime] = []
    post_positions_km: list[np.ndarray] = []
    for i, t_s in enumerate(post_t_s):
        dt = burn_epoch + timedelta(seconds=float(t_s))
        post_times.append(dt)
        post_positions_km.append(post_pos_teme[i])

    # Convert post-burn to ECEF
    post_pos_m = np.array([
        teme_to_ecef(r, t) * KM_TO_M for r, t in zip(post_positions_km, post_times)
    ])

    # Combine: pre-burn ECEF + post-burn ECEF
    all_times = pre_times + post_times
    pre_arr = np.array(pre_positions) * KM_TO_M
    all_pos_m = np.vstack([pre_arr, post_pos_m])

    if len(all_times) < 2:
        return None

    cartesian = _positions_czml_array(all_times, all_pos_m)

    return {
        "id": entity_id,
        "name": f"Maneuver: {option.kind} ({option.dv_total_ms:.0f} m/s)",
        "availability": _iso_interval(all_times[0], all_times[-1]),
        "path": {
            "material": {"solidColor": {"color": {"rgba": COLOR_MANEUVER}}},
            "width": 3,
            "leadTime": 0,
            "trailTime": 0,
            "resolution": DEFAULT_STEP_S,
        },
        "position": {
            "epoch": _iso(all_times[0]),
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 5,
            "referenceFrame": "FIXED",
            "cartesian": cartesian,
        },
    }


# ── covariance ellipsoid ─────────────────────────────────────────────────────

def _rotation_to_quaternion(R: np.ndarray) -> list[float]:
    """3×3 rotation matrix → quaternion [x, y, z, w] (Shoemake)."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        return [
            (R[2, 1] - R[1, 2]) * s,
            (R[0, 2] - R[2, 0]) * s,
            (R[1, 0] - R[0, 1]) * s,
            0.25 / s,
        ]
    if R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        return [
            0.25 * s,
            (R[0, 1] + R[1, 0]) / s,
            (R[0, 2] + R[2, 0]) / s,
            (R[2, 1] - R[1, 2]) / s,
        ]
    if R[1, 1] > R[2, 2]:
        s = 2.0 * math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        return [
            (R[0, 1] + R[1, 0]) / s,
            0.25 * s,
            (R[1, 2] + R[2, 1]) / s,
            (R[0, 2] - R[2, 0]) / s,
        ]
    s = 2.0 * math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
    return [
        (R[0, 2] + R[2, 0]) / s,
        (R[1, 2] + R[2, 1]) / s,
        0.25 * s,
        (R[1, 0] - R[0, 1]) / s,
    ]


def covariance_ellipsoid_czml(
    tca: datetime,
    r_primary_teme: np.ndarray,
    v_primary_teme: np.ndarray,
    r_secondary_teme: np.ndarray,
    visual_scale: float = VISUAL_COV_SCALE,
) -> dict:
    """CZML ellipsoid for the combined encounter uncertainty (1σ in RSW).

    The covariance is the same fixed diagonal used by ``engine.pc``
    (σR=0.5, σS=1.0, σW=0.5 km).  The ellipsoid is rendered at ×visual_scale
    around the secondary's ECEF position, oriented with the primary's RSW frame.
    Label: "combined encounter uncertainty (1σ, ×{visual_scale} visual scale)".

    On a ~6,800 km Earth, kilometer-scale covariance is invisible without
    scaling; the default ×10 makes the 1σ ellipsoid ~5–10 km across so the
    analyst can see it.  Numerical labels are not altered.
    """
    from engine.frames import rsw_rotation
    from engine.pc import SIGMA_CROSSTRACK_KM, SIGMA_INTRACK_KM, SIGMA_RADIAL_KM

    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)

    # RSW basis in TEME
    rot_teme = rsw_rotation(r_primary_teme, v_primary_teme)  # TEME→RSW, rows
    rsw_to_teme = rot_teme.T  # RSW→TEME (columns are R, S, W in TEME)

    # Rotate RSW basis vectors to ECEF
    # Columns of rsw_to_teme are R_hat, S_hat, W_hat in TEME.
    # Rotate each by GMST to get ECEF directions.
    r_ecef = np.zeros((3, 3))
    for col in range(3):
        r_ecef[:, col] = teme_to_ecef(rsw_to_teme[:, col], tca)

    # Normalize (the GMST rotation preserves orthogonality but re-normalize for safety)
    for col in range(3):
        r_ecef[:, col] /= np.linalg.norm(r_ecef[:, col])

    # Semi-axes in km, then m, then ×visual_scale
    radii_m = np.array([
        SIGMA_RADIAL_KM,
        SIGMA_INTRACK_KM,
        SIGMA_CROSSTRACK_KM,
    ]) * KM_TO_M * visual_scale

    # Ellipsoid center: secondary position in ECEF (m)
    center_ecef = teme_to_ecef(r_secondary_teme, tca) * KM_TO_M

    orientation = _rotation_to_quaternion(r_ecef)

    avail = _iso_interval(tca - timedelta(seconds=5), tca + timedelta(seconds=5))

    return {
        "id": "covariance-ellipsoid",
        "name": f"combined encounter uncertainty (1σ, ×{visual_scale:g} visual scale)",
        "availability": avail,
        "position": {"referenceFrame": "FIXED", "cartesian": list(center_ecef)},
        "ellipsoid": {
            "radii": {
                "cartesian": list(radii_m),
            },
            "material": {
                "solidColor": {"color": {"rgba": COLOR_COVARIANCE}},
            },
            "fill": True,
            "outline": True,
            "outlineColor": {"rgba": [COLOR_COVARIANCE[0], COLOR_COVARIANCE[1], COLOR_COVARIANCE[2], 160]},
        },
        "orientation": {
            "unitQuaternion": orientation,
        },
    }


# ── event scene assembler ────────────────────────────────────────────────────

def event_czml_document(
    primary: TLEData,
    secondary: TLEData,
    state: TCAState,
    event: ScoredConjunction,
    maneuver_option: ManeuverOption | None = None,
    window_min: float = DEFAULT_WINDOW_MIN,
    step_s: float = DEFAULT_STEP_S,
    with_covariance: bool = True,
    label: str | None = None,
) -> list[dict] | None:
    """Assemble the full CZML scene for one conjunction.

    Composes both orbits over ±``window_min`` around TCA, the TCA-moment entities
    (points, miss line, relative-velocity arrow), the covariance ellipsoid, and —
    when ``maneuver_option`` is given — the pre/post-burn maneuver track, then
    wraps everything in a time-dynamic document whose clock starts at TCA.

    Returns None when the primary fails to propagate — the scene is meaningless
    without the protected satellite.
    """
    tca = _as_utc(event.tca)

    window_s = window_min * 60.0
    orbit_start = tca - timedelta(seconds=window_s)
    orbit_duration_min = 2.0 * window_min

    packets: list[dict] = []

    p_orbit = orbit_czml(
        primary, primary.name, COLOR_PRIMARY, orbit_start,
        orbit_duration_min, step_s=step_s, entity_id="orbit-primary",
    )
    if p_orbit is None:
        return None  # primary cannot be shown — no scene
    packets.append(p_orbit)

    s_orbit = orbit_czml(
        secondary, secondary.name, COLOR_SECONDARY, orbit_start,
        orbit_duration_min, step_s=step_s, entity_id="orbit-secondary",
    )
    if s_orbit is not None:
        packets.append(s_orbit)

    packets.extend(conjunction_entities(state, tca, primary.name, secondary.name))

    if with_covariance:
        packets.append(
            covariance_ellipsoid_czml(
                tca, state.r_primary, state.v_primary, state.r_secondary
            )
        )

    clock_start, clock_stop = orbit_start, orbit_start + timedelta(seconds=2 * window_s)
    if maneuver_option is not None:
        track = maneuver_track_czml(primary, state, maneuver_option)
        if track is not None:
            packets.append(track)
            burn = _as_utc(maneuver_option.burn_epoch)
            # The maneuver track spans burn−60 min … TCA+15 min — widen the clock
            # so the timeline covers every packet's availability.
            clock_start = min(clock_start, burn - timedelta(minutes=60))
            clock_stop = max(clock_stop, tca + timedelta(minutes=15))

    return build_czml_document(
        packets,
        clock_start,
        clock_stop,
        tca,
        label or f"{primary.name} vs {secondary.name}",
    )


# ── document builder ──────────────────────────────────────────────────────────

def build_czml_document(
    packets: list[dict],
    clock_start: datetime,
    clock_stop: datetime,
    tca: datetime,
    label: str = "OrbitWarden conjunction",
) -> list[dict]:
    """Wrap entity packets in a CZML document with clock + timeline.

    The document packet (id="document") comes first; Cesium reads its ``clock``
    to set the viewer timeline.

    Args:
        packets: entity packets (path, point, polyline, ellipsoid, …).
        clock_start / clock_stop: the full timeline span.
        tca: currentTime for the clock (where the timeline starts).
        label: document name shown in the Cesium data-source list.
    """
    if clock_start.tzinfo is None:
        clock_start = clock_start.replace(tzinfo=timezone.utc)
    if clock_stop.tzinfo is None:
        clock_stop = clock_stop.replace(tzinfo=timezone.utc)
    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)

    doc: dict[str, Any] = {
        "id": "document",
        "name": label,
        "version": "1.0",
        "clock": {
            "interval": _iso_interval(clock_start, clock_stop),
            "currentTime": _iso(tca),
            "multiplier": 60,
            "range": "LOOP_STOP",
        },
    }
    return [doc] + packets
