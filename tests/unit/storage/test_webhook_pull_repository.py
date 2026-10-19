"""Durable staging, cursor, ordering, and lease behavior for hosted inbox pulls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import WEBHOOK_PULL_STATUS_VALUES, WebhookPullReceipt
from news_collector.storage.webhook_pull_repository import (
    MAX_DELIVERY_ATTEMPTS,
    CursorConflict,
    is_exhausted,
)


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


def _fail_receipt(repo, *, target_attempts: int) -> int:
    """Drive the oldest staged receipt to ``failed`` at ``target_attempts``."""
    claimed = repo.claim_pending(
        ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=False
    )
    assert claimed, "expected a fresh receipt to claim"
    view = claimed[0]
    while view.attempts < target_attempts:
        assert repo.mark_failed(view.id, view.lease_token or "", "injected failure")
        claimed = repo.claim_pending(
            ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True
        )
        assert claimed, "expected a below-cap failure to be retryable"
        view = claimed[0]
    assert repo.mark_failed(view.id, view.lease_token or "", "injected failure")
    return view.id


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


def test_exhausted_receipt_leaves_the_queue_without_hiding_later_rows(
    db_manager: DatabaseManager,
):
    repo = db_manager.webhook_pull_receipts
    repo.stage_page(ENDPOINT_KEY, expected_after_id=None, rows=[_row(1)])
    _fail_receipt(repo, target_attempts=MAX_DELIVERY_ATTEMPTS)

    exhausted = repo.get_receipt(ENDPOINT_KEY, 1)
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.attempts == MAX_DELIVERY_ATTEMPTS
    assert is_exhausted(exhausted)

    # Neither pass may lease it again (retry_only=True used to, forever).
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True)
        == []
    )
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=False)
        == []
    )

    # It must not hide a fresh receipt staged behind it either.
    assert repo.stage_page(ENDPOINT_KEY, expected_after_id=1, rows=[_row(2)]) == 1
    claimed = repo.claim_pending(
        ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=False
    )
    assert [view.remote_id for view in claimed] == [2]

    assert repo.mark_processed(claimed[0].id, claimed[0].lease_token or "")
    # Terminal rows are not pending work.
    assert repo.count_pending(ENDPOINT_KEY) == 0
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True)
        == []
    )


def test_failed_receipt_below_the_cap_is_claimed_then_exhausts(
    db_manager: DatabaseManager,
):
    repo = db_manager.webhook_pull_receipts
    repo.stage_page(ENDPOINT_KEY, expected_after_id=None, rows=[_row(1)])
    _fail_receipt(repo, target_attempts=MAX_DELIVERY_ATTEMPTS - 1)

    below_cap = repo.get_receipt(ENDPOINT_KEY, 1)
    assert below_cap is not None
    assert below_cap.status == "failed"
    assert below_cap.attempts == MAX_DELIVERY_ATTEMPTS - 1
    assert not is_exhausted(below_cap)

    # One more attempt is still allowed; crossing the cap is what ends it.
    claimed = repo.claim_pending(
        ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True
    )
    assert [view.remote_id for view in claimed] == [1]
    assert claimed[0].attempts == MAX_DELIVERY_ATTEMPTS

    assert repo.mark_failed(
        claimed[0].id, claimed[0].lease_token or "", "injected failure"
    )
    at_cap = repo.get_receipt(ENDPOINT_KEY, 1)
    assert at_cap is not None
    assert is_exhausted(at_cap)
    assert (
        repo.claim_pending(ENDPOINT_KEY, limit=1, lease_seconds=60, retry_only=True)
        == []
    )


def test_webhook_pull_status_set_is_unchanged():
    # Exhaustion must stay derived: widening the CHECK-constrained status set
    # would be a schema change (models.py plus an Alembic rebuild on SQLite).
    assert WEBHOOK_PULL_STATUS_VALUES == (
        "received",
        "processing",
        "processed",
        "failed",
    )
