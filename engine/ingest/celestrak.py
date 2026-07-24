"""CelesTrak GP catalog ingestion.

Fetches Two-Line Element groups from celestrak.org (no auth required), parses
them into TLEData with cheap derived orbital geometry, and caches to disk for
24 hours so repeated runs are polite and fast.

CelesTrak GP text format (FORMAT=tle) — records of three lines:

    ISS (ZARYA)
    1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993
    2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from engine.models import TLEData

GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

# WGS-72 constants — the canonical values SGP4 itself uses.
MU_EARTH_KM3_S2 = 398600.8  # Earth gravitational parameter
R_EARTH_KM = 6378.135  # WGS-72 equatorial radius

# Catalog groups we screen against. Payloads first, then the big debris
# families — together these cover the overwhelming majority of LEO risk.
PAYLOAD_GROUPS = ("active", "stations", "cubesat")
DEBRIS_GROUPS = ("iridium-33-debris", "cosmos-2251-debris", "fengyun-1c-debris")
DEFAULT_GROUPS = PAYLOAD_GROUPS + DEBRIS_GROUPS

CACHE_TTL = timedelta(hours=24)
REQUEST_PAUSE_S = 1.0  # politeness between consecutive fetches
MAX_ATTEMPTS =3
USER_AGENT = "OrbitWarden/1.0 (IBM AI Builders Challenge; research use)"


class CelesTrakError(RuntimeError):
    """Raised when the catalog cannot be fetched or parsed."""


def _parse_epoch(line1: str) -> datetime:
    """TLE epoch field (cols 19-32): YYDDD.DDDDDDDD — 2-digit year + day of year."""
    field = line1[18:32].strip()
    year = int(field[:2])
    year += 1900 if year >= 57 else 2000
    day_of_year = float(field[2:])  # e.g. "001.50000000" -> 1.5
    base = datetime(year, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(days=day_of_year - 1.0)


def _derive_geometry(line2: str) -> tuple[float, float, float]:
    """(inclination_deg, perigee_alt_km, apogee_alt_km) from TLE line 2."""
    inclination = float(line2[8:16])
    eccentricity = float("0." + line2[26:33])
    mean_motion_rev_day = float(line2[52:63])

    n_rad_s = mean_motion_rev_day * 2.0 * math.pi / 86400.0
    semi_major_km = (MU_EARTH_KM3_S2 / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
    perigee_alt = semi_major_km * (1.0 - eccentricity) - R_EARTH_KM
    apogee_alt = semi_major_km * (1.0 + eccentricity) - R_EARTH_KM
    return inclination, perigee_alt, apogee_alt


def parse_tle_text(text: str) -> list[TLEData]:
    """Parse CelesTrak GP text (3-line records) into TLEData objects.

    Self-synchronizing: scans for a '1 ' line immediately followed by a '2 '
    line and takes the preceding line as the name, so stray lines in the feed
    cannot desync the parser.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    objects: list[TLEData] = []
    i = 0
    while i < len(lines) - 1:
        line1, line2 = lines[i], lines[i + 1]
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            i += 1
            continue
        name = lines[i - 1] if i > 0 else ""
        # Space-Track 3LE prefixes the name line with "0 "; CelesTrak does not.
        name = name[2:] if name.startswith("0 ") else name
        try:
            norad_id = int(line2[2:7])
            inclination, perigee_alt, apogee_alt = _derive_geometry(line2)
            objects.append(
                TLEData(
                    norad_id=norad_id,
                    name=name.strip(),
                    line1=line1,
                    line2=line2,
                    epoch=_parse_epoch(line1),
                    inclination_deg=inclination,
                    perigee_alt_km=perigee_alt,
                    apogee_alt_km=apogee_alt,
                )
            )
        except (ValueError, IndexError):
            pass  # skip malformed records
        i += 2
    return objects


def _cache_path(group: str, catalog_dir: Path) -> Path:
    return catalog_dir / f"{group}.json"


def _read_cache(group: str, catalog_dir: Path) -> list[TLEData] | None:
    path = _cache_path(group, catalog_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    fetched_at = datetime.fromisoformat(payload["fetched_at"])
    if datetime.now(timezone.utc) - fetched_at > CACHE_TTL:
        return None
    return [TLEData.model_validate(o) for o in payload["objects"]]


def _write_cache(group: str, objects: list[TLEData], catalog_dir: Path) -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "group": group,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "objects": [o.model_dump(mode="json") for o in objects],
    }
    _cache_path(group, catalog_dir).write_text(json.dumps(payload))


def fetch_group(
    group: str,
    catalog_dir: Path | str = "data/cache/celestrak",
    use_cache: bool = True,
    client: httpx.Client | None = None,
) -> list[TLEData]:
    """Fetch one CelesTrak GP group, cached to disk for 24 h.

    Args:
        group: CelesTrak GROUP name, e.g. "active", "stations", "cosmos-2251-debris".
        catalog_dir: Where cached group JSON is stored.
        use_cache: Set False to force a fresh fetch.
        client: Optional shared httpx.Client (for connection reuse across groups).
    """
    catalog_dir = Path(catalog_dir)
    if use_cache:
        cached = _read_cache(group, catalog_dir)
        if cached is not None:
            return cached

    own_client = client is None
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT})
    try:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = http.get(GP_URL, params={"GROUP": group, "FORMAT": "tle"})
                resp.raise_for_status()
                objects = parse_tle_text(resp.text)
                if not objects:
                    raise CelesTrakError(f"group '{group}' returned no parseable TLEs")
                _write_cache(group, objects, catalog_dir)
                return objects
            except (httpx.HTTPError, CelesTrakError) as exc:
                last_error = exc
                time.sleep(REQUEST_PAUSE_S * (attempt + 1))
        raise CelesTrakError(f"failed to fetch group '{group}': {last_error}") from last_error
    finally:
        if own_client:
            http.close()


def fetch_groups(
    groups: tuple[str, ...] = DEFAULT_GROUPS,
    catalog_dir: Path | str = "data/cache/celestrak",
    use_cache: bool = True,
) -> list[TLEData]:
    """Fetch several groups into one de-duplicated catalog (by NORAD id)."""
    catalog: dict[int, TLEData] = {}
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        for group in groups:
            for obj in fetch_group(group, catalog_dir, use_cache, client):
                catalog.setdefault(obj.norad_id, obj)
            time.sleep(REQUEST_PAUSE_S)
    return list(catalog.values())
