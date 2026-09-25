"""Plan 060 / Phase 5a: durable webhook receipt integration tests.

Exercises the real handler against a real SQLite DatabaseManager: a processed
delivery is not reapplied, a processing exception leaves a failed receipt that
a retry can recover, a crash state (`received`) is reprocessed, and a manager
without the receipts repository keeps working.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.contracts.webhook import (
    compute_delivery_key,
    parse_webhook_payload,
)
from news_collector.serving.webhook_handler import handle_webhook_event
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

ARTICLE_URL = "https://example.com/receipts"
REFINERY_ID = "refinery-receipt-1"


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "receipts.db"})
    with manager.get_session() as session:
        session.add(
            Article(
                title="Receipt test",
                url=ARTICLE_URL,
                summary="A test article",
                source_id="test-source",
                source_name="Test Source",
                category="science",
                processing_status="publishing",
                article_metadata={
                    "publication": {
                        "state": "PR_CREATED",
                        "refinery_id": REFINERY_ID,
                    },
                },
            )
        )
    yield manager
    manager.close()


def _publish_payload() -> dict:
    return {
        "event": "publish_complete",
        "commit_sha": "abc123def",
        "branch": "publish/test",
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
        "publication_ids": [REFINERY_ID],
    }


def _validation_fail_payload() -> dict:
    return {
        "event": "validation_result",
        "commit_sha": "abc123def",
        "branch": "publish/test",
        "status": "fail",
        "diagnostics": [
            {"check": "frontmatter-dates", "status": "fail", "errors": ["bad"]}
        ],
        "frontend_ref": "abc123def",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
        "publication_ids": [REFINERY_ID],
    }


def _article_status(db_manager: DatabaseManager) -> str:
    with db_manager.get_session() as session:
        article = session.query(Article).filter_by(url=ARTICLE_URL).first()
        assert article is not None
        return article.processing_status


def _set_article_status(db_manager: DatabaseManager, status: str) -> None:
    with db_manager.get_session() as session:
        article = session.query(Article).filter_by(url=ARTICLE_URL).first()
        assert article is not None
        article.processing_status = status


class TestIdempotentDelivery:
    def test_first_delivery_processes_and_records_receipt(
        self, db_manager: DatabaseManager
    ):
        event = parse_webhook_payload(_publish_payload())

        result = handle_webhook_event(event, db_manager)

        assert result["result"] == {
            "action": "completed",
            "updated": 1,
            "deploy_url": "https://noticiencias.com",
        }
        assert _article_status(db_manager) == "completed"
        receipt = db_manager.webhook_receipts.get_receipt(compute_delivery_key(event))
        assert receipt is not None
        assert receipt.status == "processed"
        assert receipt.attempts == 1

    def test_duplicate_returns_stored_result_without_reapplying(
        self, db_manager: DatabaseManager
    ):
        event = parse_webhook_payload(_publish_payload())
        first = handle_webhook_event(event, db_manager)

        # Reset the article so a reapplied transition would be observable.
        _set_article_status(db_manager, "publishing")

        second = handle_webhook_event(event, db_manager)

        assert second["duplicate"] is True
        assert second["result"] == first["result"]
        assert _article_status(db_manager) == "publishing"
        receipt = db_manager.webhook_receipts.get_receipt(compute_delivery_key(event))
        assert receipt is not None
        assert receipt.attempts == 1


class TestFailureRetention:
    def test_processing_exception_leaves_failed_receipt_then_retry_succeeds(
        self, db_manager: DatabaseManager
    ):
        event = parse_webhook_payload(_validation_fail_payload())
        key = compute_delivery_key(event)

        with patch(
            "news_collector.serving.webhook_handler.process_validation_result",
            side_effect=RuntimeError("boom"),
        ):
            result = handle_webhook_event(event, db_manager)

        assert result["processed"] is False
        failed = db_manager.webhook_receipts.get_receipt(key)
        assert failed is not None
        assert failed.status == "failed"
        assert "RuntimeError: boom" in (failed.error or "")
        assert failed.attempts == 1
        assert _article_status(db_manager) == "publishing"

        retry = handle_webhook_event(event, db_manager)

        assert retry["result"] == {"action": "rejected", "updated": 1}
        assert _article_status(db_manager) == "rejected"
        recovered = db_manager.webhook_receipts.get_receipt(key)
        assert recovered is not None
        assert recovered.status == "processed"
        assert recovered.attempts == 2


class TestCrashRecovery:
    def test_received_crash_state_is_reprocessed(self, db_manager: DatabaseManager):
        event = parse_webhook_payload(_publish_payload())
        key = compute_delivery_key(event)
        # Simulate a crash after the receipt was persisted, before processing.
        db_manager.webhook_receipts.record_receipt(
            delivery_key=key,
            event_type=event.event,
            payload=event.model_dump(mode="json", by_alias=True),
        )

        result = handle_webhook_event(event, db_manager)

        assert result["result"]["action"] == "completed"
        assert _article_status(db_manager) == "completed"
        receipt = db_manager.webhook_receipts.get_receipt(key)
        assert receipt is not None
        assert receipt.status == "processed"


class TestLegacyFallback:
    def test_manager_without_receipts_repo_still_processes(self):
        db = SimpleNamespace(reject_publication_attempts=MagicMock(return_value=2))
        event = parse_webhook_payload(_validation_fail_payload())

        result = handle_webhook_event(event, db)

        assert result["result"] == {"action": "rejected", "updated": 2}
        db.reject_publication_attempts.assert_called_once()
