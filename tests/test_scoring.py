"""Tests for engine/scoring.py — geometry, maneuverability, risk score."""

import numpy as np

from engine.scoring import geometry_class, is_maneuverable, risk_score


def test_geometry_class():
    assert geometry_class([0.0, 10.0, 0.0]) == "in-track"
    assert geometry_class([10.0, 0.0, 0.0]) == "radial"
    assert geometry_class([0.0, 0.0, 10.0]) == "cross-track"
    # ties resolved deterministically (in-track preferred when s ties)
    assert geometry_class([5.0, 5.0, 0.0]) == "in-track"


def test_is_maneuverable():
    assert is_maneuverable("PAYLOAD") is True
    assert is_maneuverable("DEBRIS") is False
    assert is_maneuverable("ROCKET BODY") is False
    assert is_maneuverable("UNKNOWN") is False
    assert is_maneuverable(None) is False


def test_risk_score_bounds():
    for miss in (0.001, 1.0,50.0, 500.0):
        for vrel in (0.5, 7.0, 15.0):
            score = risk_score(miss, vrel, "radial", False)
            assert 0.0 <= score <= 100.0


def test_risk_score_closer_is_higher():
    assert risk_score(0.1, 10.0, "in-track", True) > risk_score(10.0, 10.0, "in-track", True)


def test_risk_score_unmaneuverable_is_higher():
    base = dict(miss_km=1.0, vrel_kms=10.0, geometry="in-track")
    assert risk_score(**base, secondary_maneuverable=False) > risk_score(
        **base, secondary_maneuverable=True
    )


def test_risk_score_radial_beats_intrack():
    base = dict(miss_km=1.0, vrel_kms=10.0, secondary_maneuverable=True)
    assert risk_score(**base, geometry="radial") > risk_score(**base, geometry="in-track")
