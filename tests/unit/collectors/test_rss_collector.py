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
        patch.object(
            rss_collector,
            "_fetch_feed_robust",
            return_value={
                "success": True,
                "status_code": 200,
                "content": b"xml-content",
                "url": "http://feed.com",
            },
        ),
    ):

        mock_parse.return_value.entries = []
        mock_parse.return_value.bozo = False

        articles = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "RSS"}
        )
        assert isinstance(articles, dict)
        mock_parse.assert_called_with(b"xml-content")


def test_extract_articles_recency_filter_skips_non_datetime(rss_collector):
    """The recency filter must not crash when a candidate carries a
    non-datetime published_date (e.g. a string from a future source), and
    must drop candidates older than the recency window."""
    from datetime import timedelta, timezone

    recent = datetime.now(timezone.utc)
    old = recent - timedelta(days=400)
    candidates = [
        {
            "title": "Old article title that is long enough",
            "url": "https://old.example.com/a",
            "published_date": old,
            "summary": "s" * 60,
        },
        {
            "title": "Fresh article title that is long enough",
            "url": "https://fresh.example.com/b",
            "published_date": recent,
            "summary": "s" * 60,
        },
        {
            "title": "String-date article title that is long enough",
            "url": "https://str.example.com/c",
            "published_date": "2024-01-01T00:00:00Z",
            "summary": "s" * 60,
        },
    ]

    parser_mock = MagicMock()
    parser_mock.extract_items.return_value = candidates
    rss_collector.parser = parser_mock
    rss_collector.db_manager = MagicMock()
    rss_collector.db_manager.article_exists.return_value = False
    rss_collector.pre_scorer = MagicMock()
    rss_collector.pre_scorer.model_name = "ollama"

    from unittest.mock import patch as _patch

    with (
        _patch.object(
            rss_collector, "_process_article", return_value=None
        ) as mock_process,
        _patch.object(rss_collector, "router", MagicMock()),
        _patch.object(rss_collector, "image_extractor", MagicMock()),
    ):
        # Only the date filter path runs here; deep processing is stubbed.
        from news_collector.config.settings import refresh_runtime_config

        refresh_runtime_config()
        raw_articles = rss_collector._extract_articles_from_feed(
            MagicMock(), {"url": "http://feed.com"}, "s1"
        )
        urls = [a["url"] for a in raw_articles]
        # Old item dropped by the recency gate; fresh + string-date kept
        # (string date is not compared, so it passes rather than crashing).
        assert "https://old.example.com/a" not in urls
        assert "https://fresh.example.com/b" in urls
        assert "https://str.example.com/c" in urls


def test_parse_success_records_article_count_as_found(rss_collector):
    """FOUND column must count parsed articles, not the implicit count-1
    (regression for the FOUND/SAVED mislabeling, plans ledger #248)."""
    from news_collector.diagnostics import SourceHealthTracker

    tracker = SourceHealthTracker()
    candidates = [
        {
            "title": f"Title {i} is long enough",
            "url": f"http://feed.com/{i}",
            "summary": "Summary",
            "published_date": datetime(2026, 8, 1, 12, 0, 0),
        }
        for i in range(3)
    ]

    with (
        patch.object(
            rss_collector,
            "_fetch_feed_robust",
            return_value={
                "success": True,
                "status_code": 200,
                "content": b"xml-content",
                "url": "http://feed.com",
            },
        ),
        patch.object(
            rss_collector,
            "_parse_feed_robust",
            return_value={"success": True, "parsed_feed": object()},
        ),
        patch.object(rss_collector.parser, "extract_items", return_value=candidates),
        # The router must not reach the network: this test only asserts the
        # FOUND/parse count, not enrichment behavior (real HTTP to feed.com
        # made this order-dependent under pytest-randomly).
        patch.object(
            rss_collector,
            "router",
            MagicMock(route_enrichment=lambda *a, **k: {}),
        ),
    ):
        rss_collector.health_tracker = tracker
        rss_collector.db_manager.article_exists.return_value = False
        rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "RSS"}
        )

    source = tracker.get_source("s1")
    assert source.parsed_ok == 3
