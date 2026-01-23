import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from news_collector.collectors.async_rss_collector import AsyncRSSCollector

# Tests regarding SSRF protection (P0 Vulnerability) - httpx version


# Tests regarding SSRF protection (P0 Vulnerability) - httpx version


def test_async_collector_blocks_private_ip():
    """
    Verify that AsyncRSSCollector blocks requests to private/loopback IPs.
    Now testing the httpx implementation.
    """

    async def _run_test():
        collector = AsyncRSSCollector()

        # Private IP examples
        unsafe_urls = [
            "http://127.0.0.1/feed.xml",
            "http://localhost:8080/rss",
            "http://169.254.169.254/metadata",
            "http://192.168.1.5/secret",
        ]

        # Mock access to avoid external calls context
        mock_client = MagicMock(spec=httpx.AsyncClient)

        # Context manager mock
        # async with client -> returns client
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Mock get response if it were called
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<rss>...</rss>"
        mock_response.content = b"<rss>...</rss>"
        mock_response.headers = {}

        mock_client.get = AsyncMock(return_value=mock_response)

        for url in unsafe_urls:

            # Real validation IS running in the code we wrote.
            # So passing 'http://127.0.0.1' to `_collect_from_source_async_internal`
            # SHOULD trigger the ValueError inside the try/except block.
            # And thus `client.get` should NEVER be called.

            stats = await collector._collect_from_source_async_internal(
                "test_source", {"url": url}, mock_client
            )

            # Assertions:
            # 1. client.get should NOT be called
            if mock_client.get.called:
                pytest.fail(f"VULNERABILITY: AsyncCollector fetched unsafe URL: {url}")
                mock_client.get.reset_mock()

            # 2. Stats should indicate error
            assert stats["success"] is False
            assert stats["error_message"] is not None
            assert (
                "SSRF" in stats["error_message"]
                or "Blocked" in stats["error_message"]
                or "Invalid URL" in stats["error_message"]
            )

    asyncio.run(_run_test())
