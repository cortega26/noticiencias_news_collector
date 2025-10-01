from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import json

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monitoring import (
    AutoSuppressionManager,
    CanaryCheck,
    CanaryRunner,
    ContentShiftDetector,
    MonitoringDataset,
    SchemaDriftDetector,
    SchemaExpectation,
    SourceBaseline,
    SourceOutageDetector,
    SourceOutageDetectorConfig,
    SourceWindowStats,
    default_quality_report_generator,
)
from monitoring.canary import build_canary_alerts
from monitoring.common import Severity
from monitoring.detectors import ContentShiftThresholds
from monitoring.io import load_monitoring_dataset


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)


def make_source_window(
    source_id: str,
    articles: int,
    failures: int,
    last_seen_hours: float,
    languages: dict[str, int] | None = None,
    topics: dict[str, int] | None = None,
) -> SourceWindowStats:
    now = _now()
    last_article = (
        now - timedelta(hours=last_seen_hours) if last_seen_hours is not None else None
    )
    return SourceWindowStats(
        source_id=source_id,
        window_start=now - timedelta(hours=6),
        window_end=now,
        articles_found=articles,
        expected_count=6,
        last_article_at=last_article,
        consecutive_failures=failures,
        schema_violations=0,
        languages=languages or {"en": articles},
        topics=topics or {"biology": articles},
    )


def test_source_outage_detector_flags_drop() -> None:
    detector = SourceOutageDetector(
        SourceOutageDetectorConfig(
            warn_ratio=0.6, alert_ratio=0.3, consecutive_failure_threshold=3
        ),
        now=_now(),
    )
    baselines = {
        "nature": SourceBaseline(
            expected_articles_per_window=5,
            max_gap_hours=8,
            language_distribution={"en": 0.9, "es": 0.1},
            topic_distribution={"biology": 0.6, "physics": 0.4},
        )
    }
    stats = [make_source_window("nature", articles=0, failures=4, last_seen_hours=10.0)]
    result = detector.evaluate(stats, baselines)
    assert result["anomalies"], "Expected outage anomaly"
    anomaly = result["anomalies"][0]
    assert anomaly.severity == Severity.CRITICAL
    assert "consecutive" in anomaly.message


def test_schema_drift_detector_missing_field() -> None:
    expectation = SchemaExpectation(
        required_fields={"article_id": str, "title": str},
        optional_fields={"summary": str},
        max_missing_ratio=0.1,
    )
    detector = SchemaDriftDetector(expectation)
    samples = [
        {"article_id": "a", "title": "One"},
        {"article_id": "b", "title": "Two"},
        {"article_id": "c"},
    ]
    result = detector.evaluate(samples)
    assert any(a.labels.get("field") == "title" for a in result["anomalies"])


def test_content_shift_detector_raises_alert() -> None:
    thresholds = ContentShiftThresholds(
        language_divergence_alert=0.2,
        topic_divergence_alert=0.2,
    )
    detector = ContentShiftDetector(thresholds)
    baselines = {
        "nature": SourceBaseline(
            expected_articles_per_window=5,
            max_gap_hours=8,
            language_distribution={"en": 0.9},
            topic_distribution={"biology": 0.7, "physics": 0.3},
        )
    }
    stats = [
        make_source_window(
            "nature",
            articles=5,
            failures=0,
            last_seen_hours=1.0,
            languages={"es": 5},
            topics={"politics": 5},
        )
    ]
    result = detector.evaluate(stats, baselines)
    severities = {anomaly.severity for anomaly in result["anomalies"]}
    assert Severity.CRITICAL in severities


def test_canary_alert_and_suppression() -> None:
    stats = [make_source_window("nature", articles=0, failures=3, last_seen_hours=72.0)]
    baselines = {
        "nature": SourceBaseline(
            expected_articles_per_window=5,
            max_gap_hours=6,
            language_distribution={"en": 1.0},
            topic_distribution={"biology": 1.0},
        )
    }
    outage_result = SourceOutageDetector(now=_now()).evaluate(stats, baselines)
    runner = CanaryRunner(
        [CanaryCheck(source_id="nature", max_latency_ms=1000, max_idle_hours=12.0)]
    )
    canary_results = runner.execute(stats)
    alerts = build_canary_alerts(canary_results)
    assert alerts
    suppression = AutoSuppressionManager(failure_threshold=1, idle_hours_threshold=48.0)
    decisions = suppression.evaluate(stats, outage_result["anomalies"])
    assert decisions and decisions[0].source_id == "nature"


def test_quality_report_generator_builds_payload() -> None:
    stats = [make_source_window("nature", articles=0, failures=3, last_seen_hours=72.0)]
    baselines = {
        "nature": SourceBaseline(
            expected_articles_per_window=5,
            max_gap_hours=6,
            language_distribution={"en": 1.0},
            topic_distribution={"biology": 1.0},
        )
    }
    dataset = MonitoringDataset(
        window_start=_now() - timedelta(days=7),
        window_end=_now(),
        source_windows=stats,
        baselines=baselines,
        schema_samples=[
            {
                "article_id": "a1",
                "title": "hello",
                "language": "en",
                "published_at": "2025-01-01T00:00:00Z",
                "topics": ["biology"],
                "source_id": "nature",
            }
        ],
    )
    generator = default_quality_report_generator(
        canary_runner=CanaryRunner(
            [CanaryCheck("nature", max_latency_ms=1000, max_idle_hours=12.0)]
        )
    )
    payload = generator.generate(dataset)
    data = payload.to_dict()
    assert data["status"] in {"warning", "critical"}
    assert data["metadata"]["suppressed_sources"] == ["nature"]


def test_load_monitoring_dataset_roundtrip(tmp_path) -> None:
    now = _now()
    payload = {
        "window": {
            "start": (now - timedelta(days=7)).isoformat(),
            "end": now.isoformat(),
        },
        "baselines": {
            "nature": {
                "expected_articles_per_window": 5,
                "max_gap_hours": 6,
                "language_distribution": {"en": 1.0},
                "topic_distribution": {"biology": 1.0},
            }
        },
        "source_windows": [
            {
                "source_id": "nature",
                "window_start": (now - timedelta(hours=6)).isoformat(),
                "window_end": now.isoformat(),
                "articles_found": 0,
                "expected_count": 5,
                "last_article_at": (now - timedelta(hours=10)).isoformat(),
                "consecutive_failures": 4,
                "schema_violations": 0,
                "languages": {"en": 0},
                "topics": {},
            }
        ],
        "schema_samples": [
            {
                "article_id": "a1",
                "source_id": "nature",
                "published_at": now.isoformat(),
                "language": "en",
                "topics": ["biology"],
                "title": "hello",
            }
        ],
    }
    dataset = load_monitoring_dataset(payload)
    generator = default_quality_report_generator(
        canary_runner=CanaryRunner(
            [CanaryCheck("nature", max_latency_ms=1000, max_idle_hours=6.0)]
        )
    )
    report = generator.generate(dataset)
    assert report.metadata["suppressed_sources"] == ["nature"]
    # ensure serialization roundtrip
    text = json.dumps(report.to_dict())
    assert "monitoring.v1" in text
