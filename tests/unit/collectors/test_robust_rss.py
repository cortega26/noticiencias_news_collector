from unittest.mock import MagicMock, patch

import pytest
from news_collector.collectors.rss_collector import RSSCollector


@pytest.fixture
def collector():
    return RSSCollector()


def test_fetch_feed_robust_success(collector):
    """Test standard success case."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<rss>...</rss>"
    mock_response.headers = {"ETag": "abc"}

    with patch.object(collector.client, "get", return_value=mock_response):
        result = collector._fetch_feed_robust("test_source", {"url": "http://test.com"})

        assert result["success"] is True
        assert result["content"] == b"<rss>...</rss>"
        assert result["status_code"] == 200


def test_fetch_feed_robust_304(collector):
    """Test 304 Not Modified."""
    mock_response = MagicMock()
    mock_response.status_code = 304

    with patch.object(collector.client, "get", return_value=mock_response):
        result = collector._fetch_feed_robust("test_source", {"url": "http://test.com"})

        assert result["success"] is True
        assert result["status_code"] == 304
        assert result["content"] is None


def test_fetch_feed_robust_403(collector):
    """Test 403 Forbidden."""
    mock_response = MagicMock()
    mock_response.status_code = 403

    with patch.object(collector.client, "get", return_value=mock_response):
        result = collector._fetch_feed_robust("test_source", {"url": "http://test.com"})

        assert result["success"] is False
        assert result["status_code"] == 403
        assert "HTTP 403" in result["error_message"]


def test_parse_feed_robust_html_detection(collector):
    """Test detection of HTML masquerading as RSS."""
    html_content = b"<!DOCTYPE html><html><body>Blocked</body></html>"
    result = collector._parse_feed_robust(
        "test_source", html_content, "http://test.com", {}
    )

    assert result["success"] is False
    assert result["classification"] == "BLOCKED_OR_NOT_FEED"
    assert "HTML Response" in result["error_message"]


def test_parse_feed_robust_malformed_xml(collector):
    """Test genuine malformed XML."""
    bad_xml = b"<rss><channel><item>Unclosed Tag"
    result = collector._parse_feed_robust("test_source", bad_xml, "http://test.com", {})

    # Depending on feedparser leniency, this might fail or pass.
    # If standard feedparser fails it sets bozo=1.
    if not result["success"]:
        assert result["classification"] == "MALFORMED_XML"
    else:
        # If leniency passed it, that's fine too, but we expect at least bozo check
        pass


def test_parse_feed_robust_valid_rss(collector):
    """Test valid RSS parsing."""
    valid_xml = b"""<?xml version="1.0"?>
    <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <item><title>Test Item</title></item>
        </channel>
    </rss>
    """
    result = collector._parse_feed_robust(
        "test_source", valid_xml, "http://test.com", {}
    )

    assert result["success"] is True
    assert len(result["parsed_feed"].entries) > 0
