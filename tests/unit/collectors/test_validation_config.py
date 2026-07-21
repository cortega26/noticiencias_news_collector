import dataclasses
from unittest.mock import MagicMock, patch

import pytest
from news_collector.collectors.base_collector import BaseCollector
from news_collector.config.settings import get_runtime_config


class MockCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {}


def _snapshot_with_text_processing(**overrides):
    """Return the current live snapshot with text_processing_config overridden.

    _validate_article_data reads get_runtime_config() per call, so tests
    patch that accessor rather than mutating the deprecated by-value
    TEXT_PROCESSING_CONFIG shim (which no longer affects the deep-copied
    snapshot consumers actually read).
    """
    base = get_runtime_config()
    return dataclasses.replace(
        base,
        text_processing_config={**base.text_processing_config, **overrides},
    )


@pytest.fixture
def collector():
    return MockCollector(logger_factory=MagicMock())


def test_validation_default_threshold(collector):
    """Verify default threshold of 10 chars."""
    snapshot = _snapshot_with_text_processing(min_content_length=0)
    assert snapshot.text_processing_config.get("min_title_length") == 10

    with patch(
        "news_collector.collectors.base_collector.get_runtime_config",
        return_value=snapshot,
    ):
        # Too short
        assert (
            collector._validate_article_data(
                {"title": "Short", "url": "http://example.com", "content": "valid"}
            )
            is False
        )
        # Exact/Long enough
        assert (
            collector._validate_article_data(
                {
                    "title": "Long enough title",
                    "url": "http://example.com",
                    "content": "valid",
                }
            )
            is True
        )


def test_validation_config_override(collector):
    """Verify modifying config changes behavior."""
    snapshot = _snapshot_with_text_processing(min_content_length=0, min_title_length=3)
    with patch(
        "news_collector.collectors.base_collector.get_runtime_config",
        return_value=snapshot,
    ):
        # "Short" (5 chars) should now pass
        assert (
            collector._validate_article_data(
                {"title": "Short", "url": "http://example.com", "content": "valid"}
            )
            is True
        )

        # "Ab" (2 chars) should still fail
        assert (
            collector._validate_article_data(
                {"title": "Ab", "url": "http://example.com", "content": "valid"}
            )
            is False
        )
