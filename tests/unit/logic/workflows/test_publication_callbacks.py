"""Unit tests for the workflow-owned publication callback effects
(Plan 060 / Phase 5b).

Real SQLite through ``DatabaseManager``; no serving import except the
delegate-compatibility assertion.
"""

from __future__ import annotations

import pytest

from news_collector.contracts.webhook import (
    PublishCompleteEvent,
    ValidationResultEvent,
)
from news_collector.logic.workflows.publication_callbacks import (
    apply_publish_complete,
    apply_validation_result,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

ARTICLE_URL = "https://example.com/callbacks"
REFINERY_ID = "refinery-callback-1"


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "callbacks.db"})
    with manager.get_session() as session:
        session.add(
            Article(
                title="Callback test",
                url=ARTICLE_URL,
                summary="A test article",
                source_id="test-source",
                source_name="Test Source",
                category="science",
                processing_status="pending",
            )
        )
    yield manager
    manager.close()


def _article_id(db_manager: DatabaseManager) -> int:
    with db_manager.get_session() as session:
        article = session.query(Article).filter_by(url=ARTICLE_URL).first()
        assert article is not None
        return int(article.id)


def _pr_created_attempt(db_manager: DatabaseManager):
    article_id = _article_id(db_manager)
    db_manager.mark_article_publishing(article_id, "content/update-cb")
    db_manager.mark_article_published(
        article_id, "https://github.com/pr/cb", REFINERY_ID
    )
    [attempt] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    return article_id, attempt


def _validation_event(status: str, ids: list[str] | None = None):
    return ValidationResultEvent.model_validate(
        {
            "event": "validation_result",
            "commit_sha": "abc123def",
            "branch": "publish/callback-test",
            "status": status,
            "diagnostics": [],
            "frontend_ref": "abc123def",
            "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
            "publication_ids": ids if ids is not None else [REFINERY_ID],
        }
    )


def _publish_event(ids: list[str] | None = None):
    return PublishCompleteEvent.model_validate(
        {
            "event": "publish_complete",
            "commit_sha": "abc123def",
            "branch": "publish/callback-test",
            "status": "success",
            "diagnostics": [
                {
                    "check": "deploy",
                    "status": "pass",
                    "deploy_url": "https://noticiencias.com",
                }
            ],
            "frontend_ref": "abc123def",
            "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
            "publication_ids": ids if ids is not None else [REFINERY_ID],
        }
    )


class TestValidationPass:
    def test_records_check_passed_event_for_matching_attempt(
        self, db_manager: DatabaseManager
    ):
        _, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(_validation_event("pass"), db_manager)

        assert result == {"action": "noop", "reason": "validation_passed"}
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "check_passed"]
        assert events[1].details == {
            "commit_sha": "abc123def",
            "branch": "publish/callback-test",
            "refinery_id": REFINERY_ID,
        }

    def test_duplicate_ids_record_one_event_per_attempt(
        self, db_manager: DatabaseManager
    ):
        _, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(
            _validation_event("pass", ids=[REFINERY_ID, REFINERY_ID, REFINERY_ID]),
            db_manager,
        )

        assert result == {"action": "noop", "reason": "validation_passed"}
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "check_passed"]

    def test_unknown_attempt_records_nothing(self, db_manager: DatabaseManager):
        result = apply_validation_result(
            _validation_event("pass", ids=["refinery-unknown"]), db_manager
        )

        assert result == {"action": "noop", "reason": "validation_passed"}

    def test_terminal_attempt_records_nothing(self, db_manager: DatabaseManager):
        article_id, attempt = _pr_created_attempt(db_manager)
        db_manager.reject_publication_attempts([REFINERY_ID], reason="earlier fail")

        apply_validation_result(_validation_event("pass"), db_manager)

        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "rejected"]

    def test_lifecycle_failure_is_swallowed(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        _pr_created_attempt(db_manager)

        def _boom(*args, **kwargs):
            raise RuntimeError("event write exploded")

        monkeypatch.setattr(
            db_manager.lifecycle,
            "find_latest_publication_attempt_by_refinery_id",
            _boom,
        )

        result = apply_validation_result(_validation_event("pass"), db_manager)

        assert result == {"action": "noop", "reason": "validation_passed"}

    def test_manager_without_lifecycle_is_a_noop(self):
        class _FakeDb:
            pass

        result = apply_validation_result(_validation_event("pass"), _FakeDb())

        assert result == {"action": "noop", "reason": "validation_passed"}


class TestValidationFail:
    def test_records_rejected_event_with_reason(self, db_manager: DatabaseManager):
        article_id, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(_validation_event("fail"), db_manager)

        assert result == {"action": "rejected", "updated": 1}
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "rejected"]
        assert events[1].details == {
            "reason": "Content Guard failed (commit: abc123def)"
        }


class TestPublishComplete:
    def test_records_deployed_event_with_url(self, db_manager: DatabaseManager):
        article_id, attempt = _pr_created_attempt(db_manager)

        result = apply_publish_complete(_publish_event(), db_manager)

        assert result == {
            "action": "completed",
            "updated": 1,
            "deploy_url": "https://noticiencias.com",
        }
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "deployed"]
        assert events[1].details == {"deploy_url": "https://noticiencias.com"}

    def test_missing_deploy_url_still_completes_without_url(
        self, db_manager: DatabaseManager
    ):
        article_id, attempt = _pr_created_attempt(db_manager)
        event = _publish_event()
        event.diagnostics = []

        result = apply_publish_complete(event, db_manager)

        assert result == {"action": "completed", "updated": 1, "deploy_url": None}
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert events[-1].event_type == "deployed"
        assert events[-1].details == {"deploy_url": None}


def test_serving_delegates_preserve_the_effect(db_manager: DatabaseManager):
    """The serving seam must call the exact same effect (plan 5b moved the
    body; the patch/direct-call seam stays)."""
    from news_collector.serving.webhook_handler import process_validation_result

    _, attempt = _pr_created_attempt(db_manager)

    result = process_validation_result(_validation_event("fail"), db_manager)

    assert result == {"action": "rejected", "updated": 1}
    events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
    assert events[-1].event_type == "rejected"
