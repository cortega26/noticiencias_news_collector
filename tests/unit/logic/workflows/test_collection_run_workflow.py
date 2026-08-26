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

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from news_collector.logic.workflows.collection_run_workflow import CollectionRunWorkflow
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun


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
    def __init__(self, *, initialize_ok=True, cycle_result=None, cycle_error=None):
        self._initialize_ok = initialize_ok
        self._cycle_result = cycle_result if cycle_result is not None else {}
        self._cycle_error = cycle_error
        self.export_called = False
        self.shutdown_called = False

    def initialize(self) -> bool:
        return self._initialize_ok

    async def run_collection_cycle(self, dry_run: bool = False):
        if self._cycle_error is not None:
            raise self._cycle_error
        return self._cycle_result

    async def shutdown(self):
        self.shutdown_called = True

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
