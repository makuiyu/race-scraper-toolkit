"""UTMB spider.

Technique: UTMB exposes a public JSON API at `api.utmb.world/search/races` with
date-range and offset/limit pagination. No scraping of rendered HTML — we just
walk the API in order. The "event" concept on UTMB is a group of named races
(e.g. `"Foo by UTMB - 100K"` and `"Foo by UTMB - 50K"`); we group races by
event name and emit one item per event with all distances embedded.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response, TextResponse

from racescraper.spiders.base import BaseRaceSpider, RawEventItem

API_BASE = "https://api.utmb.world/search/races"
PAGE_SIZE = 50

STATUS_MAP: dict[str, str] = {
    "open": "open",
    "registration_open": "open",
    "registration_closed": "closed",
    "registration_sold_out": "closed",
    "coming_soon": "upcoming",
    "cancelled": "cancelled",
}


def _parse_utmb_date(date_str: str) -> str:
    """`'1st May 2026'` -> `'2026-05-01'`. Returns `''` on parse failure."""
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str.strip())
    try:
        return datetime.strptime(cleaned, "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _get_stat(stats: list[dict[str, Any]], name: str) -> Any:
    for s in stats:
        if s.get("name") == name:
            return s.get("value")
    return None


def _split_name(name: str) -> tuple[str, str]:
    """`'Foo by UTMB - 100K'` -> `('Foo by UTMB', '100K')`."""
    if " - " in name:
        event_name, _, label = name.partition(" - ")
        return event_name.strip(), label.strip()
    return name.strip(), ""


class UtmbSpider(BaseRaceSpider):
    """Walks the UTMB public race-search API and emits one event per group."""

    name = "utmb"
    source = "utmb"
    allowed_domains: list[str] = ["api.utmb.world"]

    custom_settings: dict[bool | float | int | str | None, Any] | None = {
        **(BaseRaceSpider.custom_settings or {}),
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.0,
    }

    def __init__(self, year: int | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        now = datetime.now(UTC)
        base_year = int(year) if year else now.year
        self._date_min = f"{base_year}-01-01"
        self._date_max = f"{base_year + 1}-12-31"
        self._all_races: list[dict[str, Any]] = []
        self._nb_hits = 0

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        yield self._make_request(offset=0)

    def _make_request(self, offset: int) -> scrapy.Request:
        params = {
            "lang": "en",
            "dateMin": self._date_min,
            "dateMax": self._date_max,
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        return scrapy.Request(f"{API_BASE}?{urlencode(params)}", callback=self.parse_api)

    def parse_api(self, response: Response) -> Generator[RawEventItem | scrapy.Request, None, None]:
        assert isinstance(response, TextResponse)
        try:
            data = response.json()
        except Exception:
            self.logger.error("Failed to parse UTMB API response")
            return

        races = data.get("races", [])
        self._nb_hits = data.get("nbHits", 0)
        offset = data.get("offset", 0)
        self._all_races.extend(races)

        next_offset = offset + PAGE_SIZE
        if next_offset < self._nb_hits:
            yield self._make_request(offset=next_offset)
        else:
            yield from self._emit_items()

    def _emit_items(self) -> Generator[RawEventItem, None, None]:
        """Group races by event name and emit one `RawEventItem` per event."""
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for race in self._all_races:
            name = race.get("name", "").strip()
            event_name, _ = _split_name(name)
            groups[event_name].append(race)

        self.logger.info("UTMB: %d races -> %d events", len(self._all_races), len(groups))

        for event_name, races in groups.items():
            item = self._build_item(event_name, races)
            if item:
                yield item

    def _build_item(self, event_name: str, races: list[dict[str, Any]]) -> RawEventItem | None:
        # Sort by date; earliest is the event start, latest is the end.
        dated: list[tuple[str, dict[str, Any]]] = []
        for race in races:
            d = _parse_utmb_date(race.get("startDate", ""))
            if d:
                dated.append((d, race))
        if not dated:
            return None
        dated.sort(key=lambda x: x[0])

        race_start_date = dated[0][0]
        race_end_date = dated[-1][0] if dated[-1][0] != race_start_date else None

        # Combine all UTMB race IDs into a stable source_id.
        all_ids = sorted(str(r.get("id", "")) for r in races)
        source_id = "_".join(all_ids)

        # Pick the first non-empty start location as the event location.
        locations = [r.get("startLocation", "") for r in races if r.get("startLocation")]
        location = locations[0] if locations else ""
        parts = [p.strip() for p in location.split(",")]
        city = parts[0] if parts else ""
        country = parts[-1] if len(parts) > 1 else ""

        distances: list[dict[str, Any]] = []
        for i, (d, r) in enumerate(dated):
            _, label = _split_name(r.get("name", ""))
            details = r.get("details") or {}
            stats_up = details.get("statsUp") or []
            distance_km = _get_stat(stats_up, "distance")
            elevation = _get_stat(stats_up, "elevationGain")
            stone_points = _get_stat(stats_up, "runningStones")
            race_slug = r.get("slug", "") or None
            if distance_km:
                distances.append(
                    {
                        "label": label or "Ultra",
                        "distance_km": float(distance_km),
                        "elevation_gain": elevation,
                        "race_start_date": d if d != race_start_date else None,
                        "points": stone_points,
                        "official_url": race_slug,
                        "sort_order": i,
                    }
                )

        distances_by_km = sorted(distances, key=lambda x: x["distance_km"], reverse=True)
        slug = next((d["official_url"] for d in distances_by_km if d["official_url"]), "")
        max_km = distances_by_km[0]["distance_km"] if distances_by_km else 0
        event_type = "ultra" if max_km > 60 else "trail"

        # Aggregate status: any "open" wins; otherwise mode.
        statuses: list[str] = []
        for race in races:
            race_status = race.get("raceStatus") or {}
            statuses.append(STATUS_MAP.get(race_status.get("status", ""), "upcoming"))
        event_status = "open" if "open" in statuses else max(set(statuses), key=statuses.count)

        item = RawEventItem()
        item["source"] = self.source
        item["source_id"] = source_id
        item["name"] = event_name
        item["race_start_date"] = race_start_date
        if race_end_date:
            item["race_end_date"] = race_end_date
        item["series"] = "UTMB Series"
        item["event_type"] = event_type
        item["tags"] = ["UTMB Series"]
        item["city"] = city
        item["country"] = country
        item["official_url"] = slug or None
        item["registration_urls"] = [slug] if slug else []
        item["source_url"] = slug or API_BASE
        item["distances"] = distances
        item["event_status"] = event_status
        item["raw_data"] = {
            "utmb_ids": all_ids,
            "races": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "status": (r.get("raceStatus") or {}).get("status"),
                    "startDate": r.get("startDate"),
                    "startLocation": r.get("startLocation"),
                    "details": r.get("details"),
                    "playgrounds": r.get("playgrounds"),
                }
                for r in races
            ],
        }
        return item
