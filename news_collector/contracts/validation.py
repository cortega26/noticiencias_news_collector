"""
Module role: Data Contract for Content Validation (D1 Phase 1), defining the payload structure exchanged between the System and the Validator.

Inputs:
- Raw or partially processed article data via ArticleValidationItem instantiation.
- Validation context dictionaries.

Outputs:
- Validated ArticleValidationPayload instances representing a batch of articles ready for validation.

Side effects:
- None. Purely defines data structures and validation schemas.

Invariants:
- LAW-1: Data Contracts Are Mandatory. This defines the rigid boundaries for validation.
- Extra fields on ArticleValidationItem are allowed to prevent validation errors on irrelevant data from raw dicts.
- Context dictionary must be isolated from article data.

Failure modes:
- Missing required fields (title, url, source_id) raises ValidationError.
- Improper data types for defined fields raises ValidationError.
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
