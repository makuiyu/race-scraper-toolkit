"""AIMS spider — supplement-only.

Technique: AIMS publishes a static HTML calendar page with ~450 race links.
For each race we GET `/races/{id}.html` and extract the official URL plus
city/country. Unlike the WA and UTMB spiders, AIMS does *not* create new
canonical events. Every item is tagged with ``_supplement_only=True`` so the
dedupe step backfills `official_url` on already-known races and silently drops
anything that doesn't match.

Why a separate pattern? AIMS is high-trust (it's a sanctioning body) but its
data is sparse — typically just name, date, location, official URL. Treating
it as a primary source would litter the dataset with low-coverage entries.
Treating it as a supplement keeps the primary catalog clean while still
benefiting from AIMS's authoritative `official_url` field.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any

import scrapy
from scrapy.http import Response, TextResponse

from racescraper.spiders.base import BaseRaceSpider, RawEventItem

CALENDAR_URL = "https://aims-worldrunning.org/calendar.html"
BASE_URL = "https://aims-worldrunning.org"


def _fix_url(raw: str) -> str:
    """`'//www.msm.no'` -> `'https://www.msm.no'`."""
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def _extract_city(body: str) -> str:
    """Extract the city name from the contact-details block.

    Handles three common address formats:
      ``9020 Tromsdalen``   — postcode first (Norway/Hungary/etc.)
      ``Madrid 28039``      — city first (Spain/etc.)
      ``Chicago, IL 60606`` — US style with state code
    """
    start = body.find('id="race-contact-details"')
    if start < 0:
        return ""
    block = body[start : start + 1200]

    # Strip tags down to text lines.
    text = re.sub(r"<[^>]+>", "\n", block)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Address lines sit between the contact name and the T:/E:/www lines.
    address_lines: list[str] = []
    for line in lines:
        if re.match(r"^(T:|E:|www\.|http)", line, re.IGNORECASE):
            break
        if line not in ("Contact details",):
            address_lines.append(line)

    # Walk from the bottom up looking for the first postcode-bearing line.
    for line in reversed(address_lines):
        m = re.match(r"^([A-Za-z][A-Za-z\s\-\.\']+),\s+[A-Z]{2}\s+[\d\-]+$", line)
        if m:
            return m.group(1).strip()
        m = re.match(r"^\d{3,6}(?:\s*-\s*\d+)?\s+([A-Za-z].+)$", line)
        if m:
            return m.group(1).strip()
        m = re.match(r"^([A-Za-z][A-Za-z\s\-\.\']+)\s+\d{3,6}(?:\s*-\s*\d+)?$", line)
        if m:
            return m.group(1).strip()

    return ""


def _infer_event_type(name: str) -> str:
    lower = name.lower()
    if "half" in lower:
        return "half_marathon"
    if "marathon" in lower or "maratón" in lower or "maratona" in lower or "maraton" in lower:
        return "marathon"
    return "other"


class AimsSpider(BaseRaceSpider):
    """AIMS-certified race calendar. Supplement-only by design.

    Items emitted by this spider carry ``_supplement_only=True``. The dedupe
    pipeline uses them to backfill `official_url` (and other fields) on
    already-known races — it does *not* create new canonical events for AIMS
    items that fail to match.
    """

    name = "aims"
    source = "aims"
    allowed_domains: list[str] = ["aims-worldrunning.org", "www.aims-worldrunning.org"]

    custom_settings: dict[bool | float | int | str | None, Any] | None = {
        **(BaseRaceSpider.custom_settings or {}),
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_TIMES": 5,
    }

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        yield scrapy.Request(CALENDAR_URL, callback=self.parse_calendar)

    def parse_calendar(
        self, response: Response, **kwargs: Any
    ) -> Generator[scrapy.Request, None, None]:
        assert isinstance(response, TextResponse)
        links = response.css("a[href*='/races/']::attr(href)").getall()
        seen: set[str] = set()
        count = 0
        for link in links:
            if "/races/" in link and link.endswith(".html"):
                url = response.urljoin(link)
                if url not in seen:
                    seen.add(url)
                    count += 1
                    yield scrapy.Request(url, callback=self.parse_race)
        self.logger.info("AIMS: queuing %d race detail pages", count)

    def parse_race(self, response: Response, **kwargs: Any) -> Generator[RawEventItem, None, None]:
        assert isinstance(response, TextResponse)

        name = response.css("h1::text").get("").strip()
        if not name:
            return

        body = response.text
        forth_index = body.find("Forthcoming events")
        past_index = body.find("Past events")

        race_dates: list[str] = []

        _date_pattern = r'<time datetime="(\d{4}-\d{2}-\d{2})"'
        if forth_index >= 0:
            forth_end = past_index if past_index > forth_index else forth_index + 5000
            race_dates += re.findall(_date_pattern, body[forth_index:forth_end])

        if past_index >= 0:
            race_dates += re.findall(_date_pattern, body[past_index : past_index + 5000])

        current_year = datetime.now(UTC).year
        qualifying = [d for d in race_dates if int(d[:4]) in (current_year, current_year + 1)]
        if not qualifying:
            return

        web_m = re.search(r'class="web"><a href="([^"]+)"', body)
        official_url = _fix_url(web_m.group(1)) if web_m else None

        h2_text = response.css("h2::text").get("").strip()
        country_raw = ""
        if "|" in h2_text:
            candidate = h2_text.split("|")[0].strip()
            if candidate.isascii():
                country_raw = candidate

        city = _extract_city(body)

        aims_id_m = re.search(r"/races/(\d+)\.html", response.url)
        aims_id = aims_id_m.group(1) if aims_id_m else response.url

        for race_start_date in qualifying:
            item = RawEventItem()
            item["source"] = self.source
            item["source_id"] = f"{aims_id}-{race_start_date}"
            item["source_url"] = response.url
            item["name"] = name
            item["race_start_date"] = race_start_date
            item["country"] = country_raw
            item["city"] = city
            item["official_url"] = official_url
            item["registration_urls"] = [official_url] if official_url else []
            item["event_type"] = _infer_event_type(name)
            item["distances"] = []
            item["tags"] = ["AIMS"]
            item["raw_data"] = {"aims_id": aims_id, "h2": h2_text}
            # This is the signal that makes AIMS supplement-only.
            item["_supplement_only"] = True
            yield item
