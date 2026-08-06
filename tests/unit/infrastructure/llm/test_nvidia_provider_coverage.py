"""
Coverage tests for NvidiaProvider (infrastructure/llm/nvidia_provider.py).

Targets the branches not exercised by tests/test_nvidia_routing_fix.py:
model resolution, payload building, list_models, backoff, retry-after
parsing, JSON extraction fallbacks, health checks, SSE streaming, and the
acquire-failure / retry / exhausted paths of the async and sync loops.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests

from news_collector.config import settings
from news_collector.infrastructure.llm.nvidia_provider import (
    LLMRateLimiter,
    NvidiaProvider,
    RateLimitError,
)
from news_collector.infrastructure.llm.rate_limiter import parse_retry_after

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _provider(**kwargs) -> NvidiaProvider:
    opts = {
        "api_key": "nvapi-test",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "max_retries": 3,
    }
    opts.update(kwargs)
    return NvidiaProvider(**opts)


class _Breaker:
    def __init__(self, is_open: bool = False):
        self.is_open = is_open
        self.record_error = MagicMock()
        self.record_rate_limit = MagicMock()
        self.record_success = MagicMock()


class _FakeLimiter:
    def __init__(self, acquire: bool = True, breaker: _Breaker | None = None):
        self._acquire = acquire
        self.breaker = breaker or _Breaker()

    @property
    def circuit_breaker(self):
        return self.breaker

    def acquire_sync(self):
        return self._acquire

    def release_sync(self):
        return None

    async def acquire_async(self):
        return self._acquire

    async def release_async(self):
        return None


class _FakeResp:
    """requests-compatible fake response."""

    def __init__(self, status: int = 200, payload=None, lines=None):
        self.status_code = status
        self._payload = payload
        self._lines = lines

    @property
    def headers(self):
        return {"Retry-After": "2"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)


def _fake_async_client(
    exc=None, result: dict | None = None, attempt: list | None = None
):
    """Return an httpx.AsyncClient replacement with a callable post()."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def post(self, *args, **kwargs):
            if attempt is not None:
                attempt.append(1)
            if exc is not None and (attempt is None or len(attempt) == 1):
                raise exc
            resp = _FakeResp(status=200, payload=result)
            return resp

        async def aclose(self):
            return None

    return _Client


def _set_limiter(monkeypatch, limiter: _FakeLimiter) -> None:
    monkeypatch.setattr(LLMRateLimiter, "get_instance", staticmethod(lambda: limiter))
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", True)


# ---------------------------------------------------------------------------
# RateLimitError, close, model resolution, payload, backoff
# ---------------------------------------------------------------------------


class TestBasics:
    def test_rate_limit_error_attrs(self):
        exc = RateLimitError("boom", retry_after=2.5)
        assert str(exc) == "boom"
        assert exc.retry_after == 2.5
        exc2 = RateLimitError()
        assert exc2.retry_after is None

    async def test_close_closes_async_client(self):
        provider = _provider()
        await provider.close()

    def test_resolve_model_cloud_slug_passthrough(self):
        provider = _provider()
        assert (
            provider._resolve_model("meta/llama-3.1-70b-instruct")
            == "meta/llama-3.1-70b-instruct"
        )

    def test_resolve_model_ollama_tag_replaced(self):
        provider = _provider()
        assert provider._resolve_model("qwen2.5:32b") == provider.model

    def test_resolve_model_ollama_name_no_tag_replaced(self):
        provider = _provider()
        assert provider._resolve_model("llama3.2") == provider.model
        assert provider._resolve_model("mistral-small") == provider.model

    def test_resolve_model_unknown_passthrough(self):
        provider = _provider()
        assert provider._resolve_model("gpt-4o") == "gpt-4o"

    def test_resolve_model_none_uses_configured(self):
        provider = _provider()
        assert provider._resolve_model(None) == provider.model

    def test_prepare_payload_system_and_json_mode(self):
        provider = _provider()
        payload = provider._prepare_payload(
            "prompt", system="sys", json_mode=True, model="gpt-4o"
        )
        assert payload["model"] == "gpt-4o"
        assert payload["stream"] is False
        assert payload["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "prompt"},
        ]
        assert payload["response_format"] == {"type": "json_object"}

    def test_prepare_payload_no_system_default_model(self):
        provider = _provider()
        payload = provider._prepare_payload("prompt")
        assert payload["model"] == provider.model
        assert len(payload["messages"]) == 1
        assert "response_format" not in payload

    def test_backoff_delay_bounded(self):
        delay = NvidiaProvider._backoff_delay(0, base=2.0, cap=30.0, jitter=0.0)
        assert 2.0 <= delay <= 2.0
        capped = NvidiaProvider._backoff_delay(20, base=2.0, cap=30.0, jitter=0.0)
        assert capped == 30.0


# ---------------------------------------------------------------------------
# Retry-after extraction
# ---------------------------------------------------------------------------


