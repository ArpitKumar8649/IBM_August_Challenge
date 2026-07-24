"""Performance benchmark — screen the ISS against a large real catalog.

Uses Space-Track's `gp` class (the full catalog) as the data source, which also
demonstrates the CelesTrak-independent fallback path. Fetches all Starlink
objects (~8,000+) and screens the ISS against them over a 7-day window.

Usage:
    python -m validation.benchmark
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ingest.celestrak import parse_tle_text
from engine.models import ScreeningConfig
from engine.screen import screen_satellite

ST_LOGIN = "https://www.space-track.org/ajaxauth/login"
ST_QUERY = "https://www.space-track.org/basicspacedata/query/class/gp"


def spacetrack_login(client: httpx.Client) -> None:
    client.post(
        ST_LOGIN,
        data={
            "identity": os.environ.get("SPACETRACK_USERNAME", ""),
            "password": os.environ.get("SPACETRACK_PASSWORD", ""),
        },
    )


def fetch_starlink(client: httpx.Client):
    """All Starlink objects as TLEData (one query, 3LE format for names)."""
    resp = client.get(f"{ST_QUERY}/OBJECT_NAME/~~STARLINK/format/3le/", timeout=180.0)
    resp.raise_for_status()
    return parse_tle_text(resp.text)


def fetch_iss(client: httpx.Client):
    resp = client.get(f"{ST_QUERY}/NORAD_CAT_ID/25544/format/3le/", timeout=60.0)
    resp.raise_for_status()
    return parse_tle_text(resp.text)[0]


def main() -> int:
    # Load .env if present
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    with httpx.Client(timeout=120.0) as client:
        spacetrack_login(client)
        time.sleep(2)
        print("Fetching Starlink catalog from Space-Track...")
        t0 = time.perf_counter()
        catalog = fetch_starlink(client)
        print(f"  {len(catalog)} Starlink objects fetched in {time.perf_counter()-t0:.1f}s\n")
        time.sleep(2)
        iss = fetch_iss(client)

    print(f"Screening {iss.name} (NORAD {iss.norad_id}) over 7 days...")
    print(f"  perigee {iss.perigee_alt_km:.0f} km / apogee {iss.apogee_alt_km:.0f} km\n")

    config = ScreeningConfig(window_days=7.0, time_step_s=60.0, miss_threshold_km=100.0)
    candidates, run = screen_satellite(iss, catalog, config)

    print(f"Band filter : {run.catalog_size} -> {run.band_filtered_size} objects")
    print(f"Candidates  : {run.candidates_found}")
    print(f"Screen time : {run.duration_s:.1f} s")
    if run.band_filtered_size:
        print(f"Throughput  : {run.band_filtered_size / run.duration_s:.0f} objects/s\n")

    print(f"{'RANK':>4}  {'TCA (UTC)':<20}  {'MISS (km)':>10}  {'VREL (km/s)':>11}  OBJECT")
    print("-" * 88)
    for i, c in enumerate(candidates[:12], 1):
        print(
            f"{i:>4}  {c.tca:%Y-%m-%d %H:%M:%S}  {c.miss_distance_km:>10.3f}  "
            f"{c.relative_velocity_kms:>11.3f}  {c.secondary_name} ({c.secondary_norad})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
