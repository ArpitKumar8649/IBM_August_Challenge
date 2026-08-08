"""Visible-pass prediction — "what's passing over me?" (Phase 5.3).

For a ground observer (lat/lon), find the satellites that will be *visually
visible* tonight. Visibility requires all three conditions at once:

  1. Above the horizon — elevation > ~10° (atmosphere + terrain kill low passes).
  2. The observer is in darkness — the Sun is below the twilight angle
     (default −6°, nautical twilight; the classic satellite-watching threshold).
  3. The satellite is sunlit — it is still in sunlight while the ground is
     dark. This is the key "satellite flare" geometry: the ISS is only visible
     after sunset because the Sun is still shining on it up there.

Per pass we derive start / apex / end times, max elevation, the compass
direction at start and end ("look northwest, moving NW→SE"), range at apex,
and a brightness (apparent magnitude) estimate from the standard
satellite-magnitude formula — a physical Lambertian-sphere phase function
combined with a published per-object standard magnitude.

Reuses the existing TEME→ECEF rotation helpers (open_notify.py), the
vectorized SGP4 grid propagation (propagate.py), and mirrors the cylindrical
Earth-shadow test from horizons.py. The Sun is computed with the Astronomical
Almanac low-precision algorithm (NOAA solar-calculator form, ~0.01° accuracy,
no network) — the same frame the rest of the engine uses.

The catalog is deliberately curated to the *bright and famous*: the ISS,
Tiangong, Hubble, and a handful of large bright Earth-observation payloads —
the objects a member of the public can actually see with the naked eye.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from engine.ingest.open_notify import _gmst_rad, _julian_date
from engine.models import PassesResponse, TLEData, VisiblePass
from engine.propagate import propagate_grid, satrec_from_tle, tsince_minutes

R_EARTH_KM = 6378.137  # equatorial radius (WGS-84; matches open_notify/ground_track)
AU_KM = 1.495978707e8  # astronomical unit
STEP_S = 20.0          # pass-scan time step (seconds)
DARK_SPAN_MIN = 4       # minimum contiguous samples to count as a pass (≈ 80 s)
MERGE_GAP_SAMPLES = 3   # merge visibility gaps shorter than ~60 s into one pass
TLE_MAX_RELIABLE_DAYS = 2.0  # pass times drift with TLE age; refuse older windows


# ---------------------------------------------------------------------------
# Curated bright & famous visual catalog: NORAD → (display name, M0, blurb)
# ---------------------------------------------------------------------------
# M0 is the object's standard magnitude — its brightness at the formula's
# reference range. Values are published community figures (Heavens-Above
# class); they are approximate, used for *ranking* passes, and always labelled
# an estimate in the UI. Smaller = brighter (ISS ≈ −1.8 → typically the
# brightest thing in the night sky after the Moon and Venus).
FAMOUS_SATELLITES: dict[int, dict] = {
    25544: {
        "m0": -1.8,
        "blurb": "The International Space Station — the largest structure humanity has ever put in orbit.",
    },
    48274: {
        "m0": -0.7,
        "blurb": "Tiangong, China's space station — the second station visible to the naked eye.",
    },
    20580: {
        "m0": 1.6,
        "blurb": "The Hubble Space Telescope — the orbiting observatory that rewrote astronomy.",
    },
    25994: {"m0": 2.2, "blurb": "Terra — a NASA Earth-observation satellite mapping our planet."},
    27424: {"m0": 2.5, "blurb": "Aqua — a NASA Earth-observation satellite studying water and the climate."},
    39084: {"m0": 3.2, "blurb": "Landsat 8 — the land-monitoring mission that photographs Earth's surface."},
    49260: {"m0": 3.2, "blurb": "Landsat 9 — the newest Landsat, continuing 50 years of land records."},
    40697: {"m0": 3.4, "blurb": "Sentinel-2A — a Copernicus satellite imaging every place on Earth."},
    43013: {"m0": 3.6, "blurb": "NOAA-20 — a weather satellite, our eyes on the atmosphere."},
    37849: {"m0": 3.8, "blurb": "Suomi NPP — a NASA/NOAA climate and weather satellite."},
    38771: {"m0": 3.5, "blurb": "MetOp-B — a European weather satellite."},
    49336: {"m0": 3.5, "blurb": "MetOp-C — a European weather satellite."},
    40446: {"m0": 3.8, "blurb": "GPM — NASA's rain-measuring satellite."},
    41335: {"m0": 3.6, "blurb": "Sentinel-3A — a Copernicus satellite watching the oceans and land."},
    41240: {"m0": 3.8, "blurb": "Jason-3 — a NASA/CNES satellite measuring sea level from space."},
}

# CelesTrak GP groups that cover the curated set: `stations` (ISS, Tiangong)
# plus `active` (everything operational, incl. Hubble, the EOS fleet, weather).
FETCH_GROUPS = ("stations", "active")


# ---------------------------------------------------------------------------
# Sun position (analytical — no network)
# ---------------------------------------------------------------------------


def sun_position_eci(dt: datetime) -> np.ndarray:
    """Geocentric Sun unit vector (equatorial/ICRF≈TEME) — low-precision AA.

    The Astronomical Almanac / NOAA solar-calculator algorithm (Meeus form):
    mean longitude + equation of center + obliquity rotation. Accurate to
    ~0.01° — far below the pass-timing error of the TLEs themselves. The Sun
    moves < 0.05° over a night, so one vector per window is plenty.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    n = _julian_date(dt) - 2451545.0
    mean_long = math.radians(280.460 + 0.9856474 * n)      # deg → rad
    mean_anom = math.radians(357.528 + 0.9856003 * n)
    # Ecliptic longitude with the equation of center.
    lam = mean_long + math.radians(1.915 * math.sin(mean_anom) + 0.020 * math.sin(2 * mean_anom))
    eps = math.radians(23.439 - 0.0000004 * n)             # obliquity of the ecliptic
    return np.array(
        [
            math.cos(lam),
            math.cos(eps) * math.sin(lam),
            math.sin(eps) * math.sin(lam),
        ]
    )


