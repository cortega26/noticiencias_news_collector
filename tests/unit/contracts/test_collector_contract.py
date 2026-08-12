"""Tests for Collector Article Contract."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.contracts.collector import CollectorArticleModel


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
        dump["url"] == "https://example.com/"
    )  # Canonicalized: http → https + trailing slash
    assert dump["article_metadata"]["credibility_score"] == 0.9


@pytest.mark.parametrize(
    "bad_word_count,expected",
    [
        (float("inf"), 0),
        (float("-inf"), 0),
        ("1e999", 0),
        (float("nan"), 0),
        ("not-a-number", 0),
        (None, 0),
        (-17, 0),
        ("", 0),
    ],
)
def test_word_count_sanitizer_clamps_all_non_finite(bad_word_count, expected):
    """±inf/1e999/NaN/negative/non-numeric word counts must not crash or leak."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "x" * 60,
        "published_date": datetime.now(timezone.utc),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": bad_word_count,
        "reading_time_minutes": 1,
        "content": "A" * 501,
    }
    model = CollectorArticleModel(**data)
    assert model.word_count == expected


@pytest.mark.parametrize(
    "bad_reading_time,expected",
    [
        (float("inf"), 1),
        (float("-inf"), 1),
        ("1e999", 1),
        (float("nan"), 1),
        ("not-a-number", 1),
        (None, 1),
        (-5, 1),
        (0, 1),
        ("", 1),
    ],
)
def test_reading_time_sanitizer_clamps_all_non_finite(bad_reading_time, expected):
    """±inf/1e999/NaN/negative/zero reading times must clamp to a safe minimum."""
    data = {
        "url": "http://example.com",
        "title": "Title sufficient length",
        "summary": "x" * 60,
        "published_date": datetime.now(timezone.utc),
        "source_id": "src_id",
        "source_name": "SrcName",
        "category": "category",
        "word_count": 10,
        "reading_time_minutes": bad_reading_time,
        "content": "A" * 501,
    }
    model = CollectorArticleModel(**data)
    assert model.reading_time_minutes == expected
