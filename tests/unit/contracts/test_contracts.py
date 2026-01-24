"""Unit tests for D1 contracts."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from news_collector.contracts.export import ExportContractV1, ExportArticleModel
from news_collector.contracts.scoring import ScoringInputModel
from news_collector.contracts.validation import ArticleValidationPayload
from news_collector.contracts.adapters import (
    adapt_article_to_export,
    adapt_to_scoring_input,
    adapt_to_validation_payload
)

def test_export_contract_v1_valid():
    """Verify ExportContractV1 structure."""
    article = ExportArticleModel(
        id=1,
        title="Test",
        url="http://example.com",
        source_name="test_source",
        score=0.9
    )
    contract = ExportContractV1(
        generated_at=datetime.now().isoformat(),
        article_count=1,
        articles=[article]
    )
    dump = contract.model_dump()
    assert dump["contract"] == "news_collector.export.v1"
    assert dump["articles"][0]["score"] == 0.9  # Alias checking

def test_adapt_article_to_export():
    """Verify ORM adapter for export."""
    mock_art = MagicMock()
    mock_art.id = 101
    mock_art.title = "Export Me"
    mock_art.url = "http://test.com/1"
    mock_art.source_name = "MockSource"
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

def test_scoring_input_model_validation():
    """Verify ScoringInputModel requires essential fields."""
    with pytest.raises(ValidationError):
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
        "content": None
    }
    # It allows TypedDict construction
    model = ScoringInputModel(article=valid_data)
    assert model.article["title"] == "Test Scorer"

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
    assert model.article["id"] == 55
    assert model.source_config["credibility"] == 0.5

def test_validation_payload_adapter():
    """Verify validation payload adapter."""
    mock_art = MagicMock()
    mock_art.to_dict.return_value = {"id": 1, "title": "Validation"}
    mock_art.content = "Should be here"
    
    payload = adapt_to_validation_payload([mock_art])
    assert len(payload.articles) == 1
    assert payload.articles[0].content == "Should be here"
