"""OllamaProvider: sync/async retry, 429, admission-error and health paths."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
import requests

from news_collector.config import settings
from news_collector.infrastructure.llm import provider as pv
from news_collector.infrastructure.llm.ollama_errors import (
    OllamaAdmissionError,
    OllamaProviderError,
)
from news_collector.infrastructure.llm.provider import OllamaProvider, RateLimitError
from news_collector.infrastructure.llm.rate_limiter import LLMRateLimiter


class _Breaker:
    def __init__(self, is_open=False):
        self.is_open = is_open
        self.record_success = MagicMock()
        self.record_error = MagicMock()
        self.record_rate_limit = MagicMock()


class _Limiter:
    def __init__(self, acquire=True):
        self._acquire = acquire
        self.breaker = _Breaker()

    def breaker_for(self, key):
        assert key == "ollama"
        return self.breaker

    def acquire_sync(self, breaker=None):
        return self._acquire

    async def acquire_async(self, breaker=None):
        return self._acquire

    def release_sync(self):
        return None

    def release_async(self):
        return None


def _wire(monkeypatch, limiter=None):
    limiter = limiter or _Limiter()
    monkeypatch.setattr(LLMRateLimiter, "get_instance", staticmethod(lambda: limiter))
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(pv.time, "sleep", lambda _s: None)

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    return limiter


def _provider(**kw):
    return OllamaProvider(
        api_url="http://ollama.test:11434", model="llama3.2:latest", **kw
    )


class _Resp(requests.Response):
    def __init__(self, status=200, payload=None, lines=None, text=""):
        super().__init__()
        self.status_code = status
        self._payload = payload
        self._lines = lines or []
        self._text = text

    @property
    def text(self):  # type: ignore[override]
        return self._text

    def json(self, **_kwargs):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_lines(self, *_a, **_k):
        return iter(self._lines)


def test_constructor_normalizes_url_and_helpers():
    assert _provider().api_url == "http://ollama.test:11434/api/generate"
    p2 = OllamaProvider(api_url="http://h:1/api/generate/", model=None)
    assert p2.api_url == "http://h:1/api/generate" and p2.model is None
    assert OllamaProvider()._base_url() == "http://127.0.0.1:11434"
    assert _provider()._breaker_key == "ollama"
    assert 2.0 <= OllamaProvider._backoff_delay(0) <= 3.5
    assert OllamaProvider._response_status_code(SimpleNS(status_code="x")) == 200


class SimpleNS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------- sync


def test_sync_success_json_text_and_stream(monkeypatch):
    limiter = _wire(monkeypatch)
    monkeypatch.setattr(
        pv.requests, "post", lambda *_a, **_k: _Resp(200, {"response": '{"a": 1}'})
    )
    p = _provider()
    assert p.generate_sync("p") == '{"a": 1}'
    assert p.generate_sync("p", json_mode=True) == {"a": 1}
    limiter.breaker.record_success.assert_called()
    lines = [
        b'{"response": "ho"}',
        b"",
        b"basura",
        b'{"response": ""}',
        b'{"response": "la"}',
    ]
    monkeypatch.setattr(pv.requests, "post", lambda *_a, **_k: _Resp(200, lines=lines))
    assert "".join(p.generate_sync("p", stream=True)) == "hola"


def test_sync_guards(monkeypatch):
    _wire(monkeypatch, _Limiter(acquire=False))
    with pytest.raises(RateLimitError):
        _provider().generate_sync("p")
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", False)
    with pytest.raises(ValueError, match="unavailable"):
        _provider().generate_sync("p")


def test_sync_429_retries_then_raises_and_open_breaker(monkeypatch):
    limiter = _wire(monkeypatch)
    calls = iter([_Resp(429), _Resp(200, {"response": "ok"})])
    monkeypatch.setattr(pv.requests, "post", lambda *_a, **_k: next(calls))
    assert _provider().generate_sync("p") == "ok"
    limiter.breaker.record_rate_limit.assert_called_once()

    monkeypatch.setattr(pv.requests, "post", lambda *_a, **_k: _Resp(429))
    with pytest.raises(RateLimitError):
        _provider(max_retries=1).generate_sync("p")
    limiter.breaker.is_open = True
    with pytest.raises(RateLimitError):
        _provider().generate_sync("p")


def test_sync_admission_error_is_not_retried(monkeypatch):
    _wire(monkeypatch)
    posts = []

    def post(*_a, **_k):
        posts.append(1)
        return _Resp(
            500,
            {"error": "model requires more system memory (60 GiB) than is available"},
        )

    monkeypatch.setattr(pv.requests, "post", post)
    with pytest.raises(OllamaProviderError) as err:
        _provider().generate_sync("p")
    assert isinstance(err.value, OllamaAdmissionError) and len(posts) == 1


def test_sync_5xx_is_retried_then_raised_as_http_error(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(
        pv.requests, "post", lambda *_a, **_k: _Resp(503, {"error": "busy"})
    )
    with pytest.raises(OllamaProviderError):
        _provider(max_retries=1).generate_sync("p", log_errors_as_warning=True)


def test_sync_404_non_retryable_and_connection_errors(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(
        pv.requests, "post", lambda *_a, **_k: _Resp(404, {"error": "model not found"})
    )
    with pytest.raises(OllamaProviderError):
        _provider().generate_sync("p")

    def down(*_a, **_k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(pv.requests, "post", down)
    with pytest.raises(requests.ConnectionError):
        _provider(max_retries=1).generate_sync("p")


def test_sync_response_error_from_exception_paths(monkeypatch):
    _wire(monkeypatch)

    def raising(status, payload):
        def post(*_a, **_k):
            resp = _Resp(status, payload)
            resp.status_code = 200  # bypass the status checks in generate_sync
            raise requests.HTTPError("boom", response=_Resp(status, payload))

        return post

    monkeypatch.setattr(pv.requests, "post", raising(404, {"error": "model not found"}))
    with pytest.raises(OllamaProviderError):
        _provider().generate_sync("p")
    monkeypatch.setattr(pv.requests, "post", raising(503, {"error": "busy"}))
    with pytest.raises(OllamaProviderError):
        _provider(max_retries=1).generate_sync("p")


def test_sync_zero_attempts_runtime_error(monkeypatch):
    _wire(monkeypatch)
    with pytest.raises(RuntimeError):
        _provider(max_retries=-1).generate_sync("p")


# --------------------------------------------------------------------- async


class _AResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.request = httpx.Request("POST", "http://x")

    def raise_for_status(self):
        if self.status_code >= 400:
            resp = httpx.Response(
                self.status_code, json=self._payload, request=self.request
            )
            raise httpx.HTTPStatusError("err", request=self.request, response=resp)

    def json(self):
        return self._payload


class _AClient:
    def __init__(self, results):
        self.results = list(results)

    async def post(self, *_a, **_k):
        out = self.results.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    async def aclose(self):
        return None


def _async(p, results):
    p.async_client = _AClient(results)
    return p


def test_async_success_and_guards(monkeypatch):
    _wire(monkeypatch)
    p = _async(
        _provider(),
        [_AResp(200, {"response": "hola"}), _AResp(200, {"response": '{"a": 2}'})],
    )
    assert asyncio.run(p.generate_async("p")) == "hola"
    assert asyncio.run(p.generate_async("p", json_mode=True)) == {"a": 2}
    asyncio.run(p.close())
    _wire(monkeypatch, _Limiter(acquire=False))
    with pytest.raises(RateLimitError):
        asyncio.run(_async(_provider(), []).generate_async("p"))


def test_async_429_retry_then_success_and_exhaustion(monkeypatch):
    limiter = _wire(monkeypatch)
    p = _async(_provider(), [_AResp(429), _AResp(200, {"response": "ok"})])
    assert asyncio.run(p.generate_async("p")) == "ok"
    p2 = _async(_provider(max_retries=1), [_AResp(429), _AResp(429)])
    with pytest.raises(RateLimitError):
        asyncio.run(p2.generate_async("p"))
    assert limiter.breaker.record_rate_limit.call_count >= 2


def test_async_http_errors(monkeypatch):
    _wire(monkeypatch)
    admission = {
        "error": "model requires more system memory (60 GiB) than is available"
    }
    with pytest.raises(OllamaProviderError):
        asyncio.run(_async(_provider(), [_AResp(500, admission)]).generate_async("p"))
    p = _async(
        _provider(), [_AResp(503, {"error": "busy"}), _AResp(200, {"response": "ok"})]
    )
    assert asyncio.run(p.generate_async("p")) == "ok"
    with pytest.raises(OllamaProviderError):
        asyncio.run(
            _async(
                _provider(max_retries=1), [_AResp(503, {"error": "x"})] * 2
            ).generate_async("p")
        )


def test_async_request_errors_and_zero_attempts(monkeypatch):
    _wire(monkeypatch)
    err = httpx.ConnectError("refused")
    p = _async(_provider(), [err, _AResp(200, {"response": "ok"})])
    assert asyncio.run(p.generate_async("p")) == "ok"
    with pytest.raises(httpx.ConnectError):
        asyncio.run(_async(_provider(max_retries=1), [err, err]).generate_async("p"))
    with pytest.raises(RuntimeError):
        asyncio.run(_async(_provider(max_retries=-2), []).generate_async("p"))


# ------------------------------------------------------------ health / models


def test_health_and_model_listing(monkeypatch):
    p = _provider()
    monkeypatch.setattr(
        pv.requests,
        "get",
        lambda *_a, **_k: _Resp(200, {"models": [{"name": "llama3.2:latest"}]}),
    )
    assert p.check_health() == (True, "ok")
    assert p.list_models() == ["llama3.2:latest"]
    assert p.check_model_exists("llama3.2:latest") is True
    monkeypatch.setattr(pv.requests, "get", lambda *_a, **_k: _Resp(500))
    assert p.check_health() == (False, "http_500")
    assert p.list_models() == []

    def down(*_a, **_k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(pv.requests, "get", down)
    assert p.check_health()[0] is False
    assert p.list_models() == []


def test_extract_json_strategies():
    p = _provider()
    assert p._extract_json('{"a": 1}') == {"a": 1}
    assert p._extract_json('x {"a": 2} y') == {"a": 2}
    assert p._extract_json("[1]") == {}
    assert p._extract_json("nada") == {}
    assert p._extract_braced_segment("sin llaves") is None
    assert json.loads('{"ok": true}') == {"ok": True}
