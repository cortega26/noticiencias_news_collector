from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from news_collector.collectors.rss_collector import RSSCollector


@pytest.fixture
def collector():
    logger_factory = MagicMock()
    return RSSCollector(logger_factory=logger_factory)


def test_rss_collector_image_fallback_to_dom(collector):
    long_content = "Content " * 200
    collector.router = MagicMock()
    collector.router.route_enrichment.return_value = {
        "success": True,
        "content": "Long enough summary to pass validation for testing",
        "raw_content": """
        <html>
            <meta property="og:image" content="https://example.com/og_extracted.jpg" />
            <body><article><p>{long_content}</p></article></body>
        </html>
        """,
        "strategy_used": "http",
    }

    # Mock source config
    source_config = {
        "name": "Test Source",
        "url": "https://example.com/rss",
        "category": "Tech",
        "credibility_score": 1.0,
    }
    source_id = "test_src"

    # Mock mocks
    collector.parser.extract_items = MagicMock(
        return_value=[
            {
                "title": "Test Article",
                "url": "https://example.com/article",
                "original_url": "https://example.com/article",
                "published_date": datetime.now(timezone.utc),
                "image_url": None,
                "source_metadata": {},
                "summary": "Long enough summary to pass validation for testing",
            }
        ]
    )

    collector.pre_scorer.select_top_candidates = MagicMock(side_effect=lambda x, **k: x)

    # Mock DB manager
    collector.db_manager = MagicMock()
    collector.db_manager.article_exists.return_value = False
    collector.db_manager.save_articles.return_value = 1

    # Mock Session
    collector.session = MagicMock()  # Replace the whole session object
    collector.client.session = (
        collector.session
    )  # Ensure RobustRequestsClient uses the mock

    # 1. Feed Fetch Response
    feed_response = MagicMock()
    feed_response.status_code = 200
    feed_response.text = "<rss></rss>"  # Dummy, since we mocked extract_items
    feed_response.content = b"<rss></rss>"
    feed_response.headers = {"content-type": "application/rss+xml"}

    # 2. Article HTML Fetch Response (The detailed page)
    long_content = "Content " * 200  # 8 * 200 = 1600 chars
    article_response = MagicMock()
    article_response.status_code = 200
    article_response.text = f"""
    <html>
        <meta property="og:image" content="https://example.com/og_extracted.jpg" />
        <body><article><p>{long_content}</p></article></body>
    </html>
    """
    article_response.headers = {"Content-Type": "text/html"}

    # 3. Image Validation Head Request
    head_response = MagicMock()
    head_response.status_code = 200
    head_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": "10000",
    }

    # Setup side effects for session.get and session.head
    def get_side_effect(url, **kwargs):
        if url == "https://example.com/rss":
            return feed_response
        elif url == "https://example.com/article":
            return article_response
        return MagicMock(status_code=404)

    collector.session.get.side_effect = get_side_effect
    collector.session.head.return_value = head_response
    collector.image_extractor.session = (
        collector.session
    )  # Ensure it uses same mocked session

    # Mock _filter_and_save_articles to capture result
    collector._filter_and_save_articles = MagicMock(return_value=1)

    # execute
    collector.collect_from_source(source_id, source_config)
    print("DEBUG STATS:", collector.session_stats)
    print("DEBUG LOGGER:", collector.module_logger.mock_calls)

    # VERIFY
    assert collector._filter_and_save_articles.called
    args = collector._filter_and_save_articles.call_args[0]
    print("DEBUG ARGS[1]:", args[1])
    saved_articles = args[1]
    assert len(saved_articles) == 1
    article = saved_articles[0]

    # Note: image_url was removed from ArticleMetadataModel (CRIT-03: no extras).
    # Image tracking is done via image_status and image_source fields.
    assert article.article_metadata.image_status == "IMAGE_OK"
    assert article.article_metadata.image_source == "meta:og:image"


def test_rss_collector_image_missing_source(collector):
    long_content = "Content " * 200
    collector.router = MagicMock()
    collector.router.route_enrichment.return_value = {
        "success": True,
        "content": "Long enough summary to pass validation for testing",
        "raw_content": "<html><body>{long_content}</body></html>",
        "strategy_used": "http",
    }

    # Test case where neither feed nor HTML has image
    source_config = {
        "name": "Test Source",
        "url": "https://example.com/rss",
        "category": "Tech",
        "credibility_score": 1.0,
    }
    source_id = "test_src"

    # Mock mocks
    collector.parser.extract_items = MagicMock(
        return_value=[
            {
                "title": "No Image Article",
                "url": "https://example.com/no-image",
                "original_url": "https://example.com/no-image",
                "published_date": datetime.now(timezone.utc),
                "image_url": None,
                "source_metadata": {},
                "summary": "Long enough summary to pass validation for testing",
            }
        ]
    )
    collector.pre_scorer.select_top_candidates = MagicMock(side_effect=lambda x, **k: x)
    collector.db_manager = MagicMock()
    collector.db_manager.article_exists.return_value = False

    # Mock Session
    collector.session = MagicMock()
    collector.client.session = collector.session
    long_content = "Content " * 200
    feed_response = MagicMock(
        status_code=200,
        text="<rss></rss>",
        content=b"<rss></rss>",
        headers={"content-type": "xml"},
    )
    article_response = MagicMock(
        status_code=200,
        text=f"<html><body>{long_content}</body></html>",
        headers={"Content-Type": "text/html"},
    )

    collector.session.get.side_effect = lambda url, **k: (
        feed_response if "rss" in url else article_response
    )
    collector._filter_and_save_articles = MagicMock(return_value=1)

    collector.collect_from_source(source_id, source_config)

    args, _ = collector._filter_and_save_articles.call_args
    article = args[1][0]

    assert article.article_metadata.image_status == "IMAGE_MISSING_SOURCE"
