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

    def mock_handler(request):
        raise Exception("SSRF Bypass: Reached network transport!")

    transport = httpx.MockTransport(mock_handler)
    client.client._transport = transport

    for url in unsafe_urls:
        # SSRF validation happens via event_hooks BEFORE transport is called.
        with pytest.raises(ValueError):
            await client.get(url)


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

    def mock_handler(request):
        raise Exception("SSRF Bypass: Reached network transport!")

    transport = httpx.MockTransport(mock_handler)
    client.client._transport = transport

    for url in unsupported_urls:
        with pytest.raises(ValueError) as excinfo:
            await client.get(url)

        assert "Invalid URL scheme" in str(excinfo.value)


@pytest.mark.asyncio
async def test_ssrf_allows_public_https():
    """Verify public HTTPS URLs are allowed."""
    client = SmartHttpClient()

    def mock_handler(request):
        return httpx.Response(status_code=200, text="ok")

    transport = httpx.MockTransport(mock_handler)
    client.client._transport = transport

    response = await client.get("https://google.com")
    assert response.status_code == 200
