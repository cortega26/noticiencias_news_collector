"""Durable staging, cursor, ordering, and lease behavior for hosted inbox pulls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import WebhookPullReceipt
from news_collector.storage.webhook_pull_repository import CursorConflict


@pytest.fixture()
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "pull-state.db"})
    yield manager
    manager.close()


ENDPOINT = "https://api.example/v1/admin/webhook/receipts"
ENDPOINT_KEY = ENDPOINT


def _row(receipt_id: int) -> dict:
    return {
        "id": receipt_id,
        "delivery_key": f"id:{receipt_id}",
        "event_type": "publish_complete",
        "status": "processed",
        "payload": {"event": "publish_complete", "delivery_id": receipt_id},
    }


def test_cursor_and_page_are_committed_atomically(db_manager: DatabaseManager):
    repo = db_manager.webhook_pull_receipts
    assert repo.stage_page(ENDPOINT_KEY, expected_after_id=None, rows=[_row(1)]) == 1

    with pytest.raises(CursorConflict):
        repo.stage_page(ENDPOINT_KEY, expected_after_id=None, rows=[_row(2)])

    assert repo.get_cursor(ENDPOINT_KEY) == 1
    assert repo.get_receipt(ENDPOINT_KEY, 2) is None


def test_oldest_unsettled_event_blocks_later_ids(db_manager: DatabaseManager):
    repo = db_manager.webhook_pull_receipts
    repo.stage_page(
        ENDPOINT_KEY,
        expected_after_id=None,
        rows=[_row(1), _row(2)],
    )

    first = repo.claim_pending(
        ENDPOINT_KEY, limit=10, lease_seconds=60, retry_only=False
    )[0]
    assert first.remote_id == 1
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=10, lease_seconds=60, retry_only=False)
        == []
    )

    assert repo.mark_failed(first.id, first.lease_token or "", "injected failure")
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=10, lease_seconds=60, retry_only=False)
        == []
    )
    retry = repo.claim_pending(
        ENDPOINT_KEY, limit=10, lease_seconds=60, retry_only=True
    )[0]
    assert retry.remote_id == 1
    assert repo.mark_processed(retry.id, retry.lease_token or "")

    second = repo.claim_pending(
        ENDPOINT_KEY, limit=10, lease_seconds=60, retry_only=False
    )[0]
    assert second.remote_id == 2


def test_expired_lease_is_reclaimed_and_stale_worker_cannot_ack(
    db_manager: DatabaseManager,
):
    repo = db_manager.webhook_pull_receipts
    repo.stage_page(ENDPOINT_KEY, expected_after_id=None, rows=[_row(1)])
    first = repo.claim_pending(
        ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=False
    )[0]

    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True)
        == []
    )
    with db_manager.get_session() as session:
        session.execute(
            update(WebhookPullReceipt)
            .where(WebhookPullReceipt.id == first.id)
            .values(
                lease_until=(
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).timestamp()
            )
        )

    recovered = repo.claim_pending(
        ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True
    )[0]
    assert recovered.remote_id == 1
    assert recovered.attempts == 2
    assert not repo.mark_processed(first.id, first.lease_token or "")
    assert repo.mark_processed(recovered.id, recovered.lease_token or "")
