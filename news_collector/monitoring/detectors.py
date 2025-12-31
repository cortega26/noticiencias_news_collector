"""Anomaly detectors for source health, schema drift, and content shifts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import log2
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence
from zoneinfo import ZoneInfo

from .common import Anomaly, Metric, Severity

UTC = ZoneInfo("UTC")


@dataclass(slots=True)
class SourceBaseline:
    """Baseline expectations for a news source."""

    expected_articles_per_window: float
    max_gap_hours: float
    language_distribution: Mapping[str, float]
    topic_distribution: Mapping[str, float]


@dataclass(slots=True)
class SourceWindowStats:
    """Aggregated stats for a source within a monitoring window."""

    source_id: str
    window_start: datetime
    window_end: datetime
    articles_found: int
    expected_count: int
    last_article_at: Optional[datetime]
    consecutive_failures: int
    schema_violations: int
    languages: Mapping[str, int] = field(default_factory=dict)
    topics: Mapping[str, int] = field(default_factory=dict)

    def language_distribution(self) -> Mapping[str, float]:
        total = sum(self.languages.values())
        if total == 0:
            return {}
        return {lang: count / total for lang, count in self.languages.items()}

    def topic_distribution(self) -> Mapping[str, float]:
        total = sum(self.topics.values())
        if total == 0:
            return {}
        return {topic: count / total for topic, count in self.topics.items()}


@dataclass(slots=True)
class SourceOutageDetectorConfig:
    warn_ratio: float = 0.5
    alert_ratio: float = 0.2
    consecutive_failure_threshold: int = 3


class SourceOutageDetector:
    """Detects outages or severe degradation for ingestion sources."""

    def __init__(
        self,
        config: Optional[SourceOutageDetectorConfig] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self._config = config or SourceOutageDetectorConfig()
        self._now = now or datetime.now(tz=UTC)

    def evaluate(
        self,
        stats: Sequence[SourceWindowStats],
        baselines: Mapping[str, SourceBaseline],
    ) -> Dict[str, List]:
        anomalies: List[Anomaly] = []
        metrics: List[Metric] = []
        for window in stats:
            baseline = baselines.get(window.source_id)
            if not baseline:
                continue
            ratio = (
                window.articles_found / baseline.expected_articles_per_window
                if baseline.expected_articles_per_window > 0
                else 1.0
            )
            metrics.append(
                Metric(
                    name="source.ingestion_ratio",
                    value=ratio,
                    labels={
                        "source_id": window.source_id,
                    },
                )
            )
            severity: Optional[Severity] = None
            message: Optional[str] = None
            if (
                window.consecutive_failures
                >= self._config.consecutive_failure_threshold
            ):
                severity = Severity.CRITICAL
                message = f"Source {window.source_id} has {window.consecutive_failures} consecutive fetch failures"
            elif ratio <= self._config.alert_ratio:
                severity = Severity.CRITICAL
                message = (
                    f"Source {window.source_id} delivered {window.articles_found} articles vs. "
                    f"expected {baseline.expected_articles_per_window:.1f}"
                )
            elif ratio <= self._config.warn_ratio:
                severity = Severity.WARNING
                message = f"Source {window.source_id} volume dropped to {ratio:.2f} of baseline"
            last_seen_gap = None
            if window.last_article_at:
                last_seen_gap = (
                    self._now - window.last_article_at
                ).total_seconds() / 3600
                metrics.append(
                    Metric(
                        name="source.last_seen_gap_hours",
                        value=last_seen_gap,
                        labels={"source_id": window.source_id},
                    )
                )
                if last_seen_gap > baseline.max_gap_hours:
                    gap_message = (
                        f"Source {window.source_id} idle for {last_seen_gap:.1f}h"
                        f" (threshold {baseline.max_gap_hours}h)"
                    )
                    if severity is None:
                        severity = Severity.CRITICAL
                        message = gap_message
                    else:
                        message = (
                            f"{message}; {gap_message}" if message else gap_message
                        )
            if message and severity:
                anomalies.append(
                    Anomaly(
                        detector="source_outage",
                        severity=severity,
                        message=message,
                        labels={
                            "source_id": window.source_id,
                        },
                        observations={
                            "ratio": round(ratio, 3),
                            "articles_found": window.articles_found,
                            "expected": baseline.expected_articles_per_window,
                            "consecutive_failures": window.consecutive_failures,
                            "last_seen_gap_hours": round(last_seen_gap or 0.0, 2),
                        },
                    )
                )
        return {"metrics": metrics, "anomalies": anomalies}


@dataclass(slots=True)
class SchemaExpectation:
    """Expected schema definition for normalized articles."""

    required_fields: Mapping[str, type]
    optional_fields: Mapping[str, type] = field(default_factory=dict)
    max_missing_ratio: float = 0.05
    max_type_mismatch_ratio: float = 0.02


class SchemaDriftDetector:
    """Detects schema drift based on article payload samples."""

    def __init__(self, expectation: SchemaExpectation) -> None:
        self._expectation = expectation

    def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Dict[str, List]:
        if not samples:
            return {"metrics": [], "anomalies": []}
        total = len(samples)
        missing_counts: MutableMapping[str, int] = {
            key: 0 for key in self._expectation.required_fields
        }
        type_mismatch_counts: MutableMapping[str, int] = {
            key: 0 for key in self._expectation.required_fields
        }
        optional_mismatch: MutableMapping[str, int] = {
            key: 0 for key in self._expectation.optional_fields
        }
        for sample in samples:
            for field_name, field_type in self._expectation.required_fields.items():
                if field_name not in sample or sample[field_name] is None:
                    missing_counts[field_name] += 1
                    continue
                if not isinstance(sample[field_name], field_type):
                    type_mismatch_counts[field_name] += 1
            for field_name, field_type in self._expectation.optional_fields.items():
                if field_name in sample and sample[field_name] is not None:
                    if not isinstance(sample[field_name], field_type):
                        optional_mismatch[field_name] += 1
        anomalies: List[Anomaly] = []
        metrics: List[Metric] = []
        for field_name, count in missing_counts.items():
            ratio = count / total
            metrics.append(
                Metric(
                    name="schema.missing_ratio",
                    value=ratio,
                    labels={"field": field_name},
                )
            )
            if ratio > self._expectation.max_missing_ratio:
                anomalies.append(
                    Anomaly(
                        detector="schema_drift",
                        severity=Severity.CRITICAL,
                        message=f"Field '{field_name}' missing in {ratio:.1%} of samples",
                        labels={"field": field_name},
                        observations={"missing_ratio": round(ratio, 3)},
                    )
                )
        for field_name, count in type_mismatch_counts.items():
            ratio = count / total
            metrics.append(
                Metric(
                    name="schema.type_mismatch_ratio",
                    value=ratio,
                    labels={"field": field_name},
                )
            )
            if ratio > self._expectation.max_type_mismatch_ratio:
                anomalies.append(
                    Anomaly(
                        detector="schema_drift",
                        severity=Severity.WARNING,
                        message=f"Field '{field_name}' has {ratio:.1%} type mismatches",
                        labels={"field": field_name},
                        observations={"type_mismatch_ratio": round(ratio, 3)},
                    )
                )
        for field_name, count in optional_mismatch.items():
            ratio = count / total
            metrics.append(
                Metric(
                    name="schema.optional_type_mismatch_ratio",
                    value=ratio,
                    labels={"field": field_name},
                )
            )
        return {"metrics": metrics, "anomalies": anomalies}


@dataclass(slots=True)
class ContentShiftThresholds:
    language_divergence_alert: float = 0.25
    topic_divergence_alert: float = 0.35
    language_divergence_warn: float = 0.15
    topic_divergence_warn: float = 0.25


class ContentShiftDetector:
    """Detects shifts in language/topic distributions."""

    def __init__(
        self,
        thresholds: Optional[ContentShiftThresholds] = None,
    ) -> None:
        self._thresholds = thresholds or ContentShiftThresholds()

    def evaluate(
        self,
        stats: Sequence[SourceWindowStats],
        baselines: Mapping[str, SourceBaseline],
    ) -> Dict[str, List]:
        if not stats:
            return {"metrics": [], "anomalies": []}
        aggregated_languages: MutableMapping[str, int] = {}
        aggregated_topics: MutableMapping[str, int] = {}
        baseline_language: MutableMapping[str, float] = {}
        baseline_topic: MutableMapping[str, float] = {}
        for window in stats:
            for lang, count in window.languages.items():
                aggregated_languages[lang] = aggregated_languages.get(lang, 0) + count
            for topic, count in window.topics.items():
                aggregated_topics[topic] = aggregated_topics.get(topic, 0) + count
            baseline = baselines.get(window.source_id)
            if baseline:
                for lang, share in baseline.language_distribution.items():
                    baseline_language[lang] = baseline_language.get(lang, 0.0) + share
                for topic, share in baseline.topic_distribution.items():
                    baseline_topic[topic] = baseline_topic.get(topic, 0.0) + share
        aggregated_language_dist = _normalize_counts(aggregated_languages)
        aggregated_topic_dist = _normalize_counts(aggregated_topics)
        baseline_language_dist = _normalize_shares(baseline_language)
        baseline_topic_dist = _normalize_shares(baseline_topic)
        language_divergence = _jensen_shannon_divergence(
            aggregated_language_dist, baseline_language_dist
        )
        topic_divergence = _jensen_shannon_divergence(
            aggregated_topic_dist, baseline_topic_dist
        )
        metrics = [
            Metric(name="content.language_jsd", value=language_divergence),
            Metric(name="content.topic_jsd", value=topic_divergence),
        ]
        anomalies: List[Anomaly] = []
        if language_divergence >= self._thresholds.language_divergence_alert:
            anomalies.append(
                Anomaly(
                    detector="content_shift",
                    severity=Severity.CRITICAL,
                    message=f"Language mix diverged (JSD={language_divergence:.2f})",
                    observations={
                        "language_divergence": round(language_divergence, 3),
                        "observed": aggregated_language_dist,
                        "baseline": baseline_language_dist,
                    },
                )
            )
        elif language_divergence >= self._thresholds.language_divergence_warn:
            anomalies.append(
                Anomaly(
                    detector="content_shift",
                    severity=Severity.WARNING,
                    message=f"Language mix drift detected (JSD={language_divergence:.2f})",
                    observations={
                        "language_divergence": round(language_divergence, 3),
                        "observed": aggregated_language_dist,
                        "baseline": baseline_language_dist,
                    },
                )
            )
        if topic_divergence >= self._thresholds.topic_divergence_alert:
            anomalies.append(
                Anomaly(
                    detector="content_shift",
                    severity=Severity.CRITICAL,
                    message=f"Topic mix diverged (JSD={topic_divergence:.2f})",
                    observations={
                        "topic_divergence": round(topic_divergence, 3),
                        "observed": aggregated_topic_dist,
                        "baseline": baseline_topic_dist,
                    },
                )
            )
        elif topic_divergence >= self._thresholds.topic_divergence_warn:
            anomalies.append(
                Anomaly(
                    detector="content_shift",
                    severity=Severity.WARNING,
                    message=f"Topic mix drift detected (JSD={topic_divergence:.2f})",
                    observations={
                        "topic_divergence": round(topic_divergence, 3),
                        "observed": aggregated_topic_dist,
                        "baseline": baseline_topic_dist,
                    },
                )
            )
        return {"metrics": metrics, "anomalies": anomalies}


def _normalize_counts(counts: Mapping[str, int]) -> Mapping[str, float]:
    total = sum(counts.values())
    if total == 0:
        return {}
    return {key: value / total for key, value in counts.items() if value > 0}


def _normalize_shares(shares: Mapping[str, float]) -> Mapping[str, float]:
    total = sum(shares.values())
    if total == 0:
        return {}
    return {key: value / total for key, value in shares.items() if value > 0}


def _jensen_shannon_divergence(
    observed: Mapping[str, float], baseline: Mapping[str, float]
) -> float:
    if not observed and not baseline:
        return 0.0
    keys = set(observed) | set(baseline)
    if not keys:
        return 0.0
    m: Dict[str, float] = {}
    for key in keys:
        m[key] = 0.5 * observed.get(key, 0.0) + 0.5 * baseline.get(key, 0.0)
    divergence = 0.0
    for key in keys:
        o = observed.get(key, 0.0)
        b = baseline.get(key, 0.0)
        if o > 0:
            divergence += 0.5 * _kl_term(o, m[key])
        if b > 0:
            divergence += 0.5 * _kl_term(b, m[key])
    return divergence


def _kl_term(p: float, q: float) -> float:
    if p == 0 or q == 0:
        return 0.0
    return p * log2(p / q)
