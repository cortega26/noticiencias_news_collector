from unittest.mock import MagicMock, patch

import pytest
from news_collector.collectors.rss_collector import RSSCollector


@pytest.fixture
def rss_collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        logger_mock = MagicMock()
        return RSSCollector(logger_factory=logger_mock)


from datetime import datetime


def test_parse_feed_entry(rss_collector):
    # RSSCollector delegates to parser. Test that integration or skip if unit testing parser separately.
    # We can check if _process_article works, which uses the dict.
    raw_article = {
        "title": "Title That Is Long Enough (>10 chars)",
        "url": "http://test.com",
        "summary": "Summary",
        "content": "Content " * 200,  # > 1000 chars
        "published_date": datetime(2025, 1, 1, 12, 0, 0),
    }
    enrichment_mock = {
        "language": "en",
        "topics": ["Science"],
        "sentiment": "neutral",
        "entities": [],
        "normalized_title": "Title",
        "normalized_summary": "Summary",
        "model_version": "v1",
    }
    with patch(
        "news_collector.collectors.rss_collector.enrichment_pipeline.enrich_article",
        return_value=enrichment_mock,
    ):
        processed = rss_collector._process_article(
            raw_article,
            "s1",
            {
                "name": "Src",
                "category": "general",
                "credibility_score": 1.0,
                "language": "en",
            },
        )
    assert processed is not None
    assert processed.title == "Title That Is Long Enough (>10 chars)"


def test_collect_sync_mock(rss_collector):
    with patch(
        "news_collector.collectors.rss_collector.feedparser.parse"
    ) as mock_parse:
        mock_parse.return_value.entries = []
        mock_parse.return_value.bozo = False

    with (
        patch("news_collector.collectors.rss_collector.feedparser.parse") as mock_parse,
        patch.object(rss_collector, "_fetch_feed", return_value=("xml-content", 200)),
    ):

        mock_parse.return_value.entries = []
        mock_parse.return_value.bozo = False

        articles = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "RSS"}
        )
        assert isinstance(articles, dict)
        mock_parse.assert_called_with("xml-content")
