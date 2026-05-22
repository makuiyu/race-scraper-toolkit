"""Pydantic event schema shared across spiders, pipelines, and the CLI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Distance(BaseModel):
    """A single race within an event (events can host multiple distances)."""

    model_config = ConfigDict(extra="allow")

    label: str
    distance_km: float
    elevation_gain: float | None = None
    race_start_date: str | None = None
    points: int | None = None
    official_url: str | None = None
    sort_order: int | None = None


class Event(BaseModel):
    """A single endurance race event as emitted by a spider.

    Required fields mirror the original `RawEventItem`: a source identifier,
    a human-readable name, and a start date. Everything else is best-effort.
    """

    model_config = ConfigDict(extra="allow")

    # Required
    source: str
    source_id: str
    source_url: str | None = None
    name: str
    race_start_date: str  # YYYY-MM-DD

    # Optional descriptive fields
    name_en: str | None = None
    event_type: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2
    city: str | None = None
    province: str | None = None
    race_end_date: str | None = None
    registration_open_date: str | None = None
    registration_close_date: str | None = None
    lottery_date: str | None = None
    result_date: str | None = None
    official_url: str | None = None
    registration_urls: list[str] = Field(default_factory=list)
    distances: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    series: str | None = None
    event_status: str | None = None
    raw_data: dict[str, Any] | None = None

    # Spider control flag
    supplement_only: bool = Field(default=False, alias="_supplement_only")

    # Pipeline-populated fields
    quality_score: float | None = Field(default=None, alias="_quality_score")
    needs_review: bool | None = Field(default=None, alias="_needs_review")
    match_confidence: float | None = Field(default=None, alias="_match_confidence")
    canonical_event_id: str | None = Field(default=None, alias="_canonical_event_id")
