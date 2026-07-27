"""Tests for engine/ingest/donki_ext.py — DONKI notification parsing + analysis."""

import pytest

from engine.ingest.donki_ext import (
    NOTIFICATION_TYPES,
    STORM_PRECURSORS,
    _parse_notifications,
    _summarize,
    analyze_donki,
)
from engine.models import DonkiNotification

# --- recorded fixture (representative DONKI response, multiple types) ---

DONKI_FIXTURE = [
    {
        "messageID": "20260724-GST-001",
        "messageType": "GST",
        "messageIssueTime": "2026-07-24T12:00Z",
        "messageURL": "https://kauai.ccmc.gsfc.nasa.gov/...",
        "messageBody": "## Space Weather Notification - Geomagnetic Storm\n##\nGeomagnetic storm conditions are expected.",
    },
    {
        "messageID": "20260723-CME-001",
        "messageType": "CME",
        "messageIssueTime": "2026-07-23T08:00Z",
        "messageURL": "https://kauai.ccmc.gsfc.nasa.gov/...",
        "messageBody": "## Coronal Mass Ejection\nA CME was observed departing the Sun.",
    },
    {
        "messageID": "20260722-FLR-001",
        "messageType": "FLR",
        "messageIssueTime": "2026-07-22T15:30Z",
        "messageURL": "https://kauai.ccmc.gsfc.nasa.gov/...",
        "messageBody": "## Solar Flare\nAn M-class flare was detected.",
    },
]


# --- parsing ---

def test_parse_notifications_count():
    notifs = _parse_notifications(DONKI_FIXTURE)
    assert len(notifs) == 3


def test_parse_notifications_fields():
    notifs = _parse_notifications(DONKI_FIXTURE)
    gst = next(n for n in notifs if n["message_type"] == "GST")
    assert gst["message_id"] == "20260724-GST-001"
    assert gst["issue_time"] == "2026-07-24T12:00Z"
    assert "Geomagnetic storm" in gst["summary"]


def test_parse_notifications_empty():
    assert _parse_notifications([]) == []


def test_notification_model_validates():
    for n in _parse_notifications(DONKI_FIXTURE):
        DonkiNotification.model_validate(n)


def test_summarize_strips_headers():
    body = "## Header Line\n## Another Header\nActual content here."
    summary = _summarize(body)
    assert "Header" not in summary
    assert "Actual content" in summary


def test_summarize_truncates():
    long_body = "x" * 500
    summary = _summarize(long_body, max_len=200)
    assert len(summary) <= 203  #200 + "..."
    assert summary.endswith("...")


def test_summarize_empty():
    assert _summarize("") == ""


# --- analysis ---

def test_analyze_by_type():
    notifs = [DonkiNotification.model_validate(n) for n in _parse_notifications(DONKI_FIXTURE)]
    analysis = analyze_donki(notifs)
    assert analysis["total"] == 3
    assert analysis["by_type"]["GST"] == 1
    assert analysis["by_type"]["CME"] == 1
    assert analysis["by_type"]["FLR"] == 1


def test_analyze_active_storm():
    notifs = [DonkiNotification.model_validate(n) for n in _parse_notifications(DONKI_FIXTURE)]
    analysis = analyze_donki(notifs)
    assert analysis["active_storm"] is True  # GST present


def test_analyze_storm_building():
    """Precursors (CME) present but no GST → storm_building True."""
    cme_only = [
        DonkiNotification.model_validate(n)
        for n in _parse_notifications(DONKI_FIXTURE)
        if n["message_type"] != "GST"
    ]
    analysis = analyze_donki(cme_only)
    assert analysis["active_storm"] is False
    assert "CME" in analysis["storm_precursors"]
    assert analysis["storm_building"] is True


def test_analyze_no_storm_activity():
    """Only flares (not a storm precursor) → no storm building."""
    flr_only = [
        DonkiNotification.model_validate(n)
        for n in _parse_notifications(DONKI_FIXTURE)
        if n["message_type"] == "FLR"
    ]
    analysis = analyze_donki(flr_only)
    assert analysis["active_storm"] is False
    assert analysis["storm_building"] is False


def test_analyze_type_meanings():
    notifs = [DonkiNotification.model_validate(n) for n in _parse_notifications(DONKI_FIXTURE)]
    analysis = analyze_donki(notifs)
    assert "GST" in analysis["type_meanings"]
    assert "drag" in analysis["type_meanings"]["GST"].lower()


def test_storm_precursors_defined():
    """CME, HSS, IPS should be recognized as storm precursors."""
    assert "CME" in STORM_PRECURSORS
    assert "HSS" in STORM_PRECURSORS
    assert "IPS" in STORM_PRECURSORS


def test_notification_types_documented():
    """Key notification types should have documented meanings."""
    for t in ["GST", "CME", "FLR", "HSS", "SEP", "RBE"]:
        assert t in NOTIFICATION_TYPES
