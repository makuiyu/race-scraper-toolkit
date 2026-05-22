"""Scrapy settings for the toolkit. No database — everything is in-memory or JSON."""

from __future__ import annotations

BOT_NAME = "racescraper"
SPIDER_MODULES = ["racescraper.spiders"]
NEWSPIDER_MODULE = "racescraper.spiders"

# Async pipelines/spiders require the asyncio reactor.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Default to respecting robots.txt; API-style spiders override in custom_settings.
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Pipeline order: quality filter → field normalization → dedup → JSON export.
# Each pipeline is independent and can be turned off via configure_settings().
ITEM_PIPELINES = {
    "racescraper.pipelines.quality.QualityPipeline": 100,
    "racescraper.pipelines.normalize.NormalizePipeline": 200,
    "racescraper.pipelines.exporter.JsonExporterPipeline": 400,
}

LOG_LEVEL = "INFO"
TELNETCONSOLE_ENABLED = False

# Output file consumed by JsonExporterPipeline. Override per-run via CLI.
OUTPUT_PATH: str | None = None
OUTPUT_LIMIT: int | None = None
