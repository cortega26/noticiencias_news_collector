import socket

import pytest

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
