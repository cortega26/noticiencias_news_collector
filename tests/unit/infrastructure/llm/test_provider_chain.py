"""Provider chain: failure taxonomy, failover policy, endpoints and ordering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import requests
from noticiencias.config_schema import Config, LLMEndpointConfig

from news_collector.infrastructure.llm import attempts
from news_collector.infrastructure.llm.factory import (
    FallbackProvider,
    _apply_chain_order,
    _build_endpoint_providers,
    get_provider,
)
from news_collector.infrastructure.llm.failure_kinds import (
    EmptyResponseError,
    FailureKind,
    classify_exception,
    is_provider_fault,
    retry_after_seconds,
)
from news_collector.infrastructure.llm.nvidia_provider import (
    ProviderDegradedError,
    RateLimitError,
)
from news_collector.infrastructure.llm.openai_compat_provider import (
    OpenAICompatProvider,
)


@pytest.fixture(autouse=True)
def _clean_attempt_state():
    attempts.reset_state()
    yield
    attempts.reset_state()


def _http_error(status: int, headers: dict[str, str] | None = None):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    return requests.HTTPError(f"{status}", response=response)


class FakeProvider:
    """Scripted provider: each call pops the next outcome (value or exception)."""

    def __init__(self, name: str, *outcomes: Any):
        self.name = name
        self.model = f"{name}-model"
        self.timeout = 300
        self.outcomes = list(outcomes)
        self.calls = 0

    def _next(self):
        self.calls += 1
        out = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(out, BaseException):
            raise out
        return out

    def generate_sync(self, **_kwargs):
        return self._next()

    async def generate_async(self, **_kwargs):
        return self._next()


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (requests.Timeout("t"), FailureKind.TIMEOUT),
        (httpx.ReadTimeout("t"), FailureKind.TIMEOUT),
        (_http_error(503), FailureKind.HTTP_5XX),
        (_http_error(429), FailureKind.RATE_LIMITED),
        (_http_error(401), FailureKind.AUTH),
        (_http_error(403), FailureKind.AUTH),
        (_http_error(400), FailureKind.CLIENT_ERROR),
        (RateLimitError("rl"), FailureKind.RATE_LIMITED),
        (ProviderDegradedError("d"), FailureKind.DEGRADED_SKIP),
        (EmptyResponseError(), FailureKind.EMPTY_RESPONSE),
        (EmptyResponseError(FailureKind.INVALID_JSON), FailureKind.INVALID_JSON),
        (RuntimeError("?"), FailureKind.UNKNOWN),
    ],
)
def test_classify_exception(exc, kind):
    assert classify_exception(exc) is kind


def test_classify_httpx_status_error():
    response = httpx.Response(502, request=httpx.Request("POST", "http://x"))
    err = httpx.HTTPStatusError("bad", request=response.request, response=response)
    assert classify_exception(err) is FailureKind.HTTP_5XX
    response = httpx.Response(404, request=response.request)
    err = httpx.HTTPStatusError("bad", request=response.request, response=response)
    assert classify_exception(err) is FailureKind.CLIENT_ERROR


def test_provider_fault_and_retry_after():
    assert is_provider_fault(FailureKind.HTTP_5XX) is True
    assert is_provider_fault(FailureKind.CLIENT_ERROR) is False
    assert retry_after_seconds(RateLimitError("x", retry_after=7)) == 7.0
    assert retry_after_seconds(_http_error(429, {"Retry-After": "12"})) == 12.0
    assert retry_after_seconds(_http_error(429, {"Retry-After": "soon"})) is None
    assert retry_after_seconds(RuntimeError()) is None


# ------------------------------------------------------------------- failover matrix


@pytest.mark.parametrize(
    "failure",
    [
        _http_error(503),
        requests.Timeout("slow"),
        "",
        "   ",
        {},
        RuntimeError("boom"),
    ],
)
def test_sync_fails_over_to_next_provider(failure):
    first, second = FakeProvider("a", failure), FakeProvider("b", "answer")
    chain = FallbackProvider([first, second], purpose="test")
    assert chain.generate_sync("p") == "answer"
    assert (first.calls, second.calls) == (1, 1)


def test_async_fails_over_and_restores_timeouts():
    first, second = FakeProvider("a", _http_error(503)), FakeProvider("b", "ok")
    chain = FallbackProvider([first, second])
    assert asyncio.run(chain.generate_async("p")) == "ok"
    assert first.timeout == second.timeout == 300


def test_last_provider_keeps_historical_semantics():
    assert (
        FallbackProvider(
            [FakeProvider("a", _http_error(503)), FakeProvider("b", "")]
        ).generate_sync("p")
        == ""
    )
    with pytest.raises(requests.HTTPError):
        FallbackProvider(
            [FakeProvider("a", _http_error(503)), FakeProvider("b", _http_error(500))]
        ).generate_sync("p")


def test_client_error_still_fails_over_but_is_not_a_provider_fault():
    first, second = FakeProvider("a", _http_error(400)), FakeProvider("b", "ok")
    assert FallbackProvider([first, second]).generate_sync("p") == "ok"
    assert attempts.blocked_reason(first) is None


def test_auth_error_disables_provider_once_process_wide(caplog):
    first = FakeProvider("a", _http_error(401), "never")
    second = FakeProvider("b", "ok", "ok")
    assert FallbackProvider([first, second]).generate_sync("p") == "ok"
    assert "disabled" in attempts.blocked_reason(first)
    # A different chain instance (each caller builds its own) must skip it.
    assert FallbackProvider([first, second]).generate_sync("p") == "ok"
    assert first.calls == 1


def test_rate_limit_cools_provider_down_using_retry_after():
    first = FakeProvider("a", _http_error(429, {"Retry-After": "30"}))
    second = FakeProvider("b", "ok", "ok")
    chain = FallbackProvider([first, second])
    chain.generate_sync("p")
    assert "cooldown" in attempts.blocked_reason(first)
    chain.generate_sync("p")
    assert first.calls == 1


def test_cooldown_is_capped_and_expires(monkeypatch):
    provider = FakeProvider("a")
    assert attempts.cool_down_provider(provider, 99999) == attempts.MAX_COOLDOWN_S
    assert attempts.cool_down_provider(provider, None) == 60.0
    monkeypatch.setattr(attempts.time, "monotonic", lambda: 10**9)
    assert attempts.blocked_reason(provider) is None


def test_all_providers_blocked_raises_clear_error():
    provider = FakeProvider("a")
    attempts.disable_provider(provider, "bad key")
    with pytest.raises(RuntimeError, match="no active providers"):
        FallbackProvider([provider]).generate_sync("p")


class Streamer(FakeProvider):
    def __init__(self, name, *chunks):
        super().__init__(name)
        self.chunks = chunks

    def generate_sync(self, **kwargs):
        assert kwargs["stream"] is True
        self.calls += 1
        return iter(self.chunks)


def test_stream_success_after_failover():
    out = FallbackProvider(
        [FakeProvider("x", _http_error(503)), Streamer("s", "a", "b")]
    )
    assert list(out.generate_sync("p", stream=True)) == ["a", "b"]


def test_empty_stream_from_non_final_provider_fails_over():
    first, second = Streamer("s1"), Streamer("s2", "ok")
    chain = FallbackProvider([first, second])
    assert list(chain.generate_sync("p", stream=True)) == ["ok"]
    assert (first.calls, second.calls) == (1, 1)


def test_endpoint_timeout_shorter_than_failover_leash_is_honored():
    short, long_, last = FakeProvider("a"), FakeProvider("b"), FakeProvider("c")
    short.timeout, long_.timeout = 30, 300
    chain = FallbackProvider([short, long_, last])
    assert chain._timeout_for(0, None, short) == 30
    assert chain._timeout_for(1, None, long_) == FallbackProvider.FAILOVER_TIMEOUT_S
    assert chain._timeout_for(2, 500, last) == 500


def test_skipped_providers_emit_degraded_skip_events():
    seen: list[attempts.AttemptRecord] = []
    attempts.register_attempt_sink(seen.append)
    blocked, healthy = FakeProvider("a"), FakeProvider("b", "ok")
    attempts.cool_down_provider(blocked, 30)
    try:
        assert (
            FallbackProvider([blocked, healthy], purpose="scoring").generate_sync("p")
            == "ok"
        )
    finally:
        attempts.unregister_attempt_sink(seen.append)
    assert seen[0].kind is FailureKind.DEGRADED_SKIP
    assert (
        seen[0].provider == "a"
        and seen[0].latency_ms == 0
        and seen[0].purpose == "scoring"
    )
    assert blocked.calls == 0


def test_auth_disable_expires(monkeypatch):
    provider = FakeProvider("a")
    assert attempts.disable_provider(provider, "401") is True
    assert attempts.disable_provider(provider, "401") is False
    assert "disabled" in attempts.blocked_reason(provider)
    monkeypatch.setattr(attempts.time, "monotonic", lambda: 10**9)
    assert attempts.blocked_reason(provider) is None
    assert attempts.disable_provider(provider, "401") is True


# ------------------------------------------------------------ events and sinks


def test_attempt_events_reach_sinks_and_sink_errors_are_swallowed():
    seen: list[attempts.AttemptRecord] = []

    def bad_sink(_record):
        raise RuntimeError("sink down")

    attempts.register_attempt_sink(bad_sink)
    attempts.register_attempt_sink(seen.append)
    try:
        chain = FallbackProvider(
            [FakeProvider("a", _http_error(503)), FakeProvider("b", "ok")],
            purpose="headline",
        )
        assert chain.generate_sync("p") == "ok"
    finally:
        attempts.unregister_attempt_sink(bad_sink)
        attempts.unregister_attempt_sink(seen.append)
    assert [(r.provider, r.ok, r.failover_index) for r in seen] == [
        ("a", False, 0),
        ("b", True, 1),
    ]
    assert seen[0].kind is FailureKind.HTTP_5XX and seen[0].purpose == "headline"
    event = seen[0].as_event()
    assert event["event"] == "llm.attempt" and event["details"]["kind"] == "http_5xx"


def test_attempt_error_text_is_redacted_and_truncated():
    seen: list[attempts.AttemptRecord] = []
    attempts.register_attempt_sink(seen.append)
    try:
        chain = FallbackProvider(
            [
                FakeProvider("a", RuntimeError("Bearer sk-secret-123 " + "x" * 900)),
                FakeProvider("b"),
            ]
        )
        chain.generate_sync("p")
    finally:
        attempts.unregister_attempt_sink(seen.append)
    assert len(seen[0].error) <= 300


# ---------------------------------------------------------- OpenAICompatProvider


def _endpoint(**overrides):
    data = {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1/",
        "model": "some-model",
        "api_key_env": "GROQ_TEST_KEY",
    }
    data.update(overrides)
    return LLMEndpointConfig(**data)


def test_compat_provider_payload_headers_and_model_resolution():
    provider = OpenAICompatProvider(
        name="groq",
        api_key="k",
        base_url="https://x.test/v1/",
        model="served-model",
        extra_headers={"HTTP-Referer": "https://noticiencias.com"},
    )
    payload = provider._prepare_payload(
        "hi", "sys", json_mode=True, model="llama3.2:latest"
    )
    assert payload["model"] == "served-model"  # Ollama-style tags are ignored
    assert payload["response_format"] == {"type": "json_object"}
    headers = provider._auth_headers()
    assert headers["Authorization"] == "Bearer k"
    assert headers["HTTP-Referer"] == "https://noticiencias.com"
    assert provider._endpoint_url == "https://x.test/v1/chat/completions"


def test_compat_provider_without_json_mode_support_and_label():
    provider = OpenAICompatProvider(
        name="cerebras",
        api_key="k",
        base_url="https://x.test/v1",
        model="m",
        json_mode_supported=False,
    )
    assert "response_format" not in provider._prepare_payload("hi", json_mode=True)
    assert attempts.provider_name(provider) == "cerebras"
    assert provider._label == "cerebras"


# ----------------------------------------------------------------- factory / config


def _cfg(endpoints=None, chain=None, nvidia_key=None):
    cfg = Config.model_validate(
        {
            "llm_endpoints": [e.model_dump() for e in (endpoints or [])],
            "llm": {"chain": chain or []},
        }
    )
    cfg.nvidia.api_key = nvidia_key
    cfg.gemini.api_key = None
    return cfg


def test_endpoint_without_env_key_is_skipped(monkeypatch, caplog):
    monkeypatch.delenv("GROQ_TEST_KEY", raising=False)
    assert _build_endpoint_providers(_cfg([_endpoint()]), None) == []


def test_disabled_endpoint_is_skipped(monkeypatch):
    monkeypatch.setenv("GROQ_TEST_KEY", "k")
    assert _build_endpoint_providers(_cfg([_endpoint(enabled=False)]), None) == []


def test_endpoint_inherits_degradation_settings(monkeypatch):
    monkeypatch.setenv("GROQ_TEST_KEY", "k")
    cfg = _cfg([_endpoint(degraded_failure_threshold=4)])
    (provider,) = _build_endpoint_providers(cfg, cfg.nvidia)
    assert provider.degraded_failure_threshold == 4
    assert provider.degraded_cooldown_seconds == cfg.nvidia.degraded_cooldown_seconds


def test_get_provider_without_endpoints_is_unchanged():
    provider = get_provider(config=_cfg())
    assert provider.__class__.__name__ == "OllamaProvider"


def test_get_provider_chain_order_and_purpose(monkeypatch):
    monkeypatch.setenv("GROQ_TEST_KEY", "k")
    monkeypatch.setenv("CEREBRAS_TEST_KEY", "k")
    cfg = _cfg(
        [
            _endpoint(),
            _endpoint(name="cerebras", api_key_env="CEREBRAS_TEST_KEY"),
        ],
        nvidia_key="nv",
    )
    chain = get_provider(config=cfg, purpose="scoring")
    assert [attempts.provider_name(p) for p in chain.providers] == [
        "nvidia",
        "groq",
        "cerebras",
        "ollama",
    ]
    assert chain.purpose == "scoring"

    cfg.llm.chain = ["cerebras", "nvidia", "ghost"]
    chain = get_provider(config=cfg)
    assert [attempts.provider_name(p) for p in chain.providers] == [
        "cerebras",
        "nvidia",
        "ollama",
    ]


def test_apply_chain_order_default_passthrough():
    providers = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
    assert _apply_chain_order(providers, []) is providers
    assert _apply_chain_order(providers, None) is providers


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "Bad Name"},
        {"base_url": "ftp://x"},
        {"api_key_env": "lowercase"},
        {"model": ""},
    ],
)
def test_endpoint_schema_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        _endpoint(**bad)


def test_health_checker_prefers_endpoint_when_no_cloud_keys(monkeypatch):
    from news_collector.infrastructure.llm.health import (
        OpenAICompatHealthChecker,
        resolve_health_checker,
    )

    monkeypatch.setenv("GROQ_TEST_KEY", "k")
    cfg = _cfg([_endpoint()])
    assert isinstance(resolve_health_checker(cfg), OpenAICompatHealthChecker)
    monkeypatch.delenv("GROQ_TEST_KEY")
    assert resolve_health_checker(cfg).__class__.__name__ == "OllamaHealthChecker"


def test_health_checker_reports_probe_result(monkeypatch):
    from news_collector.infrastructure.llm.health import OpenAICompatHealthChecker

    monkeypatch.setenv("GROQ_TEST_KEY", "k")
    cfg = _cfg([_endpoint()])
    monkeypatch.setattr(
        OpenAICompatProvider, "check_health", lambda *_a, **_k: (True, "ok")
    )
    assert OpenAICompatHealthChecker().check(cfg, None).healthy is True
    monkeypatch.setattr(
        OpenAICompatProvider, "check_health", lambda *_a, **_k: (False, "http_401")
    )
    result = OpenAICompatHealthChecker().check(cfg, None)
    assert result.healthy is False and "http_401" in result.error
    monkeypatch.delenv("GROQ_TEST_KEY")
    assert OpenAICompatHealthChecker().check(cfg, None).healthy is False


def test_endpoint_key_is_read_from_dotenv_when_not_exported(monkeypatch, tmp_path):
    from news_collector.infrastructure.llm import factory

    monkeypatch.delenv("GROQ_TEST_KEY", raising=False)
    monkeypatch.setattr(
        factory, "load_env_overrides", lambda: {"GROQ_TEST_KEY": " from-dotenv "}
    )
    (provider,) = _build_endpoint_providers(_cfg([_endpoint()]), None)
    assert provider.api_key == "from-dotenv"
    # The process environment wins over the file.
    monkeypatch.setenv("GROQ_TEST_KEY", "from-env")
    (provider,) = _build_endpoint_providers(_cfg([_endpoint()]), None)
    assert provider.api_key == "from-env"


def test_broken_dotenv_does_not_break_endpoint_resolution(monkeypatch):
    from news_collector.infrastructure.llm import factory

    def boom():
        raise OSError("unreadable")

    monkeypatch.delenv("GROQ_TEST_KEY", raising=False)
    monkeypatch.setattr(factory, "load_env_overrides", boom)
    assert factory.resolve_secret("GROQ_TEST_KEY") == ""
