"""Unit tests for attempt-correlated publication callback effects.

These tests use temporary SQLite and never touch the configured publication
database.
"""

from __future__ import annotations

import hashlib

import pytest

from news_collector.contracts.webhook import PublishCompleteEvent, ValidationResultEvent
from news_collector.logic.workflows.publication_callbacks import (
    apply_publish_complete,
    apply_validation_result,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

ARTICLE_URL = "https://example.com/callbacks"
REFINERY_ID = "refinery-callback-1"
PUBLICATION_ATTEMPT_ID = "callback-test-attempt"
PULL_REQUEST_NUMBER = 208
CONTENT_SHA256 = hashlib.sha256(b"callback fixture post").hexdigest()


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
    db_manager.mark_article_publishing(
        article_id,
        "content/update-cb",
        publication_attempt_id=PUBLICATION_ATTEMPT_ID,
    )
    db_manager.mark_article_published(
        article_id,
        f"https://github.com/cortega26/noticiencias/pull/{PULL_REQUEST_NUMBER}",
        REFINERY_ID,
        publication_attempt_id=PUBLICATION_ATTEMPT_ID,
        content_sha256=CONTENT_SHA256,
    )
    [attempt] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    return article_id, attempt


def _attempt_refs(ids: list[str]) -> list[dict[str, object]]:
    return [
        {
            "refinery_id": refinery_id,
            "pull_request_number": PULL_REQUEST_NUMBER,
            "content_sha256": CONTENT_SHA256,
        }
        for refinery_id in dict.fromkeys(ids)
    ]


def _validation_event(status: str, ids: list[str] | None = None):
    publication_ids = ids if ids is not None else [REFINERY_ID]
    return ValidationResultEvent.model_validate(
        {
            "event": "validation_result",
            "commit_sha": "abc123def",
            "branch": "publish/callback-test",
            "status": status,
            "diagnostics": [],
            "frontend_ref": "abc123def",
            "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
            "publication_ids": publication_ids,
            "publication_attempt_refs": _attempt_refs(publication_ids),
        }
    )


def _publish_event(ids: list[str] | None = None):
    publication_ids = ids if ids is not None else [REFINERY_ID]
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
            "publication_ids": publication_ids,
            "publication_attempt_refs": _attempt_refs(publication_ids),
        }
    )


class TestValidationPass:
    def test_records_check_passed_event_for_matching_attempt(
        self, db_manager: DatabaseManager
    ):
        _, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(_validation_event("pass"), db_manager)

        assert result["action"] == "noop"
        assert result["recorded"] == 1
        assert result["needs_attention"] is False
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "check_passed"]
        assert events[1].details["commit_sha"] == "abc123def"
        assert events[1].details["refinery_id"] == REFINERY_ID
        assert events[1].details["content_sha256"] == CONTENT_SHA256
        assert events[1].details["pull_request_number"] == PULL_REQUEST_NUMBER

    def test_duplicate_ids_record_one_event_per_attempt(
        self, db_manager: DatabaseManager
    ):
        _, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(
            _validation_event("pass", ids=[REFINERY_ID, REFINERY_ID, REFINERY_ID]),
            db_manager,
        )

        assert result["recorded"] == 1
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "check_passed"]

    def test_unknown_attempt_is_observable_without_transition(
        self, db_manager: DatabaseManager
    ):
        result = apply_validation_result(
            _validation_event("pass", ids=["refinery-unknown"]), db_manager
        )

        assert result["action"] == "unmatched"
        assert result["needs_attention"] is True
        assert result["unmatched"] == 1

    def test_terminal_attempt_records_no_second_transition(
        self, db_manager: DatabaseManager
    ):
        article_id, attempt = _pr_created_attempt(db_manager)
        db_manager.reject_publication_attempts([REFINERY_ID], reason="earlier fail")

        result = apply_validation_result(_validation_event("pass"), db_manager)

        assert result["needs_attention"] is True
        assert result["conflicts"] == 1
        assert (
            db_manager.lifecycle.get_publication_attempts_for_article(article_id)[
                0
            ].state
            == "REJECTED"
        )
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "rejected"]

    def test_lifecycle_failure_is_not_swallowed(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        _pr_created_attempt(db_manager)

        def _boom(*args, **kwargs):
            raise RuntimeError("event write exploded")

        monkeypatch.setattr(
            db_manager.lifecycle, "record_correlated_check_passed", _boom
        )

        with pytest.raises(RuntimeError, match="event write exploded"):
            apply_validation_result(_validation_event("pass"), db_manager)

    def test_manager_without_lifecycle_is_attention_not_success(self):
        class _FakeDb:
            pass

        result = apply_validation_result(_validation_event("pass"), _FakeDb())

        assert result["needs_attention"] is True
        assert result["reason"] == "correlated_callback_storage_unavailable"


class TestValidationFail:
    def test_records_rejected_event_with_correlated_evidence(
        self, db_manager: DatabaseManager
    ):
        article_id, attempt = _pr_created_attempt(db_manager)

        result = apply_validation_result(_validation_event("fail"), db_manager)

        assert result["action"] == "rejected"
        assert result["updated"] == 1
        assert result["article_updated"] == 1
        assert result["needs_attention"] is False
        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "rejected"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "rejected"]
        assert events[1].details["event"] == "validation_result"
        assert events[1].details["commit_sha"] == "abc123def"
        assert events[1].details["content_sha256"] == CONTENT_SHA256


class TestPublishComplete:
    def test_records_deployed_event_with_url(self, db_manager: DatabaseManager):
        article_id, attempt = _pr_created_attempt(db_manager)

        result = apply_publish_complete(_publish_event(), db_manager)

        assert result["action"] == "completed"
        assert result["updated"] == 1
        assert result["article_updated"] == 1
        assert result["deploy_url"] == "https://noticiencias.com"
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert [e.event_type for e in events] == ["pr_created", "deployed"]
        assert events[1].details["deploy_url"] == "https://noticiencias.com"
        assert events[1].details["content_sha256"] == CONTENT_SHA256
        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "completed"
            assert article.published_at is not None
            assert article.published_url == "https://noticiencias.com"

    def test_missing_deploy_url_still_completes_without_url(
        self, db_manager: DatabaseManager
    ):
        article_id, attempt = _pr_created_attempt(db_manager)
        event = _publish_event()
        event.diagnostics = []

        result = apply_publish_complete(event, db_manager)

        assert result["updated"] == 1
        assert result["deploy_url"] is None
        events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
        assert events[-1].event_type == "deployed"
        assert events[-1].details["deploy_url"] is None
        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "completed"
            assert article.published_url is None


def test_serving_delegates_preserve_attempt_correlated_effect(
    db_manager: DatabaseManager,
):
    from news_collector.serving.webhook_handler import process_validation_result

    _, attempt = _pr_created_attempt(db_manager)

    result = process_validation_result(_validation_event("fail"), db_manager)

    assert result["action"] == "rejected"
    assert result["updated"] == 1
    events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
    assert events[-1].event_type == "rejected"
