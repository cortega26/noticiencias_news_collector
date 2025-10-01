"""Common monitoring data structures and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


class Severity(str, Enum):
    """Normalized severity levels for monitoring signals."""

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


COMMON_PAYLOAD_VERSION = "monitoring.v1"


@dataclass(slots=True)
class Metric:
    """Scalar metric in the common monitoring output format."""

    name: str
    value: float
    unit: Optional[str] = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "value": self.value,
        }
        if self.unit:
            payload["unit"] = self.unit
        if self.labels:
            payload["labels"] = dict(self.labels)
        return payload


@dataclass(slots=True)
class Anomaly:
    """An anomaly detected by the monitoring system."""

    detector: str
    severity: Severity
    message: str
    labels: Mapping[str, str] = field(default_factory=dict)
    observations: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "detector": self.detector,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.labels:
            payload["labels"] = dict(self.labels)
        if self.observations:
            payload["observations"] = dict(self.observations)
        return payload


@dataclass(slots=True)
class Alert:
    """Actionable alert derived from anomalies."""

    title: str
    severity: Severity
    runbook_url: Optional[str]
    targets: List[str]
    labels: Mapping[str, str] = field(default_factory=dict)
    annotations: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": self.title,
            "severity": self.severity.value,
            "targets": list(self.targets),
        }
        if self.runbook_url:
            payload["runbook_url"] = self.runbook_url
        if self.labels:
            payload["labels"] = dict(self.labels)
        if self.annotations:
            payload["annotations"] = dict(self.annotations)
        return payload


@dataclass(slots=True)
class MonitoringPayload:
    """Canonical monitoring payload used across monitoring surfaces."""

    status: Severity
    window_start: datetime
    window_end: datetime
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    metrics: List[Metric] = field(default_factory=list)
    anomalies: List[Anomaly] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)
    version: str = COMMON_PAYLOAD_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status.value,
            "window": {
                "start": self.window_start.isoformat(),
                "end": self.window_end.isoformat(),
            },
            "generated_at": self.generated_at.isoformat(),
            "metrics": [metric.to_dict() for metric in self.metrics],
            "anomalies": [anomaly.to_dict() for anomaly in self.anomalies],
            "alerts": [alert.to_dict() for alert in self.alerts],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_components(
        cls,
        window_start: datetime,
        window_end: datetime,
        metrics: Optional[List[Metric]] = None,
        anomalies: Optional[List[Anomaly]] = None,
        alerts: Optional[List[Alert]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "MonitoringPayload":
        """Build a payload inferring the status from anomalies/alerts."""

        highest = Severity.OK
        for candidate in alerts or []:
            if candidate.severity == Severity.CRITICAL:
                highest = Severity.CRITICAL
                break
            if candidate.severity == Severity.WARNING and highest not in {
                Severity.CRITICAL,
            }:
                highest = Severity.WARNING
        else:
            for anomaly in anomalies or []:
                if anomaly.severity == Severity.CRITICAL:
                    highest = Severity.CRITICAL
                    break
                if anomaly.severity == Severity.WARNING and highest not in {
                    Severity.CRITICAL,
                }:
                    highest = Severity.WARNING
                if anomaly.severity == Severity.INFO and highest not in {
                    Severity.CRITICAL,
                    Severity.WARNING,
                }:
                    highest = Severity.INFO
        payload = cls(
            status=highest,
            window_start=window_start,
            window_end=window_end,
        )
        if metrics:
            payload.metrics.extend(metrics)
        if anomalies:
            payload.anomalies.extend(anomalies)
        if alerts:
            payload.alerts.extend(alerts)
        if metadata:
            payload.metadata.update(dict(metadata))
        return payload


def serialize_payload(payload: MonitoringPayload) -> Dict[str, Any]:
    """Return a dict representation of a payload (alias for compatibility)."""

    return payload.to_dict()
