"""Performance baseline thresholds for regression checks."""

from __future__ import annotations

PIPELINE_PERF_THRESHOLDS: dict[str, dict[str, float]] = {
    "ingestion": {
        "p95_seconds": 0.35,
        "max_seconds": 0.45,
    },
    "enrichment": {
        "p95_seconds": 0.20,
        "max_seconds": 0.30,
    },
    "scoring": {
        "p95_seconds": 0.15,
        "max_seconds": 0.25,
    },
}

__all__ = ["PIPELINE_PERF_THRESHOLDS"]
