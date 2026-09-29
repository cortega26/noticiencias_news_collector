"""Unit tests for ProductionReadonlyStore (plan 113).

A real SQLite file is used (repo convention for storage-shaped code): the
store must read through an injected path, and a poisoned connection must
reset instead of failing every later read.
"""

from __future__ import annotations

import sqlite3

from news_collector.observability.enrichment_metrics_store import (
    ProductionReadonlyStore,
)


def _make_metrics_db(path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE enrichment_metrics "
        "(source_id TEXT PRIMARY KEY, total_discovered INTEGER)"
    )
    con.execute("INSERT INTO enrichment_metrics VALUES ('src', 3)")
    con.commit()
    con.close()


def test_reads_metrics_from_injected_path(tmp_path) -> None:
    db_path = tmp_path / "enrichment_metrics.db"
    _make_metrics_db(db_path)
    store = ProductionReadonlyStore(db_path=str(db_path))

    assert store.get_metrics("src")["total_discovered"] == 3
    assert store.get_all_metrics()["src"]["total_discovered"] == 3
    assert store.get_metrics("missing") is None


def test_missing_db_returns_none_and_empty(tmp_path) -> None:
    store = ProductionReadonlyStore(db_path=str(tmp_path / "nope.db"))

    assert store.get_metrics("src") is None
    assert store.get_all_metrics() == {}


def test_failed_read_resets_connection_and_recovers(tmp_path) -> None:
    """A connection closed behind the store's back (the plan-113 poisoning
    case) fails the read once, then reconnects instead of failing forever."""
    db_path = tmp_path / "enrichment_metrics.db"
    _make_metrics_db(db_path)
    store = ProductionReadonlyStore(db_path=str(db_path))
    assert store.get_metrics("src") is not None

    store.conn.close()  # self.conn is still set, but the handle is dead

    assert store.get_metrics("src") is None
    assert store.conn is None

    assert store.get_metrics("src")["total_discovered"] == 3
    assert store.get_all_metrics()["src"]["total_discovered"] == 3


def test_close_resets_connection(tmp_path) -> None:
    db_path = tmp_path / "enrichment_metrics.db"
    _make_metrics_db(db_path)
    store = ProductionReadonlyStore(db_path=str(db_path))
    assert store.get_metrics("src") is not None

    store.close()

    assert store.conn is None
    assert store.get_metrics("src")["total_discovered"] == 3
