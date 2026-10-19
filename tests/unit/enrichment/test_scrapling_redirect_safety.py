"""Final-URL re-checks for the scrapling fetchers (plan 141, Step 2).

Both scrapling strategies follow redirects, so a public candidate URL can land
on an internal address via a 30x. The fetchers are mocked at the library
boundary (no network); the real ``validate_url_safety`` guard is the subject.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from news_collector.enrichment.headless_enricher import budget_manager
from news_collector.enrichment.scrapling_enricher import (
    ScraplingEnricher,
    ScraplingHttpEnricher,
)

REDIRECT_TARGETS = [
    "http://127.0.0.1/admin",  # loopback
    "http://192.168.1.10/internal",  # private range
]


def _fake_response(url: str) -> MagicMock:
    response = MagicMock()
    response.url = url
    response.body = "<html><body>secret internal page</body></html>"
    response.status = 200
    response.get_all_text.return_value = "secret internal page"
    return response


@pytest.mark.parametrize("final_url", REDIRECT_TARGETS)
def test_scrapling_http_rejects_unsafe_redirect_target(final_url: str) -> None:
    enricher = ScraplingHttpEnricher()
    response = _fake_response(final_url)

    with patch("news_collector.enrichment.scrapling_enricher.Fetcher") as mock_fetcher:
        mock_fetcher.get.return_value = response
        result = enricher.enrich("https://public.example.org/article", {})

    assert result["success"] is False
    assert result["content"] is None
    assert "Unsafe final URL after navigation" in result["error"]
    response.get_all_text.assert_not_called()


@pytest.mark.parametrize("final_url", REDIRECT_TARGETS)
def test_scrapling_stealth_rejects_unsafe_redirect_target(final_url: str) -> None:
    response = _fake_response(final_url)

    with (
        patch.dict(os.environ, {"ENABLE_HEADLESS": "true"}),
        patch(
            "news_collector.enrichment.scrapling_enricher.StealthyFetcher"
        ) as mock_fetcher,
    ):
        budget_manager.reset()
        enricher = ScraplingEnricher()
        mock_fetcher.fetch.return_value = response
        result = enricher.enrich(
            "https://public.example.org/article", {"proxy_mode": "off"}
        )

    assert result["success"] is False
    assert result["content"] is None
    assert "Unsafe final URL after navigation" in result["error"]
    response.get_all_text.assert_not_called()


def test_scrapling_http_accepts_public_redirect_target() -> None:
    enricher = ScraplingHttpEnricher()
    response = _fake_response("https://cdn.example.org/final")

    with (
        patch("news_collector.enrichment.scrapling_enricher.Fetcher") as mock_fetcher,
        patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 0))]),
    ):
        mock_fetcher.get.return_value = response
        result = enricher.enrich("https://public.example.org/article", {})

    assert result["success"] is True
    assert result["content"] == "secret internal page"
    response.get_all_text.assert_called_once_with(separator=" ", strip=True)
