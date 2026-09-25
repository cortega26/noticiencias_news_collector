"""
Module role: Normalized editorial input for `EditorAgent.process_article` —
the typed extraction of one article payload (dict or raw text) before category
resolution, HTML cleaning and the LLM stages.

Owns:
- EditorialInput.from_raw: field extraction and article_id derivation

Does NOT own:
- Category resolution (CategoryResolver)
- HTML cleaning and min-length validation (EditorAgent)
- Cache identity (editorial_stages.EditorialStage)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EditorialInput:
    """One article's normalized input fields."""

    article_id: str
    title: str
    summary: str
    content: str
    content_mode: str
    image_url: Optional[str]
    image_alt: Optional[str]
    source_id: Optional[str]
    source_name: Optional[str]
    source_url: Optional[str]
    raw_category: Optional[str]
    metadata_category: Optional[str]

    @classmethod
    def from_raw(
        cls, raw_text: str | dict, explicit_article_id: str | None = None
    ) -> "EditorialInput":
        """Extract the normalized fields from a dict payload or raw text.

        Verbatim move of the previous inline logic in `process_article`
        (plan 060 Phase 7c-1): same defaults, same source_url fallback chain,
        same article_id derivation (explicit → dict id → sha256 for strings).
        """
        article_id = explicit_article_id or "unknown"
        if isinstance(raw_text, dict):
            title = raw_text.get("title", "") or ""
            summary = raw_text.get("summary", "") or ""
            content = raw_text.get("content", "") or ""
            content_mode = raw_text.get("content_mode") or "full_text"

            # Fallback for RSS feeds where "content" is often in "summary"
            if not content and summary:
                content = summary

            metadata = raw_text.get("metadata") or {}
            image_url = raw_text.get("image_url")
            image_alt = raw_text.get("image_alt")
            source_id = raw_text.get("source_id")
            source_name = raw_text.get("source_name")
            source_url = (
                raw_text.get("url")
                or metadata.get("original_url")
                or (metadata.get("source_metadata") or {}).get("entry_id")
            )
            raw_category = raw_text.get("category")
            metadata_category = metadata.get("category")
            if article_id == "unknown":
                article_id = str(raw_text.get("id") or "unknown")
        else:
            content = raw_text
            if article_id == "unknown":
                article_id = hashlib.sha256(content.encode()).hexdigest()[:8]
            title = ""
            summary = ""
            content_mode = "full_text"
            image_url = None
            image_alt = None
            source_id = None
            source_name = None
            source_url = None
            raw_category = None
            metadata_category = None

        return cls(
            article_id=article_id,
            title=title,
            summary=summary,
            content=content,
            content_mode=content_mode,
            image_url=image_url,
            image_alt=image_alt,
            source_id=source_id,
            source_name=source_name,
            source_url=source_url,
            raw_category=raw_category,
            metadata_category=metadata_category,
        )
