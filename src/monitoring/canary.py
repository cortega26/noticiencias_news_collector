"""Canary checks and auto-suppression logic for sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Mapping, Optional, Sequence

from zoneinfo import ZoneInfo

from .common import Alert, Anomaly, Severity
from .detectors import SourceWindowStats

UTC = ZoneInfo("UTC")


@dataclass(slots=True)
class CanaryCheck:
    """Represents an automated health probe for a source."""

    source_id: str
    max_latency_ms: float
    max_idle_hours: float
    min_articles: int = 1


@dataclass(slots=True)
class CanaryResult:
    """Outcome from executing a canary check."""

    source_id: str
    latency_ms: float
    articles_found: int
    last_seen_hours: float
    error: Optional[str] = None

    @property
    def healthy(self) -> bool:
        return self.error is None


@dataclass(slots=True)
class SuppressionDecision:
    """Decision to auto-suppress a source."""

    source_id: str
    reason: str
    severity: Severity


class CanaryRunner:
    """Aggregates canary results from window statistics."""

    def __init__(self, checks: Sequence[CanaryCheck]) -> None:
        self._checks = {check.source_id: check for check in checks}

    def execute(self, stats: Sequence[SourceWindowStats]) -> List[CanaryResult]:
        results: List[CanaryResult] = []
        now = datetime.now(tz=UTC)
        for window in stats:
            check = self._checks.get(window.source_id)
            if not check:
                continue
            last_seen_hours = 1e9
            if window.last_article_at:
                last_seen_hours = (now - window.last_article_at).total_seconds() / 3600
            error: Optional[str] = None
            if last_seen_hours > check.max_idle_hours:
                error = f"last article seen {last_seen_hours:.1f}h ago (limit {check.max_idle_hours}h)"
            elif window.articles_found < check.min_articles:
                error = f"only {window.articles_found} article(s) fetched (<{check.min_articles})"
            results.append(
                CanaryResult(
                    source_id=window.source_id,
                    latency_ms=check.max_latency_ms,
                    articles_found=window.articles_found,
                    last_seen_hours=last_seen_hours,
                    error=error,
                )
            )
        return results


class AutoSuppressionManager:
    """Automatically suppresses sources with repeated critical failures."""

    def __init__(
        self,
        failure_threshold: int = 2,
        idle_hours_threshold: float = 48.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._idle_hours_threshold = idle_hours_threshold

    def evaluate(
        self,
        stats: Sequence[SourceWindowStats],
        anomalies: Sequence[Anomaly],
    ) -> List[SuppressionDecision]:
        decisions: List[SuppressionDecision] = []
        by_source: Mapping[str, List[Anomaly]] = {}
        for anomaly in anomalies:
            source_id = anomaly.labels.get("source_id") if anomaly.labels else None
            if not source_id:
                continue
            if source_id not in by_source:
                by_source[source_id] = []
            by_source[source_id].append(anomaly)
        for window in stats:
            source_anomalies = by_source.get(window.source_id, [])
            critical_events = [
                a for a in source_anomalies if a.severity == Severity.CRITICAL
            ]
            last_seen_hours = 0.0
            if window.last_article_at:
                last_seen_hours = (
                    datetime.now(tz=UTC) - window.last_article_at
                ).total_seconds() / 3600
            if (
                len(critical_events) >= self._failure_threshold
                or last_seen_hours >= self._idle_hours_threshold
                or window.consecutive_failures >= self._failure_threshold
            ):
                decisions.append(
                    SuppressionDecision(
                        source_id=window.source_id,
                        reason="Repeated critical anomalies",
                        severity=Severity.CRITICAL,
                    )
                )
        return decisions


def build_canary_alerts(results: Sequence[CanaryResult]) -> List[Alert]:
    alerts: List[Alert] = []
    for result in results:
        if result.error:
            alerts.append(
                Alert(
                    title=f"Canary failure for {result.source_id}",
                    severity=Severity.CRITICAL,
                    runbook_url="https://runbooks.noticiencias/collector-outage",
                    targets=["pager", "slack://#news-alerts"],
                    labels={"source_id": result.source_id},
                    annotations={
                        "error": result.error,
                        "last_seen_hours": round(result.last_seen_hours, 2),
                    },
                )
            )
    return alerts
