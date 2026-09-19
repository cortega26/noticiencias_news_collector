"""Failure taxonomy for LLM provider calls.

One place decides what a failed attempt *means* so the fallback chain, the
logs and (later) the metrics all agree. Each kind maps to a policy:

=================  ===========  ===========================================
kind               fail over?   provider policy
=================  ===========  ===========================================
TIMEOUT            yes          counts against provider health
HTTP_5XX           yes          counts against provider health
RATE_LIMITED       yes          cool the provider down (honors Retry-After)
AUTH               yes          disable for the process (bad/expired key)
EMPTY_RESPONSE     yes          counts against provider health
INVALID_JSON       yes          counts against provider health
DEGRADED_SKIP      yes          already degraded; not a new failure
CLIENT_ERROR       yes          our request was rejected; not provider health
UNKNOWN            yes          counts against provider health
=================  ===========  ===========================================
"""

from __future__ import annotations

import enum
from typing import Optional

import httpx
import requests

from news_collector.infrastructure.llm.nvidia_provider import (
    ProviderDegradedError,
)
from news_collector.infrastructure.llm.nvidia_provider import (
    RateLimitError as _NimRateLimitError,
)
from news_collector.infrastructure.llm.provider import (
    RateLimitError as _OllamaRateLimitError,
)


class FailureKind(str, enum.Enum):
    TIMEOUT = "timeout"
    HTTP_5XX = "http_5xx"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    EMPTY_RESPONSE = "empty_response"
    INVALID_JSON = "invalid_json"
    DEGRADED_SKIP = "degraded_skip"
    CLIENT_ERROR = "client_error"
    UNKNOWN = "unknown"


class EmptyResponseError(ValueError):
    """A provider answered successfully but with no usable content."""

    def __init__(self, kind: FailureKind = FailureKind.EMPTY_RESPONSE) -> None:
        super().__init__(f"provider returned {kind.value}")
        self.kind = kind


# Kinds that say nothing about the provider's own health.
_NOT_PROVIDER_FAULT = frozenset({FailureKind.CLIENT_ERROR, FailureKind.DEGRADED_SKIP})


def _status_kind(status: Optional[int]) -> FailureKind:
    if status in (401, 403):
        return FailureKind.AUTH
    if status == 429:
        return FailureKind.RATE_LIMITED
    if status is not None and status >= 500:
        return FailureKind.HTTP_5XX
    if status is not None and 400 <= status < 500:
        return FailureKind.CLIENT_ERROR
    return FailureKind.UNKNOWN


def classify_exception(exc: BaseException) -> FailureKind:
    """Map any exception raised by a provider call to a :class:`FailureKind`."""
    if isinstance(exc, EmptyResponseError):
        return exc.kind
    if isinstance(exc, ProviderDegradedError):
        return FailureKind.DEGRADED_SKIP
    if isinstance(exc, (_NimRateLimitError, _OllamaRateLimitError)):
        return FailureKind.RATE_LIMITED
    if isinstance(exc, (requests.Timeout, httpx.TimeoutException, TimeoutError)):
        return FailureKind.TIMEOUT
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return _status_kind(None if response is None else response.status_code)
    if isinstance(exc, httpx.HTTPStatusError):
        return _status_kind(exc.response.status_code)
    return FailureKind.UNKNOWN


def is_provider_fault(kind: FailureKind) -> bool:
    """True when the failure should count against the provider's health."""
    return kind not in _NOT_PROVIDER_FAULT


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Best-effort ``Retry-After`` (seconds) carried by a rate-limit failure."""
    explicit = getattr(exc, "retry_after", None)
    if isinstance(explicit, (int, float)):
        return float(explicit)
    response = getattr(exc, "response", None)
    # NB: compare with None — ``requests.Response`` is falsy for 4xx/5xx.
    header = None if response is None else response.headers.get("Retry-After")
    try:
        return float(header) if header is not None else None
    except (TypeError, ValueError):
        return None
