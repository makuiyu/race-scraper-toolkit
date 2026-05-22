"""Standalone demo: 30 raw events from three "sources" -> ~25 canonical events.

Run with:
    python examples/dedupe_demo.py

The demo intentionally seeds five near-duplicate triples / pairs so you can
watch the dedupe collapse them. The exact final count depends on rapidfuzz's
WRatio thresholds; on a stock install you should see ~25.
"""

from __future__ import annotations

import json
from typing import Any

from racescraper.pipelines.dedupe import (
    CONFIDENCE_AUTO_MERGE,
    dedupe_events,
    score_pair,
)


def _event(
    source: str,
    source_id: str,
    name: str,
    *,
    city: str,
    country: str,
    event_type: str,
    race_start_date: str,
    official_url: str | None = None,
    tags: list[str] | None = None,
    supplement: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": source,
        "source_id": source_id,
        "name": name,
        "city": city,
        "country": country,
        "event_type": event_type,
        "race_start_date": race_start_date,
        "official_url": official_url,
        "registration_urls": [],
        "distances": [],
        "tags": tags or [],
    }
    if supplement:
        item["_supplement_only"] = True
    return item


# 30 raw events. Notice the deliberate overlaps:
#   Tokyo Marathon appears in WA + UTMB-style + AIMS
#   Boston Marathon appears in WA + AIMS
#   Berlin Marathon appears in WA + AIMS
#   UTMB Mont-Blanc appears twice (UTMB Series + UTMB Worlds tag)
#   Two distinct events with similar names ("City Marathon" in two countries)
#     should NOT collapse.
RAW: list[dict[str, Any]] = [
    # --- Tokyo Marathon trio ---
    _event("worldathletics", "wa-1", "Tokyo Marathon",
           city="Tokyo", country="JP", event_type="marathon",
           race_start_date="2026-03-01", tags=["Platinum Label"]),
    _event("utmb_demo", "u-1", "Tokyo Marathon 2026",
           city="Tokyo", country="JP", event_type="marathon",
           race_start_date="2026-03-01"),
    _event("aims", "a-1", "Tokyo Marathon",
           city="Tokyo", country="JP", event_type="marathon",
           race_start_date="2026-03-01",
           official_url="https://www.marathon.tokyo/",
           tags=["AIMS"], supplement=True),

    # --- Boston Marathon pair ---
    _event("worldathletics", "wa-2", "Boston Marathon",
           city="Boston", country="US", event_type="marathon",
           race_start_date="2026-04-20", tags=["Platinum Label"]),
    _event("aims", "a-2", "Boston Marathon",
           city="Boston", country="US", event_type="marathon",
           race_start_date="2026-04-20",
           official_url="https://www.baa.org/",
           tags=["AIMS"], supplement=True),

    # --- Berlin Marathon pair ---
    _event("worldathletics", "wa-3", "Berlin Marathon",
           city="Berlin", country="DE", event_type="marathon",
           race_start_date="2026-09-27", tags=["Platinum Label"]),
    _event("aims", "a-3", "Berlin Marathon",
           city="Berlin", country="DE", event_type="marathon",
           race_start_date="2026-09-27",
           official_url="https://www.bmw-berlin-marathon.com/",
           tags=["AIMS"], supplement=True),

    # --- UTMB Mont-Blanc near-duplicate ---
    _event("utmb_demo", "u-2", "UTMB Mont-Blanc",
           city="Chamonix", country="FR", event_type="ultra",
           race_start_date="2026-08-28"),
    _event("utmb_demo", "u-3", "UTMB Mont Blanc",
           city="Chamonix", country="FR", event_type="ultra",
           race_start_date="2026-08-28"),

    # --- Same name, different country — must NOT collapse ---
    _event("worldathletics", "wa-4", "City Marathon",
           city="Boston", country="US", event_type="marathon",
           race_start_date="2026-04-20"),
    _event("worldathletics", "wa-5", "City Marathon",
           city="Tokyo", country="JP", event_type="marathon",
           race_start_date="2027-11-01"),

    # --- Unique singletons (no duplicates) ---
    _event("worldathletics", "wa-6", "London Marathon",
           city="London", country="GB", event_type="marathon",
           race_start_date="2026-04-26", tags=["Platinum Label"]),
    _event("worldathletics", "wa-7", "Chicago Marathon",
           city="Chicago", country="US", event_type="marathon",
           race_start_date="2026-10-11", tags=["Platinum Label"]),
    _event("worldathletics", "wa-8", "New York City Marathon",
           city="New York", country="US", event_type="marathon",
           race_start_date="2026-11-01", tags=["Platinum Label"]),
    _event("worldathletics", "wa-9", "Sydney Marathon",
           city="Sydney", country="AU", event_type="marathon",
           race_start_date="2026-08-30", tags=["Platinum Label"]),
    _event("worldathletics", "wa-10", "Valencia Half Marathon",
           city="Valencia", country="ES", event_type="half_marathon",
           race_start_date="2026-10-25", tags=["Gold Label"]),
    _event("worldathletics", "wa-11", "Copenhagen Half Marathon",
           city="Copenhagen", country="DK", event_type="half_marathon",
           race_start_date="2026-09-13", tags=["Gold Label"]),
    _event("worldathletics", "wa-12", "C&D Xiamen Marathon",
           city="Xiamen", country="CN", event_type="marathon",
           race_start_date="2026-01-11", tags=["Platinum Label"]),
    _event("worldathletics", "wa-13", "Houston Marathon",
           city="Houston", country="US", event_type="marathon",
           race_start_date="2026-01-18"),
    _event("worldathletics", "wa-14", "Seoul Marathon",
           city="Seoul", country="KR", event_type="marathon",
           race_start_date="2026-03-15"),
    _event("worldathletics", "wa-15", "Paris Marathon",
           city="Paris", country="FR", event_type="marathon",
           race_start_date="2026-04-12"),
    _event("worldathletics", "wa-16", "Rotterdam Marathon",
           city="Rotterdam", country="NL", event_type="marathon",
           race_start_date="2026-04-19"),
    _event("worldathletics", "wa-17", "Madrid Marathon",
           city="Madrid", country="ES", event_type="marathon",
           race_start_date="2026-04-26"),
    _event("worldathletics", "wa-18", "Prague Marathon",
           city="Prague", country="CZ", event_type="marathon",
           race_start_date="2026-05-10"),
    _event("utmb_demo", "u-4", "Western States 100",
           city="Olympic Valley", country="US", event_type="ultra",
           race_start_date="2026-06-27"),
    _event("utmb_demo", "u-5", "Hardrock 100",
           city="Silverton", country="US", event_type="ultra",
           race_start_date="2026-07-10"),
    _event("utmb_demo", "u-6", "Lavaredo Ultra Trail",
           city="Cortina d'Ampezzo", country="IT", event_type="ultra",
           race_start_date="2026-06-26"),
    _event("utmb_demo", "u-7", "Eiger Ultra Trail",
           city="Grindelwald", country="CH", event_type="ultra",
           race_start_date="2026-07-18"),
    _event("utmb_demo", "u-8", "TDS 145",
           city="Courmayeur", country="IT", event_type="ultra",
           race_start_date="2026-08-26"),
    _event("utmb_demo", "u-9", "CCC 100",
           city="Courmayeur", country="IT", event_type="ultra",
           race_start_date="2026-08-28"),
]


def main() -> None:
    print(f"Loaded {len(RAW)} raw events from 3 sources.")

    # Show one example pair score so the reader can see the math in action.
    a, b = RAW[0], RAW[1]  # Tokyo Marathon (WA) vs Tokyo Marathon 2026 (UTMB-style)
    score = score_pair(a, b)
    print(
        f"Example pair: {a['name']!r} vs {b['name']!r} -> "
        f"score = {score:.3f} (auto-merge threshold = {CONFIDENCE_AUTO_MERGE})"
    )

    canonical = dedupe_events(RAW)
    print(f"Deduped: {len(RAW)} raw -> {len(canonical)} canonical")
    print()
    print("Final canonical events:")
    for ev in canonical:
        backfilled = " [+url]" if ev.get("official_url") else ""
        print(f"  - {ev['name']:<30} {ev['city']:<25} {ev['race_start_date']}{backfilled}")

    # Also dump full JSON for downstream tooling.
    out_path = "dedupe_demo_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2, ensure_ascii=False)
    print(f"\nFull JSON written to ./{out_path}")


if __name__ == "__main__":
    main()
