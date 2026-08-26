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

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.logic.workflows.collection_run_workflow import (
    CollectionRunWorkflow,
)
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
    result = workflow.start(dry_run=False)
    assert workflow._transition(
        result.run_id, from_status="queued", to_status="running"
    )
    assert workflow.complete(result.run_id, summary={"sources_processed": 3})

    status = workflow.get_status(result.run_id)
    assert status.status == "found"
    assert status.run_status == "succeeded"
    assert status.summary == {"sources_processed": 3}
    assert status.finished_at is not None


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


def test_recover_expired_leases_transitions_stale_running_rows(
    db_manager, workflow
) -> None:
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        stale_null = WorkflowRun(
            run_type="collection",
            status="running",
            started_at=now - timedelta(hours=2),
            heartbeat_at=None,
        )
        stale_old = WorkflowRun(
            run_type="refinery",
            status="running",
            started_at=now - timedelta(hours=2),
            heartbeat_at=now - timedelta(hours=1),
        )
        # A different run_type: uq_workflow_runs_one_active_collection only
        # scopes run_type='collection', so a second 'collection' row here
        # would itself be rejected by that index — not what this test is
        # about (it only cares whether recovery respects heartbeat
        # freshness, across run_types).
        fresh = WorkflowRun(
            run_type="editorial", status="running", started_at=now, heartbeat_at=now
        )
        session.add_all([stale_null, stale_old, fresh])
        session.flush()
        stale_null_id = stale_null.id
        stale_old_id = stale_old.id
        fresh_id = fresh.id

    recovered = workflow.recover_expired_leases()

    assert sorted(recovered) == sorted([stale_null_id, stale_old_id])
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, stale_null_id).status == "interrupted"
        assert session.get(WorkflowRun, stale_old_id).status == "interrupted"
        assert session.get(WorkflowRun, fresh_id).status == "running"


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
