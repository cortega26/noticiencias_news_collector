"""Integration tests for the Phase 5b stale-publication reconciler.

Real SQLite through ``DatabaseManager``; all evidence comes from stored
receipts and the legacy article projection. No network, no GitHub client:
the no-duplicate-PR guarantee is enforced structurally (the workflow has no
publisher collaborator) and asserted with a tripwire monkeypatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.components.publishing.github_publisher import GitHubPublisher
from news_collector.logic.workflows.publication_reconciliation import (
    RUN_TYPE_PUBLICATION_RECONCILIATION,
    PublicationReconciliationWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, WorkflowRun

REFINERY_ID = "refinery-reconcile-1"


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "reconcile.db"})
    yield manager
    manager.close()


def _stale_reference() -> datetime:
    """A reference time far enough after creation to make fresh attempts
    stale without sleeping."""
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _pr_created_article(db_manager: DatabaseManager, *, suffix: str = "a") -> int:
    with db_manager.get_session() as session:
        article = Article(
            title=f"Reconcile test {suffix}",
            url=f"https://example.com/reconcile/{suffix}",
            summary="A test article",
            source_id="test-source",
            source_name="Test Source",
            category="science",
            processing_status="pending",
        )
        session.add(article)
        session.flush()
        article_id = int(article.id)
    db_manager.mark_article_publishing(article_id, f"content/update-{suffix}")
    db_manager.mark_article_published(
        article_id, f"https://github.com/pr/{suffix}", REFINERY_ID
    )
    return article_id


def _attempt(db_manager: DatabaseManager, article_id: int):
    [attempt] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    return attempt


def _publish_payload(
    *,
    refinery_id: str = REFINERY_ID,
    deploy_url: str | None = "https://noticiencias.com",
) -> dict:
    diagnostics = (
        [{"check": "deploy", "status": "pass", "deploy_url": deploy_url}]
        if deploy_url
        else []
    )
    return {
        "event": "publish_complete",
        "commit_sha": "abc123def",
        "branch": "publish/reconcile",
        "status": "success",
        "diagnostics": diagnostics,
        "frontend_ref": "abc123def",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
        "publication_ids": [refinery_id],
    }


def _validation_payload(*, refinery_id: str = REFINERY_ID) -> dict:
    return {
        "event": "validation_result",
        "commit_sha": "abc123def",
        "branch": "publish/reconcile",
        "status": "fail",
        "diagnostics": [
            {"check": "frontmatter-dates", "status": "fail", "errors": ["bad"]}
        ],
        "frontend_ref": "abc123def",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
        "publication_ids": [refinery_id],
    }


def _failed_receipt(db_manager: DatabaseManager, *, key: str, payload: dict) -> None:
    view, _ = db_manager.webhook_receipts.record_receipt(
        delivery_key=key, event_type=payload["event"], payload=payload
    )
    db_manager.webhook_receipts.mark_processing(view.delivery_key)
    db_manager.webhook_receipts.mark_failed(view.delivery_key, "RuntimeError: boom")


def _audit_runs(db_manager: DatabaseManager) -> list[WorkflowRun]:
    with db_manager.get_session() as session:
        return (
            session.query(WorkflowRun)
            .filter(WorkflowRun.run_type == RUN_TYPE_PUBLICATION_RECONCILIATION)
            .all()
        )


@pytest.fixture(autouse=True)
def _no_pr_creation(monkeypatch: pytest.MonkeyPatch):
    """Tripwire: any attempt to open a PR during reconciliation fails the
    test (the workflow must never own a publisher)."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("reconciler must never create a pull request")

    monkeypatch.setattr(GitHubPublisher, "create_pull_request", _forbidden)


