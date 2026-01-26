from unittest.mock import MagicMock, patch

import pytest
from news_collector.collectors.base_collector import BaseCollector
from news_collector.config.settings import TEXT_PROCESSING_CONFIG


class MockCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {}


@pytest.fixture
def collector():
    # Patch min_content_length to avoid needing huge strings
    with patch.dict(TEXT_PROCESSING_CONFIG, {"min_content_length": 0}):
        yield MockCollector(logger_factory=MagicMock())


def test_validation_default_threshold(collector):
    """Verify default threshold of 10 chars."""
    # Strict assumption: config default is 10
    assert TEXT_PROCESSING_CONFIG.get("min_title_length") == 10

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
    # Override config to 3 chars
    with patch.dict(TEXT_PROCESSING_CONFIG, {"min_title_length": 3}):
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
