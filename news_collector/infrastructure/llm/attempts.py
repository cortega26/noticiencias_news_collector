"""Per-attempt bookkeeping for the LLM provider chain.

Three small, process-wide concerns kept out of ``FallbackProvider``:

* provider identity (``provider_name`` / ``provider_key``);
* a *blocked* registry — providers disabled for the process (rejected credentials, temporarily)
  or cooling down after a rate limit — shared by every chain instance, since
  each caller builds its own ``FallbackProvider``;
* an ``AttemptRecord`` stream: one structured log event per attempt plus
  optional sinks (e.g. a metrics store) that are strictly fail-open.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

from news_collector.infrastructure.llm.failure_kinds import FailureKind
from news_collector.infrastructure.llm.rate_limiter import queue_wait_s, redact_message
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.attempts")

_DEFAULT_NAMES = {
    "NvidiaProvider": "nvidia",
    "GeminiProvider": "gemini",
    "OllamaProvider": "ollama",
}


def provider_name(provider: Any) -> str:
    """Stable short name (``nvidia``, ``groq``, ...) used in logs and config."""
    explicit = getattr(provider, "name", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    cls = provider.__class__.__name__
    return str(_DEFAULT_NAMES.get(cls, cls.lower()))


def provider_key(provider: Any) -> str:
    """Identity for process-wide state: name + endpoint + model."""
    return "|".join(
        str(getattr(provider, attr, "") or "") for attr in ("name", "base_url", "model")
    ) or provider_name(provider)


# --------------------------------------------------------------------- blocking

_LOCK = threading.Lock()
_DISABLED: Dict[str, tuple[str, float]] = {}
_COOLDOWN_UNTIL: Dict[str, float] = {}

MAX_COOLDOWN_S = 300.0
# A rejected credential is retried after this long: long enough not to spam a
# revoked key, short enough that a rotation heals without a restart.
AUTH_DISABLE_S = 3600.0
DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0


def blocked_reason(provider: Any) -> Optional[str]:
    """Why the provider must be skipped right now, or ``None`` if it may run."""
    key = provider_key(provider)
    with _LOCK:
        disabled = _DISABLED.get(key)
        if disabled:
            reason, until_disabled = disabled
            if until_disabled > time.monotonic():
                return f"disabled: {reason}"
            _DISABLED.pop(key, None)
        until = _COOLDOWN_UNTIL.get(key, 0.0)
        if until > time.monotonic():
            return f"rate-limit cooldown ({until - time.monotonic():.0f}s left)"
        _COOLDOWN_UNTIL.pop(key, None)
    return None


def disable_provider(
    provider: Any, reason: str, seconds: float = AUTH_DISABLE_S
) -> bool:
    """Disable for ``seconds``. Returns True only when newly disabled (log once)."""
    key = provider_key(provider)
    now = time.monotonic()
    with _LOCK:
        current = _DISABLED.get(key)
        first = current is None or current[1] <= now
        _DISABLED[key] = (reason, now + seconds)
    return first


def cool_down_provider(provider: Any, seconds: Optional[float]) -> float:
    """Skip the provider for ``seconds`` (capped). Returns the applied delay."""
    delay = min(max(seconds or DEFAULT_RATE_LIMIT_COOLDOWN_S, 1.0), MAX_COOLDOWN_S)
    with _LOCK:
        _COOLDOWN_UNTIL[provider_key(provider)] = time.monotonic() + delay
    return delay


def reset_state() -> None:
    """Clear process-wide state (tests / long-lived services)."""
    with _LOCK:
        _DISABLED.clear()
        _COOLDOWN_UNTIL.clear()


# ---------------------------------------------------------------------- records


@dataclass(frozen=True)
class AttemptRecord:
    """One provider attempt inside a ``FallbackProvider`` call."""

    provider: str
    model: Optional[str]
    purpose: str
    ok: bool
    kind: Optional[FailureKind]
    latency_ms: int  # service time (queue wait excluded)
    failover_index: int
    error: Optional[str] = None
    ts: float = 0.0
    queue_wait_ms: int = 0

    def as_event(self) -> Dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value if self.kind else None
        return {"event": "llm.attempt", "details": data}


AttemptSink = Callable[[AttemptRecord], None]
_SINKS: List[AttemptSink] = []


def register_attempt_sink(sink: AttemptSink) -> None:
    if sink not in _SINKS:
        _SINKS.append(sink)


def unregister_attempt_sink(sink: AttemptSink) -> None:
    if sink in _SINKS:
        _SINKS.remove(sink)


def emit_attempt(
    provider: Any,
    *,
    purpose: str,
    ok: bool,
    kind: Optional[FailureKind],
    started: float,
    failover_index: int,
    error: Optional[BaseException] = None,
) -> AttemptRecord:
    """Log the attempt as a structured event and fan out to sinks (fail-open)."""
    total_ms = int((time.monotonic() - started) * 1000)
    wait_ms = min(int(queue_wait_s() * 1000), total_ms)
    record = AttemptRecord(
        provider=provider_name(provider),
        model=getattr(provider, "model", None),
        purpose=purpose,
        ok=ok,
        kind=kind,
        latency_ms=total_ms - wait_ms,
        failover_index=failover_index,
        error=redact_message(str(error))[:300] if error is not None else None,
        ts=time.time(),
        queue_wait_ms=wait_ms,
    )
    quiet = ok or kind is FailureKind.DEGRADED_SKIP  # skips repeat per call
    (logger.info if quiet else logger.warning)(record.as_event())
    for sink in list(_SINKS):
        try:
            sink(record)
        except Exception as sink_err:  # noqa: BLE001 - metrics must never break calls
            logger.debug("LLM attempt sink failed: {}", sink_err)
    return record
