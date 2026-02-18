"""Tests for Common Contracts."""

import pytest
from news_collector.contracts.common import ArticleMetadataModel
from pydantic import ValidationError


def test_article_metadata_valid():
    """Verify valid metadata."""
    meta = ArticleMetadataModel(credibility_score=0.5, original_url="http://test.com")
    assert meta.credibility_score == 0.5


def test_article_metadata_invalid_score():
    """Verify credibility score range."""
    with pytest.raises(ValidationError):
        ArticleMetadataModel(credibility_score=1.5)


def test_article_metadata_invalid_url():
    """Verify url scheme."""
    with pytest.raises(ValidationError):
        ArticleMetadataModel(original_url="ftp://bad.com")


def test_ensure_original_url():
    """Verify fallback logic."""
    meta = ArticleMetadataModel()
    meta.ensure_original_url("http://fallback.com")
    assert meta.original_url == "http://fallback.com"


def test_dump_for_storage():
    """Verify serialization."""
    meta = ArticleMetadataModel(credibility_score=0.8)
    dump = meta.model_dump_for_storage()
    assert dump["credibility_score"] == 0.8
