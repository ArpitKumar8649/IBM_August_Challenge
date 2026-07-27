"""JPL Horizons — precision ephemerides for planets, moons, and the Sun.

Enables deep-space awareness and a precision reference. The key integration:
the **real Sun direction** (geocentric, from Horizons) feeds the solar-radiation-
pressure (SRP) model in engine/precision.py, replacing the crude default, and
enables an **Earth-shadow (eclipse) check** — SRP is zero when the satellite is
in Earth's shadow.

Verified endpoint (2026-07-27):
  GET https://ssd.jpl.nasa.gov/api/horizons.api?format=json&COMMAND='10'
      &EPHEM_TYPE='VECTOR'&CENTER='500@399'&START_TIME=…&STOP_TIME=…&STEP_SIZE=…
  → JSON {"result": "...formatted text..."}; the ephemeris is the block between
    $$SOE and $$EOE, with X/Y/Z (km) and VX/VY/VZ (km/s) in ICRF/J2000.

Gotchas:
  · Horizons uses COMMAND codes ('499' Mars, '301' Moon, '10' Sun, '399' Earth).
  · The vectors are strings in a formatted block — parse with regex.
  · The frame is ICRF (≈J2000); our TEME≈J2000 approximation is fine for the
    Sun direction (the Sun is ~1 AU away, so frame nuances are negligible).
  · Rate limit ~300 req/min — plenty.

Cache TTL 24 h (planets move slowly).
"""

from __future__ import annotations

import re

import httpx

from engine.ingest.cache import DiskCache
from engine.models import EphemerisState

HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
TTL = 24 * 3600  # 24 h

# Common solar-system bodies: name → Horizons COMMAND code.
BODY_CODES = {
    "sun": "10",
    "mercury": "199",
    "venus": "299",
    "earth": "399",
    "moon": "301",
    "mars": "499",
    "jupiter": "599",
    "saturn": "699",
    "uranus": "799",
    "neptune": "899",
    "pluto": "999",
}

# Approximate radii (km) for shadow/geometry sanity checks.
BODY_RADII_KM = {
    "sun": 696000.0,
    "earth": 6378.137,
    "moon": 1737.4,
    "mars": 3389.5,
}

_SOE_BLOCK = re.compile(r"\$\$SOE(.*?)\$\$EOE", re.S)
_STATE_LINE = re.compile(
    r"X\s*=\s*([-+0-9.eE]+)\s+Y\s*=\s*([-+0-9.eE]+)\s+Z\s*=\s*([-+0-9.eE]+)\s+"
    r"VX\s*=\s*([-+0-9.eE]+)\s+VY\s*=\s*([-+0-9.eE]+)\s+VZ\s*=\s*([-+0-9.eE]+)"
)
_JD_LINE = re.compile(r"^\s*([0-9.]+)\s*=\s*A\.D\.\s*(.+?)\s*(?:TDB|TDT)\s*$", re.M)


def body_code(name_or_code: str) -> str:
    """Resolve a body name (e.g. 'mars') to its Horizons COMMAND code ('499').

    Accepts either a known name or a raw numeric code (returned as-is).
    """
    key = name_or_code.strip().lower()
    if key in BODY_CODES:
        return BODY_CODES[key]
    # Already a numeric code?
    if name_or_code.strip().lstrip("-").isdigit():
        return name_or_code.strip()
    raise ValueError(f"unknown body '{name_or_code}' (known: {', '.join(sorted(BODY_CODES))})")


def parse_ephemeris(result_text: str, body_name: str = "") -> list[EphemerisState]:
    """Parse the $$SOE..$$EOE block of a Horizons VECTOR result into states."""
    match = _SOE_BLOCK.search(result_text)
    if not match:
        return []
    block = match.group(1)

    # Collect (jd, calendar_time) headers and state vectors in order.
    headers = [(m.group(1), m.group(2).strip()) for m in _JD_LINE.finditer(block)]
    vectors = [
        tuple(float(g) for g in m.groups()) for m in _STATE_LINE.finditer(block)
    ]

    states: list[EphemerisState] = []
    for i, vec in enumerate(vectors):
        jd = float(headers[i][0]) if i < len(headers) else 0.0
        time = headers[i][1] if i < len(headers) else ""
        states.append(
            EphemerisState(
                body_name=body_name,
                time=time,
                jd=jd,
                r_eci=[vec[0], vec[1], vec[2]],
                v_eci=[vec[3], vec[4], vec[5]],
            )
        )
    return states


