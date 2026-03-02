from datetime import date, datetime, timezone

import pytest
from news_collector.contracts import ArticleMetadataModel, CollectorArticleModel
from pydantic import ValidationError


def test_article_metadata_model_validation():
    """Verify ArticleMetadataModel invariants."""
    # Invalid credibility score
    with pytest.raises(ValidationError):
        ArticleMetadataModel(
            source_metadata={}, credibility_score=1.5  # Must be <= 1.0
        )

    # Valid
    valid = ArticleMetadataModel(
        source_metadata={"id": "123"},
        credibility_score=0.8,
        original_url="https://valid.com",
    )
    assert valid.credibility_score == 0.8


def test_collector_article_model_timezones():
    """Verify published_date is converted to UTC."""
    # Create with naive datetime (should fail or warn? Schema says it raises TypeError if not datetime, validator fixes tz)
    # Validator: if tzinfo is None -> replace(tzinfo=utc)

    naive = datetime(2026, 1, 1, 12, 0, 0)
    model = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/naive",
        source_id="source_id",
        source_name="Source Name",
        category="tech",
        published_date=naive,
        content="Long content " * 200,  # > 1000 chars
        summary="Summary " * 200,
        word_count=100,
        reading_time_minutes=1,
        # Explicitly provide required fields or ensure defaults work
        authors=["Test Author"],
        language="en",
    )

    assert model.published_date.tzinfo == timezone.utc
    assert model.published_date.year == 2026


def test_content_length_validation():
    """Verify minimum content length."""
    short = "Short"
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(
            title="Valid Title length > 10",
            url="https://example.com/short",
            source_id="source",
            source_name="Source",
            category="tech",
            published_date=datetime.now(timezone.utc),
            content=short,
            summary=short,
            word_count=1,
            reading_time_minutes=1,
        )
    assert "Article too short" in str(exc.value)


def test_published_date_type_error():
    """Ensure invalid date strings raise a clear validation error."""
    with pytest.raises(ValidationError, match="published_date has invalid ISO-8601 value"):
        CollectorArticleModel(
            title="Valid Title length > 10",
            url="https://example.com/bad-date",
            source_id="src",
            source_name="Source",
            category="gen",
            published_date="not-a-datetime",
            summary="Valid length " * 200,
            word_count=50,
            reading_time_minutes=1,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 1, 1, 12, 0),
            datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        (
            "2026-01-01T12:00:00Z",
            datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        (
            "2026-01-01T09:00:00-03:00",
            datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        (
            "2026-01-01",
            datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        ),
        (
            date(2026, 1, 1),
            datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        ),
        (
            1735689600,
            datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        ),
        (
            1735689600.0,
            datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        ),
        (
            1735689600000,
            datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_published_date_normalization(value, expected):
    model = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/date-normalization",
        source_id="src",
        source_name="Source",
        category="gen",
        published_date=value,
        summary="Valid length " * 200,
        word_count=50,
        reading_time_minutes=1,
    )
    assert model.published_date == expected
    assert model.published_date.tzinfo == timezone.utc


def test_published_date_none_rejected_with_clear_error():
    with pytest.raises(ValidationError, match="published_date is required and cannot be None"):
        CollectorArticleModel(
            title="Valid Title length > 10",
            url="https://example.com/bad-none-date",
            source_id="src",
            source_name="Source",
            category="gen",
            published_date=None,
            summary="Valid length " * 200,
            word_count=50,
            reading_time_minutes=1,
        )


def test_authors_normalization():
    """Ensure authors list is normalized and generic names filtered."""
    # Test None input
    model_none = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/none-author",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=50,
        reading_time_minutes=1,
        authors=None,  # Should convert to empty list
    )
    assert model_none.authors == []

    # Test generic names filtering
    model_filtered = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/filtered",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=50,
        reading_time_minutes=1,
        authors=["Admin", "Real Author", "Staff"],
    )
    assert model_filtered.authors == ["Real Author"]

    # Test invalid type
    with pytest.raises(TypeError, match="must be a list of strings"):
        CollectorArticleModel(
            title="Valid Title length > 10",
            url="https://example.com/bad-author-type",
            source_id="src",
            source_name="Src",
            category="cat",
            published_date=datetime.now(timezone.utc),
            summary="Valid " * 200,
            word_count=50,
            reading_time_minutes=1,
            authors="Not a list",
        )


def test_language_validation():
    """Ensure language code validation."""
    # Test None -> default 'en'
    model_none = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/lang-none",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=50,
        reading_time_minutes=1,
        language=None,
    )
    assert model_none.language == "en"

    # Test invalid code
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(
            title="Valid Title length > 10",
            url="https://example.com/bad-lang",
            source_id="src",
            source_name="Src",
            category="cat",
            published_date=datetime.now(timezone.utc),
            summary="Valid " * 200,
            word_count=50,
            reading_time_minutes=1,
            language="invalid_code_123",  # Definitely Unsupported
        )
    assert "language must be one of" in str(exc.value)


def test_word_count_low_pass():
    """Ensure extremely low word count is accepted (pass)."""
    model = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/low-word",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=5,  # < 10, should pass logic check, but content validation needs length
        reading_time_minutes=1,
    )
    assert model.word_count == 5


def test_dump_original_url():
    """Ensure model_dump_for_storage handles original_url logic."""
    model = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/dump",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=100,
        reading_time_minutes=1,
        article_metadata={"original_url": "https://example.com/original"},
    )
    dump = model.model_dump_for_storage()
    assert dump["url"] == "https://example.com/dump"
    assert dump["original_url"] == "https://example.com/original"

    # Test when original_url is missing in metadata but present in model
    model2 = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/dump2",
        source_id="src",
        source_name="Src",
        category="cat",
        published_date=datetime.now(timezone.utc),
        summary="Valid " * 200,
        word_count=100,
        reading_time_minutes=1,
    )
    # Validator sets original_url = url if missing
    dump2 = model2.model_dump_for_storage()
    assert dump2["original_url"] == "https://example.com/dump2"
