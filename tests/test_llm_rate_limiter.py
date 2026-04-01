"""
Tests for LLM rate limiter, circuit breaker, secret redaction, and provider 429 handling.
"""

import asyncio
import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from news_collector.infrastructure.llm.rate_limiter import (
    CircuitBreaker,
    CircuitState,
    LLMRateLimitConfig,
    LLMRateLimiter,
    parse_retry_after,
    redact_message,
    redact_url,
)

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    def test_redact_url_removes_api_key(self):
        url = "https://api.example.com/v1/models/foo:gen?key=AIzaSyABCDEFG12345"
        assert "AIzaSyABCDEFG12345" not in redact_url(url)
        assert "key=[REDACTED]" in redact_url(url)

    def test_redact_url_preserves_other_params(self):
        url = "https://api.example.com/v1?key=SECRET&alt=sse"
        result = redact_url(url)
        assert "SECRET" not in result
        assert "alt=sse" in result

    def test_redact_url_no_key(self):
        url = "https://api.example.com/v1/models/foo"
        assert redact_url(url) == url

    def test_redact_message_embedded_url(self):
        msg = "HTTP 429: https://api.example.com/v1?key=SECRET123 rate limited"
        result = redact_message(msg)
        assert "SECRET123" not in result
        assert "key=[REDACTED]" in result
        assert "429" in result

    def test_redact_message_no_secret(self):
        msg = "Connection refused"
        assert redact_message(msg) == msg


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(threshold=3, cooldown=10.0)
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    def test_opens_after_threshold_consecutive_429s(self):
        cb = CircuitBreaker(threshold=3, cooldown=60.0)
        cb.record_rate_limit()
        cb.record_rate_limit()
        assert not cb.is_open  # 2 < 3
        cb.record_rate_limit()
        assert cb.is_open  # 3 >= 3

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(threshold=3, cooldown=60.0)
        cb.record_rate_limit()
        cb.record_rate_limit()
        cb.record_success()
        # Counter reset — 3 more needed
        cb.record_rate_limit()
        cb.record_rate_limit()
        assert not cb.is_open

    def test_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.1)
        cb.record_rate_limit()
        assert cb.is_open
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_success_after_half_open_closes(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.1)
        cb.record_rate_limit()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_non_429_error_does_not_trip(self):
        cb = CircuitBreaker(threshold=2, cooldown=60.0)
        cb.record_error()
        cb.record_error()
        cb.record_error()
        assert not cb.is_open

    def test_reset(self):
        cb = CircuitBreaker(threshold=1, cooldown=60.0)
        cb.record_rate_limit()
        assert cb.is_open
        cb.reset()
        assert not cb.is_open

    def test_thread_safety(self):
        cb = CircuitBreaker(threshold=50, cooldown=60.0)
        errors = []

        def hammer():
            try:
                for _ in range(25):
                    cb.record_rate_limit()
                    cb.record_success()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# LLMRateLimiter
# ---------------------------------------------------------------------------


class TestLLMRateLimiter:
    def setup_method(self):
        LLMRateLimiter.reset_instance()

    def teardown_method(self):
        LLMRateLimiter.reset_instance()

    def test_singleton(self):
        a = LLMRateLimiter.get_instance()
        b = LLMRateLimiter.get_instance()
        assert a is b

    def test_acquire_sync_returns_false_when_cb_open(self):
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=60.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)
        limiter.circuit_breaker.record_rate_limit()
        assert not limiter.acquire_sync()

    def test_acquire_sync_returns_true_when_closed(self):
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)
        assert limiter.acquire_sync()
        limiter.release_sync()

    def test_semaphore_bounds_concurrency(self):
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=2,
            min_delay_between_requests=0.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)

        # Acquire 2 — should succeed
        assert limiter.acquire_sync()
        assert limiter.acquire_sync()

        # Third acquire blocks — test with a timeout thread
        acquired = [False]

        def try_acquire():
            acquired[0] = limiter._semaphore.acquire(timeout=0.2)

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join()
        assert not acquired[0]  # couldn't acquire within timeout

        # Release one — now it should be available
        limiter.release_sync()
        assert limiter._semaphore.acquire(timeout=0.5)
        # Cleanup
        limiter.release_sync()
        limiter.release_sync()

    @pytest.mark.asyncio
    async def test_acquire_async_returns_false_when_cb_open(self):
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=60.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)
        limiter.circuit_breaker.record_rate_limit()
        result = await limiter.acquire_async()
        assert not result


# ---------------------------------------------------------------------------
# parse_retry_after
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    def test_numeric(self):
        assert parse_retry_after("30") == 30.0

    def test_float(self):
        assert parse_retry_after("1.5") == 1.5

    def test_none(self):
        assert parse_retry_after(None) is None

    def test_garbage(self):
        assert parse_retry_after("not-a-number") is None


# ---------------------------------------------------------------------------
# PreScorer circuit breaker integration
# ---------------------------------------------------------------------------


