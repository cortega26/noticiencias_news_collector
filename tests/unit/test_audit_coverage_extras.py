"""Coverage for HTTP/image helpers touched by the pipeline log audit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from news_collector.enrichment.http_enricher import HttpEnricher
from news_collector.infrastructure import requests_client as rc
from news_collector.logic.parsers.image_extractor import (
    ImageCandidate,
    ImageExtractor,
    is_site_logo_url,
)

# ---------------------------------------------------------------- image_extractor


def _resp(status=200, ctype="image/jpeg", length="90000"):
    r = MagicMock()
    r.status_code = status
    r.headers = {"Content-Type": ctype}
    if length is not None:
        r.headers["Content-Length"] = length
    return r


@pytest.fixture
def extractor():
    return ImageExtractor(session=MagicMock())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.org/a/biorxiv_logo_homepage.png", True),
        ("https://x.org/a/logo.svg?v=1", True),
        ("https://x.org/a/analogous.jpg", False),
        ("https://x.org/logos/photo.jpg", False),
    ],
)
def test_is_site_logo_url(url, expected):
    assert is_site_logo_url(url) is expected


def test_validate_image_variants(extractor):
    cand = ImageCandidate(url="https://x.org/i.jpg", source="t")
    s = extractor.session
    s.head.return_value = _resp()
    assert extractor.validate_image(cand) is True
    s.head.return_value = _resp(status=404)
    assert extractor.validate_image(cand) is False
    s.head.return_value = _resp(ctype="text/html")
    assert extractor.validate_image(cand) is False
    s.head.return_value = _resp(length="100")
    assert extractor.validate_image(cand) is False
    s.head.return_value = _resp(status=405)
    s.get.return_value = _resp()
    extractor.validate_image(cand)
    s.get.assert_called_once()
    s.head.side_effect = RuntimeError("boom")
    assert extractor.validate_image(cand) is False


def test_normalize_and_dimension_helpers(extractor):
    assert (
        extractor._normalize_url("/a.jpg", "https://x.org/p") == "https://x.org/a.jpg"
    )
    assert extractor._normalize_url("ftp://x.org/a.jpg", "https://x.org") is None
    assert extractor._normalize_url("a.jpg", "") is None
    assert extractor._parse_dimension("120px") == 120
    assert extractor._parse_dimension("abc") is None
    assert extractor._parse_dimension(None) is None
    assert extractor._is_blacklisted("https://x.org/tracker.gif") is True


def test_dom_extraction_filters_and_scores(extractor):
    html = """
    <html><body><article>
      <img data-src="/big.jpg" width="900" height="500">
      <img src="/small.jpg" width="50" height="50">
      <img src="/short.jpg" width="400" height="40">
      <img src="/brand.jpg" class="site logo" width="400" height="300">
      <img src="/branded.jpg" id="logo" width="400" height="300">
      <img src="/icon-x.png" width="400" height="300">
      <img src="/plain.jpg">
    </article></body></html>
    """
    urls = [c.url for c in extractor.extract_candidates(html, "https://x.org/p")]
    assert "https://x.org/big.jpg" in urls
    assert "https://x.org/plain.jpg" in urls
    for skipped in ("small", "short", "brand.", "branded", "icon-x"):
        assert not any(skipped in u for u in urls)
    assert extractor.extract_candidates("", "https://x.org") == []


# ------------------------------------------------------------------ http_enricher


class _Resp:
    def __init__(self, status=200, text="<p>hi</p>"):
        self.status_code = status
        self.text = text


class _Client:
    def __init__(self, result):
        self.result = result

    def get(self, url, timeout=15):  # noqa: ARG002
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_enricher_status_paths(monkeypatch):
    monkeypatch.delenv("NOTICIENCIAS_SMOKE", raising=False)
    forbidden = HttpEnricher(request_client=_Client(_Resp(403)))
    assert forbidden.enrich("https://a.org/x")["status_code"] == 403
    assert forbidden.enrich("https://a.org/x")["error"] == "HTTP 403"  # cached
    assert (
        HttpEnricher(request_client=_Client(_Resp(500))).enrich("https://a.org")[
            "error"
        ]
        == "HTTP 500"
    )
    ok = HttpEnricher(
        request_client=_Client(_Resp(200, "<p>hola</p><script>x</script>"))
    )
    assert ok.enrich("https://a.org")["content"] == "hola"
    boom = HttpEnricher(request_client=_Client(RuntimeError("x")))
    assert boom.enrich("https://a.org")["success"] is False


def test_www_fallback_is_skipped_when_not_applicable():
    ssl_err = requests.exceptions.SSLError("x")
    assert HttpEnricher._www_fallback_url("https://www.a.org/x", ssl_err) is None
    assert HttpEnricher._www_fallback_url("/relative", ssl_err) is None
    assert HttpEnricher._www_fallback_url("https://a.org", ValueError()) is None


def test_ssl_error_fallback_only_once():
    calls: list[str] = []

    class _AlwaysSSL:
        def get(self, url, timeout=15):  # noqa: ARG002
            calls.append(url)
            raise requests.exceptions.SSLError("bad")

    result = HttpEnricher(request_client=_AlwaysSSL()).enrich("https://a.org/x")
    assert calls == ["https://a.org/x", "https://www.a.org/x"]
    assert result["success"] is False


# ---------------------------------------------------------------- requests_client


def test_redact_headers_redacts_sensitive():
    assert rc._redact_headers(None) == {}
    out = rc._redact_headers({"Authorization": "x", "Accept": "y"})
    assert out == {"Authorization": "[REDACTED]", "Accept": "y"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, False), (404, False), (503, True), (429, True), (400, False)],
)
def test_is_retryable_by_status(status, expected):
    r = requests.Response()
    r.status_code = status
    assert rc._is_retryable_error(requests.HTTPError(response=r)) is expected
    assert rc._is_retryable_error(ValueError("x")) is False


def _client():
    c = rc.RobustRequestsClient(timeout=1.0)
    c._retry_sleep = lambda _s: None
    return c


def test_get_reraises_without_source_config():
    c = _client()
    with patch.object(c, "_execute_request", side_effect=requests.Timeout("t")):
        with pytest.raises(requests.Timeout):
            c.get("http://example.com")
    c.close()


def _proxy_manager(eligible=True, settings=None):
    pm = MagicMock()
    pm.should_retry_with_proxy.return_value = eligible
    pm.get_proxy_settings.return_value = settings
    return pm


def test_get_proxy_fallback_success_failure_and_ineligible():
    src = {"name": "s"}
    c = _client()
    direct = requests.Timeout("t")
    good = MagicMock()
    with patch("news_collector.infrastructure.proxy_manager.proxy_manager") as pm:
        pm.should_retry_with_proxy.return_value = True
        pm.get_proxy_settings.return_value = {"https": "p"}
        with patch.object(c, "_execute_request", side_effect=[direct, good]):
            assert c.get("http://e.com", source_config=src) is good
        pm.record_usage.assert_called_once()

        pm.record_usage.reset_mock()
        with patch.object(
            c, "_execute_request", side_effect=[direct, requests.Timeout("p")]
        ):
            with pytest.raises(requests.Timeout):
                c.get("http://e.com", source_config=src)
        pm.record_usage.assert_called_once()

        pm.should_retry_with_proxy.return_value = False
        with patch.object(c, "_execute_request", side_effect=direct):
            with pytest.raises(requests.Timeout):
                c.get("http://e.com", source_config=src)
    c.close()
