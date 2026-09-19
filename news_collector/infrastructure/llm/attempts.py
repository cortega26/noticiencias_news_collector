"""Per-attempt bookkeeping for the LLM provider chain.

Three small, process-wide concerns kept out of ``FallbackProvider``:

* provider identity (``provider_name`` / ``provider_key``);
* a *blocked* registry — providers disabled for the process (bad credentials)
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
from news_collector.infrastructure.llm.rate_limiter import redact_message
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
_DISABLED: Dict[str, str] = {}
_COOLDOWN_UNTIL: Dict[str, float] = {}

MAX_COOLDOWN_S = 300.0
DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0


def blocked_reason(provider: Any) -> Optional[str]:
    """Why the provider must be skipped right now, or ``None`` if it may run."""
    key = provider_key(provider)
    with _LOCK:
        if key in _DISABLED:
            return f"disabled: {_DISABLED[key]}"
        until = _COOLDOWN_UNTIL.get(key, 0.0)
        if until > time.monotonic():
            return f"rate-limit cooldown ({until - time.monotonic():.0f}s left)"
        _COOLDOWN_UNTIL.pop(key, None)
    return None


def disable_provider(provider: Any, reason: str) -> bool:
    """Disable for the process. Returns True only the first time (log once)."""
    key = provider_key(provider)
    with _LOCK:
        first = key not in _DISABLED
        _DISABLED[key] = reason
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
    latency_ms: int
    failover_index: int
    error: Optional[str] = None
    ts: float = 0.0

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
    record = AttemptRecord(
        provider=provider_name(provider),
        model=getattr(provider, "model", None),
        purpose=purpose,
        ok=ok,
        kind=kind,
        latency_ms=int((time.monotonic() - started) * 1000),
        failover_index=failover_index,
        error=redact_message(str(error))[:300] if error is not None else None,
        ts=time.time(),
    )
    (logger.info if ok else logger.warning)(record.as_event())
    for sink in list(_SINKS):
        try:
            sink(record)
        except Exception as sink_err:  # noqa: BLE001 - metrics must never break calls
            logger.debug("LLM attempt sink failed: {}", sink_err)
    return record
