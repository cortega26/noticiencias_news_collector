"""Unit tests for CollectionRunWorkflow (Plan 060 / Phase 4a).

Exercises the class directly against a real SQLite DB — the same
convention this repo already uses for anything doing CAS/session work
(tests/test_database_migrations.py, tests/unit/storage/test_prune_workflow_runs.py)
rather than mocking the session. HTTP-layer behavior (status-code mapping,
lifespan-triggered recovery through a real app restart) is covered
separately in tests/test_serving_admin_api.py.

`_dispatch` is monkeypatched to a no-op in every test that calls `start()`
so no real background thread/collection system is touched — this file
tests the workflow class's own state machine, not the collection pipeline
it dispatches.
"""

import inspect
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from news_collector.logic.workflows.collection_run_workflow import CollectionRunWorkflow
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "collection_run_workflow.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


@pytest.fixture
def workflow(db_manager):
    return CollectionRunWorkflow(db_manager, lease_timeout_seconds=60)


def test_start_inserts_queued_row_and_dispatches(db_manager, workflow, monkeypatch):
    dispatched = {}
    monkeypatch.setattr(
        workflow,
        "_dispatch",
        lambda run_id, *, dry_run: dispatched.update(run_id=run_id, dry_run=dry_run),
    )

    result = workflow.start(dry_run=True)

    assert result.status == "started"
    assert dispatched == {"run_id": result.run_id, "dry_run": True}
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, result.run_id)
        assert row.status == "queued"
        assert row.run_type == "collection"


def test_start_conflicts_when_already_queued_or_running(
    db_manager, workflow, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    first = workflow.start(dry_run=False)
    assert first.status == "started"

    second = workflow.start(dry_run=False)
    assert second.status == "already_running"
    assert second.run_id == first.run_id


def test_start_allows_new_run_after_previous_terminal(
    db_manager, workflow, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    first = workflow.start(dry_run=False)
    workflow._transition(first.run_id, from_status="queued", to_status="running")
    assert workflow.complete(first.run_id, summary={"ok": True})

    second = workflow.start(dry_run=False)
    assert second.status == "started"
    assert second.run_id != first.run_id


def test_complete_after_running_transition_records_summary(
    db_manager, workflow, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=True)
    assert workflow._transition(
        result.run_id, from_status="queued", to_status="running"
    )
    assert workflow.complete(result.run_id, summary={"sources_processed": 3})

    status = workflow.get_status(result.run_id)
    assert status.status == "found"
    assert status.run_status == "succeeded"
    assert status.summary == {"sources_processed": 3}
    assert status.finished_at is not None

    # complete() must merge into run_metadata, not replace it — the
    # request payload start() wrote (dry_run) must survive alongside the
    # success summary (spec.md Design §1: run_metadata is the catch-all
    # for "the run's request payload and success summary", both).
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, result.run_id)
        assert row.run_metadata["dry_run"] is True
        assert row.run_metadata["summary"] == {"sources_processed": 3}


def test_complete_coerces_a_non_json_serialisable_summary(
    db_manager, workflow, monkeypatch
) -> None:
    """The collection report is a deep dict that can carry pydantic models
    (the dry-run selection branch puts `CollectorArticleModel` objects in
    `selection_results.articles`) and datetimes. `complete()` must persist
    the row anyway — a finished run losing its bookkeeping write is the
    exact failure mode Phase 4a exists to prevent.
    """
    import json

    import pydantic

    class _Article(pydantic.BaseModel):
        title: str
        published_at: datetime

    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(dry_run=True).run_id
    assert workflow._transition(run_id, from_status="queued", to_status="running")

    summary = {
        "collection_summary": {"sources_processed": 4},
        "selection_results": {
            "articles": [
                _Article(
                    title="Freeze-dried microbes",
                    published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            ]
        },
    }
    assert workflow.complete(run_id, summary=summary)

    status = workflow.get_status(run_id)
    assert status.run_status == "succeeded"
    stored = status.summary
    assert stored["collection_summary"]["sources_processed"] == 4
    assert (
        stored["selection_results"]["articles"][0]["title"] == "Freeze-dried microbes"
    )
    json.dumps(stored)  # the whole thing is now JSON-round-trippable


def test_fail_records_error_code_and_detail(db_manager, workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)
    workflow._transition(result.run_id, from_status="queued", to_status="running")

    assert workflow.fail(result.run_id, error_code="boom", error_detail="kaboom")

    status = workflow.get_status(result.run_id)
    assert status.run_status == "failed"
    assert status.error_code == "boom"
    assert status.error_detail == "kaboom"


def test_complete_is_a_cas_miss_when_not_running(
    db_manager, workflow, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)  # still 'queued', not 'running'
    assert workflow.complete(result.run_id, summary={}) is False
    status = workflow.get_status(result.run_id)
    assert status.run_status == "queued"  # untouched by the CAS miss


def test_heartbeat_updates_timestamp_and_false_when_not_running(
    db_manager, workflow, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)
    assert workflow.heartbeat(result.run_id) is False  # still queued, not running

    workflow._transition(result.run_id, from_status="queued", to_status="running")
    assert workflow.heartbeat(result.run_id) is True
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, result.run_id)
        assert row.heartbeat_at is not None


def test_get_status_not_found_for_unknown_id(db_manager, workflow) -> None:
    result = workflow.get_status(999999)
    assert result.status == "not_found"
    assert result.run_id is None


def test_get_status_returns_most_recent_when_no_id_given(db_manager, workflow) -> None:
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="succeeded",
                started_at=now - timedelta(minutes=5),
                finished_at=now - timedelta(minutes=5),
            )
        )
        session.add(
            WorkflowRun(
                run_type="collection",
                status="succeeded",
                started_at=now,
                finished_at=now,
            )
        )

    with db_manager.get_session() as session:
        latest_id = (
            session.query(WorkflowRun.id)
            .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
            .first()[0]
        )

    result = workflow.get_status(None)
    assert result.status == "found"
    assert result.run_id == latest_id


