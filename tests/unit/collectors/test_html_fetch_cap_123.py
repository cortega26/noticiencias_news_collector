"""Plan 123 step 6: HTML fetch byte cap (mirrors the RSS 10MB policy).

Over-limit bodies must fail fast as fetch failures — (None, 413) via the
existing caller handling — without decoding or parsing. Mocked HTTP, no
network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from news_collector.collectors.html_collector import (
    HTML_MAX_BODY_BYTES,
    HtmlCollector,
)


@pytest.fixture
def collector():
    with patch("news_collector.collectors.html_collector.get_runtime_config"):
        collector = HtmlCollector(logger_factory=MagicMock())
        collector.db_manager = MagicMock()
        collector.db_manager.get_source_feed_metadata.return_value = None
        return collector


def _client_mock(*responses):
    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    mock_client.get = AsyncMock(side_effect=list(responses))
    return mock_client


def test_cap_mirrors_rss_policy():
    assert HTML_MAX_BODY_BYTES == 10 * 1024 * 1024


@pytest.mark.asyncio
async def test_declared_content_length_over_limit_fails_fast(collector):
    """A lying-huge Content-Length rejects before decode (small body)."""
    resp = httpx.Response(
        200,
        headers={"Content-Length": str(HTML_MAX_BODY_BYTES + 1)},
        text="<html><body><p>tiny</p></body></html>",
    )
    with patch("httpx.AsyncClient", return_value=_client_mock(resp)):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news",
            "s",
            {"url": "https://example.com/news", "name": "N"},
        )
    assert (content, status) == (None, 413)


@pytest.mark.asyncio
async def test_actual_body_over_limit_fails(collector):
    """No (or honest) Content-Length: the buffered body cap still applies."""
    resp = httpx.Response(200, content=b"x" * (HTML_MAX_BODY_BYTES + 1))
    with patch("httpx.AsyncClient", return_value=_client_mock(resp)):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news",
            "s",
            {"url": "https://example.com/news", "name": "N"},
        )
    assert (content, status) == (None, 413)


@pytest.mark.asyncio
async def test_body_under_limit_still_fetched(collector):
    """The cap must not break the normal small-page path."""
    html = "<html><body><article><p>hello world</p></article></body></html>"
    resp = httpx.Response(200, headers={"Content-Length": str(len(html))}, text=html)
    with patch("httpx.AsyncClient", return_value=_client_mock(resp)):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news",
            "s",
            {"url": "https://example.com/news", "name": "N"},
        )
    assert status == 200
    assert content is not None and "hello world" in content
