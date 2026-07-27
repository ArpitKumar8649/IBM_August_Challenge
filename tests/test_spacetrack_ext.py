"""Tests for engine/ingest/spacetrack_ext.py — boxscore, decay, launch_site parsing."""

import pytest

from engine.ingest.spacetrack_ext import _parse_boxscore, _parse_decay, _parse_launch_sites
from engine.models import CountryStats, DecayEvent, LaunchSite

# --- recorded fixtures (representative real responses) ---

BOXSCORE_FIXTURE = [
    {
        "COUNTRY": "ALL",
        "SPADOC_CD": "ALL",
        "ORBITAL_PAYLOAD_COUNT": "19085",
        "ORBITAL_ROCKET_BODY_COUNT": "2750",
        "ORBITAL_DEBRIS_COUNT": "12501",
        "ORBITAL_TOTAL_COUNT": "34737",
        "DECAYED_TOTAL_COUNT": "35385",
        "COUNTRY_TOTAL": "70122",
    },
    {
        "COUNTRY": "UNITED STATES OF AMERICA",
        "SPADOC_CD": "US",
        "ORBITAL_PAYLOAD_COUNT": "13454",
        "ORBITAL_ROCKET_BODY_COUNT": "776",
        "ORBITAL_DEBRIS_COUNT": "3906",
        "ORBITAL_TOTAL_COUNT": "18146",
        "DECAYED_TOTAL_COUNT": "10612",
        "COUNTRY_TOTAL": "28758",
    },
    {
        "COUNTRY": "PEOPLES REPUBLIC OF CHINA",
        "SPADOC_CD": "PRC",
        "ORBITAL_PAYLOAD_COUNT": "1272",
        "ORBITAL_ROCKET_BODY_COUNT": "582",
        "ORBITAL_DEBRIS_COUNT": "4188",
        "ORBITAL_TOTAL_COUNT": "6042",
        "DECAYED_TOTAL_COUNT": "3161",
        "COUNTRY_TOTAL": "9203",
    },
]

DECAY_FIXTURE = [
    {
        "NORAD_CAT_ID": "46171",
        "INTLDES": "2020-057BG",
        "COUNTRY": "US",
        "DECAY_EPOCH": "2026-07-27 14:30:00",
        "MSG_EPOCH": "2026-07-26 12:00:00",
        "MSG_TYPE": "PREDICTED",
    },
    {
        "NORAD_CAT_ID": "66310",
        "INTLDES": "2025-249A",
        "COUNTRY": "IND",
        "DECAY_EPOCH": "2026-07-30 08:15:00",
        "MSG_EPOCH": "2026-07-26 12:00:00",
        "MSG_TYPE": "PREDICTED",
    },
]

LAUNCH_SITE_FIXTURE = [
    {"LAUNCH_SITE": "AFETR", "LAUNCH_SITE_NAME": "Air Force Eastern Test Range", "COUNTRY": "US"},
    {"LAUNCH_SITE": "TTMTR", "LAUNCH_SITE_NAME": "Tyuratam (Baikonur)", "COUNTRY": "KZ"},
]


# --- boxscore ---

def test_parse_boxscore_counts():
    stats = _parse_boxscore(BOXSCORE_FIXTURE)
    assert len(stats) == 3
    us = next(s for s in stats if s["country_code"] == "US")
    assert us["orbital_payloads"] == 13454
    assert us["orbital_debris"] == 3906
    assert us["orbital_total"] == 18146
    assert us["decayed_total"] == 10612


def test_parse_boxscore_global_row():
    stats = _parse_boxscore(BOXSCORE_FIXTURE)
    all_row = next(s for s in stats if s["country"] == "ALL")
    assert all_row["orbital_payloads"] == 19085
    assert all_row["orbital_debris"] == 12501


def test_boxscore_model_validates():
    for s in _parse_boxscore(BOXSCORE_FIXTURE):
        CountryStats.model_validate(s)


def test_boxscore_active_payloads_alias():
    stats = _parse_boxscore(BOXSCORE_FIXTURE)
    us = next(CountryStats.model_validate(s) for s in stats if s["country_code"] == "US")
    assert us.active_payloads == us.orbital_payloads == 13454


def test_parse_boxscore_empty():
    assert _parse_boxscore([]) == []


# --- decay ---

def test_parse_decay_fields():
    events = _parse_decay(DECAY_FIXTURE)
    assert len(events) == 2
    e = events[0]
    assert e["norad_id"] == 46171
    assert e["intl_des"] == "2020-057BG"
    assert e["country"] == "US"
    assert "2026-07-27" in e["decay_epoch"]
    assert e["msg_type"] == "PREDICTED"


def test_decay_model_validates():
    for e in _parse_decay(DECAY_FIXTURE):
        DecayEvent.model_validate(e)


def test_parse_decay_empty():
    assert _parse_decay([]) == []


# --- launch sites ---

def test_parse_launch_sites_fields():
    sites = _parse_launch_sites(LAUNCH_SITE_FIXTURE)
    assert len(sites) == 2
    assert sites[0]["code"] == "AFETR"
    assert sites[0]["name"] == "Air Force Eastern Test Range"
    assert sites[0]["country"] == "US"


def test_launch_site_model_validates():
    for s in _parse_launch_sites(LAUNCH_SITE_FIXTURE):
        LaunchSite.model_validate(s)


def test_parse_launch_sites_empty():
    assert _parse_launch_sites([]) == []
