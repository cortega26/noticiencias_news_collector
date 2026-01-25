"""Contracts for data export."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExportArticleModel(BaseModel):
    """
    Normalized article representation for export.

    Matches the schema historically produced by system.export_latest_articles.
    """

    id: int
    title: str
    url: str
    summary: str | None = None
    content: str | None = None
    source_name: str
    published_date: str | None = None
    published_at: str | None = None
    published_url: str | None = None
    collected_date: str | None = None
    score: float | None = Field(
        default=None
    )  # Note: system.py maps final_score -> score. We'll handle mapping in adapter.
    image_url: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    authors: List[str] | None = None
    category: str | None = None
    components: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ExportContractV1(BaseModel):
    """
    Version 1 of the data export contract.

    Used by: system.export_latest_articles
    """

    schema_version: int = 1
    version: Literal["1.0"] = "1.0"
    generated_at: str
    contract: Literal["news_collector.export.v1"] = "news_collector.export.v1"
    article_count: int
    articles: List[ExportArticleModel]

    model_config = ConfigDict(extra="ignore")