def test_get_status_ignores_non_collection_run_types_for_latest(
    db_manager, workflow
) -> None:
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="succeeded",
                started_at=now - timedelta(minutes=5),
                finished_at=now - timedelta(minutes=5),
            )
        )
        # A more recent row, but a different run_type — must not be
        # returned as "the latest collection run".
        session.add(WorkflowRun(run_type="refinery", status="running", started_at=now))

    result = workflow.get_status(None)
    assert result.status == "found"
    assert result.run_status == "succeeded"


def test_recover_expired_leases_transitions_stale_running_collection_rows(
    db_manager, workflow
) -> None:
    """Stale 'collection' rows (NULL or expired heartbeat) are recovered
    to 'interrupted'; a fresh 'collection' row is left alone."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        stale_null = WorkflowRun(
            run_type="collection",
            status="running",
            started_at=now - timedelta(hours=2),
            heartbeat_at=None,
        )
        session.add(stale_null)
        session.flush()
        stale_null_id = stale_null.id

    recovered = workflow.recover_expired_leases()

    assert recovered == [stale_null_id]
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, stale_null_id).status == "interrupted"


def test_recover_expired_leases_recovers_orphaned_queued_rows(
    db_manager, workflow, monkeypatch
) -> None:
    """A `queued` row can only exist momentarily between start()'s INSERT
    and _dispatch()'s thread flipping it to `running` — at process startup
    no such in-flight call exists, so any `queued` row found here is
    definitionally an orphan (the process crashed between those two
    steps). An automated review caught that the original implementation
    only checked `status == "running"`, so an orphaned `queued` row would
    permanently block every future collection request with 409 (the
    active-collection index treats queued the same as running) with no
    process left able to recover it. Freshness/age doesn't matter for a
    queued row — even one just inserted a second ago at startup is
    orphaned by definition — and queued rows never get a heartbeat_at at
    all, so there's no staleness window to wait out."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        orphaned_queued = WorkflowRun(
            run_type="collection",
            status="queued",
            started_at=now,
        )
        session.add(orphaned_queued)
        session.flush()
        orphaned_id = orphaned_queued.id

    recovered = workflow.recover_expired_leases()

    assert recovered == [orphaned_id]
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, orphaned_id)
        assert row.status == "interrupted"
        assert row.error_code == "process_restarted"

    # And the active-collection index no longer blocks a fresh start().
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=True)
    assert result.status == "started"