class TestReceiptReplay:
    def test_failed_publish_receipt_replay_completes_stale_attempt(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        attempt = _attempt(db_manager, article_id)
        _failed_receipt(db_manager, key="derived:publish-1", payload=_publish_payload())

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.scanned == 1
        assert summary.replayable_receipts == 1
        assert summary.replayed == 1
        assert summary.completed == 1
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "COMPLETED"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "deployed"]
        receipt = db_manager.webhook_receipts.get_receipt("derived:publish-1")
        assert receipt is not None and receipt.status == "processed"
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            assert article.processing_status == "completed"
            assert article.published_url == "https://noticiencias.com"

    def test_failed_validation_receipt_replay_rejects_stale_attempt(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        attempt = _attempt(db_manager, article_id)
        _failed_receipt(
            db_manager, key="derived:validation-1", payload=_validation_payload()
        )

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.rejected == 1
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "REJECTED"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert events[-1].event_type == "rejected"

    def test_replay_failure_keeps_receipt_retryable(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        article_id = _pr_created_article(db_manager)
        _failed_receipt(db_manager, key="derived:boom", payload=_publish_payload())

        def _boom(*args, **kwargs):
            raise RuntimeError("apply exploded")

        monkeypatch.setattr(
            "news_collector.logic.workflows.publication_reconciliation."
            "apply_publish_complete",
            _boom,
        )

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.replayed == 0
        receipt = db_manager.webhook_receipts.get_receipt("derived:boom")
        assert receipt is not None and receipt.status == "failed"
        assert "apply exploded" in (receipt.error or "")
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "PR_CREATED"


class TestEvidenceRepairs:
    def test_legacy_completed_with_deploy_url_repairs_attempt(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        attempt = _attempt(db_manager, article_id)
        # Simulate the legacy half succeeding while the dual-write half
        # missed: article is completed with a real deploy URL, attempt row
        # is still PR_CREATED.
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            article.processing_status = "completed"
            article.published_url = "https://noticiencias.com/live"
            session.add(article)

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.completed == 1
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "COMPLETED"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert events[-1].event_type == "deployed"
        assert events[-1].details["source"] == "legacy_projection"

    def test_legacy_completed_without_deploy_url_is_not_published(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            article.processing_status = "completed"
            article.published_url = None
            session.add(article)

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.completed == 0
        assert summary.missing_deploy_evidence == 1
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "PR_CREATED"

    def test_legacy_rejected_repairs_attempt_with_reason(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        attempt = _attempt(db_manager, article_id)
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            metadata = dict(article.article_metadata or {})
            publication = dict(metadata.get("publication") or {})
            publication.update({"state": "REJECTED", "reason": "Content Guard failed"})
            metadata["publication"] = publication
            article.article_metadata = metadata
            article.processing_status = "rejected"
            session.add(article)

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.rejected == 1
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "REJECTED"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert events[-1].details["reason"] == "Content Guard failed"

    def test_terminal_attempt_is_not_a_candidate(self, db_manager: DatabaseManager):
        article_id = _pr_created_article(db_manager)
        db_manager.complete_publication_attempts([REFINERY_ID], "https://x/live")

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.scanned == 0
        assert summary.actions == ()


class TestStaleOpenPr:
    def test_stale_open_pr_without_evidence_is_reported_not_touched(
        self, db_manager: DatabaseManager
    ):
        article_id = _pr_created_article(db_manager)
        attempt = _attempt(db_manager, article_id)

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.scanned == 1
        assert summary.stale_pr_open == 1
        assert summary.actions[0].outcome == "stale_pr_open"
        assert summary.actions[0].refinery_id == REFINERY_ID
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "PR_CREATED"
        assert reloaded.id == attempt.id
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            assert article.processing_status == "publishing"
            assert article.published_url is None


class TestQueueHygiene:
    def test_malformed_payload_is_reported_not_guessed(
        self, db_manager: DatabaseManager
    ):
        _pr_created_article(db_manager)
        view, _ = db_manager.webhook_receipts.record_receipt(
            delivery_key="derived:malformed",
            event_type="publish_complete",
            payload={"event": "not-a-real-event"},
        )
        db_manager.webhook_receipts.mark_failed(view.delivery_key, "boom")

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.malformed_payloads == 1
        assert summary.replayed == 0
        receipt = db_manager.webhook_receipts.get_receipt("derived:malformed")
        assert receipt is not None and receipt.status == "failed"

    def test_unmatched_receipt_is_reported(self, db_manager: DatabaseManager):
        _pr_created_article(db_manager)
        _failed_receipt(
            db_manager,
            key="derived:elsewhere",
            payload=_publish_payload(refinery_id="refinery-other"),
        )

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference()
        )

        assert summary.unmatched_receipts == 1
        assert summary.replayed == 0
        receipt = db_manager.webhook_receipts.get_receipt("derived:elsewhere")
        assert receipt is not None and receipt.status == "failed"


class TestDryRunAndAudit:
    def test_dry_run_writes_nothing(self, db_manager: DatabaseManager):
        article_id = _pr_created_article(db_manager)
        _failed_receipt(db_manager, key="derived:dry", payload=_publish_payload())

        summary = PublicationReconciliationWorkflow(db_manager).run(
            now=_stale_reference(), dry_run=True
        )

        assert summary.dry_run is True
        assert summary.replayable_receipts == 1
        assert summary.replayed == 0
        # Without the replay the legacy article is still 'publishing', so the
        # on-disk truth is a stale-open-PR report — no prospective repair is
        # simulated.
        assert summary.stale_pr_open == 1
        assert summary.completed == 0
        [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert reloaded.state == "PR_CREATED"
        receipt = db_manager.webhook_receipts.get_receipt("derived:dry")
        assert receipt is not None and receipt.status == "failed"
        assert _audit_runs(db_manager) == []

    def test_real_run_persists_audit_row_with_summary(
        self, db_manager: DatabaseManager
    ):
        _pr_created_article(db_manager)

        PublicationReconciliationWorkflow(db_manager).run(now=_stale_reference())

        [run] = _audit_runs(db_manager)
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.run_metadata["summary"]["stale_pr_open"] == 1
        assert run.run_metadata["summary"]["dry_run"] is False

    def test_no_candidates_still_records_an_audit_row(
        self, db_manager: DatabaseManager
    ):
        # Fresh attempt: not stale yet at the real current time. The empty
        # pass is still recorded — it is evidence the reconciler ran.
        _pr_created_article(db_manager)

        summary = PublicationReconciliationWorkflow(db_manager).run()

        assert summary.scanned == 0
        [run] = _audit_runs(db_manager)
        assert run.status == "succeeded"
        assert run.run_metadata["summary"]["scanned"] == 0
