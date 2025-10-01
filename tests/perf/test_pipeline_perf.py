"""Performance regression tests for the offline pipeline path."""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from config.perf_thresholds import PIPELINE_PERF_THRESHOLDS
from src.collectors import RSSCollector
from src.enrichment import enrichment_pipeline
from src.contracts import ArticleForEnrichmentModel
from src.scoring import create_scorer
from src.storage import models as storage_models
from src.storage.database import DatabaseManager

FIXTURE_PATH = PROJECT_ROOT / "data" / "collector_pipeline_chain.json"

pytestmark = pytest.mark.perf


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


JSONDict = Dict[str, Any]


def _prepare_raw_article(entry: JSONDict) -> JSONDict:
    collector_raw_obj = entry["collector_raw"]
    if not isinstance(collector_raw_obj, dict):
        raise TypeError("collector_raw must be a dictionary")
    collector_raw = dict(cast(JSONDict, collector_raw_obj))
    offset_hours = float(collector_raw.pop("published_offset_hours"))
    published_ts = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    collector_raw["published_date"] = published_ts
    collector_raw.setdefault("published_tz_offset_minutes", 0)
    collector_raw.setdefault("published_tz_name", "UTC")
    collector_raw.setdefault("original_url", collector_raw["url"])
    collector_raw.setdefault("source_metadata", {})
    return collector_raw


@pytest.fixture(scope="module")
def pipeline_dataset() -> List[JSONDict]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def isolated_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> DatabaseManager:
    db_path = tmp_path / "perf_pipeline.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})

    import src.storage.database as database_module

    monkeypatch.setattr(database_module, "_db_manager", manager, raising=False)
    monkeypatch.setattr(
        "src.collectors.rss_collector.get_database_manager", lambda: manager
    )

    return manager


@pytest.fixture()
def collector(
    monkeypatch: pytest.MonkeyPatch, isolated_database: DatabaseManager
) -> RSSCollector:
    collector = RSSCollector()

    monkeypatch.setattr(RSSCollector, "_respect_robots", lambda self, url: (True, None))
    monkeypatch.setattr(
        RSSCollector,
        "_enforce_domain_rate_limit",
        lambda self, domain, robots_delay, source_min_delay=None: None,
    )
    monkeypatch.setattr(
        RSSCollector, "_fetch_feed", lambda self, source_id, feed_url: ("<rss/>", 200)
    )

    sample_feed = type("MockFeed", (), {"bozo": 0})()
    monkeypatch.setattr("feedparser.parse", lambda content: sample_feed)

    def fake_extract(self, parsed_feed, source_config):
        return getattr(self, "_test_articles", [])

    monkeypatch.setattr(RSSCollector, "_extract_articles_from_feed", fake_extract)

    return collector


def test_pipeline_stage_latencies(
    collector: RSSCollector,
    pipeline_dataset: List[JSONDict],
    isolated_database: DatabaseManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_timings: Dict[str, List[float]] = {
        "ingestion": [],
        "enrichment": [],
        "scoring": [],
    }

    original_enrich = enrichment_pipeline.enrich_article

    def timed_enrich(
        article: JSONDict | ArticleForEnrichmentModel,
    ) -> JSONDict:
        start = perf_counter()
        result = cast(JSONDict, original_enrich(article))
        stage_timings["enrichment"].append(perf_counter() - start)
        return result

    monkeypatch.setattr(enrichment_pipeline, "enrich_article", timed_enrich)

    scorer = create_scorer()

    for entry in pipeline_dataset:
        raw_article = _prepare_raw_article(entry)
        collector._test_articles = [raw_article]

        source_obj = entry["source"]
        if not isinstance(source_obj, dict):
            raise TypeError("source must be a dictionary")
        source = cast(JSONDict, source_obj)
        source_config = {
            "name": source["name"],
            "url": source["url"],
            "category": source["category"],
            "credibility_score": source["credibility_score"],
            "language": source.get("language", "en"),
        }

        ingest_start = perf_counter()
        stats = collector.collect_from_source(source["id"], source_config)
        stage_timings["ingestion"].append(perf_counter() - ingest_start)
        assert stats["success"] is True

        with isolated_database.get_session() as session:
            stored_article = (
                session.query(storage_models.Article)
                .filter_by(url=raw_article["url"])
                .first()
            )
        assert stored_article is not None

        score_start = perf_counter()
        scorer.score_article(stored_article)
        stage_timings["scoring"].append(perf_counter() - score_start)

    metrics: Dict[str, Dict[str, float]] = {}
    for stage, durations in stage_timings.items():
        assert durations, f"No samples recorded for {stage} stage"
        metrics[stage] = {
            "samples": len(durations),
            "mean_seconds": statistics.fmean(durations),
            "p95_seconds": _percentile(durations, 0.95),
            "max_seconds": max(durations),
        }

    for stage, thresholds in PIPELINE_PERF_THRESHOLDS.items():
        stage_metrics = metrics[stage]
        assert (
            stage_metrics["p95_seconds"] <= thresholds["p95_seconds"]
        ), f"{stage} p95 exceeded: {stage_metrics['p95_seconds']:.4f}s > {thresholds['p95_seconds']:.4f}s"
        assert (
            stage_metrics["max_seconds"] <= thresholds["max_seconds"]
        ), f"{stage} max exceeded: {stage_metrics['max_seconds']:.4f}s > {thresholds['max_seconds']:.4f}s"

    perf_reports_dir = PROJECT_ROOT.parent / "reports" / "perf"
    perf_reports_dir.mkdir(parents=True, exist_ok=True)
    log_path = perf_reports_dir / "pipeline_perf_metrics.json"
    with log_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {"metrics": metrics, "thresholds": PIPELINE_PERF_THRESHOLDS}, fh, indent=2
        )

    print(f"pipeline_perf_log={log_path}")
