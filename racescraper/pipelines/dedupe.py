"""Confidence-weighted dedupe.

The original race-nexus pipeline used a PostgreSQL trigram index (`pg_trgm`)
for name similarity and an SQL JOIN to score candidates against canonical
events already in the database. That worked great in a live system but isn't
useful for a portable toolkit. Here we keep **the exact same weighting** but
swap two things:

* `rapidfuzz.fuzz.WRatio` replaces `pg_trgm`'s `similarity()` for name
  comparison. It returns a 0..100 score that we normalize to 0..1.
* Candidate state lives in a plain Python dict keyed by canonical id, so the
  dedupe is purely in-memory and works on a single JSON dump.

Weighting (unchanged from the source project):

* name similarity      -> 40 %
* same city + same event_type -> 30 % (binary flag)
* date proximity within +/- 7 days -> 30 % (linear decay)

Match decisions:

* `>= AUTO_MERGE` (0.80): merge into the canonical event; backfill empty fields.
* `>= NEW_EVENT`  (0.60): probable match, but flag for review.
* `<  NEW_EVENT`         : treat as a new canonical event — unless the item
  is `_supplement_only=True`, in which case it is dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Any

import scrapy
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Weights — these must sum to 1.0.
WEIGHT_NAME_SIMILARITY = 0.4
WEIGHT_GEO_TYPE = 0.3
WEIGHT_DATE_PROXIMITY = 0.3

# Below this name-similarity score we don't even consider the pair a candidate.
# Same threshold as the original pg_trgm pipeline.
SIMILARITY_CANDIDATE_THRESHOLD = 0.5

# Date proximity window (days). Anything beyond this contributes 0.
DATE_PROXIMITY_DAYS = 7

# Confidence cutoffs.
CONFIDENCE_AUTO_MERGE = 0.80
CONFIDENCE_NEW_EVENT = 0.60


def _name_similarity(a: str, b: str) -> float:
    """Normalized 0..1 similarity between two names. Wraps `fuzz.WRatio`."""
    if not a or not b:
        return 0.0
    return fuzz.WRatio(a, b) / 100.0


def _date_proximity(a: str | None, b: str | None) -> float:
    """Linear decay over +/- 7 days; 0 outside the window or on parse errors."""
    if not a or not b:
        return 0.0
    try:
        da = date.fromisoformat(a)
        db = date.fromisoformat(b)
    except (ValueError, TypeError):
        return 0.0
    diff = abs((da - db).days)
    if diff > DATE_PROXIMITY_DAYS:
        return 0.0
    return 1.0 - diff / DATE_PROXIMITY_DAYS


def score_pair(item: dict[str, Any], candidate: dict[str, Any]) -> float:
    """Compute the 0..1 match confidence between two event dicts.

    Public for tests and demos. Returns 0 if name similarity is below
    `SIMILARITY_CANDIDATE_THRESHOLD` — keeps the scorer cheap to call across
    a full Cartesian product.
    """
    name_sim = _name_similarity(item.get("name", ""), candidate.get("name", ""))
    if name_sim < SIMILARITY_CANDIDATE_THRESHOLD:
        return 0.0

    score = name_sim * WEIGHT_NAME_SIMILARITY

    if (
        item.get("city")
        and candidate.get("city")
        and item.get("city") == candidate.get("city")
        and item.get("event_type") == candidate.get("event_type")
    ):
        score += WEIGHT_GEO_TYPE

    score += _date_proximity(
        item.get("race_start_date"), candidate.get("race_start_date")
    ) * WEIGHT_DATE_PROXIMITY

    return round(score, 4)


def dedupe_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse an iterable of raw events into canonical events.

    Iterates in order; each new event is scored against every canonical event
    seen so far. The highest-scoring canonical wins if its score crosses the
    `AUTO_MERGE` threshold; otherwise the event becomes a new canonical
    (unless `_supplement_only=True`, in which case it is dropped if no match
    was found).

    The merge step backfills empty fields on the canonical from the new item
    and unions list fields (`registration_urls`, `tags`).
    """
    canonical: list[dict[str, Any]] = []

    for item in events:
        best_idx = -1
        best_score = 0.0
        for idx, cand in enumerate(canonical):
            score = score_pair(item, cand)
            if score > best_score:
                best_score = score
                best_idx = idx

        item.setdefault("_match_confidence", best_score)
        item["_match_confidence"] = best_score

        is_supplement = bool(item.get("_supplement_only"))

        if best_idx >= 0 and best_score >= CONFIDENCE_AUTO_MERGE:
            _merge_into(canonical[best_idx], item)
        elif best_idx >= 0 and best_score >= CONFIDENCE_NEW_EVENT:
            # Probable match but uncertain — keep the new one but flag review,
            # unless it's a supplement (in which case still merge — supplements
            # are designed to backfill, not stand alone).
            if is_supplement:
                _merge_into(canonical[best_idx], item)
            else:
                item["_needs_review"] = True
                canonical.append(item)
        else:
            # Below the new-event threshold.
            if is_supplement:
                logger.debug(
                    "Dropping supplement-only item %r — no canonical match",
                    item.get("name"),
                )
                continue
            canonical.append(item)

    return canonical


def _merge_into(canonical: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Backfill empty scalar fields and union list fields. Identity fields
    (`name`, `race_start_date`, etc.) on the canonical are never overwritten.
    """
    for field in ("official_url", "name_en", "series"):
        value = incoming.get(field)
        if value and not canonical.get(field):
            canonical[field] = value

    for list_field in ("registration_urls", "tags"):
        existing = list(canonical.get(list_field) or [])
        new_values = incoming.get(list_field) or []
        for v in new_values:
            if v and v not in existing:
                existing.append(v)
        canonical[list_field] = existing


class DedupePipeline:
    """Scrapy pipeline wrapper around `dedupe_events`.

    Accumulates items as they pass through and emits the deduped batch on
    `close_spider`. Note: this means items are *not* flushed incrementally;
    that matches the in-memory design of this toolkit.
    """

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._deduped: list[dict[str, Any]] = []

    def open_spider(self, spider: scrapy.Spider | None = None) -> None:
        self._items = []

    def process_item(self, item: Any, spider: scrapy.Spider | None = None) -> Any:
        self._items.append(dict(item))
        return item

    def close_spider(self, spider: scrapy.Spider | None = None) -> None:
        self._deduped = dedupe_events(self._items)
        logger.info(
            "Dedupe: %d raw -> %d canonical (-%d)",
            len(self._items),
            len(self._deduped),
            len(self._items) - len(self._deduped),
        )

    @property
    def deduped(self) -> list[dict[str, Any]]:
        return self._deduped
