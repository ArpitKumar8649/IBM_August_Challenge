"""Tests for validation/cdm_validate.py — era-TLE selection + summarization (offline)."""

from datetime import datetime, timezone

from engine.models import TLEData
from validation.cdm_validate import ReplayResult, pick_era_tle, summarize

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"


def _tle(epoch):
    return TLEData(
        norad_id=25544, name="X", line1=ISS_L1, line2=ISS_L2, epoch=epoch,
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


def test_pick_era_tle_prefers_most_recent_before_target():
    tles = [
        _tle(datetime(2026, 6, 22, tzinfo=timezone.utc)),
        _tle(datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)),
        _tle(datetime(2026, 6, 25, tzinfo=timezone.utc)),  # after target
    ]
    target = datetime(2026, 6, 24, 16, 0, tzinfo=timezone.utc)
    picked = pick_era_tle(tles, target)
    assert picked.epoch == datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)


def test_pick_era_tle_falls_back_to_nearest():
    tles = [_tle(datetime(2026, 6, 25, tzinfo=timezone.utc))]  # all after target
    target = datetime(2026, 6, 24, tzinfo=timezone.utc)
    picked = pick_era_tle(tles, target)
    assert picked is not None


def test_pick_era_tle_empty():
    assert pick_era_tle([], datetime(2026, 6, 24, tzinfo=timezone.utc)) is None


def _result(detected, tca_err=None, miss_ratio=None):
    return ReplayResult(
        cdm_id="1", sat1_name="A", sat2_name="B", sat1_type="DEBRIS",
        cdm_tca=datetime(2026, 6, 25, tzinfo=timezone.utc), cdm_miss_km=3.0,
        detected=detected, tca_err_s=tca_err, miss_ratio=miss_ratio,
    )


def test_summarize_detection_rate():
    results = [_result(True, 10.0, 1.2), _result(True, 30.0, 0.8), _result(False)]
    stats = summarize(results)
    assert stats["total"] == 3
    assert stats["detected"] == 2
    assert stats["detection_rate"] == 2 / 3


def test_summarize_tca_and_miss_stats():
    results = [_result(True, 10.0, 1.2), _result(True, 30.0, 0.8), _result(True, 20.0, 1.5)]
    stats = summarize(results)
    assert stats["median_tca_err_s"] == 20.0
    assert stats["max_tca_err_s"] == 30.0
    assert stats["median_miss_ratio"] == 1.2
    assert stats["miss_ratio_range"] == (0.8, 1.5)
