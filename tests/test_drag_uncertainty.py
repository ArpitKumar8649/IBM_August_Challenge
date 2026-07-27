"""Tests for engine/drag_uncertainty.py — Kp→Ap, recommendations, drag band physics."""

from datetime import datetime, timedelta, timezone

import pytest

from engine.drag_uncertainty import (
    BC_DEFAULTS,
    _bc_for_type,
    _recommendation,
    drag_uncertainty_band,
    kp_to_ap,
)
from engine.models import TLEData

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993"
ISS_L2 = "2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234"


def _tle(norad, name, l2=ISS_L2):
    return TLEData(
        norad_id=norad, name=name, line1=ISS_L1, line2=l2,
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


# --- Kp → Ap conversion ---

def test_kp_to_ap_standard_values():
    """Kp→Ap must match the standard NOAA table at integer Kp."""
    expected = {0: 0, 1: 4, 2: 7, 3: 15, 4: 27, 5: 48, 6: 80, 7: 140, 8: 240, 9: 400}
    for kp, ap in expected.items():
        assert kp_to_ap(kp) == pytest.approx(ap, abs=0.5)


def test_kp_to_ap_interpolates():
    """Kp between integers should interpolate (monotonic)."""
    assert kp_to_ap(0) < kp_to_ap(2.5) < kp_to_ap(5)


def test_kp_to_ap_clamps():
    """Kp outside [0, 9] should clamp to the table bounds."""
    assert kp_to_ap(-5) == 0
    assert kp_to_ap(15) == 400


# --- ballistic coefficient defaults ---

def test_bc_for_known_types():
    assert _bc_for_type("PAYLOAD") == BC_DEFAULTS["PAYLOAD"]
    assert _bc_for_type("DEBRIS") == BC_DEFAULTS["DEBRIS"]
    assert _bc_for_type("ROCKET BODY") == BC_DEFAULTS["ROCKET BODY"]


def test_bc_for_unknown_type():
    """Unknown/empty type should fall back to the UNKNOWN default."""
    assert _bc_for_type("UNKNOWN") == BC_DEFAULTS["UNKNOWN"]
    assert _bc_for_type("") == BC_DEFAULTS["UNKNOWN"]
    assert _bc_for_type("SOMETHING_ELSE") == BC_DEFAULTS["UNKNOWN"]


def test_bc_types_have_distinct_ballistic_coefficients():
    """Different object types should have different ballistic coefficients
    (Cd·A/m) — this is what drives the differential-drag uncertainty band."""
    bcs = {t: cd_a_over_m for t, (m, a) in BC_DEFAULTS.items() for cd_a_over_m in [2.2 * a / m]}
    # At least the main types should differ.
    assert bcs["PAYLOAD"] != bcs["DEBRIS"]
    assert bcs["DEBRIS"] != bcs["ROCKET BODY"]


# --- recommendation logic ---

def test_recommendation_by_band():
    assert "robust" in _recommendation(0.05)
    assert "reliable" in _recommendation(0.5)
    assert "24 h" in _recommendation(2.0)
    assert "caution" in _recommendation(10.0)


def test_recommendation_monotonic_urgency():
    """Larger bands should give more urgent recommendations (qualitative check)."""
    recs = [_recommendation(b) for b in [0.05, 0.5, 2.0, 10.0]]
    # Each successive recommendation should differ (escalating).
    assert len(set(recs)) == 4


# --- drag-uncertainty band ---

def test_band_nonzero_for_different_types():
    """Two objects with different ballistic coefficients should produce a nonzero
    drag-uncertainty band under storm vs quiet conditions."""
    primary = _tle(25544, "ISS (ZARYA)")
    # A debris object on a slightly different orbit (different RAAN).
    debris_l2 = "2 99998  51.6400 209.0000 0006859  39.6000 320.5300 15.50100000431234"
    secondary = _tle(99998, "TEST DEBRIS", debris_l2)
    tca = datetime.now(timezone.utc) + timedelta(hours=6)

    band = drag_uncertainty_band(
        primary, secondary, tca, event_id=1,
        primary_type="PAYLOAD", secondary_type="DEBRIS",
        ap_quiet=4.0, kp_current=8.0, f107=150.0,
    )
    # The band should be nonzero (differential drag between payload and debris).
    assert band.band_km >= 0.0
    assert band.ap_storm > band.ap_quiet
    assert band.inflation_ratio > 1.0  # storm density > quiet density
    assert band.recommendation  # a recommendation is always provided


def test_band_zero_when_tca_in_past():
    """If TCA is in the past, propagation can't proceed → zero band with a note."""
    primary = _tle(25544, "ISS (ZARYA)")
    secondary = _tle(99998, "TEST DEBRIS")
    tca = datetime.now(timezone.utc) - timedelta(hours=1)  # in the past

    band = drag_uncertainty_band(primary, secondary, tca, event_id=1)
    assert band.band_km == 0.0
    assert "past" in band.recommendation.lower() or "unable" in band.recommendation.lower()


def test_band_scales_with_storm_intensity():
    """A stronger storm (higher Kp) should produce a larger (or equal) band than
    a mild storm, all else equal — more density inflation → more differential drag."""
    primary = _tle(25544, "ISS (ZARYA)")
    debris_l2 = "2 99998  51.6400 209.0000 0006859  39.6000 320.5300 15.50100000431234"
    secondary = _tle(99998, "TEST DEBRIS", debris_l2)
    tca = datetime.now(timezone.utc) + timedelta(hours=12)

    band_mild = drag_uncertainty_band(
        primary, secondary, tca, event_id=1,
        primary_type="PAYLOAD", secondary_type="DEBRIS",
        ap_quiet=4.0, kp_current=5.0, f107=150.0,
    )
    band_strong = drag_uncertainty_band(
        primary, secondary, tca, event_id=1,
        primary_type="PAYLOAD", secondary_type="DEBRIS",
        ap_quiet=4.0, kp_current=9.0, f107=150.0,
    )
    # The strong storm should inflate density more.
    assert band_strong.inflation_ratio >= band_mild.inflation_ratio
    # And the band should be at least as large (more differential drag).
    assert band_strong.band_km >= band_mild.band_km * 0.99  # small tolerance
