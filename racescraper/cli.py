"""Command-line interface.

Subcommands:
    worldathletics  — run the WA spider for one season
    utmb            — run the UTMB spider for one year
    aims            — run the AIMS supplement-only spider
    dedupe          — run dedupe over an existing JSON dump
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import typer

from racescraper.pipelines.dedupe import dedupe_events
from racescraper.spiders import AimsSpider, UtmbSpider, WorldAthleticsSpider

app = typer.Typer(
    name="racescraper",
    help="A modular toolkit for scraping endurance race calendars.",
    no_args_is_help=True,
    add_completion=False,
)


def _run_spider(spider_cls: type, output: str, limit: int | None, **spider_kwargs: Any) -> None:
    """Run a single Scrapy spider with our pipeline stack and JSON output.

    Imported lazily so `python -m racescraper --help` doesn't need Scrapy's
    reactor to be installed cleanly.
    """
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    # Boot via the package's settings module.
    import os

    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "racescraper.settings")

    settings = get_project_settings()
    settings.set("OUTPUT_PATH", output, priority="cmdline")
    if limit:
        settings.set("OUTPUT_LIMIT", int(limit), priority="cmdline")

    # Configure logging so users get useful output even without a config file.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    process = CrawlerProcess(settings=settings)
    process.crawl(spider_cls, **spider_kwargs)
    process.start()


@app.command()
def worldathletics(
    year: int = typer.Option(..., "--year", help="Season year, e.g. 2026."),
    output: str = typer.Option(..., "--output", help="Path to write JSON output."),
    limit: int | None = typer.Option(None, "--limit", help="Cap exported items."),
) -> None:
    """Scrape the World Athletics Label Road Races calendar for one season."""
    _run_spider(WorldAthleticsSpider, output=output, limit=limit, year=year)


@app.command()
def utmb(
    year: int = typer.Option(..., "--year", help="Starting year; covers year..year+1."),
    output: str = typer.Option(..., "--output", help="Path to write JSON output."),
    limit: int | None = typer.Option(None, "--limit", help="Cap exported items."),
) -> None:
    """Scrape the UTMB public race-search API."""
    _run_spider(UtmbSpider, output=output, limit=limit, year=year)


@app.command()
def aims(
    output: str = typer.Option(..., "--output", help="Path to write JSON output."),
    limit: int | None = typer.Option(None, "--limit", help="Cap exported items."),
) -> None:
    """Scrape AIMS — supplement mode (does not create new canonical events)."""
    _run_spider(AimsSpider, output=output, limit=limit)


@app.command()
def dedupe(
    input_path: Path = typer.Option(..., "--input", help="JSON file of raw events."),
    output: Path = typer.Option(..., "--output", help="Where to write deduped JSON."),
) -> None:
    """Run the confidence-weighted dedupe over an existing JSON dump.

    Useful for combining multi-source outputs: scrape WA + UTMB + AIMS into
    separate files, concatenate them into one JSON array, then dedupe.
    """
    if not input_path.is_file():
        typer.echo(f"Input file not found: {input_path}", err=True)
        raise typer.Exit(code=1)

    raw_text = input_path.read_text(encoding="utf-8")
    try:
        items: list[dict[str, Any]] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        typer.echo(f"Invalid JSON in {input_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not isinstance(items, list):
        typer.echo("Expected a JSON array of event dicts.", err=True)
        raise typer.Exit(code=1)

    canonical = dedupe_events(items)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    typer.echo(
        f"Dedupe: {len(items)} raw -> {len(canonical)} canonical "
        f"(-{len(items) - len(canonical)}).",
        err=True,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``python -m racescraper``."""
    app(args=argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    main()