# ---------------------------------------------------------------------------
# Topocentric geometry
# ---------------------------------------------------------------------------


def _teme_to_ecef(r_teme: np.ndarray, dt: datetime) -> np.ndarray:
    """Rotate a TEME position into ECEF via GMST (same math as open_notify)."""
    gmst = _gmst_rad(_julian_date(dt))
    x, y, z = r_teme
    c, s = math.cos(gmst), math.sin(gmst)
    return np.array([x * c + y * s, -x * s + y * c, z])


def observer_ecef(lat_deg: float, lon_deg: float, alt_km: float = 0.0) -> np.ndarray:
    """Observer's ECEF position (geocentric latitude, spherical Earth)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    r = R_EARTH_KM + alt_km
    return np.array(
        [r * math.cos(lat) * math.cos(lon), r * math.cos(lat) * math.sin(lon), r * math.sin(lat)]
    )


def _enu_basis(obs_ecef: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(east, north, up) unit vectors at the observer, in ECEF."""
    up = obs_ecef / np.linalg.norm(obs_ecef)
    east = np.cross(np.array([0.0, 0.0, 1.0]), up)
    east = east / np.linalg.norm(east)
    north = np.cross(up, east)
    return east, north, up


def elevation_azimuth_range(
    r_teme: np.ndarray, dt: datetime, lat_deg: float, lon_deg: float
) -> tuple[float, float, float]:
    """Topocentric (elevation°, azimuth° from north, range km) of a satellite.

    TEME → ECEF → ENU at the observer. Elevation is the angle above the
    horizon; azimuth is measured clockwise from north (0=N, 90=E, 180=S, 270=W).
    """
    r_ecef = _teme_to_ecef(r_teme, dt)
    obs = observer_ecef(lat_deg, lon_deg)
    topo = r_ecef - obs
    range_km = float(np.linalg.norm(topo))
    if range_km == 0:
        return 0.0, 0.0, 0.0
    east, north, up = _enu_basis(obs)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, float(np.dot(up, topo)) / range_km))))
    az = math.degrees(math.atan2(float(np.dot(east, topo)), float(np.dot(north, topo)))) % 360.0
    return elev, az, range_km