def test_recover_expired_leases_is_scoped_to_collection_run_type(
    db_manager, workflow
) -> None:
    """A stale 'running' row belonging to a *different* run_type must be
    left untouched — CollectionRunWorkflow.recover_expired_leases() must
    not reach into another subsystem's workflow_runs rows just because
    they share the table (deliberate, same scoping as get_status's
    "latest run" lookup — see the method's own docstring)."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        other_stale = WorkflowRun(
            run_type="refinery",
            status="running",
            started_at=now - timedelta(hours=2),
            heartbeat_at=None,
        )
        session.add(other_stale)
        session.flush()
        other_stale_id = other_stale.id

    recovered = workflow.recover_expired_leases()

    assert recovered == []
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, other_stale_id).status == "running"


def test_recover_expired_leases_is_idempotent(db_manager, workflow) -> None:
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="running",
                started_at=now - timedelta(hours=2),
                heartbeat_at=None,
            )
        )

    first = workflow.recover_expired_leases()
    second = workflow.recover_expired_leases()
    assert len(first) == 1
    assert second == []


def test_recover_expired_leases_excludes_a_row_that_loses_the_cas_race(
    db_manager, workflow, monkeypatch
) -> None:
    """A stale row selected as a recovery candidate but that loses the
    CAS race before the UPDATE fires (running -> interrupted misses, e.g.
    it transitioned away in between) must not appear in the returned
    list — `_transition`'s False return is a real, exercised path here,
    not just a theoretical one."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        stale = WorkflowRun(
            run_type="collection",
            status="running",
            started_at=now - timedelta(hours=2),
            heartbeat_at=None,
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id

    monkeypatch.setattr(workflow, "_transition", lambda *a, **k: False)

    recovered = workflow.recover_expired_leases()

    assert recovered == []
    with db_manager.get_session() as session:
        # _transition was faked out, so the row's real status is untouched.
        assert session.get(WorkflowRun, stale_id).status == "running"


# ---------------------------------------------------------------------------
# _run / _heartbeat_loop — the background-thread execution path `start()`
# dispatches to. Every other test in this file monkeypatches `_dispatch` to
# a no-op; these call `_run`/`_heartbeat_loop` directly (synchronously, not
# via `threading.Thread`) with a fake `news_collector.system.create_system`,
# matching the pattern tests/test_serving_admin_api.py's collect tests use.
# ---------------------------------------------------------------------------


class _FakeSystem:
    def __init__(
        self,
        *,
        initialize_ok=True,
        cycle_result=None,
        cycle_error=None,
        db_manager=None,
    ):
        self._initialize_ok = initialize_ok
        self._cycle_result = cycle_result if cycle_result is not None else {}
        self._cycle_error = cycle_error
        # When set, mirrors the real system: shutdown(close_db=True) disposes
        # the engine. Left None, shutdown is a pure no-op recorder.
        self._db_manager = db_manager
        self.export_called = False
        self.shutdown_called = False
        self.shutdown_close_db: bool | None = None

    def initialize(self) -> bool:
        return self._initialize_ok

    async def run_collection_cycle(self, dry_run: bool = False):
        if self._cycle_error is not None:
            raise self._cycle_error
        return self._cycle_result

    async def shutdown(self, close_db: bool = True):
        self.shutdown_called = True
        self.shutdown_close_db = close_db
        if close_db and self._db_manager is not None:
            self._db_manager.close()

    def export_latest_articles(self, file_path=None, limit=50):
        self.export_called = True
        return {}


def test_run_completes_and_exports_when_not_dry_run(
    db_manager, workflow, monkeypatch
) -> None:
    fake = _FakeSystem(cycle_result={"sources_processed": 5})
    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: fake, raising=False
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)

    workflow._run(result.run_id, False)

    assert fake.export_called is True
    assert fake.shutdown_called is True
    status = workflow.get_status(result.run_id)
    assert status.run_status == "succeeded"
    assert status.summary == {"sources_processed": 5}


