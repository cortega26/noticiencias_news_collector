from __future__ import annotations

from unittest.mock import patch

import news_collector.enrichment.http_enricher as http_enricher_module
from news_collector.enrichment.http_enricher import HttpEnricher


class _ValueErrorClient:
    def __init__(self, message: str):
        self._message = message

    def get(self, url: str, timeout: int = 15):  # noqa: ARG002
        raise ValueError(self._message)


def test_invalid_url_logs_error_in_production(monkeypatch) -> None:
    monkeypatch.delenv("NOTICIENCIAS_SMOKE", raising=False)
    enricher = HttpEnricher(request_client=_ValueErrorClient("Invalid URL scheme: ''"))

    with patch.object(http_enricher_module.logger, "error") as error_logger:
        result = enricher.enrich("/blog/relative")

    assert result["success"] is False
    assert "Unexpected: Invalid URL scheme" in result["error"]
    error_logger.assert_called_once()
    assert "invalid URL" in error_logger.call_args[0][0]


def test_invalid_url_logs_warning_in_smoke_mode(monkeypatch) -> None:
    monkeypatch.setenv("NOTICIENCIAS_SMOKE", "1")
    enricher = HttpEnricher(request_client=_ValueErrorClient("Invalid URL scheme: ''"))

    with patch.object(http_enricher_module.logger, "warning") as warning_logger:
        result = enricher.enrich("/blog/relative")

    assert result["success"] is False
    assert "Unexpected: Invalid URL scheme" in result["error"]
    warning_logger.assert_called_once()
    assert "skipped invalid URL" in warning_logger.call_args[0][0]
