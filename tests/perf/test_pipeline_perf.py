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
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine as sqlalchemy_create_engine

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
import src.scoring.feature_scorer as feature_scorer_module

FIXTURE_PATH = PROJECT_ROOT / "data" / "collector_pipeline_chain.json"
SCORING_GOLDEN_PATH = PROJECT_ROOT / "data" / "scoring_golden.json"

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
def pipeline_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    storage_backend: str,
) -> Dict[str, Any]:
    import src.storage.database as database_module

    backend_info: Dict[str, Any] = {"backend": storage_backend}

    if storage_backend == "sqlite":
        db_path = tmp_path / "perf_pipeline.db"
        manager = DatabaseManager({"type": "sqlite", "path": db_path})
        backend_info["dsn"] = f"sqlite:///{db_path.name}"
        backend_info["pool"] = {"class": "StaticPool", "size": 1}
    else:
        captured: Dict[str, Any] = {}

        def fake_create_engine(url: Any, **kwargs: Any):
            captured["url"] = url
            captured["kwargs"] = kwargs
            sqlite_path = tmp_path / "perf_pipeline_pg.db"
            return sqlalchemy_create_engine(
                f"sqlite:///{sqlite_path}", echo=kwargs.get("echo", False)
            )

        monkeypatch.setattr("src.storage.database.create_engine", fake_create_engine)

        postgres_config = {
            "type": "postgresql",
            "host": "db.internal",
            "port": 5432,
            "name": "news_collector",
            "user": "collector",
            "password": "secret",
            "connect_timeout": 5,
            "statement_timeout": 45000,
            "pool_size": 12,
            "max_overflow": 6,
            "pool_timeout": 45,
            "pool_recycle": 1200,
        }

        manager = DatabaseManager(postgres_config)

        pool_kwargs = captured.get("kwargs", {})
        captured_url: Any | None = captured.get("url")
        if captured_url is None:
            safe_dsn = "<unavailable>"
        elif hasattr(captured_url, "render_as_string"):
            safe_dsn = str(captured_url.render_as_string(hide_password=True))
        else:
            safe_dsn = str(captured_url)
        backend_info.update(
            {
                "dsn": safe_dsn,
                "pool": {
                    "class": getattr(pool_kwargs.get("poolclass"), "__name__", "QueuePool"),
                    "size": pool_kwargs.get("pool_size"),
                    "max_overflow": pool_kwargs.get("max_overflow"),
                    "timeout": pool_kwargs.get("pool_timeout"),
                    "recycle": pool_kwargs.get("pool_recycle"),
                },
            }
        )

    monkeypatch.setattr(database_module, "_db_manager", manager, raising=False)
    monkeypatch.setattr(
        "src.collectors.rss_collector.get_database_manager", lambda: manager
    )

    backend_info["manager"] = manager
    return backend_info


@pytest.fixture(params=["sqlite", "postgresql"])
def storage_backend(request: pytest.FixtureRequest) -> str:
    return cast(str, request.param)


@pytest.fixture()
def collector(
    monkeypatch: pytest.MonkeyPatch, pipeline_storage: Dict[str, Any]
) -> RSSCollector:
    collector = RSSCollector()
    collector.db_manager = pipeline_storage["manager"]

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


def _compute_scoring_accuracy() -> Dict[str, float]:
    with SCORING_GOLDEN_PATH.open(encoding="utf-8") as fh:
        dataset = json.load(fh)

    frozen_at = datetime.fromisoformat(dataset["frozen_at"].replace("Z", "+00:00"))

    class _FrozenDateTime(datetime):
        frozen_value = frozen_at

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz:
                return cls.frozen_value.astimezone(tz)
            return cls.frozen_value

    errors: List[float] = []
    include_matches = 0
    ranks: List[Dict[str, Any]] = []

    with patch.object(feature_scorer_module, "datetime", _FrozenDateTime):
        scorer = create_scorer()
        for entry in dataset["articles"]:
            article_payload = dict(entry["article"])
            article_payload.setdefault("article_metadata", {})
            result = scorer.score_article(article_payload)
            expected = entry["expected"]
            errors.append(abs(result["final_score"] - expected["final_score"]))
            include_matches += int(
                result["should_include"] == expected["should_include"]
            )
            ranks.append(
                {
                    "id": entry["id"],
                    "predicted_score": result["final_score"],
                    "expected_rank": expected["rank"],
                }
            )

    total = len(ranks)
    predicted_order = sorted(ranks, key=lambda item: item["predicted_score"], reverse=True)
    predicted_ranks = {item["id"]: idx + 1 for idx, item in enumerate(predicted_order)}
    rank_matches = sum(
        1 for item in ranks if predicted_ranks.get(item["id"]) == item["expected_rank"]
    )

    mae = sum(errors) / total if total else 0.0
    max_abs = max(errors) if errors else 0.0
    include_accuracy = include_matches / total if total else 0.0
    rank_accuracy = rank_matches / total if total else 0.0

    return {
        "samples": total,
        "mean_absolute_error": mae,
        "max_absolute_error": max_abs,
        "should_include_accuracy": include_accuracy,
        "rank_match_ratio": rank_accuracy,
    }


def test_pipeline_stage_latencies(
    collector: RSSCollector,
    pipeline_dataset: List[JSONDict],
    pipeline_storage: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    storage_backend: str,
) -> None:
    isolated_database: DatabaseManager = pipeline_storage["manager"]
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
        if stage not in metrics:
            continue
        stage_metrics = metrics[stage]
        assert (
            stage_metrics["p95_seconds"] <= thresholds["p95_seconds"]
        ), f"{stage} p95 exceeded: {stage_metrics['p95_seconds']:.4f}s > {thresholds['p95_seconds']:.4f}s"
        assert (
            stage_metrics["max_seconds"] <= thresholds["max_seconds"]
        ), f"{stage} max exceeded: {stage_metrics['max_seconds']:.4f}s > {thresholds['max_seconds']:.4f}s"

    total_articles = len(pipeline_dataset)
    throughput = {
        "articles": total_articles,
        "ingestion_rps": (
            total_articles / sum(stage_timings["ingestion"])
            if stage_timings["ingestion"]
            else 0.0
        ),
        "enrichment_rps": (
            total_articles / sum(stage_timings["enrichment"])
            if stage_timings["enrichment"]
            else 0.0
        ),
        "scoring_rps": (
            total_articles / sum(stage_timings["scoring"])
            if stage_timings["scoring"]
            else 0.0
        ),
    }
    total_pipeline_seconds = sum(sum(durations) for durations in stage_timings.values())
    throughput["pipeline_rps"] = (
        total_articles / total_pipeline_seconds if total_pipeline_seconds else 0.0
    )

    accuracy_metrics = _compute_scoring_accuracy()

    perf_reports_dir = PROJECT_ROOT.parent / "reports" / "perf"
    perf_reports_dir.mkdir(parents=True, exist_ok=True)
    log_path = perf_reports_dir / "pipeline_perf_metrics.json"
    payload: Dict[str, Any] = {
        "latency": metrics,
        "thresholds": PIPELINE_PERF_THRESHOLDS,
        "throughput": throughput,
        "accuracy": accuracy_metrics,
        "backend": {
            key: value
            for key, value in pipeline_storage.items()
            if key in {"backend", "dsn", "pool"}
        },
    }

    if log_path.exists():
        existing = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    existing.setdefault("runs", {})[storage_backend] = payload

    with log_path.open("w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)

    print(f"pipeline_perf_log={log_path}")
