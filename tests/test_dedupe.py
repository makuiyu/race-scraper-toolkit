"""Tests for the confidence-weighted dedupe.

Each test pins one of the three weight components so a regression in any of
them surfaces clearly.
"""

from __future__ import annotations

from racescraper.pipelines.dedupe import (
    CONFIDENCE_AUTO_MERGE,
    CONFIDENCE_NEW_EVENT,
    WEIGHT_GEO_TYPE,
    WEIGHT_NAME_SIMILARITY,
    dedupe_events,
    score_pair,
)


def _make_event(
    *,
    source: str = "test",
    source_id: str = "1",
    name: str,
    city: str | None = None,
    country: str | None = None,
    event_type: str | None = None,
    race_start_date: str | None = None,
    official_url: str | None = None,
    tags: list[str] | None = None,
    supplement: bool = False,
) -> dict:
    item: dict = {
        "source": source,
        "source_id": source_id,
        "name": name,
        "city": city,
        "country": country,
        "event_type": event_type,
        "race_start_date": race_start_date,
        "official_url": official_url,
        "tags": tags or [],
        "registration_urls": [],
        "distances": [],
    }
    if supplement:
        item["_supplement_only"] = True
    return item


def test_identical_events_merge_at_auto_merge_threshold() -> None:
    """Same name, same city+type, same date -> score ~= 1.0 -> auto-merge."""
    a = _make_event(
        name="Boston Marathon",
        city="Boston",
        country="US",
        event_type="marathon",
        race_start_date="2026-04-20",
    )
    b = _make_event(
        source_id="2",
        name="Boston Marathon",
        city="Boston",
        country="US",
        event_type="marathon",
        race_start_date="2026-04-20",
    )

    score = score_pair(b, a)
    assert score >= CONFIDENCE_AUTO_MERGE, f"expected auto-merge, got {score:.3f}"

    deduped = dedupe_events([a, b])
    assert len(deduped) == 1, "two identical events must collapse"


def test_name_only_match_is_below_new_event_threshold() -> None:
    """Same name but different city, different type, far-apart dates.

    Name similarity alone (40%) should not be enough to cross the
    `CONFIDENCE_NEW_EVENT` cutoff — proving the geo+type and date weights
    are pulling their weight.
    """
    a = _make_event(
        name="City Marathon",
        city="Boston",
        country="US",
        event_type="marathon",
        race_start_date="2026-04-20",
    )
    b = _make_event(
        source_id="2",
        name="City Marathon",
        city="Tokyo",
        country="JP",
        event_type="trail",
        race_start_date="2027-11-01",
    )

    score = score_pair(b, a)
    # Name similarity is ~1.0 -> 0.4 contribution. Geo+type and date both 0.
    assert score < CONFIDENCE_NEW_EVENT, f"score should be below new-event cutoff, got {score:.3f}"

    deduped = dedupe_events([a, b])
    assert len(deduped) == 2, "weakly-matched events must remain separate"


def test_geo_type_bonus_pushes_pair_over_threshold() -> None:
    """Slightly different names + same city/type/date -> auto-merge.

    The 30% geo+type bonus plus the 30% same-day proximity bonus should
    overwhelm a small name penalty.
    """
    a = _make_event(
        name="Xiamen Marathon 2026",
        city="Xiamen",
        country="CN",
        event_type="marathon",
        race_start_date="2026-01-11",
    )
    b = _make_event(
        source_id="2",
        name="C&D Xiamen Marathon",
        city="Xiamen",
        country="CN",
        event_type="marathon",
        race_start_date="2026-01-11",
    )

    score = score_pair(b, a)
    assert score >= CONFIDENCE_AUTO_MERGE, f"expected auto-merge, got {score:.3f}"


def test_date_proximity_decays_linearly_within_window() -> None:
    """A 7-day gap contributes ~0, a 1-day gap contributes ~6/7 of the 0.3 weight."""
    base = _make_event(
        name="Foo Marathon",
        city="Foo",
        event_type="marathon",
        race_start_date="2026-05-01",
    )
    near = _make_event(
        source_id="2",
        name="Foo Marathon",
        city="Foo",
        event_type="marathon",
        race_start_date="2026-05-02",
    )
    mid = _make_event(
        source_id="3",
        name="Foo Marathon",
        city="Foo",
        event_type="marathon",
        race_start_date="2026-05-05",  # +4 days
    )
    outside = _make_event(
        source_id="4",
        name="Foo Marathon",
        city="Foo",
        event_type="marathon",
        race_start_date="2026-05-15",  # +14 days, beyond the window
    )

    s_near = score_pair(near, base)
    s_mid = score_pair(mid, base)
    s_outside = score_pair(outside, base)

    # All three share name+city+type, so the only varying component is the
    # date-proximity term: closer dates score strictly higher inside the
    # 7-day window; anything outside contributes nothing.
    assert s_near > s_mid > s_outside
    # The +14d pair gets 0 date proximity -> score == name(0.4) + geo+type(0.3) == 0.7
    expected = WEIGHT_NAME_SIMILARITY + WEIGHT_GEO_TYPE
    assert abs(s_outside - expected) < 0.01, f"expected ~{expected}, got {s_outside:.3f}"


def test_supplement_only_dropped_when_no_match() -> None:
    """AIMS-style supplement items must not create new canonical events."""
    primary = _make_event(
        name="Some Other Race",
        city="Nowhere",
        event_type="marathon",
        race_start_date="2026-04-20",
    )
    supplement = _make_event(
        source="aims",
        source_id="9",
        name="A Completely Different Race",
        city="Elsewhere",
        event_type="marathon",
        race_start_date="2026-10-10",
        official_url="https://example.com",
        supplement=True,
    )

    deduped = dedupe_events([primary, supplement])
    # Primary kept, supplement dropped because it didn't match anything.
    assert len(deduped) == 1
    assert deduped[0]["name"] == "Some Other Race"


def test_supplement_only_backfills_official_url() -> None:
    """When a supplement matches a known event, it should backfill empty fields."""
    canonical = _make_event(
        source="worldathletics",
        name="Tokyo Marathon",
        city="Tokyo",
        country="JP",
        event_type="marathon",
        race_start_date="2026-03-01",
        official_url=None,
    )
    aims_supplement = _make_event(
        source="aims",
        source_id="9",
        name="Tokyo Marathon",
        city="Tokyo",
        country="JP",
        event_type="marathon",
        race_start_date="2026-03-01",
        official_url="https://www.marathon.tokyo/",
        tags=["AIMS"],
        supplement=True,
    )

    deduped = dedupe_events([canonical, aims_supplement])
    assert len(deduped) == 1
    assert deduped[0]["official_url"] == "https://www.marathon.tokyo/"
    assert "AIMS" in deduped[0]["tags"]
