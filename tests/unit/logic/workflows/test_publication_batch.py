"""Unit tests for batch publication (Plan 109).

Same conventions as `test_publication_run_workflow.py`: real SQLite DB,
`_dispatch_batch` monkeypatched to a no-op for state-machine tests,
`_run_batch` driven synchronously with a fake `run_publication_batch`
so no real Refinery pipeline is touched. Covers:

- `start_batch` validation + single-flight (shared slot with single runs);
- `_run_batch` success / partial / total-failure summaries with explicit
  per-item outcomes (LAW-B6);
- identity stability: re-running the same batch reuses each article's
  canonical slug (LAW-B5);
- `run_publication_batch` wrapper aggregation (all/partial/none/crash).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "publication_batch.db"
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


def _write_attempt(dir_path, article_id, **fields):
    dir_path.mkdir(parents=True, exist_ok=True)
    payload = {"article_id": str(article_id), "success": True, "stages": [], **fields}
    (dir_path / f"{article_id}.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# start_batch() — validation + shared single-flight slot
# ---------------------------------------------------------------------------


def test_start_batch_rejects_empty(workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    assert workflow.start_batch([]).status == "invalid_request"
    assert workflow.start_batch(None).status == "invalid_request"


def test_start_batch_inserts_queued_row_and_dispatches(
    db_manager, workflow, monkeypatch
) -> None:
    seen = {}
    monkeypatch.setattr(
        workflow,
        "_dispatch_batch",
        lambda run_id, **kw: seen.update(run_id=run_id, **kw),
    )

    result = workflow.start_batch([3, 7])

    assert result.status == "started"
    assert seen == {"run_id": result.run_id, "article_ids": [3, 7]}
    with db_manager.get_session() as session:
        row = session.get(WorkflowRun, result.run_id)
        assert row.status == "queued"
        assert row.run_type == "publication"
        assert row.run_metadata["article_ids"] == [3, 7]
        assert row.run_metadata["mode"] == "batch"


def test_batch_conflicts_with_active_single_run(workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    first = workflow.start(article_id=1)
    assert first.status == "started"

    second = workflow.start_batch([2, 3])
    assert second.status == "already_running"
    assert second.run_id == first.run_id


def test_single_conflicts_with_active_batch_run(workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    first = workflow.start_batch([2, 3])
    assert first.status == "started"

    second = workflow.start(article_id=1)
    assert second.status == "already_running"
    assert second.run_id == first.run_id


# ---------------------------------------------------------------------------
# _run_batch — per-item outcomes, run-level mapping, identity stability
# ---------------------------------------------------------------------------


def _fake_batch(monkeypatch, calls, results):
    def fake(article_ids, **kw):
        calls.append((list(article_ids), kw))
        items = []
        for article_id, outcome in zip(article_ids, results):
            if isinstance(outcome, Exception):
                raise outcome
            items.append({"article_id": article_id, **outcome})
        succeeded = sum(1 for i in items if i["status"] == "succeeded")
        status = (
            "success"
            if succeeded == len(items)
            else ("partial" if succeeded else "error")
        )
        summary = {
            "status": status,
            "processed_count": succeeded,
            "succeeded_count": succeeded,
            "failed_count": len(items) - succeeded,
            "total_count": len(items),
            "items": items,
        }
        if status == "error":
            summary["error_code"] = "batch_no_items_succeeded"
        return summary

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_batch",
        fake,
    )


def test_run_batch_success_merges_pr_urls_per_item(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    run_id = workflow.start_batch([11, 12]).run_id
    attempts = tmp_path / "attempts"
    _write_attempt(attempts, 11, pr_url="https://x/pr/11", final_slug="s-11")
    _write_attempt(attempts, 12, pr_url="https://x/pr/12", final_slug="s-12")
    calls: list = []
    _fake_batch(
        monkeypatch,
        calls,
        [
            {"status": "succeeded", "processed_count": 1},
            {"status": "succeeded", "processed_count": 1},
        ],
    )

    workflow._run_batch(run_id, [11, 12])

    assert calls == [([11, 12], {"skip_visuals": False})]
    status = workflow.get_status(run_id)
    assert status.run_status == "succeeded"
    items = status.summary["items"]
    assert [(i["article_id"], i["status"], i["pr_url"]) for i in items] == [
        (11, "succeeded", "https://x/pr/11"),
        (12, "succeeded", "https://x/pr/12"),
    ]
    assert status.summary["succeeded_count"] == 2


def test_run_batch_partial_completes_with_explicit_failed_item(
    workflow, monkeypatch
) -> None:
    """One bad article must not abort the rest, and the run still closes
    as succeeded with the failure recorded per item (LAW-B6)."""
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    run_id = workflow.start_batch([21, 22]).run_id
    calls: list = []
    _fake_batch(
        monkeypatch,
        calls,
        [
            {"status": "succeeded", "processed_count": 1},
            {
                "status": "failed",
                "processed_count": 0,
                "message": "editorial reject",
                "error_code": "editorial_fact_check_disputed",
            },
        ],
    )

    workflow._run_batch(run_id, [21, 22])

    status = workflow.get_status(run_id)
    assert status.run_status == "succeeded"
    assert status.summary["succeeded_count"] == 1
    assert status.summary["failed_count"] == 1
    failed = status.summary["items"][1]
    assert failed["status"] == "failed"
    assert failed["message"] == "editorial reject"


def test_run_batch_total_failure_fails_the_run(workflow, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    run_id = workflow.start_batch([31]).run_id
    calls: list = []
    _fake_batch(monkeypatch, calls, [{"status": "failed", "processed_count": 0}])

    workflow._run_batch(run_id, [31])

    status = workflow.get_status(run_id)
    assert status.run_status == "failed"
    assert status.summary["items"][0]["status"] == "failed"


def test_run_batch_rerun_reuses_canonical_slugs(
    workflow, tmp_path, monkeypatch
) -> None:
    """LAW-B5: retrying the same batch must not mint new identities."""
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    attempts = tmp_path / "attempts"
    _write_attempt(attempts, 41, pr_url="https://x/pr/41", final_slug="stable-slug-41")
    calls: list = []
    _fake_batch(monkeypatch, calls, [{"status": "succeeded", "processed_count": 1}])

    first = workflow.start_batch([41]).run_id
    workflow._run_batch(first, [41])
    # A later attempt file for the same article keeps the same slug
    # (deterministic identity); the rerun must surface it unchanged.
    second = workflow.start_batch([41]).run_id
    workflow._run_batch(second, [41])

    assert workflow.get_status(first).summary["items"][0]["final_slug"] == (
        "stable-slug-41"
    )
    assert workflow.get_status(second).summary["items"][0]["final_slug"] == (
        "stable-slug-41"
    )


# ---------------------------------------------------------------------------
# run_publication_batch wrapper aggregation
# ---------------------------------------------------------------------------


def _fake_pipeline(monkeypatch, behaviour):
    def fake(*, process_id=None, **kw):
        return behaviour(process_id)

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        fake,
    )


def test_wrapper_all_success(monkeypatch) -> None:
    from news_collector.logic.workflows.publication_pipeline import (
        run_publication_batch,
    )

    _fake_pipeline(
        monkeypatch,
        lambda pid: {"status": "success", "processed_count": 1},
    )
    result = run_publication_batch([1, 2])
    assert result["status"] == "success"
    assert result["succeeded_count"] == 2
    assert [i["status"] for i in result["items"]] == ["succeeded", "succeeded"]


def test_wrapper_partial_on_mixed_outcomes(monkeypatch) -> None:
    from news_collector.logic.workflows.publication_pipeline import (
        run_publication_batch,
    )

    def behaviour(pid):
        if pid == "1":
            return {"status": "success", "processed_count": 1}
        return {"status": "error", "message": "nope", "processed_count": 0}

    _fake_pipeline(monkeypatch, behaviour)
    result = run_publication_batch([1, 2])
    assert result["status"] == "partial"
    assert result["succeeded_count"] == 1
    assert result["failed_count"] == 1


def test_wrapper_error_when_nothing_succeeds(monkeypatch) -> None:
    from news_collector.logic.workflows.publication_pipeline import (
        run_publication_batch,
    )

    _fake_pipeline(
        monkeypatch,
        lambda pid: {"status": "error", "message": "nope", "processed_count": 0},
    )
    result = run_publication_batch([1])
    assert result["status"] == "error"
    assert result["error_code"] == "batch_no_items_succeeded"


def test_wrapper_crash_becomes_explicit_failed_item(monkeypatch) -> None:
    from news_collector.logic.workflows.publication_pipeline import (
        run_publication_batch,
    )

    def behaviour(pid):
        if pid == "2":
            raise RuntimeError("boom")
        return {"status": "success", "processed_count": 1}

    _fake_pipeline(monkeypatch, behaviour)
    result = run_publication_batch([1, 2])
    assert result["status"] == "partial"
    crashed = result["items"][1]
    assert crashed["status"] == "failed"
    assert crashed["error_code"] == "batch_item_crashed"


def test_wrapper_rejects_empty_and_oversize() -> None:
    import pytest

    from news_collector.logic.workflows.publication_pipeline import (
        run_publication_batch,
    )

    with pytest.raises(ValueError):
        run_publication_batch([])
    with pytest.raises(ValueError):
        run_publication_batch([1, 2, 3, 4, 5, 6])
