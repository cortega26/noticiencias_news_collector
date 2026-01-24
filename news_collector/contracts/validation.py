"""Contracts for validation requests."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict


class ArticleValidationItem(BaseModel):
    """
    Representation of an article to be validated.

    Combines ORM fields (via to_dict) with explicit content content.
    """

    id: int
    title: str
    summary: str | None = None
    content: str | None = None
    # to_dict fields - we make them optional or Dict[str, Any] allows widely
    # But since validator accesses them, well... validator mostly uses content/title/summary.
    # We will use extra="allow" to pass through the full to_dict() payload.

    model_config = ConfigDict(extra="allow")


class ArticleValidationPayload(BaseModel):
    """
    Batch payload for validation.
    """

    articles: List[ArticleValidationItem]
