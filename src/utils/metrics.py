"""Lightweight metrics reporting utilities for the News Collector.

This module intentionally keeps the implementation minimal so that unit tests
can validate that we emit the right telemetry events without requiring a real
StatsD or OpenTelemetry backend. The API mimics a subset of common metrics
client interfaces and stores emitted events in memory for observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MetricEvent:
    """Represents a single metric emission."""

    name: str
    value: float
    attributes: Dict[str, Any]


class MetricsReporter:
    """Simple in-process metrics reporter used during development and tests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: List[MetricEvent] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def record_ingest(
        self,
        *,
        source_id: str,
        article_count: int,
        latency: float,
        trace_id: str,
        session_id: str,
    ) -> None:
        """Emit counter and latency metrics for a successful ingest."""

        attributes = {
            "source_id": source_id,
            "trace_id": trace_id,
            "session_id": session_id,
        }
        self._emit("collector.ingest.count", article_count, attributes)
        self._emit("collector.ingest.latency", latency, attributes)

    def record_error(
        self,
        *,
        source_id: str,
        error: str,
        trace_id: str,
        session_id: str,
    ) -> None:
        """Emit an error counter for collector failures."""

        attributes = {
            "source_id": source_id,
            "trace_id": trace_id,
            "session_id": session_id,
            "error": error,
        }
        self._emit("collector.ingest.error", 1, attributes)

    def snapshot(self) -> List[MetricEvent]:
        """Return a copy of the emitted events for inspection."""

        with self._lock:
            return list(self._events)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _emit(self, name: str, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
        event = MetricEvent(name=name, value=value, attributes=attributes or {})
        with self._lock:
            self._events.append(event)


_metrics_reporter: Optional[MetricsReporter] = None


def get_metrics_reporter() -> MetricsReporter:
    """Return a process-wide singleton metrics reporter."""

    global _metrics_reporter
    if _metrics_reporter is None:
        _metrics_reporter = MetricsReporter()
    return _metrics_reporter

