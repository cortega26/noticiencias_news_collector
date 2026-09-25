"""Unit tests for the dashboard health evidence builder (Plan 060 /
Phase 5c).

Real SQLite through ``DatabaseManager`` with a frozen ``now`` so age-based
status rules are deterministic. The central contract under test: no record
means ``evidence="none"`` and ``status="unknown"`` — never ``pass``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.serving.dashboard_health import build_dashboard_health
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


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
