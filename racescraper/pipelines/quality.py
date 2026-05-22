"""Quality scoring pipeline.

Computes a 0..1 score from the presence of high-value fields. Items below
`DISCARD_THRESHOLD` are dropped outright; items below `REVIEW_THRESHOLD` are
flagged for human review but kept.
"""

from __future__ import annotations

import logging
from typing import Any

import scrapy

logger = logging.getLogger(__name__)

# Field weights sum to 1.0. The numbers were tuned for endurance race
# calendars where date, registration, and location are load-bearing.
FIELD_WEIGHTS: dict[str, float] = {
    "race_start_date": 0.25,
    "registration_close_date": 0.20,
    "official_url": 0.15,
    "city": 0.10,
    "country": 0.05,
    "distances": 0.10,
    "registration_urls": 0.10,
    "event_type": 0.05,
}

DISCARD_THRESHOLD = 0.40
REVIEW_THRESHOLD = 0.70


def score_item(item: dict[str, Any]) -> float:
    """Compute the quality score for one item. Public for testing."""
    return round(sum(weight for field, weight in FIELD_WEIGHTS.items() if item.get(field)), 2)


class QualityPipeline:
    """Scrapy pipeline wrapper around `score_item`."""

    def process_item(self, item: Any, spider: scrapy.Spider | None = None) -> Any:
        score = score_item(item)
        if score < DISCARD_THRESHOLD:
            logger.debug("Discarded (score=%.2f): %s", score, item.get("name", ""))
            raise scrapy.exceptions.DropItem(f"Quality score too low: {score:.2f}")

        item["_quality_score"] = score
        item["_needs_review"] = score < REVIEW_THRESHOLD
        return item
