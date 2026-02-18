from typing import Any

import pytest
from news_collector.contracts.collector import CollectorArticleModel
from pydantic import ValidationError


def test_contract_validates_short_content(mock_article_payload: dict[str, Any]):
    """Test that content below minimum length is rejected."""
    payload = mock_article_payload.copy()
    payload["content"] = "Too short"

    with pytest.raises(ValidationError) as excinfo:
        CollectorArticleModel.model_validate(payload)

    assert "Article too short" in str(excinfo.value)


def test_contract_sanitizes_generic_authors(mock_article_payload: dict[str, Any]):
    """Test that generic author names are filtered out."""
    payload = mock_article_payload.copy()
    payload["authors"] = ["Staff", "Admin", "Real Author"]

    model = CollectorArticleModel.model_validate(payload)
    assert model.authors == ["Real Author"]


def test_contract_handles_only_generic_authors(mock_article_payload: dict[str, Any]):
    """Test that if all authors are generic, we get an empty list."""
    payload = mock_article_payload.copy()
    payload["authors"] = ["Staff", "Editor"]

    model = CollectorArticleModel.model_validate(payload)
    assert model.authors == []


def test_contract_accepts_valid_payload(mock_article_payload: dict[str, Any]):
    """Test that a fully valid payload passes validation."""
    model = CollectorArticleModel.model_validate(mock_article_payload)
    assert model.title == mock_article_payload["title"]