def _sunlit_mask(r_teme: np.ndarray, sun_unit: np.ndarray) -> np.ndarray:
    """Vectorized cylindrical Earth-shadow test (mirrors horizons.in_earth_shadow).

    A satellite is sunlit unless it is on the night side (opposite the Sun)
    *and* within Earth's radius of the Earth-Sun line — i.e. inside Earth's
    shadow cylinder, the standard LEO approximation.
    """
    s = sun_unit / np.linalg.norm(sun_unit)
    along = r_teme @ s
    perp = np.linalg.norm(r_teme - np.outer(along, s), axis=1)
    return ~((along < 0) & (perp < R_EARTH_KM))


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------


def apparent_magnitude(range_km: float, phase_cos: float, m0: float) -> float:
    """Apparent magnitude estimate: M0, range, and Lambertian phase function.

    M = M0 − 15.75 + 2.5·log10(r²) − 2.5·log10((1 + cos β)/2)

    The phase term is the integrated brightness of a Lambertian sphere: 0 at
    full phase (β=0, Sun behind the observer) and +0.75 mag at quarter phase.
    The −15.75 constant calibrates M0 to the community reference range
    (~1414 km). An estimate — used for ranking, labelled as such in the UI.
    """
    phase_cos = max(-1.0, min(1.0, phase_cos))
    phase_term = 2.5 * math.log10(max(0.5 * (1.0 + phase_cos), 1e-6))
    return m0 - 15.75 + 2.5 * math.log10(max(range_km * range_km, 1e-6)) - phase_term


def brightness_label(mag: float) -> str:
    """Plain-language band for an apparent magnitude."""
    if mag < 0:
        return "extremely bright — brighter than any star"
    if mag < 2:
        return "very bright — easy to spot"
    if mag < 3.5:
        return "bright — visible from the city"
    if mag < 5:
        return "faint — best from dark skies"
    return "very faint — binoculars help"


def elevation_plain(elev_deg: float) -> str:
    """How high in the sky, in everyday words."""
    if elev_deg >= 80:
        return "almost straight overhead"
    if elev_deg >= 60:
        return "high overhead"
    if elev_deg >= 40:
        return "about halfway up the sky"
    if elev_deg >= 20:
        return "low in the sky"
    return "just above the horizon"


COMPASS_POINTS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def compass_point(az_deg: float) -> str:
    """16-point compass label for a bearing in degrees (0=N, clockwise)."""
    idx = int(round((az_deg % 360.0) / 22.5)) % 16
    return COMPASS_POINTS[idx]


def _local_time_str(dt: datetime, lon_deg: float) -> str:
    """Format a UTC time as observer-local (longitude-offset approximation)."""
    local = dt + timedelta(hours=lon_deg / 15.0)
    # %-I is Linux-only; strip the leading zero manually for portability.
    return local.strftime("%I:%M %p").lstrip("0")


# ---------------------------------------------------------------------------
# Pass detection
# ---------------------------------------------------------------------------


