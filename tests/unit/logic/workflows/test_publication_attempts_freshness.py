"""Plan 131: run summaries must carry only *this run's* attempt evidence.

`publication_attempts/{article_id}.json` is keyed per article, not per run.
A run that wrote no attempt of its own (no-op, crash before any stage
persisted, failed batch item) used to inherit the previous attempt's
`pr_url` / `success: true`, so the review loop showed "PR ↗" for something
that failed. Rule under test: evidence is merged only when `generated_at`
parses and is strictly later than the run row's `started_at`; anything
older or undatable (legacy/hand-written files) is ignored, never trusted.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from news_collector.contracts import PublicationAttemptStageResult
from news_collector.logic.workflows.publication_attempts import (
    PublicationAttempt,
    persist_interrupted_attempt,
    persist_publication_attempt,
)
from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "publication_attempts_freshness.db"
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


def _seed_stale_attempt(dir_path, article_id, **fields):
    """Write a *previous run's* artifact: datable, but older than any run
    started after this call. No `run_id` key — like every file the current
    writer produces (the writer never saw a run id)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "article_id": str(article_id),
        "success": True,
        "stages": [],
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        **fields,
    }
    (dir_path / f"{article_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _fake_pipeline(monkeypatch, result):
    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        lambda **kw: result,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Regression: no-op / crash paths must not inherit a previous run's PR
# ---------------------------------------------------------------------------


def test_noop_run_does_not_inherit_a_previous_attempts_pr(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    """The bug: the export shortlist no longer contains the article, so the
    run writes nothing — the per-article artifact that already exists is a
    *previous* run's file and must not be merged."""
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=42).run_id
    _seed_stale_attempt(
        tmp_path / "attempts",
        42,
        pr_url="https://github.com/org/noticiencias/pull/111",
        final_slug="previous-slug",
    )
    _fake_pipeline(monkeypatch, {"status": "noop", "processed_count": 0})

    workflow._run(run_id, 42, None)

    status = workflow.get_status(run_id)
    assert status.run_status == "failed"
    assert status.summary.get("pr_url") is None
    assert status.summary.get("success") is not True
    assert status.summary.get("final_slug") is None


def test_failed_batch_item_does_not_inherit_the_previous_attempts_pr(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    """LAW-B6 symptom: a `failed` item in the batch list used to carry the
    previous attempt's `pr_url`."""
    monkeypatch.setattr(workflow, "_dispatch_batch", lambda *a, **k: None)
    run_id = workflow.start_batch([42]).run_id
    _seed_stale_attempt(
        tmp_path / "attempts",
        42,
        pr_url="https://github.com/org/noticiencias/pull/111",
        final_slug="previous-slug",
    )

    def fake_batch(article_ids, **kw):
        return {
            "status": "error",
            "processed_count": 0,
            "succeeded_count": 0,
            "failed_count": 1,
            "total_count": 1,
            "items": [
                {
                    "article_id": 42,
                    "status": "failed",
                    "processed_count": 0,
                    "message": "editorial reject",
                    "error_code": "editorial_block",
                }
            ],
        }

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_batch",
        fake_batch,
        raising=False,
    )

    workflow._run_batch(run_id, [42])

    status = workflow.get_status(run_id)
    assert status.run_status == "failed"
    item = status.summary["items"][0]
    assert item["status"] == "failed"
    assert item["pr_url"] is None


# ---------------------------------------------------------------------------
# Happy path: this run's own artifact is merged
# ---------------------------------------------------------------------------


def test_run_merges_the_attempt_it_wrote_itself(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=99).run_id
    attempts = tmp_path / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)

    def fake_pipeline(**kw):
        # The engine persists its attempt mid-run, through the canonical
        # writer (fresh `generated_at`).
        persist_publication_attempt(
            attempts,
            PublicationAttempt(
                article_id="99",
                success=True,
                pr_url="https://github.com/org/noticiencias/pull/128",
                final_slug="crispr-milestone",
                stages=[
                    PublicationAttemptStageResult(
                        name="editor_refinement", success=True
                    )
                ],
            ),
        )
        return {"status": "success", "processed_count": 1}

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        fake_pipeline,
        raising=False,
    )

    workflow._run(run_id, 99, None)

    status = workflow.get_status(run_id)
    assert status.run_status == "succeeded"
    assert status.summary["pr_url"] == "https://github.com/org/noticiencias/pull/128"
    assert status.summary["final_slug"] == "crispr-milestone"
    assert [stage["name"] for stage in status.summary["stages"]] == [
        "editor_refinement"
    ]


# ---------------------------------------------------------------------------
# Legacy / unverifiable files: ignore, never trust
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("generated_at", [None, "not-a-timestamp", ""])
def test_undatable_attempt_is_never_trusted(
    db_manager, workflow, tmp_path, monkeypatch, generated_at
) -> None:
    """A file that cannot prove when it was written (no or malformed
    `generated_at` — pre-change/hand-written artifacts) is not this run's
    evidence."""
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=7).run_id
    attempts = tmp_path / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    payload = {
        "article_id": "7",
        "success": True,
        "pr_url": "https://github.com/org/noticiencias/pull/7",
        "stages": [],
    }
    if generated_at is not None:
        payload["generated_at"] = generated_at
    (attempts / "7.json").write_text(json.dumps(payload), encoding="utf-8")
    _fake_pipeline(monkeypatch, {"status": "noop", "processed_count": 0})

    workflow._run(run_id, 7, None)

    assert workflow.get_status(run_id).summary.get("pr_url") is None


# ---------------------------------------------------------------------------
# Interrupted re-publish: prior file kept for history, not claimed
# ---------------------------------------------------------------------------


def test_interrupted_republish_keeps_prior_file_but_does_not_claim_its_pr(
    db_manager, workflow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    attempts = tmp_path / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    # The prior run's successful artifact exists on disk.
    persist_publication_attempt(
        attempts,
        PublicationAttempt(
            article_id="42",
            success=True,
            pr_url="https://github.com/org/noticiencias/pull/120",
            final_slug="crispr-milestone",
        ),
    )
    # This run starts after that file was written.
    run_id = workflow.start(article_id=42).run_id
    # The re-publish crashes before any stage persisted: the interrupt
    # handler keeps the prior success file (history), it does not overwrite.
    persist_interrupted_attempt(
        attempts,
        "42",
        [PublicationAttemptStageResult(name="editor_refinement", success=False)],
    )
    _fake_pipeline(
        monkeypatch,
        {"status": "error", "processed_count": 0, "message": "boom"},
    )

    workflow._run(run_id, 42, None)

    status = workflow.get_status(run_id)
    assert status.run_status == "failed"
    # The summary must not claim the prior run's PR...
    assert status.summary.get("pr_url") is None
    # ...while the file itself is still kept for history.
    kept = json.loads((attempts / "42.json").read_text(encoding="utf-8"))
    assert kept["success"] is True
    assert kept["pr_url"] == "https://github.com/org/noticiencias/pull/120"
