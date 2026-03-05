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
- Extra fields on ArticleValidationItem are forbidden (LAW-1: fail-closed boundary).
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
    # CRIT-03: Forbid extra fields at boundary (LAW-1 compliance)
    model_config = ConfigDict(extra="forbid")


class ArticleValidationPayload(BaseModel):
    """
    Batch payload for the Content Validator.
    """

    articles: List[ArticleValidationItem]

    context: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")
