"""Unit tests for PublicationRunWorkflow (Plan 060 / Phase 4c).

Same conventions as `test_collection_run_workflow.py`: exercises the class
directly against a real SQLite DB; `_dispatch` is monkeypatched to a no-op
for the state-machine tests; the `_run` tests call `_run` synchronously with
a fake `apps.refinery.main.main` so no real Refinery pipeline is touched.
"""

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "publication_run_workflow.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


@pytest.fixture
def workflow(db_manager, tmp_path):
    return PublicationRunWorkflow(
        db_manager,
        lease_timeout_seconds=60,
        publication_attempts_dir=tmp_path / "attempts",
    )


# ---------------------------------------------------------------------------
# start() — request validation + single-flight
# ---------------------------------------------------------------------------


def test_start_requires_exactly_one_of_id_or_url(workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)

    assert workflow.start().status == "invalid_request"
    assert (
        workflow.start(article_id=1, article_url="https://x").status
        == "invalid_request"
    )


def test_start_inserts_queued_row_and_dispatches(db_manager, workflow, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        workflow,
        "_dispatch",
        lambda run_id, **kw: seen.update(run_id=run_id, **kw),
    )

    result = workflow.start(article_id=42)

    assert result.status == "started"
    assert seen == {
        "run_id": result.run_id,
        "article_id": 42,
        "article_url": None,
        "dry_run": False,
    }
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, result.run_id)
        assert row.status == "queued"
        assert row.run_type == "publication"
        assert row.run_metadata["article_id"] == 42


def test_start_conflicts_when_a_publication_run_is_active(workflow, monkeypatch):
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    first = workflow.start(article_id=1)
    assert first.status == "started"

    second = workflow.start(article_url="https://example.com/x")
    assert second.status == "already_running"
    assert second.run_id == first.run_id


def test_a_collection_run_does_not_block_a_publication_run(db_manager, workflow):
    """The two single-flight indexes are independent — a collection run in
    flight must not 409 a publish."""
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="running",
                started_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    import unittest.mock

    with unittest.mock.patch.object(workflow, "_dispatch"):
        result = workflow.start(article_id=7)
    assert result.status == "started"


# ---------------------------------------------------------------------------
# _run — maps apps.refinery.main.main() -> succeeded / failed
# ---------------------------------------------------------------------------


def _write_attempt(dir_path, article_id, **fields):
    dir_path.mkdir(parents=True, exist_ok=True)
    payload = {"article_id": str(article_id), "success": True, "stages": [], **fields}
    (dir_path / f"{article_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_run_success_records_pr_url_from_the_attempt_summary(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=99).run_id

    _write_attempt(
        tmp_path / "attempts",
        99,
        pr_url="https://github.com/org/noticiencias/pull/128",
        final_slug="crispr-milestone",
        failure_class=None,
    )
    monkeypatch.setattr(
        "apps.refinery.main.main",
        lambda **kw: {"status": "success", "processed_count": 1},
        raising=False,
    )

    workflow._run(run_id, 99, None, False)

    status = workflow.get_status(run_id)
    assert status.run_status == "succeeded"
    assert status.summary["pr_url"] == "https://github.com/org/noticiencias/pull/128"
    assert status.summary["final_slug"] == "crispr-milestone"
    json.dumps(status.summary)  # persisted JSON-safe


def test_run_editorial_rejection_is_a_failed_run_that_keeps_the_reason(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=5).run_id

    _write_attempt(
        tmp_path / "attempts",
        5,
        success=False,
        failure_class="editorial_policy",
        pr_url=None,
    )
    monkeypatch.setattr(
        "apps.refinery.main.main",
        lambda **kw: {
            "status": "error",
            "processed_count": 0,
            "message": "Blocked by editorial policy: unverifiable claim",
            "error_code": "editorial_block",
        },
        raising=False,
    )

    workflow._run(run_id, 5, None, False)

    status = workflow.get_status(run_id)
    assert status.run_status == "failed"
    assert status.error_code == "editorial_block"
    assert "editorial policy" in (status.error_detail or "")
    assert status.summary["failure_class"] == "editorial_policy"


def test_run_does_not_close_the_shared_db(db_manager, workflow, monkeypatch) -> None:
    """Phase 4a lesson: whatever `_run` invokes must not dispose the
    process-wide engine. `apps.refinery.main.main` uses its own
    DatabaseManager, but pin the guarantee with a test."""
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=1).run_id
    monkeypatch.setattr(
        "apps.refinery.main.main",
        lambda **kw: {"status": "success", "processed_count": 1},
        raising=False,
    )

    workflow._run(run_id, 1, None, False)

    assert db_manager.SessionLocal is not None
    with db_manager.get_session() as session:  # still usable
        assert session.get(WorkflowRun, run_id).status == "succeeded"


# ---------------------------------------------------------------------------
# lease recovery + status lookup
# ---------------------------------------------------------------------------


def test_recover_expired_leases_only_touches_publication_rows(db_manager, workflow):
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    with db_manager.get_session() as session:
        session.add_all(
            [
                WorkflowRun(
                    run_type="publication",
                    status="running",
                    started_at=old,
                    heartbeat_at=old,
                ),
                WorkflowRun(
                    run_type="collection",
                    status="running",
                    started_at=old,
                    heartbeat_at=old,
                ),
            ]
        )
        session.commit()

    recovered = workflow.recover_expired_leases()

    assert len(recovered) == 1
    with db_manager.get_session() as session:
        rows = {r.run_type: r.status for r in session.query(WorkflowRun).all()}
    assert rows["publication"] == "interrupted"
    assert rows["collection"] == "running"  # untouched


def test_get_status_unknown_id_is_not_found_never_latest(
    db_manager, workflow, monkeypatch
):
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    workflow.start(article_id=1)  # a real row exists

    assert workflow.get_status(999999).status == "not_found"


# ---------------------------------------------------------------------------
# _read_attempt_for_id — keyed by RefineryEngine's own sanitiser
# ---------------------------------------------------------------------------


def test_read_attempt_for_id_uses_the_refinery_engine_sanitiser(workflow, tmp_path):
    """The file name must track `RefineryEngine._safe_publication_artifact_name`
    exactly — if that sanitiser changes, the read must follow, not silently
    stop matching and drop every `pr_url`."""
    from news_collector.logic.workflows.refinery_engine import RefineryEngine

    messy_id = "https://example.com/a?b=c&d=e"
    safe = RefineryEngine._safe_publication_artifact_name(messy_id)
    assert safe != messy_id  # sanity: the id really does need sanitising

    attempts = tmp_path / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    (attempts / f"{safe}.json").write_text(
        json.dumps({"article_id": messy_id, "pr_url": "https://x/pull/7"}),
        encoding="utf-8",
    )

    got = workflow._read_attempt_for_id(messy_id)
    assert got is not None and got["pr_url"] == "https://x/pull/7"


# ---------------------------------------------------------------------------
# Signature-drift guard for the `apps.refinery.main.main` call `_run` makes.
# The `_run` tests fake it with `lambda **kw: ...`, which would swallow a
# renamed/removed parameter silently — bind the real signature instead.
# ---------------------------------------------------------------------------


def test_refinery_main_accepts_every_kwarg_run_passes() -> None:
    from apps.refinery.main import main as run_refinery

    inspect.signature(run_refinery).bind_partial(
        process_id="123",
        article_url=None,
        skip_visuals=False,
        dry_run=False,
    )
