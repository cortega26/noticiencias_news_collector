"""Plan 120 Step 1: undated HTML articles quarantine instead of clock-stamping.

Regression lock: ``HtmlCollector._process_article_html`` must propagate
``None`` when the raw article carries no date, so that
``CollectorArticleModel._ensure_not_none`` rejects the item with an explicit
per-item ``collector.validate.error`` skip inside
``BaseCollector._filter_and_save_articles`` (deterministic, batch-safe)
instead of baking the collector's wall-clock time into ``published_date``.
"""

from unittest.mock import MagicMock, patch

import pydantic
import pytest

from news_collector.collectors.html_collector import HtmlCollector
from news_collector.contracts.collector import CollectorArticleModel

CONFIG = {"url": "https://example.com", "name": "Test Source", "category": "science"}


@pytest.fixture
def collector():
    with patch("news_collector.collectors.html_collector.get_runtime_config"):
        return HtmlCollector(logger_factory=MagicMock())


def _raw_undated():
    return {
        "title": "A sufficiently long undated article title",
        "url": "https://example.com/undated-article",
        "description": "A short description.",
        "content": "x" * 600,
    }


def test_missing_date_propagates_none_not_wall_clock(collector):
    """No ``date`` key -> ``published_date is None`` (never today's date)."""
    processed = collector._process_article_html(
        _raw_undated(), CONFIG, "test_source"
    )
    assert processed is not None
    assert processed["published_date"] is None


def test_empty_date_string_propagates_none(collector):
    """Falsy ``date`` values (\"\", None) also propagate as None."""
    for raw in (
        {**_raw_undated(), "date": ""},
        {**_raw_undated(), "date": None},
    ):
        processed = collector._process_article_html(raw, CONFIG, "test_source")
        assert processed is not None
        assert processed["published_date"] is None


def test_undated_dict_rejected_at_model_boundary():
    """None date is rejected by CollectorArticleModel (quarantine owner)."""
    payload = {
        "url": "https://example.com/undated-article",
        "title": "A sufficiently long undated article title",
        "summary": "A short description.",
        "content": "x" * 600,
        "source_id": "test_source",
        "source_name": "Test Source",
        "category": "science",
        "published_date": None,
    }
    with pytest.raises(pydantic.ValidationError) as exc_info:
        CollectorArticleModel(**payload)
    assert "published_date is required and cannot be None" in str(exc_info.value)


def test_undated_item_skips_per_item_without_crashing_batch(collector):
    """The batch survives an undated item: 0 saved, no exception raised."""
    undated = collector._process_article_html(_raw_undated(), CONFIG, "test_source")
    assert undated is not None
    # Must not raise: the per-item try/except in _filter_and_save_articles
    # converts the model rejection into a collector.validate.error skip.
    saved = collector._filter_and_save_articles("test_source", [undated], limit=5)
    assert saved == 0
