"""
Perf gate for GET /v1/articles (plan 045, Step 3).

Budgets are deliberately NON-timing: shared CI runners make microsecond
gates meaningless. The gate asserts stable structural budgets that any
regression (extra query, full-entity hydration, payload bloat) would
violate:

  - statement count per request == 1 (a second SELECT means a regression)
  - payload bytes within the accepted envelope (projection keeps it small)
  - response contract: same ordering/cursor semantics as the serving tests

Timing numbers are recorded by scripts/benchmark_serving_api.py into
reports/perf/serving_api.json for trend analysis; they are not asserted
here.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ScoreLog

pytestmark = pytest.mark.perf

N_ARTICLES = 10_000
SCORE_LOGS_PER_ARTICLE = 3
# Accepted payload envelope for a page_size=20 response at the seeded
# dataset (measured 2026-08-11: ~12.7 KB). A projection regression that
# starts shipping full entities (content Text + all JSON columns) would
# blow past this bound.
MAX_PAYLOAD_BYTES = 32_000
# A single request must issue exactly one SELECT (the ranked query itself).
# A second statement means an N+1 or a lost projection.
MAX_STATEMENTS = 1


@pytest.fixture(scope="module")
def perf_db(tmp_path_factory: object) -> Iterator[DatabaseManager]:
    """Seeded 10k-article database with 3 score logs per article (once per
    module — the seed takes ~15s and is shared by all gate tests)."""
    from scripts.benchmark_serving_api import seed_database

    db_path = tmp_path_factory.mktemp("perf") / "perf.db"  # type: ignore[attr-defined]
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    seed_database(manager, N_ARTICLES, SCORE_LOGS_PER_ARTICLE, seed=42)
    try:
        yield manager
    finally:
        manager.close()


def _statement_count(manager: DatabaseManager):
    """Attach a SELECT counter to the manager's engines.

    Returns (read_count, cleanup) where read_count() returns the number of
    SELECT statements executed since attachment and cleanup() removes the
    hooks.
    """
    state = {"count": 0}

    def _hook(conn, cursor, statement, parameters, context, executemany):
        stmt = str(statement)
        if stmt.strip().lower().startswith(("select", "with")):
            state["count"] += 1

    engines = []
    for attr in ("engine", "_engine"):
        engine = getattr(manager, attr, None)
        if engine is not None and engine not in engines:
            engines.append(engine)
    for engine in engines:
        event.listen(engine, "before_cursor_execute", _hook)

    def cleanup() -> None:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", _hook)

    return (lambda: state["count"]), cleanup


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"source": ["nature"]},
        {"topic": ["genetics"]},
        {"topic": ["genetics", "ai"]},
        {"page_size": 50},
    ],
)
def test_ranked_query_emits_exactly_one_statement(
    perf_db: DatabaseManager, params: dict
) -> None:
    client = TestClient(create_app(database_manager=perf_db))
    read_count, cleanup = _statement_count(perf_db)
    try:
        resp = client.get("/v1/articles", params=params)
        assert resp.status_code == 200
    finally:
        cleanup()
    count = read_count()
    assert count <= MAX_STATEMENTS, (
        f"expected <= {MAX_STATEMENTS} SELECT per request, got {count} "
        "(N+1 or lost projection regression)"
    )


def test_ranked_response_payload_within_envelope(perf_db: DatabaseManager) -> None:
    client = TestClient(create_app(database_manager=perf_db))
    resp = client.get("/v1/articles", params={"page_size": 20})
    assert resp.status_code == 200
    assert len(resp.content) <= MAX_PAYLOAD_BYTES, (
        f"payload {len(resp.content)} bytes exceeds {MAX_PAYLOAD_BYTES} "
        "(full-entity hydration regression)"
    )


def test_ranked_response_contract_stable(perf_db: DatabaseManager) -> None:
    """The optimized query must keep response shape and ordering identical."""
    client = TestClient(create_app(database_manager=perf_db))
    resp = client.get("/v1/articles", params={"page_size": 20})
    body = resp.json()
    assert len(body["data"]) == 20
    scores = [item["final_score"] or 0.0 for item in body["data"]]
    assert scores == sorted(scores, reverse=True), "score ordering broken"
    keys = {
        "id",
        "title",
        "summary",
        "url",
        "source",
        "category",
        "topics",
        "published_at",
        "collected_at",
        "final_score",
        "score_components",
        "why_ranked",
    }
    assert keys <= set(body["data"][0].keys())
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["next_cursor"]
