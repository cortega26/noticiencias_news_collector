"""Tests for Collector Article Contract."""

from datetime import datetime, timezone

import pytest
from news_collector.contracts.collector import CollectorArticleModel
from pydantic import ValidationError


def test_collector_article_valid():
    """Verify valid collector payload."""
    data = {
        "url": "http://example.com/foo",
        "title": "A very long title that meets the requirements",
        "summary": "Short summary",
        "content": "A" * 501,  # Must be > 500 check config
        "source_id": "test_src",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime(2025, 1, 1),
        "reading_time_minutes": 5,
        "word_count": 100,
    }
    model = CollectorArticleModel(**data)
    assert model.language == "en"
    assert model.authors == []


def test_collector_article_invalid_lang():
    """Verify invalid language rejected."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "published_date": datetime.now(),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 1,
        "reading_time_minutes": 1,
        "language": "klingon",  # Invalid
        "content": "A" * 501,
    }
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(**data)
    assert "language" in str(exc.value)


def test_collector_article_authors_normalization():
    """Verify authors normalization."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "x" * 60,
        "published_date": datetime.now(),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 10,
        "reading_time_minutes": 1,
        "authors": ["Admin", "Real Person", "Staff"],
        "content": "A" * 501,
    }
    model = CollectorArticleModel(**data)
    assert model.authors == ["Real Person"]


def test_collector_article_empty_content():
    """Verify empty content check."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "   ",
        "content": "",
        "published_date": datetime.now(),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 0,
        "reading_time_minutes": 1,
    }
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(**data)
    assert "Article content/summary empty" in str(exc.value)


def test_collector_article_date_tz():
    """Verify timezone enforcement."""
    # Naive date
    dt = datetime(2025, 1, 1)
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "x" * 60,
        "published_date": dt,
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 10,
        "reading_time_minutes": 1,
        "content": "A" * 501,
    }
    model = CollectorArticleModel(**data)
    assert model.published_date.tzinfo == timezone.utc


def test_dump_for_storage():
    """Verify storage dump format."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "x" * 60,
        "published_date": datetime.now(timezone.utc),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 10,
        "reading_time_minutes": 1,
        "article_metadata": {
            "original_url": "http://orig.com",
            "credibility_score": 0.9,
        },
        "content": "A" * 501,
    }
    model = CollectorArticleModel(**data)
    dump = model.model_dump_for_storage()
    assert (
        dump["url"] == "http://example.com/"
    )  # Pydantic normalizes URL to include slash
    assert dump["article_metadata"]["credibility_score"] == 0.9
