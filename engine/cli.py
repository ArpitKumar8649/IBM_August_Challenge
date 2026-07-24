"""OrbitWarden screening CLI — one command to screen a satellite (scored).

Usage:
    python -m engine.cli                       # screen the ISS vs the active catalog
    python -m engine.cli --norad 25544         # screen a specific satellite
    python -m engine.cli --group starlink      # screen vs a specific catalog group
    python -m engine.cli --days 3 --top 10     # 3-day window, top 10 events
    python -m engine.cli --enrich              # add SATCAT object metadata (needs .env)
"""

from __future__ import annotations

import argparse
import sys

import httpx

from engine.ingest.celestrak import fetch_group, fetch_groups
from engine.ingest.spaceweather import fetch_space_weather
from engine.ingest.spacetrack import enrich
from engine.models import ScreeningConfig
from engine.screen import full_screen


def main() -> int:
    parser = argparse.ArgumentParser(description="Screen a satellite for conjunctions")
    parser.add_argument("--norad", type=int, default=25544, help="Primary satellite NORAD id (default: ISS)")
    parser.add_argument("--group", type=str, default=None, help="Catalog group to screen against (default: active+debris)")
    parser.add_argument("--days", type=float, default=7.0, help="Look-ahead window in days")
    parser.add_argument("--step", type=float, default=60.0, help="Coarse-scan time step (s)")
    parser.add_argument("--threshold", type=float, default=100.0, help="Miss threshold (km)")
    parser.add_argument("--top", type=int, default=20, help="Show top N events")
    parser.add_argument("--enrich", action="store_true", help="Fetch SATCAT metadata (needs Space-Track creds in .env)")
    args = parser.parse_args()

    print(f"Fetching catalog ({args.group or 'active + debris groups'})...")
    catalog = fetch_group(args.group) if args.group else fetch_groups()
    print(f"Catalog: {len(catalog)} objects\n")

    primary = next((o for o in catalog if o.norad_id == args.norad), None)
    if primary is None:
        print(f"ERROR: NORAD {args.norad} not found in catalog")
        return 1

    config = ScreeningConfig(
        window_days=args.days, time_step_s=args.step, miss_threshold_km=args.threshold
    )
    print(f"Screening {primary.name} (NORAD {primary.norad_id}) over {args.days} days...")
    print(f"  perigee {primary.perigee_alt_km:.0f} km / apogee {primary.apogee_alt_km:.0f} km\n")

    object_info = {}
    space_weather = None
    with httpx.Client(timeout=120.0) as client:
        space_weather = fetch_space_weather(client)
        if args.enrich:
            object_info = enrich([primary.norad_id], client)

    scored, run = full_screen(
        primary, catalog, object_info=object_info, space_weather=space_weather, config=config
    )

    print(f"Band filter: {run.catalog_size} -> {run.band_filtered_size} objects")
    print(f"Screened in {run.duration_s:.1f}s | {len(scored)} scored conjunctions\n")
    print(
        f"{'#':>3} {'RISK':>5} {'TCA (UTC)':<17} {'MISS km':>8} {'Pc':>9} "
        f"{'GEOMETRY':<11} {'TYPE':<12} {'FLG':<3} OBJECT"
    )
    print("-" * 92)
    for i, e in enumerate(scored[: args.top], 1):
        flag = "⚠" if e.storm_flag else ""
        man = "" if e.secondary_maneuverable else " *"
        print(
            f"{i:>3} {e.risk_score:>5.1f} {e.tca:%m-%d %H:%M:%S} {e.miss_distance_km:>8.3f} "
            f"{e.pc:>9.2e} {e.geometry:<11} {e.secondary_type:<12} {flag:<3} "
            f"{e.secondary_name}{man}"
        )
    if not scored:
        print("  (no conjunctions below threshold in window)")
    print("\n(* = secondary cannot maneuver;  ⚠ = storm flag)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
