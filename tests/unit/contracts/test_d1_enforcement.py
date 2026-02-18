"""
Tests for D1 Phase 1 Data Contracts Enforcement.
Verifies that adapters produce strict Pydantic models and reject invalid data.
"""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from news_collector.contracts.adapters import (
    adapt_article_to_export,
    adapt_to_scoring_input,
    adapt_to_validation_payload,
)
from news_collector.contracts.scoring import ArticleScoringData, ScoringInputModel
from news_collector.contracts.validation import ArticleValidationPayload
from pydantic import ValidationError


class MockArticle:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.title = kwargs.get("title", "Test Article")
        self.summary = kwargs.get("summary", "Summary")
        self.url = kwargs.get("url", "http://example.com")
        self.published_date = kwargs.get("published_date", datetime.now(timezone.utc))
        self.collected_date = kwargs.get("collected_date", datetime.now(timezone.utc))
        self.source_id = kwargs.get("source_id", "test_source")
        self.source_name = kwargs.get("source_name", "Test Source")
        self.article_metadata = kwargs.get("article_metadata", {})
        self.peer_reviewed = kwargs.get("peer_reviewed", False)
        self.is_preprint = kwargs.get("is_preprint", False)
        self.doi = kwargs.get("doi")
        self.journal = kwargs.get("journal")
        self.content = kwargs.get("content", "Content")
        self.published_at = kwargs.get("published_at")
        self.published_url = kwargs.get("published_url")
        self.final_score = kwargs.get("final_score", 0.5)
        self.score_components = kwargs.get("score_components", {})
        self.authors = kwargs.get("authors", [])
        self.category = kwargs.get("category", "test")

        # Attribute simulation for random attrs
        self.duplication_confidence = 0.95
        self.word_count = 100

    def to_dict(self):
        return self.__dict__.copy()


def test_scoring_input_enforcement():
    """Verify adapt_to_scoring_input returns strict ScoringInputModel."""
    article = MockArticle(title="Strict Scoring")
    config = {"weight": 1.0}

    # 1. Successful adaptation
    model = adapt_to_scoring_input(article, config)
    assert isinstance(model, ScoringInputModel)
    assert isinstance(model.article, ArticleScoringData)  # strict model
    assert model.article.title == "Strict Scoring"
    assert model.source_config == config


def test_validation_payload_enforcement():
    """Verify adapt_to_validation_payload returns strict ArticleValidationPayload."""
    articles = [MockArticle(id=1, title="A"), MockArticle(id=2, title="B")]

    payload = adapt_to_validation_payload(articles)
    assert isinstance(payload, ArticleValidationPayload)
    assert len(payload.articles) == 2
    assert payload.articles[0].title == "A"


def test_export_contract_enforcement():
    """Verify adapt_article_to_export returns strict ExportArticleModel."""
    article = MockArticle(id=99, title="Export Me")

    export_model = adapt_article_to_export(article)
    assert export_model.id == 99
    assert export_model.title == "Export Me"


def test_scoring_data_validation_failure():
    """Verify that ScoreInputModel validation catches bad data."""
    # Create an article with missing required fields (e.g. title is None? but typed as str)
    # Since MockArticle provides defaults, we interpret 'None' as invalid for str fields
    # But adapt_article_to_scoring accesses .title.

    # Let's mock an object that returns None for title
    bad_article = Mock()
    bad_article.id = 1
    bad_article.title = None  # Invalid for str field
    bad_article.summary = "S"
    bad_article.url = "http://u"
    bad_article.published_date = None
    bad_article.collected_date = None
    bad_article.source_id = "s"
    bad_article.article_metadata = {}
    bad_article.content = "C"

    # Expect ValidationError when adapter tries to construct ArticleScoringData
    with pytest.raises(ValidationError) as exc:
        adapt_to_scoring_input(bad_article, {})

    assert "title" in str(exc.value)
