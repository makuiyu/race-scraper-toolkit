"""Tests for the normalize pipeline."""

from __future__ import annotations

from racescraper.pipelines.normalize import (
    NormalizePipeline,
    normalize_country,
    normalize_status,
    normalize_type,
)


def test_country_ioc_alpha3_translates_to_iso_alpha2() -> None:
    # World Athletics uses IOC alpha-3; these differ from ISO alpha-3 in 41 cases.
    # GER (IOC) -> DE (ISO alpha-2). Catches a regression if we ever switch to
    # naive ISO lookup.
    assert normalize_country("GER") == "DE"
    assert normalize_country("CHN") == "CN"
    assert normalize_country("SUI") == "CH"
    assert normalize_country("NED") == "NL"


def test_country_full_name_translates_to_iso_alpha2() -> None:
    assert normalize_country("United States") == "US"
    assert normalize_country("united kingdom") == "GB"
    assert normalize_country("China") == "CN"
    assert normalize_country("中国") == "CN"


def test_country_already_alpha2_passes_through_uppercased() -> None:
    assert normalize_country("us") == "US"
    assert normalize_country("JP") == "JP"


def test_country_unknown_returns_none() -> None:
    assert normalize_country(None) is None
    assert normalize_country("") is None
    assert normalize_country("Atlantis") is None


def test_event_type_maps_known_aliases() -> None:
    assert normalize_type("Road Race") == "marathon"
    assert normalize_type("half marathon") == "half_marathon"
    assert normalize_type("Ultra Trail") == "ultra"
    assert normalize_type("Ironman") == "triathlon_full"
    assert normalize_type(None) == "other"
    assert normalize_type("unknown garbage") == "other"


def test_event_status_normalizes_known_values() -> None:
    assert normalize_status("registration_open") == "open"
    assert normalize_status("REGISTRATION_CLOSED") == "closed"
    assert normalize_status("coming_soon") == "upcoming"
    assert normalize_status(None) == "upcoming"


def test_pipeline_end_to_end_normalization() -> None:
    # Pick a date far enough in the future that the test stays "upcoming"
    # regardless of when it runs.
    pipeline = NormalizePipeline()
    item: dict = {
        "name": "  Boston Marathon  ",
        "city": "Boston",
        "country": "USA",  # IOC alpha-3
        "event_type": "Road Running",
        "race_start_date": "April 20, 2099",
        "event_status": None,  # should be derived from dates
        "registration_urls": None,
        "distances": None,
        "tags": None,
    }
    result = pipeline.process_item(item)

    assert result["name"] == "Boston Marathon"
    assert result["country"] == "US"
    assert result["event_type"] == "marathon"
    assert result["race_start_date"] == "2099-04-20"
    # Date is in the future -> upcoming.
    assert result["event_status"] == "upcoming"
    # None list fields must be coerced to [].
    assert result["registration_urls"] == []
    assert result["distances"] == []
    assert result["tags"] == []
