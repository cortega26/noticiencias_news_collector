"""
tests/decompose_refinery/test_audit_scheduler.py

Verifies AuditScheduler (plan 060 Phase 7a).

Import path after implementation:
    from news_collector.logic.workflows.audit_scheduler import AuditScheduler
"""

from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest

from news_collector.logic.workflows.audit_scheduler import AuditScheduler


@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.update_article_audit_status.return_value = True
    return db


@pytest.fixture
def scheduler(mock_db: MagicMock) -> AuditScheduler:
    return AuditScheduler(mock_db)


def _schedule(scheduler: AuditScheduler, *, executor, status_recorder):
    return scheduler.schedule(
        auditor=MagicMock(),
        executor=executor,
        status_recorder=status_recorder,
        article_id="42",
        article_numeric_id=42,
        content="c",
        source_url="http://x",
        article_data={},
    )


# ---------------------------------------------------------------------------
# record_status
# ---------------------------------------------------------------------------


class TestRecordStatus:
    def test_writes_full_status(self, scheduler: AuditScheduler, mock_db: MagicMock):
        scheduler.record_status(
            42,
            "audit_passed",
            "ok",
            attempts=3,
            timeout_seconds=15,
            model="m",
            endpoint="e",
        )
        mock_db.update_article_audit_status.assert_called_once_with(
            42,
            "audit_passed",
            "ok",
            attempts=3,
            timeout_seconds=15,
            model="m",
            endpoint="e",
        )

    def test_noop_for_missing_numeric_id(
        self, scheduler: AuditScheduler, mock_db: MagicMock
    ):
        scheduler.record_status(None, "audit_pending", "r", attempts=0)
        mock_db.update_article_audit_status.assert_not_called()

    def test_noop_when_db_lacks_method(self, mock_db: MagicMock):
        mock_db.update_article_audit_status = None
        scheduler = AuditScheduler(mock_db)
        scheduler.record_status(1, "audit_pending", "r", attempts=0)

    def test_swallows_db_error(self, mock_db: MagicMock):
        mock_db.update_article_audit_status.side_effect = RuntimeError("boom")
        scheduler = AuditScheduler(mock_db)
        scheduler.record_status(1, "audit_pending", "r", attempts=0)


# ---------------------------------------------------------------------------
# schedule — backpressure and submission
# ---------------------------------------------------------------------------


class TestScheduleSubmission:
    def test_backpressure_skips_submission(self, scheduler: AuditScheduler):
        pending = MagicMock()
        pending.done.return_value = False
        scheduler.last_future = pending
        executor = MagicMock()
        recorder = MagicMock()

        _schedule(scheduler, executor=executor, status_recorder=recorder)

        executor.submit.assert_not_called()
        recorder.assert_called_once()
        assert recorder.call_args.kwargs["status"] == "audit_skipped_backpressure"

    def test_submission_failure_records_audit_failed(self, scheduler: AuditScheduler):
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("pool gone")
        recorder = MagicMock()

        _schedule(scheduler, executor=executor, status_recorder=recorder)

        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["status"] == "audit_failed"
        assert "submission_failed" in kwargs["reason"]

    def test_successful_submission_stores_last_future(self, scheduler: AuditScheduler):
        future: Future = Future()
        executor = MagicMock()
        executor.submit.return_value = future

        _schedule(scheduler, executor=executor, status_recorder=MagicMock())

        assert scheduler.last_future is future
        executor.submit.assert_called_once()


# ---------------------------------------------------------------------------
# schedule — done callback
# ---------------------------------------------------------------------------


def _capture_callback(executor: MagicMock):
    future = MagicMock()
    executor.submit.return_value = future
    return future, lambda sched, recorder: _schedule(
        sched, executor=executor, status_recorder=recorder
    )


class TestDoneCallback:
    def test_passing_result_maps_every_field(self, scheduler: AuditScheduler):
        future, run = _capture_callback(MagicMock())
        recorder = MagicMock()
        run(scheduler, recorder)
        callback = future.add_done_callback.call_args[0][0]

        done = MagicMock()
        done.result.return_value = {
            "status": "audit_passed",
            "reason": "ok",
            "attempts": 3,
            "timeout_seconds": 15,
            "model": "m",
            "endpoint": "e",
        }
        callback(done)

        recorder.assert_called_once_with(
            article_numeric_id=42,
            status="audit_passed",
            reason="ok",
            attempts=3,
            timeout_seconds=15,
            model="m",
            endpoint="e",
        )

    def test_callback_crash_records_failure(self, scheduler: AuditScheduler):
        future, run = _capture_callback(MagicMock())
        recorder = MagicMock()
        run(scheduler, recorder)
        callback = future.add_done_callback.call_args[0][0]

        done = MagicMock()
        done.result.side_effect = RuntimeError("crashed")
        callback(done)

        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["status"] == "audit_failed"
        assert "crashed" in kwargs["reason"]
        assert kwargs["attempts"] == 0

    def test_non_dict_result_records_invalid_type(self, scheduler: AuditScheduler):
        future, run = _capture_callback(MagicMock())
        recorder = MagicMock()
        run(scheduler, recorder)
        callback = future.add_done_callback.call_args[0][0]

        done = MagicMock()
        done.result.return_value = "not-a-dict"
        callback(done)

        kwargs = recorder.call_args.kwargs
        assert kwargs["status"] == "audit_failed"
        assert "invalid_audit_result_type:str" in kwargs["reason"]

    def test_bad_numeric_types_coerce_safely(self, scheduler: AuditScheduler):
        future, run = _capture_callback(MagicMock())
        recorder = MagicMock()
        run(scheduler, recorder)
        callback = future.add_done_callback.call_args[0][0]

        done = MagicMock()
        done.result.return_value = {
            "status": "audit_failed",
            "reason": "timeout",
            "attempts": "not-int",
            "timeout_seconds": "not-int",
            "model": "",
            "endpoint": "",
        }
        callback(done)

        kwargs = recorder.call_args.kwargs
        assert kwargs["attempts"] == 0
        assert kwargs["timeout_seconds"] is None
        assert kwargs["model"] is None
        assert kwargs["endpoint"] is None

    def test_callback_none_result_records_failure(self, scheduler: AuditScheduler):
        # `result() or {}` collapses None to the empty-dict defaults.
        future, run = _capture_callback(MagicMock())
        recorder = MagicMock()
        run(scheduler, recorder)
        callback = future.add_done_callback.call_args[0][0]

        done = MagicMock()
        done.result.return_value = None
        callback(done)

        kwargs = recorder.call_args.kwargs
        assert kwargs["status"] == "audit_failed"
        assert kwargs["reason"] == "unknown"
        assert kwargs["attempts"] == 0