class TestGetRetryAfter:
    def test_no_response_returns_none(self):
        assert NvidiaProvider._get_retry_after_from_exc(ValueError("x")) is None

    def test_httpx_response_header(self):
        request = httpx.Request(
            "POST", "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        response = httpx.Response(429, headers={"retry-after": "2"}, request=request)
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        assert NvidiaProvider._get_retry_after_from_exc(exc) == 2.0

    def test_requests_response_header(self):
        resp = requests.Response()
        resp.status_code = 429
        resp.headers["Retry-After"] = "5"
        exc = requests.HTTPError("429", response=resp)
        assert NvidiaProvider._get_retry_after_from_exc(exc) == 5.0

    def test_unparseable_header_returns_none(self):
        assert parse_retry_after("soon") is None


# ---------------------------------------------------------------------------
# list_models / check_health / JSON extraction helpers
# ---------------------------------------------------------------------------


class TestListModels:
    def test_success_with_names(self, monkeypatch):
        fake = _FakeResp(status=200, payload={"data": [{"id": "a"}, {"id": "b"}]})
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: fake,
        )
        assert _provider().list_models() == ["a", "b"]

    def test_empty_names_falls_back(self, monkeypatch):
        fake = _FakeResp(status=200, payload={"data": []})
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: fake,
        )
        assert _provider().list_models() == ["nvidia/nemotron-3-super-120b-a12b"]

    def test_request_error_falls_back(self, monkeypatch):
        def _boom(*a, **k):
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get", _boom
        )
        assert _provider().list_models() == ["nvidia/nemotron-3-super-120b-a12b"]

    def test_non_200_falls_back(self, monkeypatch):
        fake = _FakeResp(status=500, payload={})
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: fake,
        )
        assert _provider().list_models() == ["nvidia/nemotron-3-super-120b-a12b"]


class TestCheckHealth:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: _FakeResp(status=200),
        )
        ok, msg = _provider().check_health()
        assert ok is True
        assert msg == "ok"

    def test_non_200(self, monkeypatch):
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: _FakeResp(status=503),
        )
        ok, msg = _provider().check_health()
        assert ok is False
        assert msg == "http_503"

    def test_request_exception(self, monkeypatch):
        def _boom(*a, **k):
            raise requests.ConnectionError("boom")

        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get", _boom
        )
        ok, msg = _provider().check_health()
        assert ok is False
        assert "boom" in msg


class TestJsonHelpers:
    def test_try_parse_json_dict_non_dict(self):
        ok, parsed = NvidiaProvider._try_parse_json_dict("[1, 2]")
        assert ok is True
        assert parsed == {}

    def test_extract_braced_segment_no_braces(self):
        assert NvidiaProvider._extract_braced_segment("plain text") is None

    def test_extract_braced_segment_balanced(self):
        assert NvidiaProvider._extract_braced_segment('pre {"a": 1} post') == '{"a": 1}'

    def test_extract_braced_segment_nested(self):
        assert (
            NvidiaProvider._extract_braced_segment('{"a": {"b": 1}}')
            == '{"a": {"b": 1}}'
        )

    def test_extract_braced_segment_unclosed(self):
        assert NvidiaProvider._extract_braced_segment("pre {unclosed") is None

    def test_extract_json_direct_dict(self):
        assert _provider()._extract_json('{"a": 1}') == {"a": 1}

    def test_extract_json_inside_text(self):
        provider = _provider()
        assert provider._extract_json('Here is {"a": 1} done') == {"a": 1}

    def test_extract_json_second_braced_segment(self):
        provider = _provider()
        assert provider._extract_json('{"a": 1} trailing {"b": 2}') == {"a": 1}

    def test_extract_json_failure_returns_empty(self):
        provider = _provider()
        assert provider._extract_json("no json here") == {}


# ---------------------------------------------------------------------------
# _stream_generator (SSE)
# ---------------------------------------------------------------------------


class TestStreamGenerator:
    def test_stream_parses_sse_and_strips_think_tags(self):
        lines = [
            'data: {"choices": [{"delta": {"content": "<think>x</think>hello"}}]}',
            b'data: {"choices": [{"delta": {"content": " world"}}]}',
            'data: {"choices": [{"delta": {}}]}',
            'data: {"choices": [{"delta": {"content": ""}}]}',
            "data: not-json",
            "data: [DONE]",
            "plain line",
        ]
        resp = _FakeResp(status=200, lines=lines)
        result = list(_provider()._stream_generator(resp))
        assert result == ["hello", " world"]


# ---------------------------------------------------------------------------
# Async API
# ---------------------------------------------------------------------------