def _dark_span(lat_deg: float, lon_deg: float, local_date: datetime) -> tuple[datetime, datetime] | None:
    """The contiguous span (UTC) tonight when the Sun is below the horizon.

    Samples the Sun elevation from local 18:00 to local 10:00 the next day and
    returns the longest continuous span with Sun elevation < 0° — clipped at
    the window edges. Returns None in polar summer (no darkness).
    """
    local_18 = local_date.replace(hour=18, minute=0, second=0, microsecond=0)
    start_utc = local_18 - timedelta(hours=lon_deg / 15.0)
    times = np.arange(0, 16 * 60, 5)  # 5-minute samples
    sun = sun_position_eci(start_utc)  # Sun moves <0.05° over the night — one vector is fine
    dark: list[bool] = []
    for t_min in times:
        dt = start_utc + timedelta(minutes=int(t_min))
        # Rotate the fixed Sun direction to ECEF at each sample for the local horizon test.
        sun_ecef = _teme_to_ecef(sun, dt)
        up = observer_ecef(lat_deg, lon_deg)
        up = up / np.linalg.norm(up)
        el = math.degrees(math.asin(max(-1.0, min(1.0, float(np.dot(up, sun_ecef))))))
        dark.append(el < 0.0)

    # Longest contiguous dark run.
    best: tuple[int, int] | None = None
    run_start = None
    for i, d in enumerate(dark):
        if d and run_start is None:
            run_start = i
        elif not d and run_start is not None:
            if best is None or (i - run_start) > (best[1] - best[0]):
                best = (run_start, i)
            run_start = None
    if run_start is not None:
        if best is None or (len(dark) - run_start) > (best[1] - best[0]):
            best = (run_start, len(dark))
    if best is None:
        return None
    return start_utc + timedelta(minutes=int(times[best[0]])), start_utc + timedelta(
        minutes=int(times[best[1] - 1])
    )


