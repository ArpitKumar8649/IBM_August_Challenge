"""Tests for engine/ingest/swpc_products.py — multi-signal space weather + composite."""

import pytest

from engine.ingest.swpc_products import (
    _risk_level,
    _xray_class,
    storm_risk_composite,
)
from engine.models import ProtonState, SolarWindState, XrayState


# --- X-ray flare class mapping ---

def test_xray_class_boundaries():
    assert _xray_class(1e-8) == "A"
    assert _xray_class(1e-7) == "B"
    assert _xray_class(1e-6) == "C"
    assert _xray_class(1e-5) == "M"
    assert _xray_class(1e-4) == "X"


def test_xray_class_below_a():
    assert _xray_class(0.0) == "A"
    assert _xray_class(5e-9) == "A"


# --- risk level mapping ---

def test_risk_level_boundaries():
    assert _risk_level(0) == "quiet"
    assert _risk_level(15) == "quiet"
    assert _risk_level(25) == "unsettled"
    assert _risk_level(45) == "active"
    assert _risk_level(65) == "storm"
    assert _risk_level(85) == "severe"


# --- composite storm-risk indicator ---

def test_composite_quiet_conditions():
    """Quiet space weather → low score, 'quiet' level, no drivers."""
    sw = SolarWindState(bt_nt=3.0, bz_gsm_nt=2.0, speed_kms=350.0, f107_sfu=100.0)
    xr = XrayState(flux_w_m2=1e-8, flare_class="A")
    pr = ProtonState(flux_pfu=0.1, sep_active=False)
    comp = storm_risk_composite(kp_max_3day=2.0, solar_wind=sw, xray=xr, proton=pr)
    assert comp.level == "quiet"
    assert comp.score < 20
    assert comp.drivers == []


def test_composite_storm_conditions():
    """Strong storm signals → high score, 'storm'/'severe' level, drivers listed."""
    sw = SolarWindState(bt_nt=20.0, bz_gsm_nt=-15.0, speed_kms=750.0, f107_sfu=200.0)
    xr = XrayState(flux_w_m2=1e-4, flare_class="X")
    pr = ProtonState(flux_pfu=50.0, sep_active=True)
    comp = storm_risk_composite(kp_max_3day=8.0, solar_wind=sw, xray=xr, proton=pr)
    assert comp.score >= 60
    assert comp.level in ("storm", "severe")
    # All drivers should be present.
    assert len(comp.drivers) >= 3


def test_composite_southward_bz_driver():
    """Strongly southward Bz alone should register as a driver."""
    sw = SolarWindState(bt_nt=15.0, bz_gsm_nt=-12.0, speed_kms=400.0, f107_sfu=150.0)
    comp = storm_risk_composite(kp_max_3day=3.0, solar_wind=sw)
    assert any("Bz" in d for d in comp.drivers)


def test_composite_kp_storm_driver():
    """High Kp forecast alone should register as a geomagnetic-storm driver."""
    comp = storm_risk_composite(kp_max_3day=7.0)
    assert any("Kp" in d for d in comp.drivers)
    assert comp.score >= 30


def test_composite_sep_driver():
    """An active SEP event should register as a driver and add to the score."""
    pr = ProtonState(flux_pfu=20.0, sep_active=True)
    comp = storm_risk_composite(kp_max_3day=2.0, proton=pr)
    assert comp.sep_active is True
    assert any("particle" in d for d in comp.drivers)


def test_composite_capped_at_100():
    """The composite score must never exceed 100."""
    sw = SolarWindState(bt_nt=50.0, bz_gsm_nt=-40.0, speed_kms=1200.0, f107_sfu=300.0)
    xr = XrayState(flux_w_m2=1e-3, flare_class="X")
    pr = ProtonState(flux_pfu=1000.0, sep_active=True)
    comp = storm_risk_composite(kp_max_3day=9.0, solar_wind=sw, xray=xr, proton=pr)
    assert comp.score <= 100.0


def test_composite_handles_none_inputs():
    """The composite must handle None inputs gracefully (defaults)."""
    comp = storm_risk_composite(kp_max_3day=5.0, solar_wind=None, xray=None, proton=None)
    assert 0 <= comp.score <= 100
    assert comp.bz_gsm_nt == 0.0
    assert comp.xray_class == "A"


def test_composite_records_signals():
    """The composite must record the input signal values."""
    sw = SolarWindState(bt_nt=8.0, bz_gsm_nt=-3.0, speed_kms=500.0, f107_sfu=180.0)
    xr = XrayState(flux_w_m2=2e-6, flare_class="C")
    comp = storm_risk_composite(kp_max_3day=4.0, solar_wind=sw, xray=xr)
    assert comp.bz_gsm_nt == -3.0
    assert comp.speed_kms == 500.0
    assert comp.xray_class == "C"
    assert comp.f107_sfu == 180.0
