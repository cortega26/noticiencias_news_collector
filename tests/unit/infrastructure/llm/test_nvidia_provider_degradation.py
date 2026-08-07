"""
Tests for NvidiaProvider degradation failover (plan 051).

Covers:
- threshold arms degradation after N consecutive failures
- no network call / no sleep when degraded (fail fast via ProviderDegradedError)
- cooldown expiry + successful health probe re-arms the provider
- failed probe extends the degraded window
- successful LLM call resets the failure counter
- FallbackProvider skips degraded providers and logs a single warning
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from news_collector.config import settings
from news_collector.infrastructure.llm.nvidia_provider import (
    LLMRateLimiter,
    NvidiaProvider,
    ProviderDegradedError,
    _DEGRADATION_REGISTRY,
)


@pytest.fixture(autouse=True)
def _clear_degradation_registry():
    _DEGRADATION_REGISTRY.clear()
    yield
    _DEGRADATION_REGISTRY.clear()


def _provider(**kwargs) -> NvidiaProvider:
    opts = {
        "api_key": "nvapi-test",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "max_retries": 3,
        "degraded_failure_threshold": 2,
        "degraded_cooldown_seconds": 60.0,
        "degraded_probe_timeout_seconds": 5.0,
    }
    opts.update(kwargs)
    return NvidiaProvider(**opts)


class _Breaker:
    def __init__(self):
        self.is_open = False
        self.record_error = MagicMock()
        self.record_rate_limit = MagicMock()
        self.record_success = MagicMock()


class _FakeLimiter:
    def __init__(self, breaker=None):
        self.breaker = breaker or _Breaker()

    @property
    def circuit_breaker(self):
        return self.breaker

    def acquire_sync(self):
        return True

    def release_sync(self):
        return None

    async def acquire_async(self):
        return True

    def release_async(self):
        return None


class _FakeResp:
    def __init__(self, status: int = 200, payload=None):
        self.status_code = status
        self._payload = payload

    @property
    def headers(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload


def _boom_post(*a, **k):
    raise requests.ReadTimeout("read timed out")


def _set_limiter(monkeypatch) -> _FakeLimiter:
    limiter = _FakeLimiter()
    monkeypatch.setattr(LLMRateLimiter, "get_instance", staticmethod(lambda: limiter))
    monkeypatch.setattr(settings, "LLM_SYSTEM_AVAILABLE", True)
    return limiter


# ---------------------------------------------------------------------------
# Degradation state helpers
# ---------------------------------------------------------------------------


class TestDegradationState:
    def test_fresh_provider_not_degraded(self):
        provider = _provider()
        assert provider.is_degraded() is False

    def test_threshold_arms_degradation_after_n_failures(self):
        provider = _provider(degraded_failure_threshold=2)
        assert provider.is_degraded() is False
        provider._record_failure()
        assert provider.is_degraded() is False
        provider._record_failure()
        assert provider.is_degraded() is True

    def test_success_resets_failure_counter(self):
        provider = _provider(degraded_failure_threshold=2, degraded_window_size=2)
        provider._record_failure()
        provider._record_success()
        provider._record_failure()
        assert provider.is_degraded() is False

    def test_is_degraded_announces_once(self):
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        assert provider.is_degraded() is True
        assert provider.is_degraded() is True
        assert provider._state.degraded_announced is True
        assert provider._state.degraded_announced is True

    def test_success_after_degradation_recovers(self):
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        assert provider.is_degraded() is True
        provider._record_success()
        assert provider.is_degraded() is False
        assert provider._state.degraded_until == 0.0


# ---------------------------------------------------------------------------
# maybe_attempt / half-open probe
# ---------------------------------------------------------------------------


class TestMaybeAttempt:
    def test_healthy_always_attempts(self):
        provider = _provider()
        assert provider.maybe_attempt() is True

    def test_degraded_blocks_attempts(self):
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        assert provider.maybe_attempt() is False

    def test_cooldown_elapsed_healthy_probe_rearms(self, monkeypatch):
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        # Force the degradation window to have elapsed.
        provider._state.degraded_until = time.monotonic() - 1.0
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: _FakeResp(status=200),
        )
        assert provider.maybe_attempt() is True
        assert provider.is_degraded() is False

    def test_cooldown_elapsed_failed_probe_extends_window(self, monkeypatch):
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        provider._state.degraded_until = time.monotonic() - 1.0
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get",
            lambda *a, **k: _FakeResp(status=503),
        )
        assert provider.maybe_attempt() is False
        assert provider.is_degraded() is True
        assert provider._state.degraded_until > time.monotonic()

    def test_probe_uses_configured_timeout(self, monkeypatch):
        provider = _provider(
            degraded_failure_threshold=1, degraded_probe_timeout_seconds=7.0
        )
        provider._record_failure()
        provider._state.degraded_until = time.monotonic() - 1.0
        captured = {}

        def _get(url, headers=None, timeout=None):
            captured["timeout"] = timeout
            return _FakeResp(status=200)

        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.get", _get
        )
        provider.maybe_attempt()
        assert captured["timeout"] == 7.0


# ---------------------------------------------------------------------------
# generate_sync / generate_async integration
# ---------------------------------------------------------------------------


class TestGenerateSyncDegraded:
    def test_degraded_raises_without_network(self, monkeypatch):
        limiter = _set_limiter(monkeypatch)
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        with patch(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post"
        ) as post:
            with pytest.raises(ProviderDegradedError):
                provider.generate_sync("hello")
        post.assert_not_called()

    def test_timeouts_arm_degradation_after_threshold(self, monkeypatch):
        limiter = _set_limiter(monkeypatch)
        provider = _provider(
            degraded_failure_threshold=2,
            max_retries=1,
            degraded_cooldown_seconds=3600.0,
        )
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            _boom_post,
        )
        monkeypatch.setattr(
            NvidiaProvider, "_backoff_delay", staticmethod(lambda a: 0.0)
        )
        with pytest.raises(requests.ReadTimeout):
            provider.generate_sync("hello")
        assert provider.is_degraded() is False  # only 1 failure recorded
        with pytest.raises(requests.ReadTimeout):
            provider.generate_sync("hello")
        assert provider.is_degraded() is True

    def test_success_resets_counter_via_generate(self, monkeypatch):
        limiter = _set_limiter(monkeypatch)
        provider = _provider(degraded_failure_threshold=2)
        payload = {"choices": [{"message": {"content": "ok"}}]}
        monkeypatch.setattr(
            "news_collector.infrastructure.llm.nvidia_provider.requests.post",
            lambda *a, **k: _FakeResp(status=200, payload=payload),
        )
        provider._record_failure()
        out = provider.generate_sync("hello")
        assert out == "ok"
        assert provider.is_degraded() is False


class TestGenerateAsyncDegraded:
    async def test_degraded_raises_without_network(self, monkeypatch):
        limiter = _set_limiter(monkeypatch)
        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        with patch(
            "news_collector.infrastructure.llm.nvidia_provider.httpx.AsyncClient"
        ) as client:
            with pytest.raises(ProviderDegradedError):
                await provider.generate_async("hello")
        client.assert_not_called()

    async def test_network_failures_arm_degradation(self, monkeypatch):
        import httpx

        limiter = _set_limiter(monkeypatch)
        provider = _provider(
            degraded_failure_threshold=2,
            max_retries=1,
            degraded_cooldown_seconds=3600.0,
        )
        exc = httpx.ConnectError("down", request=httpx.Request("POST", "https://x"))

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def post(self, *args, **kwargs):
                raise exc

            async def aclose(self):
                return None

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            NvidiaProvider, "_backoff_delay", staticmethod(lambda a: 0.0)
        )
        with pytest.raises(httpx.ConnectError):
            await provider.generate_async("hello")
        assert provider.is_degraded() is False
        with pytest.raises(httpx.ConnectError):
            await provider.generate_async("hello")
        assert provider.is_degraded() is True


# ---------------------------------------------------------------------------
# FallbackProvider integration
# ---------------------------------------------------------------------------


class TestFallbackSkipsDegraded:
    def test_skips_degraded_and_uses_next(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        calls = {"bad": 0, "good": 0}

        class _Good:
            timeout = 60

            def generate_sync(self, **k):
                calls["good"] += 1
                return "from-good"

            def is_degraded(self):
                return False

        class _Bad:
            timeout = 60

            def generate_sync(self, **k):
                calls["bad"] += 1
                raise AssertionError("must not be called")

            def is_degraded(self):
                return True

        fallback = FallbackProvider([_Bad(), _Good()])
        result = fallback.generate_sync("hello")
        assert result == "from-good"
        assert calls["bad"] == 0
        assert calls["good"] == 1

    def test_skips_degraded_async(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        calls = {"bad": 0, "good": 0}

        class _Good:
            timeout = 60

            async def generate_async(self, **k):
                calls["good"] += 1
                return "from-good"

            def is_degraded(self):
                return False

        class _Bad:
            timeout = 60

            async def generate_async(self, **k):
                calls["bad"] += 1
                raise AssertionError("must not be called")

            def is_degraded(self):
                return True

        fallback = FallbackProvider([_Bad(), _Good()])

        import asyncio

        result = asyncio.run(fallback.generate_async("hello"))
        assert result == "from-good"
        assert calls["bad"] == 0
        assert calls["good"] == 1

    def test_magic_mock_not_treated_as_degraded(self):
        from news_collector.infrastructure.llm.factory import _is_degraded

        mock_provider = MagicMock()
        assert _is_degraded(mock_provider) is False

    def test_real_provider_reports_degraded(self):
        from news_collector.infrastructure.llm.factory import _is_degraded

        provider = _provider(degraded_failure_threshold=1)
        provider._record_failure()
        assert _is_degraded(provider) is True


# ---------------------------------------------------------------------------
# Shared degradation state across instances (plan 053)
# ---------------------------------------------------------------------------


class TestSharedDegradationState:
    def test_two_instances_share_degradation(self):
        a = _provider()
        b = _provider()
        a._record_failure()
        a._record_failure()
        assert b.is_degraded() is True

    def test_different_models_do_not_share_state(self):
        a = _provider(model="nvidia/model-one")
        b = _provider(model="nvidia/model-two")
        a._record_failure()
        a._record_failure()
        assert b.is_degraded() is False

    def test_windowed_non_consecutive_tripping(self):
        # failure, success, failure -> 2 failures within window of 5.
        # Strictly-consecutive counting (plan 051) could never trip here;
        # plan 053's windowed counting must.
        provider = _provider(degraded_failure_threshold=2, degraded_window_size=5)
        provider._record_failure()
        provider._record_success()
        provider._record_failure()
        assert provider.is_degraded() is True

    def test_success_does_not_erase_prior_failures(self):
        # A success after a failure must not wipe earlier failures from the
        # window: failure, success, failure still trips with threshold 2.
        provider = _provider(degraded_failure_threshold=2, degraded_window_size=5)
        provider._record_failure()
        provider._record_success()
        assert provider.is_degraded() is False
        provider._record_failure()
        assert provider.is_degraded() is True

    def test_failure_ages_out_of_window(self):
        # Window size 2 with threshold 2: the first failure ages out once
        # two more outcomes land, so a lone remaining failure never trips.
        provider = _provider(degraded_failure_threshold=2, degraded_window_size=2)
        provider._record_failure()
        provider._record_success()
        provider._record_success()
        assert provider.is_degraded() is False
