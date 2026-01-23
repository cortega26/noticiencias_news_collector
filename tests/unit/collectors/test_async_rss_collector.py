from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_collector.collectors.async_rss_collector import AsyncRSSCollector


@pytest.fixture
def async_collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        logger_mock = MagicMock()
        return AsyncRSSCollector(logger_factory=logger_mock)


@pytest.mark.asyncio
async def test_fetch_feed_async(async_collector):
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<rss></rss>"
        mock_resp.text = "<rss></rss>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        # We need to mock the context manager structure of httpx.AsyncClient
        # Actually AsyncRSSCollector uses `async with httpx.AsyncClient(...) as client` inside methods?
        # No, _fetch_feed_async takes `client` as arg.
        # But collect_from_source_async creates it.

        # Test the internal method directly passing a mock client
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        content, status = await async_collector._fetch_feed_async(
            "s1", "http://feed.com", mock_client
        )
        assert status == 200
        assert content == "<rss></rss>"


@pytest.mark.asyncio
async def test_collect_async_flow(async_collector):
    # Mock internal fetch and parse
    # AsyncRSSCollector method is _collect_from_source_async_internal
    mock_res = {"success": True, "articles_found": 1, "articles_saved": 1}

    with patch.object(
        async_collector, "_collect_from_source_async_internal", new_callable=AsyncMock
    ) as mock_internal:
        mock_internal.return_value = mock_res

        # We also need to mock _extract_articles_from_feed if called?
        # But we mocked the whole internal method.

        res = await async_collector.collect_from_source_async(
            "s1", {"url": "http://f.com"}
        )
        assert res["success"] is True
