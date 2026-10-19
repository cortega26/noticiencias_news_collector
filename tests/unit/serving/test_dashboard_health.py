"""Unit tests for the dashboard health evidence builder (Plan 060 /
Phase 5c).

Real SQLite through ``DatabaseManager`` with a frozen ``now`` so age-based
status rules are deterministic. The central contract under test: no record
means ``evidence="none"`` and ``status="unknown"`` — never ``pass``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from news_collector.contracts.webhook import ValidationResultEvent
from news_collector.logic.workflows.publication_callbacks import apply_validation_result
from news_collector.logic.workflows.publication_reconciliation import (
    PublicationReconciliationWorkflow,
)
from news_collector.serving.dashboard_health import build_dashboard_health
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

# Content Guard rejection fixtures (mirror the correlated-callback shape of
# tests/unit/logic/workflows/test_publication_callbacks.py).
CG_REFINERY_ID = "refinery-dashboard-cg"
CG_ATTEMPT_ID = "dashboard-cg-attempt"
CG_PR_NUMBER = 1490
CG_SHA256 = hashlib.sha256(b"dashboard content guard").hexdigest()
RELEASE_ATTEMPT_ID = "dashboard-release-attempt"


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "dash.db"})
    yield manager
    manager.close()


def _make_article(db_manager: DatabaseManager, seed: str = "dash") -> int:
    with db_manager.get_session() as session:
        article = Article(
            title=f"Dashboard {seed}",
            url=f"https://example.com/dashboard/{seed}",
            summary="A test article",
            source_id="test-source",
            source_name="Test Source",
            category="science",
            processing_status="publishing",
        )
        session.add(article)
        session.flush()
        return int(article.id)


def _attempt(db_manager, article_id, *, state, started_at):
    return db_manager.lifecycle.record_publication_attempt(
        article_id,
        refinery_id=f"refinery-{state}-{started_at.timestamp()}",
        state=state,
        started_at=started_at,
    )


class TestNoEvidence:
    def test_empty_database_is_all_unknown_never_pass(self, db_manager):
        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.generated_at == NOW
        assert envelope.publication.status == "unknown"
        assert envelope.publication.evidence == "none"
        assert envelope.callbacks.status == "unknown"
        assert envelope.callbacks.evidence == "none"
        assert envelope.validation.status == "unknown"
        assert envelope.validation.evidence == "none"

    def test_counts_keep_the_full_known_key_set(self, db_manager):
        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.publication.counts == {
            "PUBLISHING": 0,
            "PR_CREATED": 0,
            "REJECTED": 0,
            "COMPLETED": 0,
        }
        assert envelope.callbacks.counts == {
            "received": 0,
            "processed": 0,
            "failed": 0,
        }
        assert envelope.validation.counts == {"check_passed": 0, "rejected": 0}


class TestPublication:
    def test_stuck_publishing_is_fail_with_age(self, db_manager):
        article_id = _make_article(db_manager)
        _attempt(
            db_manager,
            article_id,
            state="PUBLISHING",
            started_at=NOW - timedelta(hours=2),
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.publication.evidence == "present"
        assert envelope.publication.status == "fail"
        assert envelope.publication.counts["PUBLISHING"] == 1
        assert envelope.publication.oldest_pending_age_seconds == 7200

    def test_stale_pr_created_is_warning_with_age(self, db_manager):
        article_id = _make_article(db_manager)
        _attempt(
            db_manager,
            article_id,
            state="PR_CREATED",
            started_at=NOW - timedelta(minutes=90),
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.publication.status == "warning"
        assert envelope.publication.oldest_pending_age_seconds == 5400

    def test_fresh_attempts_pass(self, db_manager):
        article_id = _make_article(db_manager)
        _attempt(
            db_manager,
            article_id,
            state="PR_CREATED",
            started_at=NOW - timedelta(minutes=5),
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.publication.status == "pass"
        assert envelope.publication.oldest_pending_age_seconds == 300

    def test_terminal_only_attempts_pass_without_pending_age(self, db_manager):
        article_id = _make_article(db_manager)
        _attempt(
            db_manager,
            article_id,
            state="COMPLETED",
            started_at=NOW - timedelta(minutes=5),
        )
        _attempt(
            db_manager,
            article_id,
            state="REJECTED",
            started_at=NOW - timedelta(minutes=6),
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.publication.status == "pass"
        assert envelope.publication.oldest_pending_age_seconds is None
        assert envelope.publication.counts == {
            "PUBLISHING": 0,
            "PR_CREATED": 0,
            "REJECTED": 1,
            "COMPLETED": 1,
        }


class TestCallbacks:
    def _receipt(self, db_manager, key: str, status: str):
        view, _ = db_manager.webhook_receipts.record_receipt(
            delivery_key=key,
            event_type="publish_complete",
            payload={"event": "publish_complete", "publication_ids": ["r"]},
        )
        db_manager.webhook_receipts.mark_processing(view.delivery_key)
        if status == "processed":
            db_manager.webhook_receipts.mark_processed(
                view.delivery_key, {"action": "noop"}
            )
        elif status == "failed":
            db_manager.webhook_receipts.mark_failed(view.delivery_key, "boom")

    def test_failed_receipt_is_fail(self, db_manager):
        self._receipt(db_manager, "cb-failed", "failed")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.callbacks.status == "fail"
        assert envelope.callbacks.counts["failed"] == 1
        assert envelope.callbacks.oldest_pending_age_seconds is not None

    def test_pending_receipt_is_warning(self, db_manager):
        self._receipt(db_manager, "cb-received", "received")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.callbacks.status == "warning"
        assert envelope.callbacks.counts["received"] == 1

    def test_all_processed_is_pass(self, db_manager):
        self._receipt(db_manager, "cb-processed", "processed")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.callbacks.status == "pass"
        assert envelope.callbacks.oldest_pending_age_seconds is None
        assert envelope.callbacks.counts == {
            "received": 0,
            "processed": 1,
            "failed": 0,
        }


class TestValidation:
    def _event(self, db_manager, article_id, event_type):
        attempt = _attempt(
            db_manager,
            article_id,
            state="PR_CREATED",
            started_at=NOW - timedelta(minutes=10),
        )
        db_manager.lifecycle.record_publication_event(
            attempt.id, event_type=event_type, occurred_at=NOW - timedelta(minutes=5)
        )

    def test_rejected_event_is_warning(self, db_manager):
        article_id = _make_article(db_manager)
        self._event(db_manager, article_id, "check_passed")
        self._event(db_manager, article_id, "rejected")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "warning"
        assert envelope.validation.counts == {"check_passed": 1, "rejected": 1}
        assert envelope.validation.measured_at is not None

    def test_check_passed_only_is_pass(self, db_manager):
        article_id = _make_article(db_manager)
        self._event(db_manager, article_id, "check_passed")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "pass"
        assert envelope.validation.counts == {"check_passed": 1, "rejected": 0}

    def test_rejected_event_without_details_is_not_attributed(self, db_manager):
        """Plan 149 item 3: a `rejected` row with no distinguishing details
        cannot be attributed to a Content Guard verdict."""
        article_id = _make_article(db_manager)
        self._event(db_manager, article_id, "rejected")

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "warning"
        assert "1 intento(s) rechazado(s) (0 por Content Guard)" in (
            envelope.validation.detail
        )

    def test_other_event_types_do_not_count_as_validation_evidence(self, db_manager):
        article_id = _make_article(db_manager)
        attempt = _attempt(
            db_manager,
            article_id,
            state="COMPLETED",
            started_at=NOW - timedelta(minutes=10),
        )
        db_manager.lifecycle.record_publication_event(
            attempt.id, event_type="deployed", occurred_at=NOW
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "unknown"
        assert envelope.validation.evidence == "none"


def _content_guard_validation_event(
    status: str = "fail",
) -> ValidationResultEvent:
    """The exact frontend `validation_result` payload (`apply_validation_result`
    is the real Content Guard callback emitter, plan 149 item 3 Step 6)."""
    return ValidationResultEvent.model_validate(
        {
            "event": "validation_result",
            "commit_sha": "abc123def",
            "branch": "publish/dashboard-cg",
            "status": status,
            "diagnostics": [],
            "frontend_ref": "abc123def",
            "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
            "publication_ids": [CG_REFINERY_ID],
            "publication_attempt_refs": [
                {
                    "refinery_id": CG_REFINERY_ID,
                    "pull_request_number": CG_PR_NUMBER,
                    "content_sha256": CG_SHA256,
                }
            ],
        }
    )


def _pr_created_attempt(db_manager: DatabaseManager) -> tuple[int, int]:
    article_id = _make_article(db_manager, seed="cg")
    db_manager.mark_article_publishing(
        article_id,
        "content/update-dashboard-cg",
        publication_attempt_id=CG_ATTEMPT_ID,
    )
    db_manager.mark_article_published(
        article_id,
        f"https://github.com/cortega26/noticiencias/pull/{CG_PR_NUMBER}",
        CG_REFINERY_ID,
        publication_attempt_id=CG_ATTEMPT_ID,
        content_sha256=CG_SHA256,
    )
    [attempt] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert attempt.state == "PR_CREATED"
    return article_id, attempt.id


class TestValidationAttribution:
    """Plan 149 item 3: only the Content Guard callback subset of `rejected`
    rows may be attributed to Content Guard in the sentence. Each test drives
    the real emitter for its row shape."""

    def test_content_guard_callback_rejection_is_attributed(self, db_manager):
        _article_id, attempt_id = _pr_created_attempt(db_manager)

        result = apply_validation_result(
            _content_guard_validation_event("fail"), db_manager
        )

        assert result["updated"] == 1
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt_id)
        [rejected] = [e for e in events if e.event_type == "rejected"]
        assert rejected.details["event"] == "validation_result"

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "warning"
        assert envelope.validation.counts["rejected"] == 1
        assert "1 intento(s) rechazado(s) por Content Guard" in (
            envelope.validation.detail
        )
        assert "0 por Content Guard" not in envelope.validation.detail

    def test_release_path_rejection_is_not_attributed(self, db_manager):
        """`database.release_article_publishing` (pre-PR publish failure)
        writes `{"reason", "failure_class"}`, never the callback payload."""
        article_id = _make_article(db_manager, seed="release")
        db_manager.mark_article_publishing(
            article_id,
            "content/update-dashboard-release",
            publication_attempt_id=RELEASE_ATTEMPT_ID,
        )

        released = db_manager.release_article_publishing(
            article_id,
            reason="frontend render failed",
            failure_class="frontend_render",
            publication_attempt_id=RELEASE_ATTEMPT_ID,
        )

        assert released is True
        envelope = build_dashboard_health(db_manager, now=NOW)
        assert envelope.validation.status == "warning"
        assert envelope.validation.counts["rejected"] == 1
        assert "1 intento(s) rechazado(s) (0 por Content Guard)" in (
            envelope.validation.detail
        )

    def test_legacy_projection_repair_is_not_attributed(self, db_manager):
        """`publication_reconciliation._reject_from_legacy_evidence` writes
        `{"reason", "source": "legacy_projection"}` — driven here through the
        real reconciler."""
        article_id, attempt_id = _pr_created_attempt(db_manager)
        with db_manager.get_session() as session:
            article = session.get(Article, article_id)
            metadata = dict(article.article_metadata or {})
            publication = dict(metadata.get("publication") or {})
            # Deliberately a Content-Guard-sounding legacy reason: the read
            # model must not treat unproven prose as a Content Guard verdict.
            publication.update({"state": "REJECTED", "reason": "Content Guard failed"})
            metadata["publication"] = publication
            article.article_metadata = metadata
            article.processing_status = "rejected"
            session.add(article)

        summary = PublicationReconciliationWorkflow(db_manager).run(
            stale_minutes=60,
            now=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        assert summary.rejected == 1
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt_id)
        assert events[-1].event_type == "rejected"
        assert events[-1].details["source"] == "legacy_projection"

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "warning"
        assert envelope.validation.counts["rejected"] == 1
        assert "1 intento(s) rechazado(s) (0 por Content Guard)" in (
            envelope.validation.detail
        )

    def test_mixed_rejections_report_the_content_guard_breakdown(self, db_manager):
        _article_id, _attempt_id = _pr_created_attempt(db_manager)
        apply_validation_result(_content_guard_validation_event("fail"), db_manager)

        release_article_id = _make_article(db_manager, seed="release-mixed")
        db_manager.mark_article_publishing(
            release_article_id,
            "content/update-dashboard-mixed",
            publication_attempt_id="dashboard-mixed-release-attempt",
        )
        db_manager.release_article_publishing(
            release_article_id,
            reason="clone failed",
            failure_class="git_clone",
            publication_attempt_id="dashboard-mixed-release-attempt",
        )

        envelope = build_dashboard_health(db_manager, now=NOW)

        assert envelope.validation.status == "warning"
        assert envelope.validation.counts["rejected"] == 2
        assert "2 intento(s) rechazado(s) (1 por Content Guard)" in (
            envelope.validation.detail
        )
