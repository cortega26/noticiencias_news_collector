import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from news_collector.infrastructure.http_client import SmartHttpClient


class TestSmartHttpClient(unittest.IsolatedAsyncioTestCase):
    async def test_smart_client_initialization(self):
        async with SmartHttpClient() as client:
            self.assertTrue(client.client.headers["User-Agent"])
            self.assertGreater(client.timeout, 0)

    async def test_smart_client_ssrf_check(self):
        # Setup
        with patch(
            "news_collector.infrastructure.http_client.validate_url_safety"
        ) as mock_validate:
            mock_validate.return_value = None  # Pass

            url = "https://example.com/feed"

            def mock_handler(request):
                return httpx.Response(status_code=200, text="ok")
            transport = httpx.MockTransport(mock_handler)

            async with SmartHttpClient() as client:
                client.client._transport = transport
                await client.get(url)

            # Verify SSRF was called
            mock_validate.assert_called_once_with(url)

    async def test_smart_client_blocks_unsafe_url(self):
        # Setup fail
        with patch(
            "news_collector.infrastructure.http_client.validate_url_safety"
        ) as mock_validate:
            mock_validate.side_effect = ValueError("Private IP")

            async with SmartHttpClient() as client:
                with self.assertRaises(ValueError) as cm:
                    await client.get("http://localhost:8080")

            self.assertIn("Private IP", str(cm.exception))

    async def test_smart_client_retry_logic(self):
        # We want to verify tenacity retries.
        # We need to mock httpx.AsyncClient.get but it's used inside the context manager

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # Fail 1
            mock_get.side_effect = [
                httpx.ConnectTimeout("Timeout 1"),
                httpx.ConnectTimeout("Timeout 2"),
                MagicMock(status_code=200, raise_for_status=lambda: None),
            ]

            with patch("news_collector.infrastructure.http_client.validate_url_safety"):
                async with SmartHttpClient() as client:
                    # Mock sleep to bypass delay
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        resp = await client.get("https://flaky.com")

            # It should have succeeded eventually
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
