"""Perf gate for GET /v1/admin/sources (plan 110, Step 3).

Non-timing structural budget (same rationale as plan 045): the endpoint
used to fan out one circuit lookup per configured source (N+1). It now
reads all circuit states in a single SELECT, so the budget is a constant
bound no matter how large the source catalog grows.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base

pytestmark = pytest.mark.perf

# One bulk circuit SELECT per request, regardless of catalog size.
MAX_STATEMENTS = 1


def _statement_count(manager: DatabaseManager):
    state = {"count": 0}

    def _hook(conn, cursor, statement, parameters, context, executemany):
        if str(statement).strip().lower().startswith(("select", "with")):
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


def test_sources_list_emits_at_most_one_statement(tmp_path) -> None:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "p.db"})
    Base.metadata.create_all(manager.engine)
    try:
        client = TestClient(create_app(database_manager=manager))
        read_count, cleanup = _statement_count(manager)
        try:
            with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
                resp = client.get(
                    "/v1/admin/sources",
                    headers={"Authorization": "Bearer dev-admin-token"},
                )
                assert resp.status_code == 200
        finally:
            cleanup()
        assert read_count() <= MAX_STATEMENTS
    finally:
        manager.close()
