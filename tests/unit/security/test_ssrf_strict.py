from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from news_collector.infrastructure.http_client import SmartHttpClient


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
    ]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        for url in unsafe_urls:
            # SSRF validation happens BEFORE _get_with_retry, so it raises RequestError immediately without retrying.
            with pytest.raises((ValueError, httpx.RequestError)):
                await client.get(url)

            # Critical absolute proof: request dispatch MUST NEVER BE CALLED
            mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_ssrf_protection_rejects_unsupported_schemes():
    """
    REG-02: Verify that accessing non-http/https schemes raises an error immediately.
    """
    client = SmartHttpClient()

    unsupported_urls = [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://internal-service/1",
        "smb://fileserver/share",
    ]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        for url in unsupported_urls:
            with pytest.raises((ValueError, httpx.RequestError)) as excinfo:
                await client.get(url)

            assert "Invalid URL scheme" in str(excinfo.value)
            # Critical absolute proof: request dispatch MUST NEVER BE CALLED
            mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_ssrf_allows_public_https():
    """Verify public HTTPS URLs are allowed."""
    client = SmartHttpClient()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock(status_code=200)

        response = await client.get("https://google.com")
        assert response.status_code == 200
