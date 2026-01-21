import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from news_collector.contracts import CollectorArticleModel, ArticleMetadataModel

def test_article_metadata_model_validation():
    """Verify ArticleMetadataModel invariants."""
    # Invalid credibility score
    with pytest.raises(ValidationError):
        ArticleMetadataModel(
            source_metadata={},
            credibility_score=1.5 # Must be <= 1.0
        )
    
    # Valid
    valid = ArticleMetadataModel(
        source_metadata={"id": "123"},
        credibility_score=0.8,
        original_url="https://valid.com"
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
        content="Long content " * 100, # > 1000 chars
        summary="Summary of enough length used to pass the validation check which enforces fifty chars.",
        word_count=100,
        reading_time_minutes=1,
        # Explicitly provide required fields or ensure defaults work
        authors=["Test Author"],
        language="en"
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
            reading_time_minutes=1
        )
    assert "Article too short" in str(exc.value)
