"""Tests for scripts/ops/prune_workflow_runs.py (Plan 060 / Phase 4a).

Proves the direct fix for the bug the old in-memory `_prune_collect_runs`
had: an old terminal row is pruned, but an old-but-`running` row is never
pruned regardless of age — see
plans/060/phase-4a-collection-run-workflow/spec.md Design §4.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun
from scripts.ops.prune_workflow_runs import prune_workflow_runs


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "prune_workflow_runs.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


def _add_run(db_manager, *, run_type, status, started_at, finished_at=None):
    with db_manager.get_session() as session:
        row = WorkflowRun(
            run_type=run_type,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )
        session.add(row)
        session.flush()
        return row.id


def test_old_terminal_row_is_pruned(db_manager):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=91)
    run_id = _add_run(
        db_manager,
        run_type="collection",
        status="succeeded",
        started_at=old,
        finished_at=old,
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 1
    assert summary.rows_deleted == 1
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is None


def test_old_running_row_is_never_pruned(db_manager):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=365)
    run_id = _add_run(
        db_manager, run_type="collection", status="running", started_at=old
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 0
    assert summary.rows_deleted == 0
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is not None


def test_old_queued_row_is_never_pruned(db_manager):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=365)
    run_id = _add_run(
        db_manager, run_type="collection", status="queued", started_at=old
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 0
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is not None


def test_recent_terminal_row_is_not_pruned(db_manager):
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=1)
    run_id = _add_run(
        db_manager,
        run_type="collection",
        status="succeeded",
        started_at=recent,
        finished_at=recent,
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 0
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is not None


def test_dry_run_reports_but_does_not_delete(db_manager):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=91)
    run_id = _add_run(
        db_manager,
        run_type="collection",
        status="failed",
        started_at=old,
        finished_at=old,
    )

    summary = prune_workflow_runs(db_manager, retention_days=90, dry_run=True)

    assert summary.candidates_found == 1
    assert summary.rows_deleted == 0
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is not None


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled", "interrupted"])
def test_every_terminal_status_is_eligible(db_manager, status):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=91)
    _add_run(
        db_manager,
        run_type="collection",
        status=status,
        started_at=old,
        finished_at=old,
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 1
    assert summary.rows_deleted == 1
