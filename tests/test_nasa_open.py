"""Tests for engine/ingest/nasa_open.py — NEO, EPIC, APOD, ADS parsing.

Uses recorded API responses (fixtures) so tests run offline and deterministically.
"""

import pytest

from engine.ingest.nasa_open import (
    _epic_image_url,
    _parse_apod,
    _parse_epic,
    _parse_neo,
)
from engine.models import ApodEntry, EpicImage, NeoObject

# --- recorded fixtures (representative real API responses) ---

NEO_FIXTURE = {
    "near_earth_objects": {
        "2026-07-24": [
            {
                "id": "54395025",
                "name": "(2013 OD4)",
                "is_potentially_hazardous_asteroid": True,
                "estimated_diameter": {"kilometers": {"estimated_diameter_max": 0.368}},
                "close_approach_data": [
                    {
                        "close_approach_date": "2026-07-24",
                        "relative_velocity": {"kilometers_per_hour": "41234.5"},
                        "miss_distance": {"kilometers": "4567890.123", "lunar": "11.8"},
                        "orbiting_body": "Earth",
                    }
                ],
            },
            {
                "id": "54395026",
                "name": "(2024 PT7)",
                "is_potentially_hazardous_asteroid": False,
                "estimated_diameter": {"kilometers": {"estimated_diameter_max": 0.142}},
                "close_approach_data": [],
            },
        ]
    }
}

EPIC_FIXTURE = [
    {
        "identifier": "20260724002713",
        "caption": "EPIC image of Earth",
        "date": "2026-07-24 00:22:24",
        "centroid_coordinates": {"lat": 11.7, "lon": -175.6},
    }
]

APOD_FIXTURE = {
    "title": "NGC 7635: The Bubble Nebula",
    "explanation": "A vast bubble of glowing gas " * 50,
    "url": "https://apod.nasa.gov/apod/image/2607/BubbleNebula.jpg",
    "hdurl": "https://apod.nasa.gov/apod/image/2607/BubbleNebula_big.jpg",
    "media_type": "image",
    "date": "2026-07-24",
}

ADS_FIXTURE = {
    "response": {
        "docs": [
            {
                "bibcode": "2000JGCD...23..662A",
                "title": ["Collision Probability for Spacecraft"],
                "author": ["Alfriend, K.", "Akella, M."],
                "year": 2000,
                "abstract": "We present a method for computing collision probability.",
            }
        ]
    }
}


# --- NEO ---

def test_parse_neo_extracts_objects():
    objects = _parse_neo(NEO_FIXTURE)
    assert len(objects) == 2


def test_parse_neo_hazardous_flag():
    objects = _parse_neo(NEO_FIXTURE)
    by_name = {o["name"]: o for o in objects}
    assert by_name["(2013 OD4)"]["is_potentially_hazardous"] is True
    assert by_name["(2024 PT7)"]["is_potentially_hazardous"] is False


def test_parse_neo_close_approach_fields():
    objects = _parse_neo(NEO_FIXTURE)
    od4 = next(o for o in objects if o["name"] == "(2013 OD4)")
    assert len(od4["close_approaches"]) == 1
    ca = od4["close_approaches"][0]
    assert ca["miss_distance_km"] == pytest.approx(4567890.123)
    assert ca["miss_distance_lunar"] == pytest.approx(11.8)
    assert ca["relative_velocity_kmh"] == pytest.approx(41234.5)


def test_parse_neo_diameter():
    objects = _parse_neo(NEO_FIXTURE)
    od4 = next(o for o in objects if o["name"] == "(2013 OD4)")
    assert od4["estimated_diameter_km"] == pytest.approx(0.368)


def test_neo_object_model_validates():
    objects = _parse_neo(NEO_FIXTURE)
    for o in objects:
        NeoObject.model_validate(o)  # should not raise


def test_parse_neo_empty():
    assert _parse_neo({}) == []
    assert _parse_neo({"near_earth_objects": {}}) == []


# --- EPIC ---

def test_epic_image_url_construction():
    url = _epic_image_url("20260724002713", "2026-07-24 00:22:24", "DEMO_KEY")
    assert "/2026/07/24/png/epic_1b_20260724002713.png" in url
    assert "api_key=DEMO_KEY" in url


def test_epic_image_url_bad_date():
    assert _epic_image_url("abc", "not-a-date", "KEY") == ""


def test_parse_epic_fields():
    images = _parse_epic(EPIC_FIXTURE, "DEMO_KEY")
    assert len(images) == 1
    img = images[0]
    assert img["identifier"] == "20260724002713"
    assert img["centroid_lat"] == pytest.approx(11.7)
    assert img["centroid_lon"] == pytest.approx(-175.6)
    assert "epic_1b_20260724002713.png" in img["image_url"]


def test_epic_model_validates():
    images = _parse_epic(EPIC_FIXTURE, "DEMO_KEY")
    for i in images:
        EpicImage.model_validate(i)


# --- APOD ---

def test_parse_apod_fields():
    apod = _parse_apod(APOD_FIXTURE)
    assert apod["title"] == "NGC 7635: The Bubble Nebula"
    assert apod["media_type"] == "image"
    assert apod["url"].endswith(".jpg")


def test_parse_apod_video_type():
    video = dict(APOD_FIXTURE, media_type="video", url="https://youtube.com/embed/x")
    apod = _parse_apod(video)
    assert apod["media_type"] == "video"


def test_apod_model_validates():
    ApodEntry.model_validate(_parse_apod(APOD_FIXTURE))


# --- ADS ---

def test_parse_ads_fields():
    from engine.ingest.nasa_open import _parse_ads

    papers = _parse_ads(ADS_FIXTURE)
    assert len(papers) == 1
    p = papers[0]
    assert p["title"] == "Collision Probability for Spacecraft"
    assert p["bibcode"] == "2000JGCD...23..662A"
    assert p["year"] == "2000"
    assert "Alfriend" in p["authors"][0]
    assert p["url"].endswith("2000JGCD...23..662A")


def test_parse_ads_empty():
    from engine.ingest.nasa_open import _parse_ads

    assert _parse_ads({}) == []
    assert _parse_ads({"response": {"docs": []}}) == []
