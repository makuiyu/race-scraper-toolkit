"""Common spider scaffolding and the shared `RawEventItem` definition."""

from __future__ import annotations

from typing import Any

import scrapy
from scrapy.http import Response


class RawEventItem(scrapy.Item):
    """A loose Scrapy item that maps cleanly onto `racescraper.models.Event`.

    Spiders populate as many fields as the source exposes. Downstream pipelines
    score quality, normalize values, dedup against in-memory state, and finally
    export to JSON.
    """

    # Required
    source = scrapy.Field()
    source_id = scrapy.Field()
    source_url = scrapy.Field()
    name = scrapy.Field()
    race_start_date = scrapy.Field()

    # Optional descriptive fields
    name_en = scrapy.Field()
    event_type = scrapy.Field()
    country = scrapy.Field()
    city = scrapy.Field()
    province = scrapy.Field()
    race_end_date = scrapy.Field()
    registration_open_date = scrapy.Field()
    registration_close_date = scrapy.Field()
    lottery_date = scrapy.Field()
    result_date = scrapy.Field()
    official_url = scrapy.Field()
    registration_urls = scrapy.Field()
    distances = scrapy.Field()
    tags = scrapy.Field()
    series = scrapy.Field()
    event_status = scrapy.Field()
    raw_data = scrapy.Field()

    # Spider control flag (consumed by pipelines, not exported).
    _supplement_only = scrapy.Field()

    # Pipeline-populated fields.
    _quality_score = scrapy.Field()
    _needs_review = scrapy.Field()
    _match_confidence = scrapy.Field()
    _canonical_event_id = scrapy.Field()


class BaseRaceSpider(scrapy.Spider):
    """Base class for race-calendar spiders.

    Subclasses must set `source` and implement `start()` (async generator) plus
    callbacks that yield `RawEventItem`.
    """

    custom_settings: dict[bool | float | int | str | None, Any] | None = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 4,
        "ROBOTSTXT_OBEY": True,
    }

    source: str = ""  # subclasses must override

    def parse_event(self, response: Response) -> RawEventItem:
        raise NotImplementedError