class TestGenerateAsync:
    async def test_circuit_open_raises(self, monkeypatch):
        limiter = _FakeLimiter(acquire=False)
        _set_limiter(monkeypatch, limiter)
        with pytest.raises(RateLimitError):
            await _provider().generate_async("hello")

    async def test_success_text(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        result = {"choices": [{"message": {"content": "<think>x</think>hi"}}]}
        monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(result=result))
        out = await _provider().generate_async("hello")
        assert out == "hi"
        assert limiter.breaker.record_success.called

    async def test_success_json_mode(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        result = {"choices": [{"message": {"content": '{"a": 1}'}}]}
        monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(result=result))
        out = await _provider().generate_async("hello", json_mode=True)
        assert out == {"a": 1}

    async def test_429_retries_then_succeeds(self, monkeypatch):
        request = httpx.Request(
            "POST", "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        response = httpx.Response(429, headers={"retry-after": "2"}, request=request)
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        attempt = []
        result = {"choices": [{"message": {"content": "ok"}}]}

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def post(self, *args, **kwargs):
                attempt.append(1)
                if len(attempt) == 1:
                    raise exc
                return _FakeResp(status=200, payload=result)

            async def aclose(self):
                return None

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            NvidiaProvider, "_backoff_delay", staticmethod(lambda attempt: 0.0)
        )
        out = await _provider(max_retries=2).generate_async("hello")
        assert out == "ok"
        assert len(attempt) == 2
        assert limiter.breaker.record_rate_limit.called

    async def test_429_exhausted_raises(self, monkeypatch):
        request = httpx.Request(
            "POST", "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        response = httpx.Response(429, headers={"retry-after": "2"}, request=request)
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(exc=exc))
        with pytest.raises(RateLimitError) as err:
            await _provider(max_retries=1).generate_async("hello")
        assert err.value.retry_after == 2.0
        assert limiter.breaker.record_rate_limit.called

    async def test_network_error_retries_then_succeeds(self, monkeypatch):
        request = httpx.Request(
            "POST", "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        exc = httpx.ConnectError("conn refused", request=request)
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        attempt = []
        result = {"choices": [{"message": {"content": "ok"}}]}

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def post(self, *args, **kwargs):
                attempt.append(1)
                if len(attempt) == 1:
                    raise exc
                return _FakeResp(status=200, payload=result)

            async def aclose(self):
                return None

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            NvidiaProvider, "_backoff_delay", staticmethod(lambda attempt: 0.0)
        )
        out = await _provider(max_retries=2).generate_async("hello")
        assert out == "ok"
        assert len(attempt) == 2
        assert limiter.breaker.record_error.called

    async def test_zero_retries_raises_runtime_error(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            _fake_async_client(
                exc=httpx.ConnectError("x", request=httpx.Request("POST", "https://x"))
            ),
        )
        with pytest.raises(RuntimeError, match="retry loop"):
            await _provider(max_retries=0).generate_async("hello")


# ---------------------------------------------------------------------------
# Sync API
# ---------------------------------------------------------------------------


class TestGenerateSync:
    def test_system_unavailable_raises(self, monkeypatch):
        limiter = _FakeLimiter()
        monkeypatch.setattr(
            LLMRateLimiter, "get_instance", staticmethod(lambda: limiter)
        )
        monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", False)
        with pytest.raises(ValueError, match="unavailable"):
            _provider().generate_sync("hello")

    def test_circuit_open_raises(self, monkeypatch):
        limiter = _FakeLimiter(acquire=False)
        _set_limiter(monkeypatch, limiter)
        with pytest.raises(RateLimitError, match="circuit breaker"):
            _provider().generate_sync("hello")

    def test_success_text(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        payload = {"choices": [{"message": {"content": "plain"}}]}
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=200, payload=payload),
        )
        out = _provider().generate_sync("hello")
        assert out == "plain"
        assert limiter.breaker.record_success.called

    def test_success_json_mode(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        payload = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=200, payload=payload),
        )
        out = _provider().generate_sync("hello", json_mode=True)
        assert out == {"ok": True}

    def test_stream_returns_generator(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        lines = ['data: {"choices": [{"delta": {"content": "a"}}]}', "data: [DONE]"]
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=200, lines=lines),
        )
        out = _provider().generate_sync("hello", stream=True)
        assert list(out) == ["a"]

    def test_429_retries_then_succeeds(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        calls = {"n": 0}
        payload = {"choices": [{"message": {"content": "ok"}}]}

        def _post(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp(status=429)
            return _FakeResp(status=200, payload=payload)

        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post", _post
        )
        monkeypatch.setattr(
            NvidiaProvider, "_backoff_delay", staticmethod(lambda attempt: 0.0)
        )
        out = _provider(max_retries=2).generate_sync("hello")
        assert out == "ok"
        assert calls["n"] == 2
        assert limiter.breaker.record_rate_limit.called

    def test_429_circuit_open_raises(self, monkeypatch):
        breaker = _Breaker(is_open=True)
        limiter = _FakeLimiter(breaker=breaker)
        _set_limiter(monkeypatch, limiter)
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=429),
        )
        with pytest.raises(RateLimitError):
            _provider(max_retries=3).generate_sync("hello")
        assert breaker.record_rate_limit.called

    def test_zero_retries_raises_runtime_error(self, monkeypatch):
        limiter = _FakeLimiter()
        _set_limiter(monkeypatch, limiter)
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=429),
        )
        with pytest.raises(RuntimeError, match="Retry loop"):
            _provider(max_retries=0).generate_sync("hello")
