"""Durable, media-independent editorial checkpoint (plan 190).

The internal projection retains every AstroPost editorial validator while
explicitly allowing absent media. It is never a public publication document.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from news_collector.contracts.frontend_schema import AstroPost


class EditorialFrontmatter(AstroPost):
    """The existing publication contract with only its media gate deferred."""

    image: None = Field(default=None, exclude=True)  # type: ignore[assignment]
    image_alt: None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def ensure_alt_text_contract(self) -> "EditorialFrontmatter":
        # A draft has no image at all; assembly applies the original AstroPost
        # validator once actual media is supplied. All other inherited field
        # and model validators still run here, without fabricated media.
        return self


class EditorialDraft(BaseModel):
    """Validated editorial work that can be stored and assembled without LLMs.

    ``seal`` detects nested mutation as well as damaged persisted checkpoints;
    frozen Pydantic fields alone cannot protect the contents of mappings.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1, le=1)
    article_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    frontmatter: dict[str, JsonValue | date | datetime]
    source_id: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    critic_verdict: dict[str, JsonValue] | None = None
    grounding_notes: str = ""
    seal: str = ""

    @field_validator("frontmatter")
    @classmethod
    def _validate_editorial_frontmatter(cls, value: dict) -> dict:
        if "image" in value or "image_alt" in value:
            raise ValueError("EditorialDraft frontmatter must not contain media")
        validated = EditorialFrontmatter.model_validate(value)
        # JSON persistence changes native dates to strings. Restore the typed
        # date on load so YAML emits the same timestamp as fresh preparation.
        return {**value, "date": validated.date}

    def _content_seal(self) -> str:
        serialized = json.dumps(
            self.model_dump(mode="json", exclude={"seal"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _seal_validated_work(self) -> "EditorialDraft":
        expected = self._content_seal()
        if self.seal and self.seal != expected:
            raise ValueError("Editorial draft seal does not match its content")
        object.__setattr__(self, "seal", expected)
        return self

    def assert_sealed(self) -> None:
        """Fail explicitly if a caller mutated a nested checkpoint value."""
        if self.seal != self._content_seal():
            raise ValueError("Editorial draft seal does not match its content")

    @property
    def preview_markdown(self) -> str:
        """Internal slug/review preview; deliberately lacks publishable media."""
        self.assert_sealed()
        frontmatter = yaml.safe_dump(
            self.frontmatter,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=1000,
        ).strip()
        return f"---\n{frontmatter}\n---\n\n{self.content}"
