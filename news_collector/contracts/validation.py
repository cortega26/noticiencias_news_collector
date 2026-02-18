"""
Data Contract for Content Validation (D1 Phase 1).

Defines the payload structure exchanged between the System and the Validator.
"""

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ArticleValidationItem(BaseModel):
    """
    Represents a single article candidate submitted for validation.
    """

    id: int | str | None = None  # Depending on stage (could be new or existing)
    title: str
    url: str
    content: str | None = None
    summary: str | None = None
    source_id: str
    published_date: Any | None = None
    # Allow extra fields passed from to_dict() to avoid validation errors on irrelevant fields
    model_config = ConfigDict(extra="allow")


class ArticleValidationPayload(BaseModel):
    """
    Batch payload for the Content Validator.
    """

    articles: List[ArticleValidationItem]

    context: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")
