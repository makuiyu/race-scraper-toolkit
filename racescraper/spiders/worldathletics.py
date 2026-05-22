"""World Athletics spider.

Technique: the calendar page is server-rendered Next.js. The entire event list
is embedded in the `<script id="__NEXT_DATA__">` blob, so a single HTTP request
gives us a structured JSON payload with no JS rendering. This is the toolkit's
signature trick — much faster and more robust than DOM scraping.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any

import scrapy
from scrapy.http import Response, TextResponse

from racescraper.spiders.base import BaseRaceSpider, RawEventItem

BASE_URL = (
    "https://worldathletics.org/competitions/world-athletics-label-road-races/calendar-results"
)

_LABEL_TAGS: dict[str, str] = {
    "Platinum": "Platinum Label",
    "Gold": "Gold Label",
    "Elite": "Elite Label",
    "Label": "Label",
}


def _default_seasons() -> list[int]:
    year = datetime.now(UTC).year
    return [year, year + 1]


def _infer_distance(name: str) -> list[dict[str, Any]]:
    lower = name.lower()
    if "half marathon" in lower or "21k" in lower or "21km" in lower:
        return [{"label": "Half Marathon", "distance_km": 21.0975, "elevation_gain": None}]
    if "marathon" in lower or "maratón" in lower or "maratona" in lower or "maraton" in lower:
        return [{"label": "Marathon", "distance_km": 42.195, "elevation_gain": None}]
    if "10k" in lower or "10 k" in lower or "10km" in lower:
        return [{"label": "10K", "distance_km": 10.0, "elevation_gain": None}]
    if "5k" in lower or "5 k" in lower:
        return [{"label": "5K", "distance_km": 5.0, "elevation_gain": None}]
    return []


def _infer_event_type(name: str) -> str:
    lower = name.lower()
    if "half" in lower:
        return "half_marathon"
    if "marathon" in lower or "maratón" in lower or "maratona" in lower or "maraton" in lower:
        return "marathon"
    return "other"


def _parse_venue(venue: str) -> tuple[str, str]:
    """`'Boston, MA (USA)'` -> `('Boston', 'USA')`."""
    m = re.match(r"^(.*?)\s*\(([A-Z]{2,3})\)\s*$", venue.strip())
    if m:
        return m.group(1).strip().split(",")[0].strip(), m.group(2)
    return venue, ""


class WorldAthleticsSpider(BaseRaceSpider):
    """Scrapes the World Athletics Label Road Races calendar."""

    name = "worldathletics"
    source = "worldathletics"
    allowed_domains: list[str] = ["worldathletics.org"]

    custom_settings: dict[bool | float | int | str | None, Any] | None = {
        **(BaseRaceSpider.custom_settings or {}),
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 2.0,
    }

    def __init__(self, year: int | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Allow CLI override: `-a year=2026`. Falls back to current + next year.
        self._seasons: list[int] = [int(year)] if year else _default_seasons()

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        for season in self._seasons:
            url = f"{BASE_URL}?season={season}"
            yield scrapy.Request(
                url,
                callback=self.parse_season,
                cb_kwargs={"season": season},
            )

    def parse_season(
        self, response: Response, season: int = 0, **kwargs: Any
    ) -> Generator[RawEventItem, None, None]:
        assert isinstance(response, TextResponse)

        # The signature trick: pull the SSR JSON straight out of the page.
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', response.text, re.DOTALL)
        if not m:
            self.logger.error("WorldAthletics: no __NEXT_DATA__ for season %s", season)
            return

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            self.logger.error("WorldAthletics: JSON parse error: %s", exc)
            return

        events = (
            data.get("props", {})
            .get("pageProps", {})
            .get("minisiteCalendarEvents", {})
            .get("results", [])
        )
        self.logger.info("WorldAthletics: %d events for season %s", len(events), season)

        for event in events:
            item = self._parse_event(event, url=response.url, season=season)
            if item:
                yield item

    def _parse_event(self, event: dict[str, Any], url: str, season: int) -> RawEventItem | None:
        """Parse one calendar entry. Example payload (Xiamen Marathon 2026)::

            {
                "id": 7235565,
                "name": "C&D Xiamen Marathon",
                "venue": "Xiamen (CHN)",
                "country": "CHN",
                "startDate": "2026-01-11",
                "endDate": "2026-01-11",
                "competitionSubgroup": "Platinum",
                ...
            }
        """
        name = (event.get("name") or "").strip()
        start_date = event.get("startDate") or ""
        end_date = event.get("endDate") or ""
        if not name or not start_date or start_date[:4] != str(season):
            return None

        # `country` is an IOC alpha-3 code; NormalizePipeline converts to ISO alpha-2.
        city, country = _parse_venue(event.get("venue") or "")
        country = event.get("country", "").strip() or country

        subgroup = event.get("competitionSubgroup") or "Label"
        label_tag = _LABEL_TAGS.get(subgroup, "Label")
        world_athletics_id = str(event.get("id", ""))
        source_url = f"{BASE_URL}?season={start_date[:4]}"

        item = RawEventItem()
        item["source"] = self.source
        item["source_id"] = world_athletics_id
        item["source_url"] = url or source_url
        item["name"] = name
        item["name_en"] = name
        item["series"] = "World Athletics Label Road Races"
        item["race_start_date"] = start_date
        if end_date and end_date != start_date:
            item["race_end_date"] = end_date
        item["city"] = city
        item["country"] = country
        item["event_type"] = _infer_event_type(name)
        item["official_url"] = None
        item["registration_urls"] = []
        item["distances"] = _infer_distance(name)
        item["tags"] = [label_tag, "World Athletics"]
        item["raw_data"] = {
            "world_athletics_id": world_athletics_id,
            "venue": event.get("venue"),
            "competitionSubgroup": subgroup,
            "rankingCategory": event.get("rankingCategory"),
            "disciplines": event.get("disciplines"),
            "endDate": event.get("endDate"),
        }
        return item