class TestPreScorerCircuitBreakerIntegration:
    def setup_method(self):
        LLMRateLimiter.reset_instance()

    def teardown_method(self):
        LLMRateLimiter.reset_instance()

    def test_prescorer_falls_back_to_fifo_when_cb_open(self):
        """When circuit breaker is open, PreScorer should return FIFO without calling LLM."""
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=60.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)

        # Trip the breaker
        limiter.circuit_breaker.record_rate_limit()
        assert limiter.circuit_breaker.is_open

        # Create PreScorer with a mock LLM that should NOT be called
        mock_llm = MagicMock()
        mock_llm.model = "test-model:latest"

        from news_collector.scoring.pre_scorer import PreScorer

        scorer = PreScorer(llm_client=mock_llm)

        candidates = [
            {"title": f"Article {i}", "summary": f"Summary {i}"} for i in range(10)
        ]
        result = scorer.select_top_candidates(candidates, limit=3)

        # LLM should not have been called
        mock_llm.generate_sync.assert_not_called()
        # Should return first 3 (FIFO)
        assert len(result) == 3
        assert result == candidates[:3]

    def test_prescorer_calls_llm_when_cb_closed(self):
        """When circuit breaker is closed, PreScorer should attempt LLM call."""
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
        )
        LLMRateLimiter.get_instance(cfg)

        mock_llm = MagicMock()
        mock_llm.model = "test-model:latest"
        mock_llm.generate_sync.return_value = {"selected_indices": [2, 0, 1]}

        from news_collector.scoring.pre_scorer import PreScorer

        scorer = PreScorer(llm_client=mock_llm)

        candidates = [
            {"title": f"Article {i}", "summary": f"Summary {i}"} for i in range(5)
        ]
        result = scorer.select_top_candidates(candidates, limit=3)

        mock_llm.generate_sync.assert_called_once()
        assert len(result) == 3

    def test_prescorer_handles_rate_limit_error(self):
        """PreScorer should catch RateLimitError and fall back to FIFO."""
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
        )
        LLMRateLimiter.get_instance(cfg)

        from news_collector.infrastructure.llm.provider import RateLimitError

        mock_llm = MagicMock()
        mock_llm.model = "test-model:latest"
        mock_llm.generate_sync.side_effect = RateLimitError("circuit breaker open")

        from news_collector.scoring.pre_scorer import PreScorer

        scorer = PreScorer(llm_client=mock_llm)

        candidates = [
            {"title": f"Article {i}", "summary": f"Summary {i}"} for i in range(10)
        ]
        result = scorer.select_top_candidates(candidates, limit=3)

        assert len(result) == 3
        assert result == candidates[:3]


# ---------------------------------------------------------------------------
# CognitiveScorer circuit breaker integration
# ---------------------------------------------------------------------------


class TestCognitiveScorerCircuitBreakerIntegration:
    def setup_method(self):
        LLMRateLimiter.reset_instance()

    def teardown_method(self):
        LLMRateLimiter.reset_instance()

    def test_check_budget_returns_false_when_cb_open(self):
        """CognitiveScorer._check_budget() should return False when breaker is open."""
        cfg = LLMRateLimitConfig(
            max_concurrent_requests=5,
            min_delay_between_requests=0.0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=60.0,
        )
        limiter = LLMRateLimiter.get_instance(cfg)

        mock_llm = MagicMock()
        mock_llm.model = "test-model:latest"

        from news_collector.scoring.cognitive_scorer import CognitiveScorer

        scorer = CognitiveScorer(llm_client=mock_llm)
        scorer.is_llm_healthy = True

        # Trip breaker
        limiter.circuit_breaker.record_rate_limit()
        assert not scorer._check_budget()
        assert not scorer.is_llm_healthy


# ---------------------------------------------------------------------------
# GeminiProvider secret redaction in error paths
# ---------------------------------------------------------------------------


class TestGeminiProviderSecretRedaction:
    def test_error_messages_do_not_contain_api_key(self):
        """Verify that RateLimitError messages have the key redacted."""
        from news_collector.infrastructure.llm.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="AIzaSyTOPSECRET", model="gemini-2.5-flash")

        # The URL construction embeds the key
        url = provider._endpoint_url("gemini-2.5-flash")
        assert "AIzaSyTOPSECRET" in url  # key IS in the real URL

        # But the redact_url helper strips it
        assert "AIzaSyTOPSECRET" not in redact_url(url)

    def test_check_health_does_not_leak_key(self):
        """check_health error messages should not contain the API key."""
        import requests as req_mod
        from news_collector.infrastructure.llm.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="AIzaSyTOPSECRET", model="gemini-2.5-flash")

        # Simulate a network error whose message contains the URL (with key)
        err = req_mod.ConnectionError(
            f"Connection refused: https://api.example.com?key=AIzaSyTOPSECRET"
        )
        with patch(
            "news_collector.infrastructure.llm.gemini_provider.requests.get",
            side_effect=err,
        ):
            healthy, msg = provider.check_health()
            assert not healthy
            assert "AIzaSyTOPSECRET" not in msg
