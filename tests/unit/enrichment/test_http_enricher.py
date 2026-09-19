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


class _ForbiddenClient:
    def get(self, url: str, timeout: int = 15):  # noqa: ARG002
        import requests

        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError("403 Client Error: Forbidden", response=response)


def test_blocked_host_warns_once_then_debug() -> None:
    enricher = HttpEnricher(request_client=_ForbiddenClient())

    with (
        patch.object(http_enricher_module.logger, "warning") as warning_logger,
        patch.object(http_enricher_module.logger, "debug") as debug_logger,
    ):
        first = enricher.enrich("https://blocked.example/a")
        second = enricher.enrich("https://blocked.example/b")
        other = enricher.enrich("https://other.example/c")

    assert first["status_code"] == second["status_code"] == 403
    assert warning_logger.call_count == 2  # blocked.example once + other.example once
    debug_logger.assert_called_once()
    assert other["success"] is False


def test_ssl_error_on_apex_host_retries_with_www() -> None:
    import requests

    calls: list[str] = []

    class _Resp:
        status_code = 200
        text = "<html><body><p>hola mundo</p></body></html>"
        headers: dict = {}

    class _Client:
        def get(self, url: str, timeout: int = 15):  # noqa: ARG002
            calls.append(url)
            if "://www." not in url:
                raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
            return _Resp()

    result = HttpEnricher(request_client=_Client()).enrich("https://caltech.edu/x")

    assert calls == ["https://caltech.edu/x", "https://www.caltech.edu/x"]
    assert result["success"] is True
