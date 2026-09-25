"""Unit tests for WebhookReceiptRepository (Plan 060 / Phase 5a).

Uses a real SQLite database through DatabaseManager, matching the
`tmp_path`-fixture convention of tests/unit/storage/test_lifecycle_repository.py.
"""

from __future__ import annotations

import pytest

from news_collector.storage.database import DatabaseManager

KEY = "derived:abc"


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "receipts.db"})
    yield manager
    manager.close()


def _record(repo, key: str = KEY, event_type: str = "publish_complete"):
    return repo.record_receipt(
        delivery_key=key,
        event_type=event_type,
        payload={"event": event_type, "publication_ids": ["42"]},
    )


class TestRecordReceipt:
    def test_first_delivery_creates_received_row(self, db_manager: DatabaseManager):
        view, created = _record(db_manager.webhook_receipts)

        assert created is True
        assert view.status == "received"
        assert view.attempts == 0
        assert view.payload["publication_ids"] == ["42"]
        assert view.result is None
        assert view.error is None
        assert view.processed_at is None

    def test_replay_returns_stored_row_without_mutation(
        self, db_manager: DatabaseManager
    ):
        repo = db_manager.webhook_receipts
        first, _ = _record(repo)

        second, created = _record(repo)

        assert created is False
        assert second.id == first.id
        assert second.attempts == first.attempts

    def test_get_receipt_missing_returns_none(self, db_manager: DatabaseManager):
        assert db_manager.webhook_receipts.get_receipt("nope") is None


class TestReceiptLifecycle:
    def test_mark_processing_increments_attempts(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo)

        assert repo.mark_processing(KEY) is True
        assert repo.mark_processing(KEY) is True

        view = repo.get_receipt(KEY)
        assert view is not None
        assert view.attempts == 2
        assert view.status == "received"

    def test_mark_processed_records_result(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo)

        assert repo.mark_processed(KEY, {"action": "completed", "updated": 1}) is True

        view = repo.get_receipt(KEY)
        assert view is not None
        assert view.status == "processed"
        assert view.result == {"action": "completed", "updated": 1}
        assert view.processed_at is not None

    def test_mark_failed_keeps_error_visible(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo)

        assert repo.mark_failed(KEY, "RuntimeError: boom") is True

        view = repo.get_receipt(KEY)
        assert view is not None
        assert view.status == "failed"
        assert view.error == "RuntimeError: boom"
        assert view.processed_at is not None

    def test_mark_processed_clears_prior_error(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo)
        repo.mark_failed(KEY, "boom")

        repo.mark_processed(KEY, {"action": "rejected", "updated": 1})

        view = repo.get_receipt(KEY)
        assert view is not None
        assert view.error is None
        assert view.status == "processed"

    def test_mark_methods_return_false_for_unknown_key(
        self, db_manager: DatabaseManager
    ):
        repo = db_manager.webhook_receipts
        assert repo.mark_processing("nope") is False
        assert repo.mark_processed("nope", {}) is False
        assert repo.mark_failed("nope", "x") is False


class TestRaceFallback:
    def test_unique_index_race_falls_back_to_stored_row(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        """A concurrent insert that loses the unique-index race must return the
        stored row instead of raising."""
        repo = db_manager.webhook_receipts
        stored, _ = _record(repo)

        original_get_row = repo._get_row
        calls = {"n": 0}

        def miss_once(session, delivery_key):
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate the pre-insert SELECT not seeing the row that the
                # concurrent writer committed a moment later.
                return None
            return original_get_row(session, delivery_key)

        monkeypatch.setattr(repo, "_get_row", miss_once)

        view, created = _record(repo)

        assert created is False
        assert view.id == stored.id


class TestListUnprocessed:
    def test_returns_received_and_failed_oldest_first_excluding_processed(
        self, db_manager: DatabaseManager
    ):
        repo = db_manager.webhook_receipts
        received, _ = _record(repo, key="received-1")

        failed, _ = _record(repo, key="failed-1")
        repo.mark_processing("failed-1")
        repo.mark_failed("failed-1", "boom")

        processed, _ = _record(repo, key="processed-1")
        repo.mark_processing("processed-1")
        repo.mark_processed("processed-1", {"action": "noop"})

        unprocessed = repo.list_unprocessed_receipts()

        assert [r.id for r in unprocessed] == [received.id, failed.id]
        assert [r.status for r in unprocessed] == ["received", "failed"]
        assert processed.id not in [r.id for r in unprocessed]

    def test_limit_is_respected(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo, key="one")
        _record(repo, key="two")

        assert [r.delivery_key for r in repo.list_unprocessed_receipts(limit=1)] == [
            "one"
        ]

    def test_empty_queue_returns_empty_list(self, db_manager: DatabaseManager):
        assert db_manager.webhook_receipts.list_unprocessed_receipts() == []


class TestDashboardAggregates:
    """Plan 060 / Phase 5c dashboard evidence aggregates."""

    def test_empty_db_returns_empty_aggregates(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        assert repo.count_receipts_by_status() == {}
        assert repo.oldest_unprocessed_received_at() is None
        assert repo.latest_receipt_received_at() is None

    def test_counts_and_pending_ages(self, db_manager: DatabaseManager):
        repo = db_manager.webhook_receipts
        _record(repo, key="agg-received")

        _record(repo, key="agg-failed")
        repo.mark_processing("agg-failed")
        repo.mark_failed("agg-failed", "boom")

        _record(repo, key="agg-processed")
        repo.mark_processing("agg-processed")
        repo.mark_processed("agg-processed", {"action": "noop"})

        assert repo.count_receipts_by_status() == {
            "received": 1,
            "failed": 1,
            "processed": 1,
        }

        oldest_pending = repo.oldest_unprocessed_received_at()
        assert oldest_pending is not None
        latest = repo.latest_receipt_received_at()
        assert latest is not None
        assert oldest_pending <= latest

        loaded = repo.get_receipt("agg-received")
        assert loaded is not None
        # The oldest unprocessed receipt is the first one recorded; SQLite may
        # return it naive, so compare the values after trimming tz.
        assert oldest_pending.replace(tzinfo=None) == loaded.received_at.replace(
            tzinfo=None
        )
        assert {"received", "failed"} <= set(
            r.status for r in repo.list_unprocessed_receipts()
        )
