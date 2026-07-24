"""Tests for agent/validator.py — the output-validation trust guarantee."""

import pytest

from agent.validator import (
    Validator,
    build_truth_set,
    extract_numbers,
    validate_text,
)


def test_extract_numbers():
    text = "Miss is 3.037 km at 14.3 km/s, Pc 6.69e-13, rank 1 of 200."
    nums = extract_numbers(text)
    assert 3.037 in nums
    assert 14.3 in nums
    assert pytest.approx(6.69e-13) in nums
    assert 1.0 in nums
    assert 200.0 in nums


def test_build_truth_set_nested():
    results = [
        {"miss_km": 3.037, "rsw": {"radial": 1.0, "in_track": 2.0}},
        {"options": [{"dv_total_ms": 100.0}, {"dv_total_ms": 200.0}]},
    ]
    truth = build_truth_set(results)
    assert 3.037 in truth
    assert 1.0 in truth and 2.0 in truth
    assert 100.0 in truth and 200.0 in truth


def test_build_truth_set_includes_string_numbers():
    """Numbers inside strings (names, timestamps) are legitimate ground truth."""
    results = [
        {"secondary_name": "COSMOS 2251 DEB", "tca": "2026-07-25T10:20:53+00:00"},
    ]
    truth = build_truth_set(results)
    assert 2251.0 in truth  # from the object name
    # timestamp components (regular hyphens -> signed): 2026, -7, -25, 10, 20, 53
    assert 2026.0 in truth
    assert -7.0 in truth and -25.0 in truth
    assert 10.0 in truth and 20.0 in truth and 53.0 in truth


def test_extract_numbers_normalizes_dashes():
    """Non-breaking hyphens in dates parse the same as regular hyphens."""
    regular = extract_numbers("2026-07-25")
    non_breaking = extract_numbers("2026‑07‑25")  # U+2011 non-breaking hyphen
    assert regular == non_breaking == [2026.0, -7.0, -25.0]


def test_observe_text_seeds_operator_constraints():
    """Numbers the operator states (constraints) are legitimate to restate."""
    v = Validator()
    v.observe_text("I have 100 g margin and want a 90 km miss.")
    good = v.validate_prose("That burn uses 33.8 g, under your 100 g margin, but only reaches 90 km.")
    # 100 and 90 are seeded; 33.8 is NOT in truth -> flagged
    assert "100" in good and "⚠[unverified]" in good  # 33.8 flagged, 100/90 not
    # Now add 33.8 via a tool result and it passes
    v.observe([{"propellant_g": 33.8}])
    clean = v.validate_prose("That burn uses 33.8 g, under your 100 g margin.")
    assert "⚠" not in clean


def test_verified_number_passes():
    truth = {3.037, 14.3}
    text = "The miss distance is 3.037 km."
    annotated, findings = validate_text(text, truth)
    assert "⚠" not in annotated
    assert any(f.status == "verified" for f in findings)


def test_unverified_number_flagged():
    truth = {3.037, 14.3}
    text = "The miss distance is 99.9 km."  # invented
    annotated, findings = validate_text(text, truth)
    assert "⚠[unverified]" in annotated
    assert any(f.status == "unverified" for f in findings)


def test_trivial_numbers_not_flagged():
    truth = set()
    text = "Here are the top 3 events."
    annotated, findings = validate_text(text, truth)
    assert "⚠" not in annotated
    assert all(f.status == "trivial" for f in findings)


def test_tolerance_allows_rounding():
    truth = {3.037}
    text = "Miss is about 3.04 km."  # rounded
    annotated, _ = validate_text(text, truth)
    assert "⚠" not in annotated


def test_validator_session_flow():
    v = Validator()
    v.observe([{"miss_km": 3.037, "vrel_kms": 14.3}])
    good = v.validate_prose("The miss is 3.037 km with vrel 14.3 km/s.")
    assert "⚠" not in good
    bad = v.validate_prose("The miss is 50.0 km.")  # invented
    assert "⚠[unverified]" in bad
    assert v.all_passed is False  # one prose artifact failed


def test_validator_card_is_trusted():
    v = Validator()
    record = v.validate_card({"card_type": "AVOIDANCE_MANEUVER", "dv": 100.0})
    assert record.passed is True
    assert record.artifact_type == "maneuver_card"
