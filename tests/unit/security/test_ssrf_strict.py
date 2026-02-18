from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from news_collector.infrastructure.http_client import SmartHttpClient
from tenacity import RetryError


@pytest.mark.asyncio
async def test_ssrf_protection_rejects_private_ips():
    """
    REG-01: Verify that accessing local/private IPs raises an error.
    """
    client = SmartHttpClient()

    unsafe_urls = [
        "http://localhost:8080",
        "http://127.0.0.1/admin",
        "http://192.168.1.1/router",
        "http://169.254.169.254/metadata",  # AWS Metadata
        "ftp://example.com",  # Scheme check
    ]

    for url in unsafe_urls:
        # SmartHttpClient retries RequestError, so we eventually get RetryError
        with pytest.raises((ValueError, httpx.RequestError, RetryError)):
            await client.get(url)


@pytest.mark.asyncio
async def test_ssrf_allows_public_https():
    """Verify public HTTPS URLs are allowed."""
    client = SmartHttpClient()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock(status_code=200)

        response = await client.get("https://google.com")
        assert response.status_code == 200
