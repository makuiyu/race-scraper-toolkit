"""JSON exporter pipeline.

Replaces the database writer from race-nexus. Buffers items in memory and
writes them out as a single JSON array on `close_spider` — to a file if
`OUTPUT_PATH` is set in settings, otherwise to stdout.

Honors an optional `OUTPUT_LIMIT` so the CLI's `--limit N` can cap output
without modifying every spider.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import scrapy

logger = logging.getLogger(__name__)


def _to_jsonable(item: Any) -> dict[str, Any]:
    """Convert a Scrapy item (or plain dict) to a JSON-serializable dict.

    Strips internal-only fields like `_supplement_only` so downstream tools
    don't see them.
    """
    raw = dict(item)
    # Keep the pipeline-derived metadata (it's useful for debugging) but drop
    # the control flag — that is purely a spider->pipeline signal.
    raw.pop("_supplement_only", None)
    return raw


class JsonExporterPipeline:
    """Buffer items and write JSON on spider close."""

    def __init__(self, output_path: str | None = None, output_limit: int | None = None) -> None:
        self._output_path = output_path
        self._output_limit = output_limit
        self._items: list[dict[str, Any]] = []

    @classmethod
    def from_crawler(cls, crawler: Any) -> "JsonExporterPipeline":
        return cls(
            output_path=crawler.settings.get("OUTPUT_PATH"),
            output_limit=crawler.settings.getint("OUTPUT_LIMIT") or None,
        )

    def open_spider(self, spider: scrapy.Spider | None = None) -> None:
        self._items = []

    def process_item(self, item: Any, spider: scrapy.Spider | None = None) -> Any:
        if self._output_limit and len(self._items) >= self._output_limit:
            # We don't drop the item — we just stop adding to the export
            # buffer. This keeps downstream pipelines unaffected.
            return item
        self._items.append(_to_jsonable(item))
        return item

    def close_spider(self, spider: scrapy.Spider | None = None) -> None:
        payload = json.dumps(self._items, ensure_ascii=False, indent=2, default=str)
        if self._output_path:
            path = Path(self._output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            logger.info("Wrote %d items to %s", len(self._items), path)
        else:
            sys.stdout.write(payload)
            sys.stdout.write("\n")
