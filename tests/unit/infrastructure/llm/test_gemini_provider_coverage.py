"""GeminiProvider: request/response handling, retries, 429 and breaker paths."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
import requests

from news_collector.config import settings
from news_collector.infrastructure.llm import gemini_provider as gp
from news_collector.infrastructure.llm.gemini_provider import (
    GeminiProvider,
    RateLimitError,
)
from news_collector.infrastructure.llm.rate_limiter import LLMRateLimiter


class _Breaker:
    def __init__(self, is_open=False):
        self.is_open = is_open
        self.record_success = MagicMock()
        self.record_error = MagicMock()
        self.record_rate_limit = MagicMock()


class _Limiter:
    def __init__(self, acquire=True, breaker=None):
        self._acquire = acquire
        self.breaker = breaker or _Breaker()

    def breaker_for(self, key):
        assert key == "gemini"
        return self.breaker

    def acquire_sync(self, breaker=None):
        return self._acquire

    async def acquire_async(self, breaker=None):
        return self._acquire

    def release_sync(self):
        return None

    def release_async(self):
        return None


def _wire(monkeypatch, limiter):
    monkeypatch.setattr(LLMRateLimiter, "get_instance", staticmethod(lambda: limiter))
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(gp.time, "sleep", lambda _s: None)

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)


def _payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class _Resp(requests.Response):
    """Real ``requests.Response`` (the provider type-checks it for Retry-After)."""

    def __init__(self, status=200, payload=None, lines=None, headers=None):
        super().__init__()
        self.status_code = status
        self._payload = payload
        self._lines = lines or []
        self.headers.update(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self, **_kwargs):
        return self._payload

    def iter_lines(self, *_a, **_k):
        return iter(self._lines)


def _provider(**kw):
    return GeminiProvider(api_key="k", model=kw.pop("model", None), **kw)


# ------------------------------------------------------------------ helpers


def test_model_resolution_and_urls():
    p = _provider()
    assert p._breaker_key == "gemini"
    assert p._resolve_model(None) == "gemini-2.5-flash"
    assert p._resolve_model("gemini-3.1-flash-lite") == "gemini-3.1-flash-lite"
    assert p._resolve_model("qwen3:80b") == "gemini-2.5-flash"  # local name -> default
    assert p._resolve_model("gemini-x:tag") == "gemini-x"
    assert _provider(model="llama3")._resolve_model(None) == "llama3"
    assert p._endpoint_url("m").endswith("/models/m:generateContent?key=k")


def test_prepare_payload_variants():
    p = _provider()
    plain = p._prepare_payload("hola")
    assert plain["contents"][0]["parts"][0]["text"] == "hola"
    assert "responseMimeType" not in plain["generationConfig"]
    withsys = p._prepare_payload("hola", "sé breve", json_mode=True)
    assert "System Instruction: sé breve" in withsys["contents"][0]["parts"][0]["text"]
    assert withsys["generationConfig"]["responseMimeType"] == "application/json"


def test_backoff_and_retry_after_helpers():
    assert 2.0 <= GeminiProvider._backoff_delay(0) <= 4.0
    assert GeminiProvider._backoff_delay(10) <= 32.0
    resp = httpx.Response(
        429, headers={"retry-after": "7"}, request=httpx.Request("POST", "http://x")
    )
    err = httpx.HTTPStatusError("429", request=resp.request, response=resp)
    assert GeminiProvider._is_429(err) is True
    assert GeminiProvider._get_retry_after_from_exc(err) == 7.0
    rresp = _Resp(429, headers={"Retry-After": "3"})
    rerr = requests.HTTPError("429", response=rresp)
    assert GeminiProvider._is_429(rerr) is True
    assert GeminiProvider._get_retry_after_from_exc(rerr) == 3.0
    assert GeminiProvider._is_429(ValueError()) is False
    assert GeminiProvider._get_retry_after_from_exc(ValueError()) is None


def test_extract_json_strategies():
    p = _provider()
    assert p._extract_json('{"a": 1}') == {"a": 1}
    assert p._extract_json('texto {"a": 2} fin') == {"a": 2}
    assert p._extract_json("[1,2]") == {}
    assert p._extract_json("nada") == {}
    assert p._extract_braced_segment("sin llaves") is None
    assert p._extract_braced_segment("{ sin cerrar") is None
    assert p._try_parse_json_dict("[1]") == (True, {})
    assert p._try_parse_json_dict("{malo") == (False, {})


def test_check_health(monkeypatch):
    p = _provider()
    monkeypatch.setattr(gp.requests, "get", lambda *_a, **_k: _Resp(200))
    assert p.check_health() == (True, "ok")
    monkeypatch.setattr(gp.requests, "get", lambda *_a, **_k: _Resp(503))
    assert p.check_health() == (False, "http_503")

    def boom(*_a, **_k):
        raise requests.ConnectionError("down key=SECRET")

    monkeypatch.setattr(gp.requests, "get", boom)
    ok, reason = p.check_health()
    assert ok is False and "down" in reason


# ---------------------------------------------------------------------- sync


def test_sync_success_text_and_json(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    monkeypatch.setattr(
        gp.requests, "post", lambda *_a, **_k: _Resp(200, _payload('{"t": "x"}'))
    )
    p = _provider()
    assert p.generate_sync("p") == '{"t": "x"}'
    assert p.generate_sync("p", json_mode=True) == {"t": "x"}
    limiter.breaker.record_success.assert_called()
    monkeypatch.setattr(
        gp.requests, "post", lambda *_a, **_k: _Resp(200, {"candidates": []})
    )
    assert p.generate_sync("p") == ""


def test_sync_disabled_and_open_breaker(monkeypatch):
    _wire(monkeypatch, _Limiter(acquire=False))
    with pytest.raises(RateLimitError):
        _provider().generate_sync("p")
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", False)
    with pytest.raises(ValueError, match="unavailable"):
        _provider().generate_sync("p")


def test_sync_stream(monkeypatch):
    _wire(monkeypatch, _Limiter())
    lines = [
        b"data: " + json.dumps(_payload("ho")).encode(),
        b"data: not-json",
        b"data: " + json.dumps({"candidates": []}).encode(),
        b"event: ping",
        b"data: " + json.dumps(_payload("la")).encode(),
        b"data: [DONE]",
        b"data: " + json.dumps(_payload("ignorado")).encode(),
    ]
    monkeypatch.setattr(gp.requests, "post", lambda *_a, **_k: _Resp(200, lines=lines))
    assert "".join(_provider().generate_sync("p", stream=True)) == "hola"


def test_sync_retries_transient_errors_then_succeeds(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    calls = iter([_Resp(503), _Resp(200, _payload("ok"))])
    monkeypatch.setattr(gp.requests, "post", lambda *_a, **_k: next(calls))
    assert _provider().generate_sync("p") == "ok"
    limiter.breaker.record_error.assert_called_once()


def test_sync_error_exhausts_retries_and_logs_as_warning_on_request(monkeypatch):
    _wire(monkeypatch, _Limiter())
    monkeypatch.setattr(gp.requests, "post", lambda *_a, **_k: _Resp(500))
    with pytest.raises(requests.HTTPError):
        _provider(max_retries=2).generate_sync("p", log_errors_as_warning=True)


def test_sync_429_retries_using_retry_after_then_succeeds(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    slept: list[float] = []
    monkeypatch.setattr(gp.time, "sleep", slept.append)
    calls = iter([_Resp(429, headers={"Retry-After": "2"}), _Resp(200, _payload("ok"))])
    monkeypatch.setattr(gp.requests, "post", lambda *_a, **_k: next(calls))
    assert _provider().generate_sync("p") == "ok"
    limiter.breaker.record_rate_limit.assert_called_once()
    assert slept == [2.0]


def test_sync_429_without_retry_after_uses_backoff_and_open_breaker_raises(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    monkeypatch.setattr(gp.requests, "post", lambda *_a, **_k: _Resp(429))
    with pytest.raises(requests.HTTPError):
        _provider(max_retries=2).generate_sync("p")  # backoff path, exhausts
    limiter.breaker.is_open = True
    with pytest.raises(RateLimitError):
        _provider().generate_sync("p")


def test_sync_zero_retries_raises_runtime_error(monkeypatch):
    _wire(monkeypatch, _Limiter())
    with pytest.raises(RuntimeError, match="without producing"):
        _provider(max_retries=0).generate_sync("p")


# --------------------------------------------------------------------- async


class _AsyncClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def post(self, *_a, **_k):
        self.calls += 1
        out = self.results.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    async def aclose(self):
        return None


class _AResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.request = httpx.Request("POST", "http://x")
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            resp = httpx.Response(
                self.status_code, request=self.request, headers=self.headers
            )
            raise httpx.HTTPStatusError("err", request=self.request, response=resp)

    def json(self):
        return self._payload


def test_async_success_text_json_and_empty(monkeypatch):
    _wire(monkeypatch, _Limiter())
    p = _provider()
    p.async_client = _AsyncClient(
        [
            _AResp(200, _payload("hola")),
            _AResp(200, _payload('{"a": 1}')),
            _AResp(200, {"candidates": []}),
        ]
    )
    assert asyncio.run(p.generate_async("p")) == "hola"
    assert asyncio.run(p.generate_async("p", json_mode=True)) == {"a": 1}
    assert asyncio.run(p.generate_async("p")) == ""


def test_async_open_breaker_and_close(monkeypatch):
    _wire(monkeypatch, _Limiter(acquire=False))
    p = _provider()
    p.async_client = _AsyncClient([])
    with pytest.raises(RateLimitError):
        asyncio.run(p.generate_async("p"))
    asyncio.run(p.close())


def test_async_retries_errors_then_succeeds(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    p = _provider()
    p.async_client = _AsyncClient([_AResp(503), _AResp(200, _payload("ok"))])
    assert asyncio.run(p.generate_async("p")) == "ok"
    limiter.breaker.record_error.assert_called_once()


def test_async_error_exhausts_and_raises(monkeypatch):
    _wire(monkeypatch, _Limiter())
    p = _provider(max_retries=2)
    p.async_client = _AsyncClient([_AResp(500), _AResp(500)])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(p.generate_async("p"))


def test_async_429_retry_after_then_success_and_exhaustion(monkeypatch):
    limiter = _Limiter()
    _wire(monkeypatch, limiter)
    p = _provider()
    p.async_client = _AsyncClient(
        [_AResp(429, headers={"retry-after": "1"}), _AResp(200, _payload("ok"))]
    )
    assert asyncio.run(p.generate_async("p")) == "ok"

    p2 = _provider(max_retries=2)
    p2.async_client = _AsyncClient([_AResp(429), _AResp(429)])
    with pytest.raises(RateLimitError):
        asyncio.run(p2.generate_async("p"))


def test_async_zero_retries_raises_runtime_error(monkeypatch):
    _wire(monkeypatch, _Limiter())
    p = _provider(max_retries=0)
    with pytest.raises(RuntimeError):
        asyncio.run(p.generate_async("p"))


def test_unused_names_are_importable():
    assert SimpleNamespace and gp.RateLimitError is RateLimitError


def test_foreign_provider_model_names_fall_back_to_the_gemini_default():
    """The chain forwards the caller's override to every provider: an NVIDIA/other
    name used to reach Gemini and 404 (wasted attempt before every failover)."""
    p = _provider()
    for foreign in ("nvidia/nemotron-3-super-120b-a12b", "gpt-oss-120b", "llama3.2"):
        assert p._resolve_model(foreign) == "gemini-2.5-flash"
    assert p._resolve_model("models/gemini-3.1-flash-lite") == (
        "models/gemini-3.1-flash-lite"
    )
    assert p._resolve_model("gemma-3-27b:it") == "gemma-3-27b"
