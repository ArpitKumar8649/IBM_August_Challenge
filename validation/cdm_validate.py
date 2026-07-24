"""CDM validation — replay real Space Surveillance Network conjunctions.

For each CDM_PUBLIC record (a conjunction the actual Space Surveillance Network
flagged), we:
  1. Fetch era-correct TLEs for both objects via gp_history — the TLE closest to
     the CDM's creation time, i.e. the same ephemeris vintage the CDM was based on.
     This controls for the TLE-vintage sensitivity documented in Phase 1.
  2. Replay the conjunction through the screening engine (SGP4 propagation).
  3. Compare detection, TCA, and miss distance against the CDM's reported values.

This validates the engine against ground truth — real conjunctions, real TLEs —
and honestly characterizes the SGP4-vs-precision-ephemeris gap (the CDM uses
high-precision propagation; we use fast analytic SGP4 for catalog-wide screening).

Usage:
    python -m validation.cdm_validate --days 30 --limit 20
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ingest.celestrak import parse_tle_text
from engine.ingest.spacetrack import login
from engine.models import ScreeningConfig, TLEData
from engine.screen import screen_satellite
from engine.tca import refine_tca
from engine.propagate import satrec_from_tle, tsince_minutes

CDM_URL = "https://www.space-track.org/basicspacedata/query/class/cdm_public"
GP_HISTORY_URL = "https://www.space-track.org/basicspacedata/query/class/gp_history"
QUERY_PAUSE_S = 2.0  # Space-Track sessions drop under rapid fire


@dataclass
class ReplayResult:
    cdm_id: str
    sat1_name: str
    sat2_name: str
    sat1_type: str
    cdm_tca: datetime
    cdm_miss_km: float
    detected: bool
    reason: str = ""
    our_tca: datetime | None = None
    our_miss_km: float | None = None
    our_vrel_kms: float | None = None
    tca_err_s: float | None = None
    miss_ratio: float | None = None
    tle1_epoch: datetime | None = None
    tle2_epoch: datetime | None = None


def fetch_cdms(client: httpx.Client, days_back: int = 30, limit: int = 20) -> list[dict]:
    """Recent CDM_PUBLIC records (newest first), created within `days_back` days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    resp = client.get(
        f"{CDM_URL}/CREATED/%3E{since}/LIMIT/{limit}/format/json/",
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_historical_tle(
    client: httpx.Client, norad: int, start_date: str, end_date: str
) -> list[TLEData]:
    """Historical TLEs for an object over a date range (gp_history, 3LE format)."""
    resp = client.get(
        f"{GP_HISTORY_URL}/NORAD_CAT_ID/{norad}/EPOCH/{start_date}--{end_date}/format/3le/",
        timeout=120.0,
    )
    resp.raise_for_status()
    return parse_tle_text(resp.text)


def pick_era_tle(tles: list[TLEData], target: datetime) -> TLEData | None:
    """The TLE closest to (ideally just before) the target time — the ephemeris
    vintage the CDM was based on."""
    if not tles:
        return None
    before = [t for t in tles if t.epoch <= target]
    if before:
        return max(before, key=lambda t: t.epoch)
    return min(tles, key=lambda t: abs((t.epoch - target).total_seconds()))


def replay_cdm(cdm: dict, client: httpx.Client) -> ReplayResult:
    """Replay one CDM through the screening engine with era-correct TLEs."""
    cdm_id = cdm["CDM_ID"]
    sat1_id, sat2_id = int(cdm["SAT_1_ID"]), int(cdm["SAT_2_ID"])
    sat1_name, sat2_name = cdm["SAT_1_NAME"], cdm["SAT_2_NAME"]
    sat1_type = cdm.get("SAT1_OBJECT_TYPE", "UNKNOWN")
    cdm_tca = datetime.fromisoformat(cdm["TCA"]).replace(tzinfo=timezone.utc)
    cdm_miss_km = float(cdm["MIN_RNG"]) / 1000.0  # meters -> km
    created = datetime.strptime(cdm["CREATED"], "%Y-%m-%d %H:%M:%S.%f").replace(
        tzinfo=timezone.utc
    )

    result = ReplayResult(
        cdm_id=cdm_id, sat1_name=sat1_name, sat2_name=sat2_name, sat1_type=sat1_type,
        cdm_tca=cdm_tca, cdm_miss_km=cdm_miss_km, detected=False,
    )

    # Era-correct TLEs: fetch around the CDM creation time.
    es = (created - timedelta(days=2)).strftime("%Y-%m-%d")
    ee = (created + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        tles1 = fetch_historical_tle(client, sat1_id, es, ee)
        time.sleep(QUERY_PAUSE_S)
        tles2 = fetch_historical_tle(client, sat2_id, es, ee)
        time.sleep(QUERY_PAUSE_S)
    except httpx.HTTPError as exc:
        result.reason = f"gp_history fetch failed: {exc}"
        return result

    tle1 = pick_era_tle(tles1, created)
    tle2 = pick_era_tle(tles2, created)
    if tle1 is None or tle2 is None:
        result.reason = "no era TLE available"
        return result
    result.tle1_epoch = tle1.epoch
    result.tle2_epoch = tle2.epoch

    # Screen sat1 vs [sat2] over a window centered on the CDM's TCA.
    config = ScreeningConfig(window_days=1.0, time_step_s=60.0, miss_threshold_km=1000.0)
    start = cdm_tca - timedelta(hours=12)
    try:
        candidates, _run = screen_satellite(tle1, [tle1, tle2], config, start=start)
    except Exception as exc:  # noqa: BLE001 — propagation edge cases
        result.reason = f"screening failed: {exc}"
        return result

    real = [c for c in candidates if c.secondary_norad == sat2_id]
    if not real:
        result.reason = "no candidate within 1000 km in window"
        return result

    # Refine candidates near the CDM's TCA and pick the closest match in time.
    primary_sat = satrec_from_tle(tle1)
    secondary_sat = satrec_from_tle(tle2)
    best = None
    best_tca_err = float("inf")
    for cand in real:
        if abs((cand.tca - cdm_tca).total_seconds()) > 7200:  # within ±2 h
            continue
        try:
            state = refine_tca(
                primary_sat, secondary_sat,
                tsince_minutes(cand.tca, tle1), tsince_minutes(cand.tca, tle2),
                step_s=config.time_step_s,
            )
        except (ValueError, RuntimeError):
            continue
        refined_tca = cand.tca + timedelta(seconds=state.tca_offset_s)
        tca_err = abs((refined_tca - cdm_tca).total_seconds())
        if tca_err < best_tca_err:
            best_tca_err = tca_err
            best = (refined_tca, state.miss_distance_km, cand.relative_velocity_kms)

    if best is None:
        result.reason = "no refined candidate near CDM TCA"
        return result

    refined_tca, our_miss, our_vrel = best
    result.detected = True
    result.our_tca = refined_tca
    result.our_miss_km = our_miss
    result.our_vrel_kms = our_vrel
    result.tca_err_s = best_tca_err
    result.miss_ratio = our_miss / cdm_miss_km if cdm_miss_km > 0 else float("inf")
    return result


def run_validation(days_back: int = 30, limit: int = 20) -> list[ReplayResult]:
    """Fetch recent CDMs and replay each through the engine."""
    results: list[ReplayResult] = []
    with httpx.Client(timeout=120.0) as client:
        if not login(client):
            raise RuntimeError("Space-Track login failed — check .env credentials")
        time.sleep(QUERY_PAUSE_S)
        cdms = fetch_cdms(client, days_back, limit)
        print(f"Fetched {len(cdms)} CDMs (last {days_back} days)")
        for i, cdm in enumerate(cdms, 1):
            print(f"  [{i}/{len(cdms)}] CDM {cdm['CDM_ID']}: "
                  f"{cdm['SAT_1_NAME']} vs {cdm['SAT_2_NAME']}...", end=" ", flush=True)
            result = replay_cdm(cdm, client)
            status = "detected" if result.detected else f"missed ({result.reason})"
            print(status)
            results.append(result)
    return results


def summarize(results: list[ReplayResult]) -> dict:
    """Aggregate statistics over the replay results."""
    detected = [r for r in results if r.detected]
    tca_errs = [r.tca_err_s for r in detected if r.tca_err_s is not None]
    miss_ratios = [r.miss_ratio for r in detected if r.miss_ratio is not None]
    return {
        "total": len(results),
        "detected": len(detected),
        "detection_rate": len(detected) / len(results) if results else 0.0,
        "median_tca_err_s": sorted(tca_errs)[len(tca_errs) // 2] if tca_errs else None,
        "max_tca_err_s": max(tca_errs) if tca_errs else None,
        "median_miss_ratio": sorted(miss_ratios)[len(miss_ratios) // 2] if miss_ratios else None,
        "miss_ratio_range": (min(miss_ratios), max(miss_ratios)) if miss_ratios else None,
    }


def results_to_records(results: list[ReplayResult]) -> list[dict]:
    """Serialize replay results to JSON-safe records."""
    records = []
    for r in results:
        records.append(
            {
                "cdm_id": r.cdm_id,
                "sat1_name": r.sat1_name,
                "sat2_name": r.sat2_name,
                "sat1_type": r.sat1_type,
                "cdm_tca": r.cdm_tca.isoformat(),
                "cdm_miss_km": r.cdm_miss_km,
                "detected": r.detected,
                "reason": r.reason,
                "our_tca": r.our_tca.isoformat() if r.our_tca else None,
                "our_miss_km": r.our_miss_km,
                "our_vrel_kms": r.our_vrel_kms,
                "tca_err_s": r.tca_err_s,
                "miss_ratio": r.miss_ratio,
                "tle1_epoch": r.tle1_epoch.isoformat() if r.tle1_epoch else None,
                "tle2_epoch": r.tle2_epoch.isoformat() if r.tle2_epoch else None,
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the engine against real CDMs")
    parser.add_argument("--days", type=int, default=30, help="CDM look-back window (days)")
    parser.add_argument("--limit", type=int, default=20, help="max CDMs to replay")
    parser.add_argument("--json", type=str, default=None, help="write results JSON to this path")
    args = parser.parse_args()

    results = run_validation(args.days, args.limit)
    stats = summarize(results)

    if args.json:
        import json

        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps({"summary": stats, "results": results_to_records(results)}, indent=2)
        )
        print(f"\nResults written to {args.json}")

    print("\n=== SUMMARY ===")
    print(f"Detection rate : {stats['detected']}/{stats['total']} "
          f"({stats['detection_rate']:.0%})")
    if stats["median_tca_err_s"] is not None:
        print(f"TCA error      : median {stats['median_tca_err_s']:.1f} s, "
              f"max {stats['max_tca_err_s']:.1f} s")
    if stats["median_miss_ratio"] is not None:
        lo, hi = stats["miss_ratio_range"]
        print(f"Miss ratio     : median {stats['median_miss_ratio']:.2f}×, "
              f"range {lo:.2f}–{hi:.2f}×")
    return 0


if __name__ == "__main__":
    sys.exit(main())
