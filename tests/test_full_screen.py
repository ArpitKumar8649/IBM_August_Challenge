"""Tests for the full scored pipeline (screen.py v2)."""

from datetime import datetime, timezone

import pytest

from engine.models import ObjectInfo, ScreeningConfig
from engine.screen import analyze_conjunctions, full_screen, screen_satellite

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"
# 1 deg RAAN offset -> a genuine crossing conjunction (vrel ~ 0.13 km/s, above
# the co-location filter) with a real close approach (~73 km) in the window.
NEAR_L2 = "2 99998  51.6400 209.5700 0006859  39.6000 320.5300 15.50100000431234"


def _tle(norad, name, l2, perigee=411.0, apogee=421.0):
    from engine.models import TLEData

    return TLEData(
        norad_id=norad, name=name, line1=ISS_L1, line2=l2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=perigee, apogee_alt_km=apogee,
    )


@pytest.fixture
def setup():
    primary = _tle(25544, "ISS (ZARYA)", ISS_L2)
    secondary = _tle(99998, "NEAR-OBJ", NEAR_L2)
    config = ScreeningConfig(window_days=1.0, time_step_s=60.0, miss_threshold_km=100.0)
    return primary, secondary, config


def test_full_screen_returns_scored(setup):
    primary, secondary, config = setup
    scored, run = full_screen(primary, [primary, secondary], config=config)
    assert run.band_filtered_size == 1
    assert len(scored) >= 1
    top = scored[0]
    assert top.secondary_norad == 99998
    assert top.miss_distance_km < 100.0
    assert top.relative_velocity_kms > 0
    assert top.geometry in {"in-track", "radial", "cross-track"}
    assert 0.0 <= top.pc <= 1.0
    assert 0.0 <= top.risk_score <= 100.0
    assert top.hbr_km > 0


def test_analyze_uses_object_info(setup):
    """Object type drives maneuverability; debris -> unmaneuverable -> higher risk."""
    primary, secondary, config = setup
    candidates, _ = screen_satellite(primary, [primary, secondary], config)
    catalog_by_id = {primary.norad_id: primary, secondary.norad_id: secondary}

    payload_info = {99998: ObjectInfo(norad_id=99998, object_type="PAYLOAD", size_m=2.0)}
    debris_info = {99998: ObjectInfo(norad_id=99998, object_type="DEBRIS", size_m=2.0)}

    scored_payload = analyze_conjunctions(primary, candidates, catalog_by_id, payload_info)
    scored_debris = analyze_conjunctions(primary, candidates, catalog_by_id, debris_info)

    assert scored_payload[0].secondary_maneuverable is True
    assert scored_debris[0].secondary_maneuverable is False
    assert scored_debris[0].risk_score > scored_payload[0].risk_score


def test_analyze_rsw_geometry_consistent(setup):
    """RSW miss components must reconstruct the miss distance."""
    import numpy as np

    primary, secondary, config = setup
    candidates, _ = screen_satellite(primary, [primary, secondary], config)
    catalog_by_id = {primary.norad_id: primary, secondary.norad_id: secondary}
    scored = analyze_conjunctions(primary, candidates, catalog_by_id)
    top = scored[0]
    reconstructed = np.sqrt(top.miss_r_km**2 + top.miss_s_km**2 + top.miss_w_km**2)
    assert reconstructed == pytest.approx(top.miss_distance_km, rel=1e-6)


def test_analyze_filters_colocated(setup):
    """A co-located object (identical TLE, vrel~0) must be filtered out."""
    primary, _secondary, config = setup
    # A "docked module": same TLE as primary, different NORAD id -> vrel ~ 0
    from engine.models import TLEData

    docked = TLEData(
        norad_id=99999, name="DOCKED-MODULE", line1=ISS_L1, line2=ISS_L2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )
    candidates, _ = screen_satellite(primary, [primary, docked], config)
    catalog_by_id = {primary.norad_id: primary, docked.norad_id: docked}
    scored = analyze_conjunctions(primary, candidates, catalog_by_id)
    # The docked module (vrel ~ 0) must not appear as a conjunction
    assert all(e.secondary_norad != 99999 for e in scored)
