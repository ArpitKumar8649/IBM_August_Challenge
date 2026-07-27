"""Tests for engine/standards.py — CCSDS CDM/ODM generation & parsing."""

from datetime import datetime, timezone

import pytest

from engine.models import ScoredConjunction, TLEData
from engine.standards import generate_cdm, parse_cdm_kvn, generate_omm


def _tle(norad=25544, name="ISS (ZARYA)"):
    return TLEData(
        norad_id=norad, name=name,
        line1="1 25544U 98067A   24001.50000000  .00016717  00000-0  30709-3 0  9993",
        line2="2 25544  51.6400 208.5700 0006859  39.6000 320.5300 15.50100000431234",
        epoch=datetime(2026, 7, 20, tzinfo=timezone.utc),
        inclination_deg=51.6, perigee_alt_km=411.0, apogee_alt_km=421.0,
    )


def _event():
    return ScoredConjunction(
        primary_norad=25544, secondary_norad=36558, secondary_name="COSMOS 2251 DEB",
        tca=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        miss_distance_km=3.037, relative_velocity_kms=9.886,
        miss_r_km=2.91, miss_s_km=0.62, miss_w_km=0.41,
        geometry="radial", hbr_km=0.006, pc=6.69e-13,
        secondary_type="DEBRIS", secondary_maneuverable=False,
        storm_flag=False, risk_score=72.4,
    )


def test_cdm_generation_contains_required_fields():
    """A generated CDM must contain the CCSDS-required header and data fields."""
    cdm = generate_cdm(_event(), _tle())
    assert "CCSDS_CDM_VERS = 1.0" in cdm
    assert "CREATION_DATE =" in cdm
    assert "ORIGINATOR = ORBITWARDEN" in cdm
    assert "TCA =" in cdm
    assert "MISS_DISTANCE =" in cdm
    assert "RELATIVE_SPEED =" in cdm
    assert "COLLISION_PROBABILITY =" in cdm
    assert "OBJECT1 = ISS (ZARYA)" in cdm
    assert "OBJECT2 = COSMOS 2251 DEB" in cdm


def test_cdm_miss_distance_in_meters():
    """CDM MISS_DISTANCE must be in meters (3.037 km → 3037 m)."""
    cdm = generate_cdm(_event(), _tle())
    fields = parse_cdm_kvn(cdm)
    assert float(fields["MISS_DISTANCE"]) == pytest.approx(3037.0, rel=1e-3)


def test_cdm_emergency_reportable():
    """High risk (>=60) → EMERGENCY_REPORTABLE = YES."""
    cdm = generate_cdm(_event(), _tle())  # risk 72.4
    assert "EMERGENCY_REPORTABLE = YES" in cdm
    # Low risk → NO
    low = _event()
    low.risk_score = 30.0
    cdm_low = generate_cdm(low, _tle())
    assert "EMERGENCY_REPORTABLE = NO" in cdm_low


def test_cdm_round_trip_parse():
    """A generated CDM must be parseable back into fields."""
    cdm = generate_cdm(_event(), _tle())
    fields = parse_cdm_kvn(cdm)
    assert fields["CCSDS_CDM_VERS"] == "1.0"
    assert fields["OBJECT1"] == "ISS (ZARYA)"
    assert float(fields["RELATIVE_SPEED"]) == pytest.approx(9.886, rel=1e-3)


def test_cdm_relative_position_in_meters():
    """CDM relative position components must be in meters."""
    cdm = generate_cdm(_event(), _tle())
    fields = parse_cdm_kvn(cdm)
    assert float(fields["RELATIVE_POSITION_R"]) == pytest.approx(2910.0, rel=1e-3)
    assert float(fields["RELATIVE_POSITION_T"]) == pytest.approx(620.0, rel=1e-3)


def test_omm_generation():
    """An OMM must contain the standard mean-element fields."""
    omm = generate_omm(_tle())
    assert "CCSDS_OMM_VERS = 2.0" in omm
    assert "OBJECT_NAME = ISS (ZARYA)" in omm
    assert "MEAN_ELEMENT_THEORY = SGP4" in omm
    assert "ECCENTRICITY =" in omm
    assert "INCLINATION =" in omm
    assert "MEAN_MOTION =" in omm
    assert "SEMI_MAJOR_AXIS =" in omm


def test_omm_inclination_matches_tle():
    """The OMM inclination must match the TLE's inclination (51.64°)."""
    omm = generate_omm(_tle())
    fields = parse_cdm_kvn(omm)
    assert float(fields["INCLINATION"]) == pytest.approx(51.64, rel=1e-3)


def test_omm_semi_major_axis_reasonable():
    """Semi-major axis for ISS (~416 km alt) should be ~6794 km."""
    omm = generate_omm(_tle())
    fields = parse_cdm_kvn(omm)
    sma = float(fields["SEMI_MAJOR_AXIS"])
    assert 6700 < sma < 6900, f"SMA {sma} km out of range for ISS"


def test_omm_parse_round_trip():
    """An OMM must be parseable into fields."""
    omm = generate_omm(_tle())
    fields = parse_cdm_kvn(omm)
    assert fields["OBJECT_NAME"] == "ISS (ZARYA)"
    assert float(fields["ECCENTRICITY"]) == pytest.approx(0.0006859, rel=1e-3)
