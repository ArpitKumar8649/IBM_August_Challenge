"""Nightly screening batch — the full pipeline for watched satellites.

For each watched satellite: fetch catalog (CelesTrak, Space-Track fallback) ->
coarse scan -> SATCAT-enrich the candidate secondaries (one batched query) ->
fetch space weather -> refine + score every candidate -> persist to the store.

Runnable as a one-pass script (Code Engine will schedule it as a cron later):
    python -m batch.nightly                 # screen the ISS
    python -m batch.nightly --norad 25544 63210   # ISS + JINJUSAT-1B
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ingest.celestrak import fetch_group, fetch_groups
from engine.ingest.spaceweather import fetch_space_weather
from engine.ingest.spacetrack import enrich
from engine.models import ScoredConjunction, ScreeningConfig, ScreeningRun
from engine.screen import analyze_conjunctions, screen_satellite
from engine.storage import ScreeningStore

WATCHED = [25544]  # ISS — add university CubeSat NORAD ids here (e.g. 63210 JINJUSAT-1B)


def fetch_catalog(client: httpx.Client, group: str | None, watched: list[int]):
    """CelesTrak groups first; Space-Track Starlink + watched sats as fallback.

    CelesTrak rate-limits large groups under heavy polling, so the Space-Track
    `gp` class (validated in Phase 1) is the production fallback. Watched
    satellites are always fetched so they're present even in the fallback catalog.
    """
    try:
        catalog = fetch_group(group) if group else fetch_groups()
    except Exception as exc:  # noqa: BLE001 — any CelesTrak failure -> fallback
        print(f"  CelesTrak unavailable ({exc}); falling back to Space-Track")
        from validation.benchmark import fetch_iss, fetch_starlink

        catalog = fetch_starlink(client)
        for norad in watched:
            try:
                obj = fetch_iss(client) if norad == 25544 else None
                if obj and obj.norad_id not in {o.norad_id for o in catalog}:
                    catalog.append(obj)
            except Exception:  # noqa: BLE001
                continue
    return catalog


def screen_one(
    primary_norad: int,
    catalog: list,
    store: ScreeningStore,
    config: ScreeningConfig,
    client: httpx.Client,
) -> tuple[list[ScoredConjunction], ScreeningRun] | None:
    """Run the full pipeline for one satellite and persist the results."""
    primary = next((o for o in catalog if o.norad_id == primary_norad), None)
    if primary is None:
        print(f"  NORAD {primary_norad} not in catalog — skipping")
        return None

    print(f"\nScreening {primary.name} (NORAD {primary.norad_id})...")
    candidates, run = screen_satellite(primary, catalog, config)
    print(
        f"  band filter {run.catalog_size} -> {run.band_filtered_size}, "
        f"{run.candidates_found} coarse candidates in {run.duration_s:.1f}s"
    )

    # Enrich the closest candidate secondaries (one batched SATCAT query) —
    # these are the ones analyze_conjunctions will refine. Exclude co-located
    # objects (coarse vrel ~ 0: docked modules / duplicates).
    from engine.screen import CO_LOCATION_VREL_KMS

    closest = sorted(
        (
            c
            for c in candidates
            if c.secondary_norad != primary.norad_id
            and c.relative_velocity_kms >= CO_LOCATION_VREL_KMS
        ),
        key=lambda c: c.miss_distance_km,
    )[:200]
    cand_ids = [c.secondary_norad for c in closest] + [primary.norad_id]
    object_info = enrich(cand_ids, client)
    print(f"  SATCAT enrichment: {len(object_info)} objects")

    space_weather = fetch_space_weather(client)
    print(
        f"  space weather: max Kp {space_weather.max_kp_3day:.1f}, "
        f"active storm {space_weather.active_storm}"
    )

    catalog_by_id = {o.norad_id: o for o in catalog}
    scored = analyze_conjunctions(
        primary, candidates, catalog_by_id, object_info, space_weather, config
    )

    run_id = store.save_run(run)
    store.save_events(run_id, scored)
    store.save_objects(object_info)
    # Persist the full context so the API/agent can serve this run without re-screening.
    store.save_context(run_id, scored, catalog_by_id, object_info)
    print(f"  persisted run #{run_id}: {len(scored)} scored events")
    return scored, run


def print_scored(scored: list[ScoredConjunction], top: int = 10) -> None:
    print(
        f"\n  {'#':>3} {'RISK':>5} {'TCA (UTC)':<17} {'MISS km':>8} {'Pc':>9} "
        f"{'GEOMETRY':<11} {'TYPE':<12} {'FLG':<4} OBJECT"
    )
    print("  " + "-" * 92)
    for i, e in enumerate(scored[:top], 1):
        flag = "⚠" if e.storm_flag else ""
        man = "" if e.secondary_maneuverable else " *"
        print(
            f"  {i:>3} {e.risk_score:>5.1f} {e.tca:%m-%d %H:%M:%S} {e.miss_distance_km:>8.3f} "
            f"{e.pc:>9.2e} {e.geometry:<11} {e.secondary_type:<12} {flag:<4} "
            f"{e.secondary_name}{man}"
        )
    print("  (* = secondary cannot maneuver — primary must move;  ⚠ = storm flag)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly screening batch")
    parser.add_argument("--norad", type=int, nargs="*", default=WATCHED)
    parser.add_argument("--group", type=str, default=None)
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--db", type=str, default="data/orbitwarden.db")
    args = parser.parse_args()

    config = ScreeningConfig(window_days=args.days)
    store = ScreeningStore(args.db)
    try:
        with httpx.Client(timeout=180.0) as client:
            print("Fetching catalog...")
            catalog = fetch_catalog(client, args.group, args.norad)
            print(f"Catalog: {len(catalog)} objects")
            for norad in args.norad:
                result = screen_one(norad, catalog, store, config, client)
                if result:
                    print_scored(result[0], args.top)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
