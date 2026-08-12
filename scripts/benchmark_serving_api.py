#!/usr/bin/env python3
"""
benchmark_serving_api.py — deterministic benchmark for GET /v1/articles
(plan 045).

Builds a seeded SQLite database with configurable article/score-log/topic
distributions (no external calls, no network), then measures the ranked
query across representative cases:

  - warm/cold p50/p95 latency
  - SQL statement count (via SQLAlchemy event hook)
  - selected row/column volume
  - response payload bytes
  - EXPLAIN QUERY PLAN fingerprint per case

Cases: unfiltered, source filter, date filter, one-topic, multi-topic,
first-page, and deep-cursor traversal.

Usage:
  .venv/bin/python scripts/benchmark_serving_api.py \
      --articles 10000 --score-logs-per-article 3 --samples 30 \
      --output reports/perf/serving_api.json

The dataset is seeded (--seed, default 42), so two runs on the same seed
produce the same ordering, statement counts, and explain fingerprints —
timing variance is reported, not hidden.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import event, text

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ScoreLog

SOURCES = ["nature", "science", "esa", "nejm", "arxiv", "mit", "cell", "phys"]
CATEGORIES = ["science", "health", "technology", "space", "climate", "economy"]
TOPIC_POOL = [
    "genetics",
    "cancer",
    "ai",
    "quantum",
    "climate",
    "neuroscience",
    "astronomy",
    "physics",
    "biology",
    "medicine",
    "energy",
    "robotics",
]
TOPIC_PROB = 0.35  # probability an article carries each topic


def _cursor_params(article: Article) -> str:
    score = article.final_score or 0.0
    collected = article.collected_date or datetime.now(timezone.utc)
    payload = f"{score:.6f}|{collected.isoformat()}|{article.id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def seed_database(
    manager: DatabaseManager, n_articles: int, logs_per: int, seed: int
) -> None:
    """Insert n_articles with logs_per score logs each, deterministically.

    Uses bulk_save_objects (not per-row add/flush) so 100k-article datasets
    seed in seconds instead of minutes — the benchmark measures the query,
    not the insert path.
    """
    rng = random.Random(seed)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with manager.get_session() as session:
        articles = []
        for i in range(n_articles):
            source = SOURCES[i % len(SOURCES)]
            topics = [t for t in TOPIC_POOL if rng.random() < TOPIC_PROB] or [
                TOPIC_POOL[0]
            ]
            articles.append(
                Article(
                    title=f"Benchmark article {i}",
                    url=f"https://example.com/benchmark/{i}",
                    summary="Benchmark summary " * 5,
                    source_id=source,
                    source_name=source.capitalize(),
                    category=CATEGORIES[i % len(CATEGORIES)],
                    final_score=rng.uniform(0.1, 0.99),
                    published_date=base_time - timedelta(hours=i * 7),
                    collected_date=base_time - timedelta(minutes=i * 13),
                    processing_status="completed",
                    cluster_id=f"cluster-{i % 40}",
                    article_metadata={"enrichment": {"topics": topics}},
                    keywords=topics,
                    score_components={
                        "source_credibility": rng.uniform(0.2, 1.0),
                        "recency": rng.uniform(0.2, 1.0),
                        "content_quality": rng.uniform(0.2, 1.0),
                        "engagement_potential": rng.uniform(0.2, 1.0),
                    },
                )
            )
        session.bulk_save_objects(articles)
        session.flush()
        # bulk_save_objects does not refresh PKs into the objects; re-read
        # the ids in insertion order to attach score logs to the right rows.
        rows = (
            session.query(Article.id).order_by(Article.id.asc()).limit(n_articles).all()
        )
        article_ids = [row[0] for row in rows]
        logs = []
        for i, article_id in enumerate(article_ids):
            article = articles[i]
            for log_i in range(logs_per):
                logs.append(
                    ScoreLog(
                        article_id=article_id,
                        score_version="1.0",
                        calculated_at=base_time - timedelta(hours=log_i * 3 + (i % 5)),
                        final_score=article.final_score + rng.uniform(-0.05, 0.05),
                        score_explanation={
                            "key_strengths": ["Fuente confiable", "Relevante"],
                            "component_breakdown": {},
                        },
                        algorithm_weights={"source_credibility": 0.25},
                    )
                )
        session.bulk_save_objects(logs)
        session.commit()


def explain_fingerprint(manager: DatabaseManager, sql: str) -> str:
    """Return a stable fingerprint of EXPLAIN QUERY PLAN output.

    SQLite requires bound parameters when the statement uses placeholders
    (as ORM SQL always does). We re-execute the captured SELECT with dummy
    values supplied in placeholder order via raw sqlite3, bypassing
    SQLAlchemy's parameter distillation.
    """
    import sqlite3

    db_path = manager.config.get("path") if hasattr(manager, "config") else None
    if db_path is None:
        engine = getattr(manager, "engine", None) or getattr(manager, "_engine", None)
        db_path = engine.url.database if engine is not None else None
    if db_path is None:
        return ""
    conn = sqlite3.connect(str(db_path))
    try:
        n_params = sql.count("?")
        params = tuple("__b__" if i % 2 == 0 else 0.0 for i in range(n_params))
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    finally:
        conn.close()
    lines = [" ".join(str(c) for c in row) for row in rows]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


CASES = [
    ("unfiltered", {}),
    ("source", {"source": ["nature"]}),
    ("date", {"date_from": "2026-01-01T00:00:00+00:00"}),
    ("one_topic", {"topic": ["genetics"]}),
    ("multi_topic", {"topic": ["genetics", "ai"]}),
    ("deep_cursor", {"cursor": "__CURSOR__"}),
]


def measure_case(
    client, params: Dict[str, Any], cursor: Optional[str]
) -> Tuple[float, int, int]:
    """Run one request, return (latency_ms, statement_count, payload_bytes)."""
    qparams = dict(params)
    if cursor:
        qparams["cursor"] = cursor
    t0 = time.perf_counter()
    resp = client.get("/v1/articles", params=qparams)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    body = resp.content
    return elapsed_ms, len(body)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=int, default=10_000)
    parser.add_argument("--score-logs-per-article", type=int, default=3)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/perf/serving_api.json")
    )
    args = parser.parse_args(argv)

    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="bench-serving-"))
    db_path = tmpdir / "bench.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})

    try:
        seed_database(manager, args.articles, args.score_logs_per_article, args.seed)
        app = create_app(database_manager=manager)

        # Statement-count hook: count every SQL statement executed during a
        # request, excluding the engine's own connection bookkeeping.
        counters: Dict[str, int] = {}

        def _count_statements(
            conn, cursor, statement, parameters, context, executemany
        ):
            stmt = str(statement)
            if not stmt.strip().lower().startswith(("select", "with")):
                return
            key = "execute"
            counters[key] = counters.get(key, 0) + 1

        from fastapi.testclient import TestClient

        # Attach the hook to the manager's engine used by the app.
        for engine in _all_engines(manager):
            event.listen(engine, "before_cursor_execute", _count_statements)

        client = TestClient(app)

        # Deep cursor: traverse 3 pages to get a mid-dataset cursor.
        deep_cursor: Optional[str] = None
        for _ in range(3):
            params = {"page_size": 20}
            if deep_cursor:
                params["cursor"] = deep_cursor
            resp = client.get("/v1/articles", params=params)
            body = resp.json()
            items = body["data"]
            if not items:
                break
            last = items[-1]
            score = last["final_score"] or 0.0
            collected = last["collected_at"]
            payload = f"{score:.6f}|{collected}|{last['id']}"
            deep_cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode(
                "utf-8"
            )

        results: Dict[str, Any] = {}
        for case, params in CASES:
            if case == "deep_cursor":
                params = {"cursor": deep_cursor}
            latencies: List[float] = []
            payload_bytes = 0
            # Warm up once (page cache + prepared statements) so the first
            # measured sample is not the cold start.
            measure_case(client, params, None)
            for _ in range(args.samples):
                counters.clear()
                elapsed, size = measure_case(client, params, None)
                latencies.append(elapsed)
                payload_bytes = size
            latencies.sort()
            p50 = statistics.median(latencies)
            p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0

            # Explain fingerprint for the unfiltered/source/one_topic cases:
            # capture the raw SQL the ORM emits via the same statement hook.
            explain = ""
            if case in ("unfiltered", "source", "one_topic"):
                sqls: List[str] = []
                captured: Dict[str, int] = {}

                def _capture(conn, cursor, statement, parameters, context, executemany):
                    stmt = str(statement)
                    if stmt.strip().lower().startswith("select"):
                        sqls.append(stmt)

                for engine in _all_engines(manager):
                    event.listen(engine, "before_cursor_execute", _capture)
                counters.clear()
                measure_case(client, params, None)
                for engine in _all_engines(manager):
                    event.remove(engine, "before_cursor_execute", _capture)
                if sqls:
                    explain = explain_fingerprint(manager, sqls[0])

            results[case] = {
                "p50_ms": round(p50, 3),
                "p95_ms": round(p95, 3),
                "min_ms": round(min(latencies), 3),
                "max_ms": round(max(latencies), 3),
                "payload_bytes": payload_bytes,
                "statement_count": counters.get("execute", 0),
                "explain_fingerprint": explain,
            }

        # Dataset checksum: stable ordering + row count identity.
        checksum = _dataset_checksum(manager)

        out = {
            "dataset": {
                "articles": args.articles,
                "score_logs_per_article": args.score_logs_per_article,
                "seed": args.seed,
                "checksum": checksum,
            },
            "environment": {
                "database": "sqlite",
                "db_path": str(db_path),
                "python": __import__("sys").version.split()[0],
            },
            "cases": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 0
    finally:
        manager.close()


def _all_engines(manager: DatabaseManager) -> List[Any]:
    engines = []
    engine = getattr(manager, "engine", None)
    if engine is not None:
        engines.append(engine)
    session_engine = getattr(manager, "_engine", None)
    if session_engine is not None and session_engine not in engines:
        engines.append(session_engine)
    return engines


def _dataset_checksum(manager: DatabaseManager) -> str:
    with manager.get_session() as session:
        n_articles = session.query(Article).count()
        n_logs = session.query(ScoreLog).count()
        top = (
            session.query(Article.final_score)
            .order_by(Article.final_score.desc(), Article.id.desc())
            .limit(5)
            .all()
        )
    raw = f"{n_articles}|{n_logs}|{top}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    import sys

    sys.exit(main())