def fetch_ephemeris(
    command: str,
    start_time: str,
    stop_time: str,
    step_size: str = "1 d",
    center: str = "500@399",
    body_name: str = "",
    client: httpx.Client | None = None,
) -> list[EphemerisState]:
    """Fetch a VECTOR ephemeris from Horizons.

    Args:
        command: Horizons COMMAND code (e.g. '10' for the Sun, '499' for Mars).
        start_time, stop_time: e.g. '2026-07-27'.
        step_size: e.g. '1 d', '1 h'.
        center: reference center; '500@399' = geocentric (default), '500@0' =
            solar-system barycenter.
        body_name: label for the returned states.

    Returns:
        List of EphemerisState (ICRF/J2000, km & km/s). Empty on failure.
    """
    params = {
        "format": "json",
        "COMMAND": f"'{command}'",
        "EPHEM_TYPE": "'VECTOR'",
        "CENTER": f"'{center}'",
        "START_TIME": f"'{start_time}'",
        "STOP_TIME": f"'{stop_time}'",
        "STEP_SIZE": f"'{step_size}'",
        "REF_SYSTEM": "'ICRF'",
        "VEC_TABLE": "'2'", # position + velocity
    }
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            resp = http.get(HORIZONS_API, params=params, timeout=40.0)
            resp.raise_for_status()
            data = resp.json()
            result_text = data.get("result", "")
            states = parse_ephemeris(result_text, body_name)
            return [s.model_dump() for s in states]
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set(
            "horizons", _fetch,
            params={"command": command, "start": start_time, "stop": stop_time,
                    "step": step_size, "center": center},
            ttl_s=TTL,
        )
        return [EphemerisState.model_validate(s) for s in raw]
    except Exception:  # noqa: BLE001
        return []


def fetch_body_state(
    body: str, start_time: str, stop_time: str, step_size: str = "1 d",
    center: str = "500@399", client: httpx.Client | None = None,
) -> list[EphemerisState]:
    """Convenience: fetch a body's ephemeris by name (e.g. 'mars')."""
    try:
        command = body_code(body)
    except ValueError:
        return []
    return fetch_ephemeris(command, start_time, stop_time, step_size, center, body, client)


def sun_direction_geocentric(
    date: str | None = None, client: httpx.Client | None = None
) -> list[float] | None:
    """Unit vector from Earth toward the Sun (geocentric, ICRF) on a given date.

    Used to feed the SRP model with the real Sun direction instead of a default.
    Returns None if Horizons is unavailable.
    """
    from datetime import date as _date, timedelta

    if date is None:
        date = _date.today().isoformat()
    # Fetch a 2-day window and use the first state.
    stop = (_date.fromisoformat(date) + timedelta(days=2)).isoformat()
    states = fetch_ephemeris("10", date, stop, "1 d", "500@399", "sun", client)
    if not states or not states[0].r_eci:
        return None
    r = states[0].r_eci
    norm = (r[0] ** 2 + r[1] ** 2 + r[2] ** 2) ** 0.5
    if norm == 0:
        return None
    return [r[0] / norm, r[1] / norm, r[2] / norm]


def in_earth_shadow(
    r_sat_eci: list[float], sun_dir: list[float], r_earth_km: float = 6378.137
) -> bool:
    """Cylindrical Earth-shadow test: is the satellite in Earth's shadow?

    The satellite is in shadow if it is on the night side (opposite the Sun) and
    its perpendicular distance from the Earth-Sun line is less than Earth's radius
    (cylindrical shadow approximation — accurate for LEO, where the penumbra is
    small relative to the umbra).

    Args:
        r_sat_eci: satellite ECI position (km).
        sun_dir: unit vector from Earth toward the Sun.
        r_earth_km: Earth radius.

    Returns:
        True if the satellite is in Earth's shadow (SRP should be zero).
    """
    import numpy as np

    r = np.asarray(r_sat_eci, float)
    s = np.asarray(sun_dir, float)
    s = s / np.linalg.norm(s)
    # Projection of satellite position onto the Sun direction.
    along = float(np.dot(r, s))
    if along > 0:
        return False  # on the day side (toward the Sun) → not in shadow
    # Perpendicular distance from the Earth-Sun line.
    perp_vec = r - along * s
    perp = float(np.linalg.norm(perp_vec))
    return perp < r_earth_km
