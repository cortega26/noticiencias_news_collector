import socket

import httpx
import pytest

from news_collector.infrastructure.http_client import SmartHttpClient
from news_collector.infrastructure.requests_client import RobustRequestsClient


def test_robust_requests_client_blocks_redirects(monkeypatch):
    """
    Shows that SSRFSafeSession correctly intercepts 3xx redirects pointing to private IPs.
    """
    from requests import Response
    from requests.adapters import HTTPAdapter

    original_getaddrinfo = socket.getaddrinfo

    def mock_getaddrinfo(host, *args, **kwargs):
        if host == "safe.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
        elif host == "169.254.169.254":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
            ]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_send(self, request, **kwargs):
        if request.url == "http://safe.com/":
            resp = Response()
            resp.status_code = 302
            resp.headers["Location"] = "http://169.254.169.254/metadata"
            resp.url = request.url
            resp.request = request
            from io import BytesIO

            from urllib3.response import HTTPResponse

            resp.raw = HTTPResponse(body=BytesIO(b""), preload_content=False)
            return resp
        raise Exception("SSRF Bypass! Redirect was followed to network layer.")

    monkeypatch.setattr(HTTPAdapter, "send", mock_send)

    client = RobustRequestsClient()

    with pytest.raises(ValueError, match="SSRF Protection"):
        client.get("http://safe.com/")


@pytest.mark.asyncio
async def test_smart_http_client_blocks_redirects(monkeypatch):
    """
    Shows that SmartHttpClient (httpx) correctly intercepts 3xx redirects via event_hooks.
    """
    original_getaddrinfo = socket.getaddrinfo

    def mock_getaddrinfo(host, *args, **kwargs):
        if host == "safe.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
        elif host == "169.254.169.254":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
            ]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_handler(request):
        url_str = str(request.url)
        if url_str == "http://safe.com/":
            return httpx.Response(
                status_code=302,
                headers={"Location": "http://169.254.169.254/metadata"},
            )
        raise Exception(
            f"SSRF Bypass! Redirect to {url_str} was followed to network layer."
        )

    transport = httpx.MockTransport(mock_handler)

    async with SmartHttpClient() as client:
        # Inject the mock transport
        client.client._transport = transport

        with pytest.raises(ValueError, match="SSRF Protection"):
            await client.get("http://safe.com/")
