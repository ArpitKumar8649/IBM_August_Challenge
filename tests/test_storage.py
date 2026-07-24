"""Tests for engine/storage.py — round-trip persistence."""

from datetime import datetime, timezone

from engine.models import ObjectInfo, ScoredConjunction, ScreeningRun
from engine.storage import ScreeningStore


def _run():
    return ScreeningRun(
        primary_norad=25544, primary_name="ISS", run_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        window_days=7.0, catalog_size=1000, band_filtered_size=800,
        candidates_found=2, duration_s=12.5,
    )


def _event(norad, score, pc=1e-4):
    return ScoredConjunction(
        primary_norad=25544, secondary_norad=norad, secondary_name=f"OBJ-{norad}",
        tca=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        miss_distance_km=1.5, relative_velocity_kms=10.0,
        miss_r_km=1.0, miss_s_km=1.0, miss_w_km=0.5, geometry="in-track",
        hbr_km=0.006, pc=pc, secondary_type="DEBRIS", secondary_maneuverable=False,
        storm_flag=False, risk_score=score,
    )


def test_round_trip(tmp_path):
    store = ScreeningStore(tmp_path / "test.db")
    run_id = store.save_run(_run())
    store.save_events(run_id, [_event(111, 80.0), _event(222, 60.0)])
    store.save_objects({111: ObjectInfo(norad_id=111, object_type="DEBRIS", size_m=0.5)})

    latest = store.latest_run(25544)
    assert latest["primary_name"] == "ISS"
    assert latest["candidates_found"] == 2

    events = store.events_for_run(run_id)
    assert len(events) == 2
    assert events[0]["risk_score"] == 80.0  # ordered by risk desc
    assert events[0]["secondary_type"] == "DEBRIS"
    assert events[0]["secondary_maneuverable"] == 0
    store.close()


def test_latest_run_is_most_recent(tmp_path):
    store = ScreeningStore(tmp_path / "test.db")
    store.save_run(_run())
    run2 = _run()
    run2.candidates_found = 99
    id2 = store.save_run(run2)
    assert store.latest_run(25544)["candidates_found"] == 99
    assert store.latest_run(25544)["id"] == id2
    store.close()


def test_object_upsert(tmp_path):
    store = ScreeningStore(tmp_path / "test.db")
    store.save_objects({1: ObjectInfo(norad_id=1, object_type="DEBRIS", size_m=0.5)})
    store.save_objects({1: ObjectInfo(norad_id=1, object_type="PAYLOAD", size_m=2.0)})
    row = store.conn.execute("SELECT object_type, size_m FROM objects WHERE norad_id=1").fetchone()
    assert row["object_type"] == "PAYLOAD"
    assert row["size_m"] == 2.0
    store.close()
