"""Integration-level tests for the shared admission boundary in
BaseCollector._filter_and_save_articles (plan 034, Step 3).

These verify the plan's own Step 3 acceptance criterion literally: a
rejected article must cause zero duplicate-lookup queries and zero
persistence calls, not merely "wasn't in the saved count."
"""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

from news_collector.collectors.base_collector import BaseCollector
from news_collector.config.settings import get_runtime_config

VALID_URL = "https://example.com/article"


class _MockCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {}


def _article_payload(**overrides) -> dict:
    payload = {
        "url": VALID_URL,
        "title": "A sufficiently long scientific headline",
        "summary": "",
        "content": "x" * 600,
        "source_id": "src-1",
        "source_name": "Source One",
        "category": "science",
        "published_date": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _collector() -> _MockCollector:
    collector = _MockCollector(logger_factory=MagicMock())
    collector.db_manager = MagicMock()
    collector.health_tracker = MagicMock()
    return collector


def test_title_too_short_causes_zero_duplicate_queries_and_zero_inserts():
    # CollectorArticleModel.title already enforces Field(min_length=10), same
    # as the default config min_title_length — so a title-length rejection
    # at this shared boundary is only reachable once an operator configures
    # a stricter minimum than 10 (the exact gap plan 034 closes: this
    # configuration used to have zero effect on the real save path).
    collector = _collector()
    base = get_runtime_config()
    stricter = dataclasses.replace(
        base,
        text_processing_config={**base.text_processing_config, "min_title_length": 20},
    )

    with patch(
        "news_collector.collectors.base_collector.get_runtime_config",
        return_value=stricter,
    ):
        saved = collector._filter_and_save_articles(
            "src-1", [_article_payload(title="Fifteen chars!!")]
        )

    assert saved == 0
    collector.db_manager.articles_exist.assert_not_called()
    collector.db_manager.save_articles_bulk.assert_not_called()
    collector.health_tracker.record_filter_rejection.assert_called_once_with(
        "src-1", "title_too_short"
    )


def test_content_too_short_causes_zero_duplicate_queries_and_zero_inserts():
    collector = _collector()
    saved = collector._filter_and_save_articles(
        "src-1", [_article_payload(content="x" * 100)]
    )

    assert saved == 0
    collector.db_manager.articles_exist.assert_not_called()
    collector.db_manager.save_articles_bulk.assert_not_called()
    collector.health_tracker.record_filter_rejection.assert_called_once_with(
        "src-1", "content_too_short"
    )


def test_valid_article_reaches_duplicate_check_and_save():
    collector = _collector()
    collector.db_manager.articles_exist.return_value = set()
    collector.db_manager.save_articles_bulk.return_value = 1

    saved = collector._filter_and_save_articles("src-1", [_article_payload()])

    assert saved == 1
    collector.db_manager.articles_exist.assert_called_once()
    collector.db_manager.save_articles_bulk.assert_called_once()


def test_summary_only_article_bypasses_content_length_at_the_shared_boundary():
    """The summary_only exception (STOP condition in plan 034) must survive
    centralization: a short-content, summary_only article must still reach
    save, not be rejected as content_too_short."""
    collector = _collector()
    collector.db_manager.articles_exist.return_value = set()
    collector.db_manager.save_articles_bulk.return_value = 1

    saved = collector._filter_and_save_articles(
        "src-1",
        [
            _article_payload(
                content="short summary content", content_mode="summary_only"
            )
        ],
    )

    assert saved == 1
    collector.health_tracker.record_filter_rejection.assert_not_called()
