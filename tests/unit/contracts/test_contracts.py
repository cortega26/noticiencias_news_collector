"""Unit tests for D1 contracts."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from news_collector.contracts.adapters import (
    adapt_article_to_export,
    adapt_to_scoring_input,
    adapt_to_validation_payload,
)
from news_collector.config.sources import ALL_SOURCES
from news_collector.contracts.export import ExportArticleModel, ExportContractV2
from news_collector.contracts.scoring import ScoringInputModel
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from pydantic import ValidationError
from sqlalchemy.orm import load_only


def test_export_contract_v2_valid():
    """Verify ExportContractV2 structure."""
    article = ExportArticleModel(
        id=1,
        title="Test",
        url="http://example.com",
        source_name="test_source",
        source_id="test_id",
        score=0.9,
    )
    contract = ExportContractV2(
        generated_at=datetime.now().isoformat(), article_count=1, articles=[article]
    )
    dump = contract.model_dump()
    assert dump["contract"] == "news_collector.export.v2"
    assert dump["articles"][0]["score"] == 0.9  # Alias checking


def test_adapt_article_to_export():
    """Verify ORM adapter for export."""
    mock_art = MagicMock()
    mock_art.id = 101
    mock_art.title = "Export Me"
    mock_art.url = "http://test.com/1"
    mock_art.source_name = "MockSource"
    mock_art.source_id = "mock_src_id"
    mock_art.final_score = 0.85
    mock_art.article_metadata = {"foo": "bar"}
    mock_art.published_date = datetime(2025, 1, 1)
    mock_art.published_at = None
    mock_art.collected_date = None
    mock_art.authors = []
    mock_art.score_components = {}
    mock_art.category = "tech"
    # Optional fields
    mock_art.summary = None
    mock_art.content = None
    mock_art.published_url = None

    model = adapt_article_to_export(mock_art)
    assert model.id == 101
    assert model.metadata["foo"] == "bar"
    assert model.score == 0.85


def test_adapt_article_to_export_handles_detached_saved_article(tmp_path):
    db = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "detached_export.db"}
    )
    payload = {
        "url": "https://contract-tests.example.com/article-1",
        "original_url": "https://contract-tests.example.com/article-1",
        "title": "Detached article export should remain stable",
        "summary": "A summary long enough for the collector contract to accept it.",
        "content": "Detached export content body for regression validation. " * 20,
        "source_id": "mit_news",
        "source_name": ALL_SOURCES["mit_news"]["name"],
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "authors": ["Regression Bot"],
        "language": "en",
        "word_count": 140,
        "reading_time_minutes": 1,
        "article_metadata": {
            "original_url": "https://contract-tests.example.com/article-1",
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    try:
        saved_article = db.save_article(payload)
        assert saved_article is not None

        model = adapt_article_to_export(saved_article)

        assert model.id == saved_article.id
        assert model.published_at is None
        assert model.published_url is None
        assert model.metadata["original_url"] == payload["article_metadata"]["original_url"]
        assert (
            model.metadata["processing_timestamp"]
            == payload["article_metadata"]["processing_timestamp"]
        )
    finally:
        db.close()


def test_adapt_article_to_export_handles_partially_loaded_detached_article(tmp_path):
    db = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "partial_export.db"}
    )
    payload = {
        "url": "https://contract-tests.example.com/article-2",
        "original_url": "https://contract-tests.example.com/article-2",
        "title": "Partially loaded detached article export remains stable",
        "summary": "Another summary long enough for the collector contract to accept it.",
        "content": "Partially loaded detached export content body. " * 20,
        "source_id": "mit_news",
        "source_name": ALL_SOURCES["mit_news"]["name"],
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "authors": ["Regression Bot"],
        "language": "en",
        "word_count": 140,
        "reading_time_minutes": 1,
        "article_metadata": {
            "original_url": "https://contract-tests.example.com/article-2",
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    try:
        saved_article = db.save_article(payload)
        assert saved_article is not None

        with db.get_session() as session:
            article = (
                session.query(Article)
                .options(
                    load_only(
                        Article.id,
                        Article.title,
                        Article.url,
                        Article.summary,
                        Article.content,
                        Article.source_name,
                        Article.source_id,
                        Article.published_date,
                    )
                )
                .filter(Article.id == saved_article.id)
                .one()
            )
            session.expunge(article)

        model = adapt_article_to_export(article)

        assert model.id == saved_article.id
        assert model.published_at is None
        assert model.published_url is None
        assert model.collected_date is None
        assert model.score is None
        assert model.metadata == {}
        assert model.authors == []
        assert model.components == {}
        assert model.category is None
    finally:
        db.close()


def test_scoring_input_model_validation():
    """Verify ScoringInputModel requires essential fields."""
    with pytest.raises(ValidationError):
        # We need to construct valid ArticleScoringData first, or pass invalid dict
        ScoringInputModel(article={})  # Missing required fields like id, title

    valid_data = {
        "id": 1,
        "title": "Test Scorer",
        "url": "http://scorer.com",
        "source_id": "s1",
        "article_metadata": {},
        "duplication_confidence": 0.0,
        "word_count": 100,
        "summary": None,
        "published_date": None,
        "collected_date": None,
        "peer_reviewed": None,
        "is_preprint": None,
        "doi": None,
        "journal": None,
        "content": None,
    }
    # Pydantic allows init via dict
    model = ScoringInputModel(article=valid_data)
    # ACCESS via attribute, not item
    assert model.article.title == "Test Scorer"


def test_adapt_to_scoring_input():
    """Verify adapter produces valid model."""
    mock_art = MagicMock()
    mock_art.id = 55
    mock_art.title = "Scoring Adapter"
    mock_art.url = "http://adapter.com"
    mock_art.source_id = "src_1"
    mock_art.article_metadata = {}
    mock_art.duplication_confidence = 0.1
    mock_art.word_count = 500
    # Add other required fields by TypedDict/Adapter logic
    mock_art.summary = "Summarized"
    mock_art.published_date = None
    mock_art.collected_date = None
    mock_art.peer_reviewed = False
    mock_art.is_preprint = False
    mock_art.doi = None
    mock_art.journal = None
    mock_art.content = "Some content"

    model = adapt_to_scoring_input(mock_art, {"credibility": 0.5})
    # ACCESS via attribute
    assert model.article.id == 55
    assert model.source_config["credibility"] == 0.5


def test_validation_payload_adapter():
    """Verify validation payload adapter."""
    mock_art = MagicMock()
    mock_art.to_dict.return_value = {
        "id": 1,
        "title": "Validation",
        "url": "http://val.com",
        "source_id": "src",
        "content": "Should be here",
    }
    mock_art.content = "Should be here"

    payload = adapt_to_validation_payload([mock_art])
    assert len(payload.articles) == 1
    assert payload.articles[0].content == "Should be here"