def test_run_keeps_the_shared_db_open_for_its_bookkeeping_writes(
    db_manager, workflow, monkeypatch
) -> None:
    """Regression (Plan 060): ``bootstrap.build_database()`` hands back the
    process-wide ``DatabaseManager`` singleton, which the serving process
    keeps using. ``_run`` must ask ``system.shutdown(close_db=False)`` — if
    the engine gets disposed, ``complete()``/``fail()`` here (and every later
    ``/v1/admin/*`` request) hit ``TypeError: 'NoneType' object is not
    callable`` from ``SessionLocal()``.
    """
    fake = _FakeSystem(cycle_result={"sources_processed": 7}, db_manager=db_manager)
    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: fake, raising=False
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(dry_run=False).run_id

    workflow._run(run_id, False)

    assert fake.shutdown_close_db is False
    assert db_manager.SessionLocal is not None  # engine survived the run
    status = workflow.get_status(run_id)  # ... so bookkeeping + status work
    assert status.run_status == "succeeded"
    assert status.summary == {"sources_processed": 7}


def test_run_skips_export_when_dry_run(db_manager, workflow, monkeypatch) -> None:
    fake = _FakeSystem(cycle_result={"ok": True})
    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: fake, raising=False
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=True)

    workflow._run(result.run_id, True)

    assert fake.export_called is False
    status = workflow.get_status(result.run_id)
    assert status.run_status == "succeeded"


def test_run_fails_when_system_initialize_returns_false(
    db_manager, workflow, monkeypatch
) -> None:
    fake = _FakeSystem(initialize_ok=False)
    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: fake, raising=False
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)

    workflow._run(result.run_id, False)

    status = workflow.get_status(result.run_id)
    assert status.run_status == "failed"
    assert status.error_code == "collection_failed"
    assert "System initialization failed" in status.error_detail


def test_run_returns_early_when_queued_to_running_transition_fails(
    db_manager, workflow, monkeypatch
) -> None:
    """If the row is no longer `queued` by the time `_run` fires (e.g. it
    was already recovered/cancelled), `_run` must not call into the
    collection system at all."""
    create_system_calls: list[Any] = []
    monkeypatch.setattr(
        "news_collector.system.create_system",
        lambda *a, **k: create_system_calls.append(1),
        raising=False,
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    result = workflow.start(dry_run=False)
    # Force the row out of 'queued' before _run gets to it.
    assert workflow._transition(
        result.run_id, from_status="queued", to_status="cancelled"
    )

    workflow._run(result.run_id, False)

    assert create_system_calls == []
    status = workflow.get_status(result.run_id)
    assert status.run_status == "cancelled"  # untouched by _run


def test_heartbeat_loop_stops_promptly_when_heartbeat_returns_false(
    db_manager, monkeypatch
) -> None:
    # A fresh workflow with a 1-second heartbeat interval (independent of
    # lease_timeout_seconds since that decoupling — see
    # DEFAULT_HEARTBEAT_INTERVAL_SECONDS's module-level comment) so the
    # loop's first tick fires fast enough for a test.
    short_lease_workflow = CollectionRunWorkflow(
        db_manager, heartbeat_interval_seconds=1
    )
    monkeypatch.setattr(short_lease_workflow, "heartbeat", lambda run_id: False)
    stop = threading.Event()
    thread = threading.Thread(
        target=short_lease_workflow._heartbeat_loop, args=(1, stop)
    )

    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()  # returned on its own, stop was never set


# ---------------------------------------------------------------------------
# Regression guards for the Phase 4a defect: `_run` closing the process-wide
# `DatabaseManager` the serving process (and this workflow's own cached
# `self._db`) keeps using. Two instruments:
#   1. `_run` drives the REAL `NewsCollectorSystem.shutdown` and the cached
#      manager must survive it.
#   2. a signature-drift table: every call `_run` makes must stay bindable
#      against BOTH the real system and the `_FakeSystem` the other tests use
#      — a real-side failure means the workflow's call sites went stale
#      (exactly how the Phase 4a `shutdown(close_db=...)` change slipped
#      through); a fake-side failure means the test double drifted.
# ---------------------------------------------------------------------------


def _async_returning(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def test_run_drives_the_real_system_shutdown_without_closing_the_cached_db(
    db_manager, workflow, monkeypatch
) -> None:
    """P1: not a fake `shutdown` — the real
    ``NewsCollectorSystem.shutdown``. ``get_database_manager()`` self-heals a
    closed singleton, but ``serving/api.py`` and this workflow both hold a
    *cached* reference that never re-fetches, so a regressed
    ``close_db`` default (or a dropped parameter) silently bricks every later
    ``complete()``/``fail()`` and ``/v1/admin/*`` request. Only the leaf
    pipeline steps are stubbed; ``shutdown`` runs for real.
    """
    real = NewsCollectorSystem()
    real.db_manager = db_manager  # what bootstrap.build_database would return
    real.collector = None
    real.system_logger = None
    real.initialize = lambda: True  # type: ignore[method-assign]
    real.run_collection_cycle = _async_returning(  # type: ignore[method-assign]
        {"sources_processed": 1}
    )
    real.export_latest_articles = lambda **kw: {}  # type: ignore[method-assign]

    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: real, raising=False
    )
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(dry_run=False).run_id

    workflow._run(run_id, False)

    # The real shutdown ran (close_db defaults notwithstanding) and the
    # cached manager is still usable for the bookkeeping write + status read.
    assert db_manager.SessionLocal is not None
    with db_manager.get_session() as session:
        session.execute(select(WorkflowRun.id)).all()
    assert workflow.get_status(run_id).run_status == "succeeded"


_WORKFLOW_SYSTEM_CALLS = [
    ("initialize", {}),
    ("run_collection_cycle", {"dry_run": False}),
    (
        "export_latest_articles",
        {"file_path": "data/exports/latest_articles.json", "limit": 50},
    ),
    ("shutdown", {"close_db": False}),
]


@pytest.mark.parametrize("method_name, call_kwargs", _WORKFLOW_SYSTEM_CALLS)
def test_fake_system_accepts_every_call_run_makes(method_name, call_kwargs) -> None:
    sig = inspect.signature(getattr(_FakeSystem, method_name))
    sig.bind(None, **call_kwargs)  # None stands in for `self`; TypeError on drift


# ---------------------------------------------------------------------------
# Plan 078: start() reaps expired running leases (self-healing single-flight)
# ---------------------------------------------------------------------------


def test_start_reaps_expired_running_row(db_manager, workflow, monkeypatch) -> None:
    """A stale `running` row (dead owner) is recovered on start instead of
    409-blocking the new run forever (same deadlock as publication run 20)."""
    stale = datetime.now(timezone.utc) - timedelta(seconds=3600)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="running",
                started_at=stale,
                heartbeat_at=stale,
            )
        )
        session.commit()
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)

    result = workflow.start(dry_run=True)

    assert result.status == "started"
    with db_manager.get_session() as session:
        rows = session.query(WorkflowRun).order_by(WorkflowRun.id).all()
        assert [(row.id, row.status) for row in rows] == [
            (1, "interrupted"),
            (2, "queued"),
        ]


