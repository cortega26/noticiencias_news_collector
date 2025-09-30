"""IO helpers for monitoring datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping

from zoneinfo import ZoneInfo

from .detectors import SourceBaseline, SourceWindowStats
from .reporting import MonitoringDataset

UTC = ZoneInfo("UTC")


def _parse_iso(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp).astimezone(UTC)


def load_monitoring_dataset(payload: Mapping[str, Any]) -> MonitoringDataset:
    window_start = _parse_iso(payload["window"]["start"])
    window_end = _parse_iso(payload["window"]["end"])
    baselines: Dict[str, SourceBaseline] = {}
    for source_id, data in payload["baselines"].items():
        baselines[source_id] = SourceBaseline(
            expected_articles_per_window=float(data["expected_articles_per_window"]),
            max_gap_hours=float(data["max_gap_hours"]),
            language_distribution=data.get("language_distribution", {}),
            topic_distribution=data.get("topic_distribution", {}),
        )
    source_windows = []
    for item in payload["source_windows"]:
        source_windows.append(
            SourceWindowStats(
                source_id=item["source_id"],
                window_start=_parse_iso(item["window_start"]),
                window_end=_parse_iso(item["window_end"]),
                articles_found=int(item["articles_found"]),
                expected_count=int(item.get("expected_count", item["articles_found"])),
                last_article_at=_parse_iso(item["last_article_at"])
                if item.get("last_article_at")
                else None,
                consecutive_failures=int(item.get("consecutive_failures", 0)),
                schema_violations=int(item.get("schema_violations", 0)),
                languages=item.get("languages", {}),
                topics=item.get("topics", {}),
            )
        )
    return MonitoringDataset(
        window_start=window_start,
        window_end=window_end,
        source_windows=source_windows,
        baselines=baselines,
        schema_samples=payload.get("schema_samples", []),
    )
