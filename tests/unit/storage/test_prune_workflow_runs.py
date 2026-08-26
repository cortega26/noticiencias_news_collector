"""Tests for scripts/ops/prune_workflow_runs.py (Plan 060 / Phase 4a).

Proves the direct fix for the bug the old in-memory `_prune_collect_runs`
had: an old terminal row is pruned, but an old-but-`running` row is never
pruned regardless of age — see
plans/060/phase-4a-collection-run-workflow/spec.md Design §4.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun, WorkflowStageAttempt
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


def test_terminal_row_with_stage_attempts_is_pruned_along_with_them(db_manager):
    """workflow_stage_attempts.workflow_run_id is ON DELETE RESTRICT (Phase
    3a) — an automated review caught that a naive `session.delete(row)` on
    a run with recorded stage attempts would raise IntegrityError on
    commit and roll back the *entire* pruning batch, not just this one
    row. Proves the fix: stage attempts are deleted first, in the same
    per-row unit of work, so the run and its attempts are both pruned and
    no other candidate in the batch is affected."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=91)
    run_id = _add_run(
        db_manager,
        run_type="collection",
        status="succeeded",
        started_at=old,
        finished_at=old,
    )
    with db_manager.get_session() as session:
        session.add(
            WorkflowStageAttempt(
                workflow_run_id=run_id,
                stage_name="fetch",
                attempt_number=1,
                status="completed",
                started_at=old,
                finished_at=old,
            )
        )

    # A second, independent candidate in the same batch — proves a
    # RESTRICT-blocked row (if the fix were absent) wouldn't take this one
    # down with it either.
    other_run_id = _add_run(
        db_manager,
        run_type="collection",
        status="failed",
        started_at=old,
        finished_at=old,
    )

    summary = prune_workflow_runs(db_manager, retention_days=90)

    assert summary.candidates_found == 2
    assert summary.rows_deleted == 2
    with db_manager.get_session() as session:
        assert session.get(WorkflowRun, run_id) is None
        assert session.get(WorkflowRun, other_run_id) is None
        remaining_attempts = (
            session.query(WorkflowStageAttempt)
            .filter(WorkflowStageAttempt.workflow_run_id == run_id)
            .count()
        )
        assert remaining_attempts == 0


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
