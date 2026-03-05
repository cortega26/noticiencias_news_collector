"""CRIT-03: Boundary contract models MUST reject extra fields.

Every model marked as a boundary contract in the contracts layer is sealed
with ``extra="forbid"``.  These tests prove that:

1. Injecting an arbitrary extra field (``__admin_override__``) fails
   deterministically via ``ValidationError``.
2. A normal, valid payload still passes validation.
3. The adapter path (``adapt_to_validation_payload``) strips non-contract
   keys that arrive from ``Article.to_dict()``.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from news_collector.contracts.collector import CollectorArticleModel
from news_collector.contracts.common import ArticleMetadataModel
from news_collector.contracts.enrichment import (
    ArticleEnrichmentModel,
    ArticleForEnrichmentModel,
)
from news_collector.contracts.scoring import ScoringComponentsModel, ScoringRequestModel
from news_collector.contracts.validation import ArticleValidationItem


# ---------------------------------------------------------------------------
#  Helpers: minimal valid payloads per model
# ---------------------------------------------------------------------------

def _collector_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "url": "https://example.com/test",
        "title": "A Valid Title for Testing Purposes",
        "summary": "Valid summary " * 20,
        "content": "Content " * 100,
        "source_id": "test_source",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "authors": ["Author"],
        "language": "en",
        "word_count": 100,
        "reading_time_minutes": 5,
    }
    base.update(overrides)
    return base


def _enrichment_output_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "language": "en",
        "normalized_title": "Title",
        "normalized_summary": "Summary",
        "entities": ["A"],
        "topics": ["T"],
        "sentiment": "neutral",
        "model_version": "v1",
    }
    base.update(overrides)
    return base


def _scoring_components_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "source_credibility": 0.8,
        "recency": 0.9,
        "content_quality": 0.7,
        "engagement": 0.5,
    }
    base.update(overrides)
    return base


def _scoring_request_payload(**overrides: Any) -> Dict[str, Any]:
    comps = ScoringComponentsModel(**_scoring_components_payload())
    base: Dict[str, Any] = {
        "final_score": 0.8,
        "should_include": True,
        "components": comps,
    }
    base.update(overrides)
    return base


def _validation_item_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "title": "Test Article",
        "url": "https://example.com",
        "source_id": "test_src",
    }
    base.update(overrides)
    return base


def _metadata_payload(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "source_metadata": {},
        "credibility_score": 0.9,
        "original_url": "https://example.com/test",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
#  PARAMETRISED: extras MUST be rejected at every boundary model
# ---------------------------------------------------------------------------

_EXTRAS_POISON = {"__admin_override__": True}

BOUNDARY_MODELS = [
    ("CollectorArticleModel", CollectorArticleModel, _collector_payload),
    ("ArticleMetadataModel", ArticleMetadataModel, _metadata_payload),
    ("ArticleForEnrichmentModel", ArticleForEnrichmentModel, lambda **kw: {"title": "Foo", **kw}),
    ("ArticleEnrichmentModel", ArticleEnrichmentModel, _enrichment_output_payload),
    ("ArticleValidationItem", ArticleValidationItem, _validation_item_payload),
    ("ScoringComponentsModel", ScoringComponentsModel, _scoring_components_payload),
    ("ScoringRequestModel", ScoringRequestModel, _scoring_request_payload),
]


@pytest.mark.parametrize(
    "model_name, model_cls, payload_fn",
    BOUNDARY_MODELS,
    ids=[m[0] for m in BOUNDARY_MODELS],
)
class TestExtrasRejected:
    """Prove that injecting extra fields fails deterministically."""

    def test_extra_field_rejected(self, model_name, model_cls, payload_fn):
        """Arbitrary extra key MUST raise ValidationError."""
        data = payload_fn(**_EXTRAS_POISON)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model_cls(**data)

    def test_valid_payload_accepted(self, model_name, model_cls, payload_fn):
        """Normal valid payload MUST still pass validation."""
        data = payload_fn()
        model = model_cls(**data)
        assert model is not None


# ---------------------------------------------------------------------------
#  Integration-ish: adapter path strips extras from Article.to_dict()
# ---------------------------------------------------------------------------

class TestAdapterBoundary:
    """Verify adapt_to_validation_payload strips non-contract keys."""

    def test_adapter_strips_extras_from_to_dict(self):
        """Article.to_dict() includes keys not on ArticleValidationItem;
        the adapter must filter them so the sealed model doesn't explode."""
        from news_collector.contracts.adapters import adapt_to_validation_payload

        # Build a fake ORM-like object whose to_dict() returns extra fields
        fake_article = SimpleNamespace(
            id=1,
            title="Test Title",
            url="https://example.com/test",
            summary="Test summary",
            source_id="src",
            source_name="Source",
            category="science",
            published_date=datetime.now(timezone.utc),
            published_at=None,
            published_url=None,
            final_score=0.75,
            is_preprint=False,
            doi=None,
            journal=None,
            score_components={},
            content="Full text content here",
        )
        fake_article.to_dict = lambda: {
            "id": fake_article.id,
            "title": fake_article.title,
            "url": fake_article.url,
            "summary": fake_article.summary,
            "source_id": fake_article.source_id,
            "source_name": fake_article.source_name,
            "category": fake_article.category,
            "published_date": (
                fake_article.published_date.isoformat()
                if fake_article.published_date
                else None
            ),
            "published_at": None,
            "published_url": None,
            "final_score": 0.75,
            "is_preprint": False,
            "doi": None,
            "journal": None,
            "components": {},
        }

        # This MUST succeed — the adapter filters out the extras
        payload = adapt_to_validation_payload([fake_article])
        assert len(payload.articles) == 1
        item = payload.articles[0]
        assert item.title == "Test Title"
        assert item.source_id == "src"
        # Verify extras were NOT stored
        assert not hasattr(item, "final_score")
        assert not hasattr(item, "components")

    def test_adapter_rejects_if_extras_not_stripped(self):
        """Direct construction with extra keys MUST fail."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ArticleValidationItem(
                title="Test",
                url="https://example.com",
                source_id="src",
                final_score=0.5,  # Extra!
            )
