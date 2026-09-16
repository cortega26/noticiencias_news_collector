"""Tests for Collector Article Contract."""

import copy
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


def test_collector_article_id_preserved_when_present():
    """Plan 077: export/DB identity survives validation (int and str)."""
    base = {
        "url": "http://example.com/foo",
        "title": "A very long title that meets the requirements",
        "summary": "Short summary",
        "content": "A" * 501,
        "source_id": "test_src",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime(2025, 1, 1),
    }
    assert CollectorArticleModel(**{**base, "id": 158}).id == 158
    assert CollectorArticleModel(**{**base, "id": "158"}).id == "158"
    assert CollectorArticleModel(**base).id is None


def test_adapt_export_payload_preserves_id():
    """Plan 077: the export->collector adapter no longer strips `id`."""
    from news_collector.contracts.adapters import (
        adapt_export_article_to_collector_payload,
    )

    out = adapt_export_article_to_collector_payload(
        {
            "id": 158,
            "title": "A very long title that meets the requirements",
            "url": "https://example.com/x",
            "summary": "s",
            "content": "c",
            "source_id": "nature",
            "source_name": "Nature",
            "category": "science",
            "published_date": "2026-01-01T00:00:00",
        }
    )
    assert out["id"] == 158


def _db_sourced_collector_payload(**metadata_extra):
    """Article 502 shape: valid content payload plus persisted run-scoped metadata."""
    return {
        "url": "http://example.com/audited-502",
        "title": "A very long title that meets the requirements",
        "summary": "Short summary",
        "content": "A" * 501,
        "source_id": "test_src",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime(2026, 9, 3, tzinfo=timezone.utc),
        "reading_time_minutes": 5,
        "word_count": 100,
        "article_metadata": {
            "source_metadata": {"source_id": "test_src"},
            "credibility_score": 0.9,
            **metadata_extra,
        },
    }


@pytest.mark.parametrize(
    "lifecycle_metadata",
    [
        {
            "audit": {
                "state": "passed",
                "reason": "",
                "updated_at": "2026-09-03T00:00:00+00:00",
            }
        },
        {
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "502",
                "pr_url": "https://github.com/org/repo/pull/1",
            }
        },
        {
            "audit": {
                "state": "passed",
                "reason": "",
                "updated_at": "2026-09-03T00:00:00+00:00",
            },
            "publication": {"state": "PR_CREATED", "refinery_id": "502"},
            "publishing_started_at": "2026-09-03T00:01:00+00:00",
            "publishing_branch": "content/update-example",
        },
    ],
)
def test_lifecycle_metadata_stripped_before_validation(lifecycle_metadata):
    """Plan 104: persisted audit/publication state must not fail the S1 guard."""
    from news_collector.contracts.adapters import strip_lifecycle_metadata

    payload = _db_sourced_collector_payload(**lifecycle_metadata)
    snapshot = copy.deepcopy(payload)

    cleaned = strip_lifecycle_metadata(payload)
    model = CollectorArticleModel.model_validate(cleaned)

    assert payload == snapshot  # persisted evidence untouched by validation
    dumped = model.model_dump()
    for key in lifecycle_metadata:
        assert key not in dumped["article_metadata"]
    assert dumped["article_metadata"]["credibility_score"] == 0.9
    assert dumped["article_metadata"]["source_metadata"] == {"source_id": "test_src"}


def test_lifecycle_keys_still_forbidden_without_strip():
    """Plan 104: schemas unchanged — raw lifecycle keys are still rejected."""
    payload = _db_sourced_collector_payload(
        audit={
            "state": "passed",
            "reason": "",
            "updated_at": "2026-09-03T00:00:00+00:00",
        }
    )
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel.model_validate(payload)
    assert "article_metadata.audit" in str(exc.value)


def test_unknown_metadata_key_still_rejected_after_strip():
    """Plan 104: the strip is a scalpel — genuinely unknown keys still fail."""
    from news_collector.contracts.adapters import strip_lifecycle_metadata

    payload = _db_sourced_collector_payload(bogus_key=1)
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel.model_validate(strip_lifecycle_metadata(payload))
    assert "bogus_key" in str(exc.value)
