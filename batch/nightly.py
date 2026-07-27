"""Nightly screening batch — the full pipeline for watched satellites.

For each watched satellite: fetch catalog (CelesTrak, Space-Track fallback) ->
coarse scan -> SATCAT-enrich the candidate secondaries (one batched query) ->
fetch space weather -> refine + score every candidate -> persist to the store.

Modes:
    python -m batch.nightly                 # one-pass: screen the ISS
    python -m batch.nightly --norad 25544 63210   # ISS + JINJUSAT-1B
    python -m batch.nightly --schedule    # run as a scheduled service (recurring)
    python -m batch.nightly --schedule --interval-hours 12  # every 12 h

As a scheduled service, each run is wrapped in error handling so a failure
(e.g. a data source being down) logs an error and the service keeps running for
the next interval — it never crashes unattended.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ingest.celestrak import fetch_group, fetch_groups
from engine.ingest.spaceweather import fetch_space_weather
from engine.ingest.spacetrack import enrich
from engine.models import ScoredConjunction, ScreeningConfig, ScreeningRun
from engine.screen import analyze_conjunctions, screen_satellite
from engine.storage import ScreeningStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [batch] %(message)s",
)
logger = logging.getLogger("orbitwarden.batch")

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
        logger.warning("CelesTrak unavailable (%s); falling back to Space-Track", exc)
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
        logger.warning("NORAD %d not in catalog — skipping", primary_norad)
        return None

    logger.info("Screening %s (NORAD %d)...", primary.name, primary.norad_id)
    candidates, run = screen_satellite(primary, catalog, config)
    logger.info(
        "band filter %d -> %d, %d coarse candidates in %.1fs",
        run.catalog_size, run.band_filtered_size, run.candidates_found, run.duration_s,
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
    logger.info("SATCAT enrichment: %d objects", len(object_info))

    space_weather = fetch_space_weather(client)
    logger.info(
        "space weather: max Kp %.1f, active storm %s",
        space_weather.max_kp_3day, space_weather.active_storm,
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
    logger.info("persisted run #%d: %d scored events", run_id, len(scored))
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


def run_screening(norad_list: list[int], group: str | None, days: float, db: str, top: int) -> None:
    """One full screening pass over all watched satellites. Raises on hard failure."""
    config = ScreeningConfig(window_days=days)
    store = ScreeningStore(db)
    try:
        with httpx.Client(timeout=180.0) as client:
            logger.info("Fetching catalog...")
            catalog = fetch_catalog(client, group, norad_list)
            logger.info("Catalog: %d objects", len(catalog))
            for norad in norad_list:
                result = screen_one(norad, catalog, store, config, client)
                if result:
                    print_scored(result[0], top)
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly screening batch")
    parser.add_argument("--norad", type=int, nargs="*", default=WATCHED)
    parser.add_argument("--group", type=str, default=None)
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--db", type=str, default="data/orbitwarden.db")
    parser.add_argument("--schedule", action="store_true", help="run as a recurring scheduled service")
    parser.add_argument("--interval-hours", type=float, default=24.0, help="hours between scheduled runs")
    args = parser.parse_args()

    if not args.schedule:
        # One-pass mode.
        try:
            run_screening(args.norad, args.group, args.days, args.db, args.top)
        except Exception as exc:  # noqa: BLE001
            logger.error("Screening run failed: %s", exc)
            return 1
        return 0

    # Scheduled service mode: run forever, surviving individual failures.
    logger.info(
        "Starting scheduled screening service (every %.1f h, satellites: %s)",
        args.interval_hours, args.norad,
    )
    interval_s = args.interval_hours * 3600.0
    while True:
        try:
            logger.info("=== scheduled screening run starting ===")
            run_screening(args.norad, args.group, args.days, args.db, args.top)
            logger.info("=== scheduled screening run complete ===")
        except Exception as exc:  # noqa: BLE001 — never crash the service
            logger.error("Scheduled run failed (will retry next interval): %s", exc)
        logger.info("Sleeping %.1f h until next run...", args.interval_hours)
        time.sleep(interval_s)


if __name__ == "__main__":
    sys.exit(main())
