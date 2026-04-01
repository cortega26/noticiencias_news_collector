"""
Shared LLM rate limiter with concurrency control, circuit breaker, and secret redaction.

This module is the single point of coordination for all LLM API calls.
It prevents request storms by:
  1. Bounding concurrency via a semaphore (default: 2 concurrent requests).
  2. Enforcing a minimum delay between requests to stay within provider quotas.
  3. Implementing a circuit breaker that opens after consecutive 429s, preventing
     further requests until a cooldown period elapses.
  4. Providing a utility to redact API keys from URLs and error messages.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.rate_limiter")

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

_KEY_PATTERN = re.compile(r"([?&]key=)[^&\s]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Remove API key query parameters from a URL for safe logging."""
    return _KEY_PATTERN.sub(r"\1[REDACTED]", url)


def redact_message(message: str) -> str:
    """Redact any embedded API keys found in an arbitrary log message."""
    return _KEY_PATTERN.sub(r"\1[REDACTED]", message)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LLMRateLimitConfig:
    """Tunable knobs for LLM rate control.  Loaded once from config.toml."""

    max_concurrent_requests: int = 2
    min_delay_between_requests: float = 1.0  # seconds
    circuit_breaker_threshold: int = 3  # consecutive 429s to trip
    circuit_breaker_cooldown: float = 60.0  # seconds before half-open
    max_retries: int = 3
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 30.0
    retry_jitter_max: float = 2.0


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker for a single LLM provider."""

    def __init__(self, threshold: int = 3, cooldown: float = 60.0):
        self._lock = threading.Lock()
        self._threshold = threshold
        self._cooldown = cooldown
        self._consecutive_failures: int = 0
        self._state: str = CircuitState.CLOSED
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._opened_at >= self._cooldown
            ):
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "LLM circuit breaker -> HALF_OPEN (cooldown elapsed, allowing probe)"
                )
            return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            if self._state != CircuitState.CLOSED:
                logger.info("LLM circuit breaker -> CLOSED (success recorded)")
            self._state = CircuitState.CLOSED

    def record_rate_limit(self, retry_after: Optional[float] = None) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                cooldown = (
                    retry_after if retry_after and retry_after > 0 else self._cooldown
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "LLM circuit breaker -> OPEN after {} consecutive 429s (cooldown={:.1f}s)",
                    self._consecutive_failures,
                    cooldown,
                )

    def record_error(self) -> None:
        """Record a non-429 error (does not count toward circuit breaker threshold)."""
        pass

    def reset(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = 0.0


# ---------------------------------------------------------------------------
# Global rate limiter singleton
# ---------------------------------------------------------------------------


class LLMRateLimiter:
    """
    Process-wide rate limiter for all LLM API calls.

    - Semaphore bounds concurrent in-flight requests.
    - Minimum inter-request delay prevents bursts.
    - Circuit breaker stops requests after repeated 429s.
    """

    _instance: Optional["LLMRateLimiter"] = None
    _init_lock = threading.Lock()

    def __init__(self, config: Optional[LLMRateLimitConfig] = None):
        cfg = config or LLMRateLimitConfig()
        self._config = cfg

        # Concurrency control
        self._semaphore = threading.Semaphore(cfg.max_concurrent_requests)
        self._async_semaphore = asyncio.Semaphore(cfg.max_concurrent_requests)

        # Inter-request pacing
        self._min_delay = cfg.min_delay_between_requests
        self._last_request_time: float = 0.0
        self._pacing_lock = threading.Lock()

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            threshold=cfg.circuit_breaker_threshold,
            cooldown=cfg.circuit_breaker_cooldown,
        )

    @classmethod
    def get_instance(
        cls, config: Optional[LLMRateLimitConfig] = None
    ) -> "LLMRateLimiter":
        """Return (or create) the process-wide singleton."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls(config)
                    logger.info(
                        "LLMRateLimiter initialized: max_concurrent={}, min_delay={:.1f}s, "
                        "cb_threshold={}, cb_cooldown={:.1f}s",
                        cls._instance._config.max_concurrent_requests,
                        cls._instance._config.min_delay_between_requests,
                        cls._instance._config.circuit_breaker_threshold,
                        cls._instance._config.circuit_breaker_cooldown,
                    )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton — primarily for tests."""
        with cls._init_lock:
            cls._instance = None

    @property
    def config(self) -> LLMRateLimitConfig:
        return self._config

    # -- Sync API --

    def acquire_sync(self) -> bool:
        """
        Acquire permission to make an LLM request (blocking).
        Returns False if the circuit breaker is open.
        """
        if self.circuit_breaker.is_open:
            return False

        self._semaphore.acquire()
        self._pace_sync()
        return True

    def release_sync(self) -> None:
        self._semaphore.release()

    def _pace_sync(self) -> None:
        with self._pacing_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_delay:
                time.sleep(self._min_delay - elapsed)
            self._last_request_time = time.monotonic()

    # -- Async API --

    async def acquire_async(self) -> bool:
        """
        Acquire permission to make an LLM request (async).
        Returns False if the circuit breaker is open.
        """
        if self.circuit_breaker.is_open:
            return False

        await self._async_semaphore.acquire()
        await self._pace_async()
        return True

    def release_async(self) -> None:
        self._async_semaphore.release()

    async def _pace_async(self) -> None:
        with self._pacing_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            wait = self._min_delay - elapsed
            self._last_request_time = time.monotonic() + max(0.0, wait)
        if wait > 0:
            await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Retry-after parsing
# ---------------------------------------------------------------------------


def parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header into seconds. Returns None if unparseable."""
    if header_value is None:
        return None
    try:
        return float(header_value)
    except (ValueError, TypeError):
        return None
