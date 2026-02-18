"""Tests for Enrichment Contracts."""

import pytest
from news_collector.contracts.enrichment import (
    ArticleEnrichmentModel,
    ArticleForEnrichmentModel,
)
from pydantic import ValidationError


def test_article_for_enrichment_valid():
    """Verify input model."""
    model = ArticleForEnrichmentModel(title="Foo")
    assert model.title == "Foo"


def test_article_for_enrichment_invalid():
    """Verify empty input."""
    with pytest.raises(ValidationError):
        ArticleForEnrichmentModel()  # Everything empty


def test_enrichment_model_valid():
    """Verify enrichment payload."""
    model = ArticleEnrichmentModel(
        language="en",
        normalized_title="Foo",
        normalized_summary="Bar",
        entities=["A", "B"],
        topics=["T1"],
        sentiment="neutral",
        model_version="v1",
    )
    assert model.language == "en"


def test_enrichment_model_truncation():
    """Verify entities truncation."""
    entities = [str(i) for i in range(20)]
    model = ArticleEnrichmentModel(
        language="en",
        normalized_title="",
        normalized_summary="",
        entities=entities,
        topics=["T1"],
        sentiment="neutral",
        model_version="v1",
    )
    assert len(model.entities) == 10


def test_enrichment_model_invalid_sentiment():
    """Verify sentiment check."""
    with pytest.raises(ValidationError):
        ArticleEnrichmentModel(
            language="en",
            normalized_title="",
            normalized_summary="",
            sentiment="happy",  # Invalid
            model_version="v1",
        )