def compute_passes_for_location(
    catalog: list[TLEData],
    lat_deg: float,
    lon_deg: float,
    date: str | None = None,
    min_elevation: float = 10.0,
    twilight_deg: float = -6.0,
    limit: int = 12,
    max_magnitude: float = 4.5,
) -> PassesResponse:
    """Tonight's visible passes for one observer, computed from TLEs.

    Args:
        catalog: TLEs to consider (usually the curated famous set).
        lat_deg, lon_deg: observer position.
        date: observer-local date (YYYY-MM-DD); defaults to today.
        min_elevation: horizon cutoff for a "visible" pass (deg).
        twilight_deg: Sun elevation below which the sky counts as dark.
        limit: cap on returned passes.
        max_magnitude: drop passes dimmer than this (naked-eye bound).

    Returns a PassesResponse envelope. If `date` is outside the reliable
    window, `available` is False with an explanatory note — pass times drift
    with TLE age, and the feature must not send a family outside at the wrong
    hour on stale numbers.
    """
    if date is None:
        date = (datetime.now(timezone.utc) + timedelta(hours=lon_deg / 15.0)).strftime("%Y-%m-%d")
    try:
        local_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return PassesResponse(
            available=False, latitude=lat_deg, longitude=lon_deg, date=date,
            note=f"'{date}' is not a valid YYYY-MM-DD date.",
        )

    now_utc = datetime.now(timezone.utc)
    oldest_ok = now_utc - timedelta(days=TLE_MAX_RELIABLE_DAYS)
    newest_ok = now_utc + timedelta(days=TLE_MAX_RELIABLE_DAYS)
    if not (oldest_ok <= local_date <= newest_ok):
        return PassesResponse(
            available=False, latitude=lat_deg, longitude=lon_deg, date=date,
            note=(
                f"Predictions are only reliable for today or tomorrow (current orbital data "
                f"ages ~1 km/day) — '{date}' is outside that window."
            ),
        )

    span = _dark_span(lat_deg, lon_deg, local_date)
    if span is None:
        return PassesResponse(
            available=True, latitude=lat_deg, longitude=lon_deg, date=date,
            night_start=None, night_end=None,
            note="The Sun never sets here tonight — no satellite passes are visible.",
        )

    dark_start, dark_end = span
    if now_utc > dark_end:
        return PassesResponse(
            available=True, latitude=lat_deg, longitude=lon_deg, date=date,
            night_start=dark_start, night_end=dark_end,
            note="Tonight's passes have already ended — check back earlier tomorrow.",
        )
    if dark_start < now_utc:
        dark_start = now_utc  # don't predict passes that already started

    n_samples = int((dark_end - dark_start).total_seconds() / STEP_S) + 1
    offsets_s = np.arange(n_samples) * STEP_S
    offsets_min = offsets_s / 60.0
    times = [dark_start + timedelta(seconds=float(o)) for o in offsets_s]

    # Precompute the TEME→ECEF rotation for every sample (vectorized), and one
    # Sun unit vector for the whole window (it moves < 0.05° in a night).
    jd = np.array([_julian_date(t) for t in times])
    t_cent = (jd - 2451545.0) / 36525.0
    gmst = np.radians(
        (280.46061837 + 360.98564736629 * (jd - 2451545.0)
         + 0.000387933 * t_cent**2 - t_cent**3 / 38710000.0) % 360.0
    )
    c_rot, s_rot = np.cos(gmst), np.sin(gmst)
    sun_teme = sun_position_eci(dark_start + (dark_end - dark_start) / 2)
    # Sun direction in ECEF per sample (constant vector, rotating frame).
    sun_ecef = np.stack(
        [
            sun_teme[0] * c_rot + sun_teme[1] * s_rot,
            -sun_teme[0] * s_rot + sun_teme[1] * c_rot,
            np.full(n_samples, sun_teme[2]),
        ],
        axis=1,
    ) * AU_KM

    obs = observer_ecef(lat_deg, lon_deg)
    up = obs / np.linalg.norm(obs)
    east, north, _up = _enu_basis(obs)

    passes: list[VisiblePass] = []
    max_tle_age = 0.0
    for tle in catalog:
        max_tle_age = max(max_tle_age, tle.age_days)
        sat = satrec_from_tle(tle)
        positions, _vel = propagate_grid(sat, tsince_minutes(dark_start, tle) + offsets_min)
        if not np.isfinite(positions).any():
            continue

        # Rotate to ECEF (vectorized), then topocentric geometry.
        X, Y, Z = positions[:, 0], positions[:, 1], positions[:, 2]
        r_ecef = np.stack([X * c_rot + Y * s_rot, -X * s_rot + Y * c_rot, Z], axis=1)
        topo = r_ecef - obs
        rng = np.linalg.norm(topo, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            elev = np.degrees(np.arcsin(np.clip(topo @ up / rng, -1.0, 1.0)))
            az = np.degrees(np.arctan2(topo @ east, topo @ north)) % 360.0
        # Sun phase angle at the satellite (sat→obs vs sat→sun).
        to_obs = obs - r_ecef
        to_sun = sun_ecef - r_ecef
        with np.errstate(invalid="ignore", divide="ignore"):
            phase_cos = np.sum(to_obs * to_sun, axis=1) / (
                np.linalg.norm(to_obs, axis=1) * np.linalg.norm(to_sun, axis=1)
            )
        phase_cos = np.clip(phase_cos, -1.0, 1.0)
        # The dark *span* only bounds the window (Sun < 0°); enforce the real
        # darkness threshold per sample (Sun below the twilight angle — the
        # zenith dot product with the rotating Sun unit vector) and require the
        # satellite to be sunlit (cylindrical Earth-shadow test).
        sun_el_obs = np.degrees(np.arcsin(np.clip((sun_ecef / AU_KM) @ up, -1.0, 1.0)))
        visible = (
            (elev >= min_elevation) & (sun_el_obs < twilight_deg) & _sunlit_mask(positions, sun_teme)
        )

        # Segment contiguous visibility into passes; merge sub-minute gaps.
        segs = _segments(visible)
        for seg_start, seg_end in segs:
            if seg_end - seg_start < DARK_SPAN_MIN:
                continue
            apex = seg_start + int(np.argmax(elev[seg_start:seg_end]))
            m0 = FAMOUS_SATELLITES.get(tle.norad_id, {}).get("m0", 4.0)
            mag = apparent_magnitude(rng[apex], phase_cos[apex], m0)
            if mag > max_magnitude:
                continue
            az0 = float(az[seg_start])
            az1 = float(az[seg_end - 1])
            passes.append(
                VisiblePass(
                    norad_id=tle.norad_id,
                    name=tle.name,
                    start=times[seg_start],
                    max_elevation_time=times[apex],
                    end=times[seg_end - 1],
                    max_elevation_deg=round(float(elev[apex]), 1),
                    elevation_start_deg=round(float(elev[seg_start]), 1),
                    elevation_end_deg=round(float(elev[seg_end - 1]), 1),
                    azimuth_start_deg=round(az0, 1),
                    azimuth_apex_deg=round(float(az[apex]), 1),
                    azimuth_end_deg=round(az1, 1),
                    direction_from=compass_point(az0),
                    direction_to=compass_point(az1),
                    range_km_at_max=round(float(rng[apex]), 0),
                    magnitude=round(mag, 1),
                    brightness_label=brightness_label(mag),
                    object_blurb=FAMOUS_SATELLITES.get(tle.norad_id, {}).get("blurb", ""),
                    look_instruction=_look_instruction(
                        tle, az0, times[seg_start], lon_deg, elev[apex]
                    ),
                )
            )

    passes.sort(key=lambda p: p.start)
    note = (
        f"Brightness is an estimate; pass times come from orbital elements "
        f"fetched today (oldest used: {max_tle_age:.1f} days old) and can drift a few "
        f"minutes. 'Dark' means the Sun is more than {abs(twilight_deg)}° below the "
        f"horizon; the satellite must still be in sunlight."
    )
    return PassesResponse(
        available=True,
        latitude=lat_deg,
        longitude=lon_deg,
        date=date,
        night_start=dark_start,
        night_end=dark_end,
        max_tle_age_days=round(max_tle_age, 1),
        passes=passes[:limit],
        note=note,
    )


def _look_instruction(tle: TLEData, az0: float, start: datetime, lon_deg: float, apex_elev: float) -> str:
    """The plain-language sentence the feature is built around."""
    short = tle.name.split("(")[0].strip()
    return (
        f"Look {compass_point(az0)} ({az0:.0f}°) at {_local_time_str(start, lon_deg)} — "
        f"{short} will pass {elevation_plain(float(apex_elev))}."
    )


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as half-open [start, end) intervals, gaps fused.

    Sub-second gaps shorter than MERGE_GAP_SAMPLES are absorbed into the run so
    a pass that flickers at the elevation threshold stays one pass.
    """
    runs: list[tuple[int, int]] = []
    start = None
    gap = 0
    for i, v in enumerate(mask):
        if v:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > MERGE_GAP_SAMPLES:
                # The False samples run from i-gap+1 .. i; the run ends just before them.
                runs.append((start, i - gap + 1))
                start = None
                gap = 0
    if start is not None:
        runs.append((start, len(mask)))
    return runs


# ---------------------------------------------------------------------------
# Catalog fetch — always fresh, deliberately no fallback (design decision)
# ---------------------------------------------------------------------------


def fetch_visible_catalog() -> tuple[list[TLEData], list[int]]:
    """Fetch fresh TLEs for the curated famous set (stations + active groups).

    Raises engine.ingest.celestrak.CelesTrakError on failure — the endpoint
    answers honestly (unavailable) rather than predicting passes from stale
    elements. The 24 h disk cache means at most one fetch per group per day.
    Returns (objects, missing_norads).
    """
    from engine.ingest.celestrak import fetch_groups

    all_objects = fetch_groups(FETCH_GROUPS)
    by_id = {o.norad_id: o for o in all_objects}
    objects = [by_id[n] for n in FAMOUS_SATELLITES if n in by_id]
    missing = [n for n in FAMOUS_SATELLITES if n not in by_id]
    return objects, missing