def test_start_leaves_fresh_queued_row_alone(db_manager, workflow, monkeypatch) -> None:
    """A fresh queued row may belong to a live concurrent start: it must
    survive start() untouched, and the second starter still gets 409."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(WorkflowRun(run_type="collection", status="queued", started_at=now))
        session.commit()
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)

    result = workflow.start(dry_run=True)

    assert result.status == "already_running"
    with db_manager.get_session() as session:
        rows = session.query(WorkflowRun).order_by(WorkflowRun.id).all()
        assert [(row.id, row.status) for row in rows] == [(1, "queued")]


def test_start_leaves_fresh_unbeaten_running_row_alone(
    db_manager, workflow, monkeypatch
) -> None:
    """Plan 078 nuance: a running row with no heartbeat yet but a fresh
    started_at may belong to a thread mid-transition — never reap it."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="running",
                started_at=now,
                heartbeat_at=None,
            )
        )
        session.commit()
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)

    result = workflow.start(dry_run=True)

    assert result.status == "already_running"
    with db_manager.get_session() as session:
        rows = session.query(WorkflowRun).order_by(WorkflowRun.id).all()
        assert [(row.id, row.status) for row in rows] == [(1, "running")]


@pytest.mark.parametrize("method_name, call_kwargs", _WORKFLOW_SYSTEM_CALLS)
def test_fake_system_accepts_every_call_run_makes(method_name, call_kwargs) -> None:
    sig = inspect.signature(getattr(_FakeSystem, method_name))
    sig.bind(None, **call_kwargs)
