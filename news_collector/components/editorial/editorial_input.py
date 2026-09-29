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
            return cls._from_dict(raw_text, article_id)
        return cls._from_string(raw_text, article_id)

    @staticmethod
    def _text_field(raw: dict, key: str) -> str:
        return raw.get(key, "") or ""

    @staticmethod
    def _dict_article_id(raw: dict, article_id: str) -> str:
        if article_id != "unknown":
            return article_id
        return str(raw.get("id") or "unknown")

    @staticmethod
    def _source_url(raw: dict, metadata: dict) -> Optional[str]:
        entry_id = (metadata.get("source_metadata") or {}).get("entry_id")
        return raw.get("url") or metadata.get("original_url") or entry_id

    @classmethod
    def _from_dict(cls, raw: dict, article_id: str) -> "EditorialInput":
        content = cls._text_field(raw, "content")
        summary = cls._text_field(raw, "summary")
        # Fallback for RSS feeds where "content" is often in "summary"
        if not content and summary:
            content = summary
        metadata = raw.get("metadata") or {}
        return cls(
            article_id=cls._dict_article_id(raw, article_id),
            title=cls._text_field(raw, "title"),
            summary=summary,
            content=content,
            content_mode=raw.get("content_mode") or "full_text",
            image_url=raw.get("image_url"),
            image_alt=raw.get("image_alt"),
            source_id=raw.get("source_id"),
            source_name=raw.get("source_name"),
            source_url=cls._source_url(raw, metadata),
            raw_category=raw.get("category"),
            metadata_category=metadata.get("category"),
        )

    @classmethod
    def _from_string(cls, content: str, article_id: str) -> "EditorialInput":
        if article_id == "unknown":
            article_id = hashlib.sha256(content.encode()).hexdigest()[:8]
        return cls(
            article_id=article_id,
            title="",
            summary="",
            content=content,
            content_mode="full_text",
            image_url=None,
            image_alt=None,
            source_id=None,
            source_name=None,
            source_url=None,
            raw_category=None,
            metadata_category=None,
        )
