"""Latency benchmarks for the configurable enrichment pipeline."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from time import perf_counter
from typing import Dict, List

import pytest

from config.perf_thresholds import PIPELINE_PERF_THRESHOLDS
from src.enrichment.pipeline import EnrichmentPipeline

pytestmark = pytest.mark.perf

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "golden_articles.json"
REPORT_PATH = Path(__file__).resolve().parents[2] / "reports" / "perf" / "enrichment_latency.json"


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def test_enrichment_latency_budget() -> None:
    pipeline = EnrichmentPipeline()
    with DATA_PATH.open(encoding="utf-8") as fh:
        samples: List[Dict[str, object]] = json.load(fh)

    durations: List[float] = []

    # Warm up caches with a single pass
    for sample in samples:
        pipeline.enrich_article(sample)

    for _ in range(3):
        for sample in samples:
            start = perf_counter()
            pipeline.enrich_article(sample)
            durations.append(perf_counter() - start)

    assert durations, "No enrichment invocations were recorded"

    metrics = {
        "samples": len(durations),
        "mean_seconds": statistics.fmean(durations),
        "p95_seconds": _percentile(durations, 0.95),
        "max_seconds": max(durations),
    }

    thresholds = PIPELINE_PERF_THRESHOLDS["enrichment_nlp"]
    assert (
        metrics["p95_seconds"] <= thresholds["p95_seconds"]
    ), f"Enrichment p95 latency {metrics['p95_seconds']:.4f}s exceeds {thresholds['p95_seconds']:.4f}s"
    assert (
        metrics["max_seconds"] <= thresholds["max_seconds"]
    ), f"Enrichment max latency {metrics['max_seconds']:.4f}s exceeds {thresholds['max_seconds']:.4f}s"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"metrics": metrics, "thresholds": thresholds}, fh, indent=2)
