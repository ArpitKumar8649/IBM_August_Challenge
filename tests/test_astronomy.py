"""Tests for engine/ingest/astronomy.py — transients, exoplanets, Gaia, TAP normalization."""

import pytest

from engine.ingest.astronomy import (
    _normalize_tap_rows,
    _parse_transient,
    mjd_to_iso,
)
from engine.models import Exoplanet, Star, Transient


# --- mjd_to_iso ---

def test_mjd_to_iso_j2000():
    """MJD 51544.5 = 2000-01-01 12:00 UTC (J2000 epoch)."""
    assert mjd_to_iso(51544.5).startswith("2000-01-01T12:00:00")


def test_mjd_to_iso_zero():
    assert mjd_to_iso(0) == ""


def test_mjd_to_iso_invalid():
    assert mjd_to_iso(-1e12) == ""  # overflow → empty


# --- _parse_transient ---

def test_parse_transient_fields():
    item = {
        "oid": "ZTF26abkitep",
        "meanra": 332.696,
        "meandec": 7.318,
        "class": "SN Ia",
        "lastmjd": 60883.5,
        "firstmjd": 60880.1,
        "ndethist": 42,
    }
    t = _parse_transient(item)
    assert t.oid == "ZTF26abkitep"
    assert t.ra == pytest.approx(332.696)
    assert t.dec == pytest.approx(7.318)
    assert t.classification == "SN Ia"
    assert t.n_detections == 42
    assert t.last_observed  # non-empty ISO date


def test_parse_transient_unclassified_default():
    """Missing/None class → 'unclassified'."""
    t = _parse_transient({"oid": "ZTF1", "class": None, "meanra": 0, "meandec": 0})
    assert t.classification == "unclassified"


def test_parse_transient_missing_fields_default():
    t = _parse_transient({"oid": "ZTF2"})
    assert t.ra == 0.0
    assert t.dec == 0.0
    assert t.n_detections == 0
    assert t.last_observed == ""


def test_transient_model_validates():
    t = _parse_transient({"oid": "ZTF3", "meanra": 10.0, "meandec": 20.0, "class": "AGN"})
    Transient.model_validate(t.model_dump())


# --- _normalize_tap_rows (the key robustness point) ---

def test_normalize_format1_list_of_dicts():
    """NASA Exoplanet Archive: top-level list of row dicts."""
    data = [{"pl_name": "TOI-209 b", "disc_year": 2026}]
    assert _normalize_tap_rows(data) == data


def test_normalize_format2a_dict_data_dicts():
    """Dict with 'data' as a list of dicts."""
    data = {"metadata": [{"name": "ra"}], "data": [{"ra": 10.0}]}
    assert _normalize_tap_rows(data) == [{"ra": 10.0}]


def test_normalize_format2b_dict_data_positional():
    """ESA Gaia: dict with 'data' as positional lists + metadata column names."""
    data = {
        "metadata": [{"name": "source_id"}, {"name": "ra"}, {"name": "dec"}],
        "data": [[123, 266.4, -28.9], [456, 266.5, -28.8]],
    }
    rows = _normalize_tap_rows(data)
    assert len(rows) == 2
    assert rows[0] == {"source_id": 123, "ra": 266.4, "dec": -28.9}
    assert rows[1]["source_id"] == 456


def test_normalize_positional_length_mismatch_skipped():
    """Positional rows with wrong length are skipped (not zipped incorrectly)."""
    data = {"metadata": [{"name": "a"}, {"name": "b"}], "data": [[1, 2, 3]]}  # 3 vals, 2 cols
    assert _normalize_tap_rows(data) == []


def test_normalize_edge_cases():
    assert _normalize_tap_rows({}) == []
    assert _normalize_tap_rows({"data": "not a list"}) == []
    assert _normalize_tap_rows("garbage") == []
    assert _normalize_tap_rows(None) == []
    assert _normalize_tap_rows({"data": [[1, 2]], "metadata": []}) == []  # no columns


# --- model validation for exoplanets and stars ---

def test_exoplanet_model():
    e = Exoplanet(name="TOI-209 b", discovery_method="Transit", discovery_year=2026, host_star="TOI-209")
    assert e.name == "TOI-209 b"
    assert e.discovery_year == 2026


def test_star_model():
    s = Star(source_id="123", ra=266.4, dec=-28.9, g_mag=15.2)
    assert s.source_id == "123"
    assert s.g_mag == 15.2


# --- live tests (graceful — skip/pass whether or not APIs are up) ---

def test_fetch_recent_transients_live():
    from engine.ingest.astronomy import fetch_recent_transients

    transients = fetch_recent_transients(limit=3)
    # May be empty if ALeRCE is slow/down — that's acceptable (graceful degradation).
    assert isinstance(transients, list)
    for t in transients:
        assert isinstance(t, Transient)
        assert t.oid


def test_exoplanet_count_live():
    from engine.ingest.astronomy import exoplanet_count

    count = exoplanet_count(2020)
    assert isinstance(count, int)
    assert count >= 0
    if count > 0:
        assert count > 1000  # there are thousands since 2020


def test_fetch_recent_exoplanets_live():
    from engine.ingest.astronomy import fetch_recent_exoplanets

    exos = fetch_recent_exoplanets(2020, limit=3)
    assert isinstance(exos, list)
    for e in exos:
        assert isinstance(e, Exoplanet)
        assert e.name


def test_query_gaia_live():
    from engine.ingest.astronomy import query_gaia

    stars = query_gaia(266.4, -28.9, radius_arcmin=6.0, limit=3)
    # May be empty if Gaia is rate-limited — acceptable.
    assert isinstance(stars, list)
    for s in stars:
        assert isinstance(s, Star)
        assert s.source_id
