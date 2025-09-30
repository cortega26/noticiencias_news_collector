"""Reporting orchestration for monitoring outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Mapping, Optional, Sequence

from zoneinfo import ZoneInfo

from .canary import AutoSuppressionManager, CanaryRunner, build_canary_alerts
from .common import Alert, Metric, MonitoringPayload
from .detectors import (
    ContentShiftDetector,
    SchemaDriftDetector,
    SchemaExpectation,
    SourceBaseline,
    SourceOutageDetector,
    SourceOutageDetectorConfig,
    SourceWindowStats,
)

UTC = ZoneInfo("UTC")


@dataclass(slots=True)
class MonitoringDataset:
    """Bundle of inputs required by the monitoring orchestrator."""

    window_start: datetime
    window_end: datetime
    source_windows: Sequence[SourceWindowStats]
    baselines: Mapping[str, SourceBaseline]
    schema_samples: Sequence[Mapping[str, object]]


@dataclass(slots=True)
class QualityReportGenerator:
    """Runs detectors and assembles the weekly monitoring payload."""

    schema_detector: SchemaDriftDetector
    outage_detector: SourceOutageDetector
    content_detector: ContentShiftDetector
    canary_runner: CanaryRunner
    suppression_manager: AutoSuppressionManager

    def generate(self, dataset: MonitoringDataset) -> MonitoringPayload:
        schema_result = self.schema_detector.evaluate(dataset.schema_samples)
        outage_result = self.outage_detector.evaluate(
            dataset.source_windows, dataset.baselines
        )
        content_result = self.content_detector.evaluate(
            dataset.source_windows, dataset.baselines
        )
        metrics: List[Metric] = []
        anomalies = []
        for bag in (schema_result, outage_result, content_result):
            metrics.extend(bag["metrics"])
            anomalies.extend(bag["anomalies"])
        canary_results = self.canary_runner.execute(dataset.source_windows)
        alerts: List[Alert] = build_canary_alerts(canary_results)
        suppression_decisions = self.suppression_manager.evaluate(
            dataset.source_windows, anomalies
        )
        metrics.append(
            Metric(
                name="sources.auto_suppressed",
                value=float(len(suppression_decisions)),
            )
        )
        metadata = {
            "suppressed_sources": [decision.source_id for decision in suppression_decisions],
        }
        return MonitoringPayload.from_components(
            window_start=dataset.window_start,
            window_end=dataset.window_end,
            metrics=metrics,
            anomalies=anomalies,
            alerts=alerts,
            metadata=metadata,
        )


def default_quality_report_generator(
    schema_expectation: Optional[SchemaExpectation] = None,
    canary_runner: Optional[CanaryRunner] = None,
) -> QualityReportGenerator:
    expectation = schema_expectation or SchemaExpectation(
        required_fields={
            "article_id": str,
            "source_id": str,
            "published_at": str,
            "language": str,
            "topics": list,
            "title": str,
        },
        optional_fields={
            "summary": str,
            "content": str,
            "authors": list,
        },
    )
    outage_detector = SourceOutageDetector(SourceOutageDetectorConfig())
    content_detector = ContentShiftDetector()
    runner = canary_runner or CanaryRunner([])
    suppression_manager = AutoSuppressionManager()
    return QualityReportGenerator(
        schema_detector=SchemaDriftDetector(expectation),
        outage_detector=outage_detector,
        content_detector=content_detector,
        canary_runner=runner,
        suppression_manager=suppression_manager,
    )
