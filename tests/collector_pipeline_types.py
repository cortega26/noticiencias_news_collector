from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class SourceFixture(TypedDict):
    id: str
    name: str
    url: str
    category: str
    credibility_score: float
    language: str


class CollectorRawMetadata(TypedDict, total=False):
    feed_title: str
    content: str
    doi: str | None


class CollectorRawFixture(TypedDict, total=False):
    url: str
    title: str
    summary: str
    authors: list[str]
    published_offset_hours: int
    published_date: datetime
    published_tz_offset_minutes: int
    published_tz_name: str
    original_url: str
    source_metadata: CollectorRawMetadata


class EnrichmentExpected(TypedDict):
    language: str
    sentiment: str
    topics: list[str]
    entities: list[str]


class ExpectedStorageFields(TypedDict):
    language: str
    category: str
    source_id: str


class ExpectedStorage(TypedDict):
    fields: ExpectedStorageFields
    final_score_min: float
    should_include: bool


class PipelineEntry(TypedDict):
    id: str
    source: SourceFixture
    collector_raw: CollectorRawFixture
    enrichment_expected: EnrichmentExpected
    expected_storage: ExpectedStorage
