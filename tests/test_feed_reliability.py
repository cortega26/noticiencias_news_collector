from unittest.mock import MagicMock, patch

import pytest
from news_collector.collectors.rss_collector import RSSCollector


@pytest.fixture
def mock_session():
    with patch("requests.Session") as mock:
        yield mock


def test_fetch_feed_handles_404(mock_session):
    collector = RSSCollector()
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.content = b""
    # Requests `raise_for_status` only raises if status is 4xx/5xx
    # We should use a real requests.HTTPError or simulate it
    from requests.exceptions import HTTPError

    def raise_if_error():
        if 400 <= mock_response.status_code < 600:
            raise HTTPError(response=mock_response)

    mock_response.raise_for_status.side_effect = raise_if_error

    collector.session.get.return_value = mock_response

    content, status = collector._fetch_feed("test_source", "http://example.com/feed")
    assert content is None
    assert status == 404


def test_fetch_feed_handles_html_content_type(mock_session):
    # Simulate a 200 OK but with text/html content type
    collector = RSSCollector()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.content = b"<html><body>Not a feed</body></html>"
    mock_response.text = "<html><body>Not a feed</body></html>"
    mock_response.encoding = None
    # Ensure has no etag/last-modified to avoid extra logic branches if needed

    collector.session.get.return_value = mock_response

    # We expect it to log a warning but potentially return the content depending on strictness
    # The current implementation logs checking "suspicious content type"

    with patch.object(collector, "_emit_log") as mock_log:
        content, status = collector._fetch_feed(
            "test_source", "http://example.com/feed"
        )

        # Check if warning was emitted
        found_warning = False
        for call in mock_log.call_args_list:
            # Check args/kwargs for the specific warning code or message
            # call.args[1] is usually the event name if using _emit_log(level, event, ...)
            if (
                len(call.args) > 1
                and call.args[1] == "collector.feed.suspicious_content_type"
            ):
                found_warning = True
                break
        assert found_warning, "Should emit warning for HTML content type"


def test_fetch_feed_handles_410_gone(mock_session):
    # Regression test for Science feed issue
    collector = RSSCollector()
    mock_response = MagicMock()
    mock_response.status_code = 410
    mock_response.content = b""
    from requests.exceptions import HTTPError

    def raise_if_error():
        if 400 <= mock_response.status_code < 600:
            raise HTTPError(response=mock_response)

    mock_response.raise_for_status.side_effect = raise_if_error
    collector.session.get.return_value = mock_response

    content, status = collector._fetch_feed("test_source", "http://example.com/feed")
    assert content is None
    assert status == 410


def test_malformed_xml_handling():
    # Test that bozo bit handling prevents crashing
    collector = RSSCollector()

    # Malformed XML
    malformed_content = "<rss><channel><title>Test</title><item><title>Bad item</item></channel></rss>"  # Missing closing title

    # We mock feedparser.parse to return bozo=1
    with patch("feedparser.parse") as mock_parse:
        mock_entry = MagicMock()
        mock_entry.bozo = 1
        mock_entry.bozo_exception = Exception("Mismatched tag")
        mock_parse.return_value = mock_entry

        # We need to mock _fetch_feed_robust to return this content
        with patch.object(
            collector, "_fetch_feed_robust", return_value={"success": True, "status_code": 200, "content": malformed_content.encode("utf-8"), "url": "http://foo"}
        ):
            stats = collector.collect_from_source(
                "test", {"url": "http://foo", "name": "Test"}
            )

            # Should have error message
            assert (
                "feed malformado" in stats["error_message"].lower()
                or "malformed" in stats["error_message"].lower()
            )
