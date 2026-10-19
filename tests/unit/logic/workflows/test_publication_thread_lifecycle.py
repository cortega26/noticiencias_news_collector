"""Plan 153 / issue #367: dispatched publication threads are joinable.

`start()` / `start_batch()` dispatch a daemon thread and return immediately
(production semantics), but nothing kept a reference to it, so a test (or a
process shutdown) could close the `DatabaseManager` while the batch was still
finishing. The batch then reached `complete()` / `fail()` against a closed
handle and `fail()` re-entered `_merge_summary()`, raising an unhandled
`RuntimeError` on `publish-batch-*` instead of recording the original failure.

These regressions are Event-controlled: no sleeps, no polling, no
"warning not in output" assertions — the unhandled exception is captured
precisely through `threading.excepthook`.
"""

from __future__ import annotations

import threading

import pytest
from loguru import logger as loguru_logger

from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
    join_dispatched_publication_threads,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(
        {"type": "sqlite", "path": tmp_path / "thread_lifecycle.db"}
    )
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


@pytest.fixture
def workflow(db_manager, tmp_path):
    return PublicationRunWorkflow(
        db_manager,
        lease_timeout_seconds=60,
        publication_attempts_dir=tmp_path / "attempts",
    )


def test_batch_thread_meeting_a_closed_db_raises_nothing_unhandled(
    workflow, db_manager, monkeypatch
) -> None:
    """The exact issue #367 shape: the DB closes mid-batch.

    The batch body is gated on an Event and only then raises, so the manager
    is provably closed before `_run_batch` reaches `fail()`. The failure must
    be contained (logged), not escape as an unhandled thread exception.
    """
    body_started = threading.Event()
    release = threading.Event()
    workers: list[threading.Thread] = []

    def gated_batch(*_args, **_kwargs):
        workers.append(threading.current_thread())
        body_started.set()
        release.wait()
        raise RuntimeError("pipeline exploded after the DB closed")

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_batch",
        gated_batch,
    )

    escaped: list[threading.ExceptHookArgs] = []
    original_excepthook = threading.excepthook
    threading.excepthook = escaped.append
    try:
        assert workflow.start_batch([41]).status == "started"
        assert body_started.wait(timeout=10)
        db_manager.close()
        release.set()
        workers[0].join(timeout=10)
    finally:
        # Never leave a gated worker behind: teardown joins the registry.
        release.set()
        threading.excepthook = original_excepthook

    assert not workers[0].is_alive()
    assert escaped == []


def test_start_batch_returns_before_the_body_finishes(workflow, monkeypatch) -> None:
    """Production semantics: the API path never blocks on the batch."""
    body_started = threading.Event()
    release = threading.Event()
    body_finished = threading.Event()
    workers: list[threading.Thread] = []

    def gated_batch(*_args, **_kwargs):
        workers.append(threading.current_thread())
        body_started.set()
        # Bounded: if dispatch ever became synchronous this wait expires and
        # the assertion below fails instead of hanging the suite.
        release.wait(timeout=10)
        body_finished.set()
        return {
            "status": "success",
            "processed_count": 1,
            "succeeded_count": 1,
            "failed_count": 0,
            "total_count": 1,
            "items": [{"article_id": 7, "status": "succeeded", "processed_count": 1}],
        }

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_batch",
        gated_batch,
    )

    result = workflow.start_batch([7])
    try:
        assert result.status == "started"
        assert body_started.wait(timeout=10)
        assert not body_finished.is_set()
    finally:
        release.set()
        if workers:
            workers[0].join(timeout=10)

    assert body_finished.is_set()
    assert workflow.get_status(result.run_id).run_status == "succeeded"


def test_join_helper_drains_a_dispatched_batch(workflow, monkeypatch) -> None:
    """The module helper waits for a registered batch and it can still finish."""
    body_started = threading.Event()
    release = threading.Event()
    workers: list[threading.Thread] = []

    def gated_batch(*_args, **_kwargs):
        workers.append(threading.current_thread())
        body_started.set()
        release.wait()
        return {
            "status": "success",
            "processed_count": 1,
            "succeeded_count": 1,
            "failed_count": 0,
            "total_count": 1,
            "items": [{"article_id": 9, "status": "succeeded", "processed_count": 1}],
        }

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_batch",
        gated_batch,
    )

    result = workflow.start_batch([9])
    try:
        assert body_started.wait(timeout=10)
    finally:
        release.set()
    join_dispatched_publication_threads()

    assert not workers[0].is_alive()
    assert workflow.get_status(result.run_id).run_status == "succeeded"


def test_fail_logs_the_error_and_does_not_retry_a_dead_db(
    workflow, monkeypatch
) -> None:
    """Issue #367 second bullet: a failed persistence must not be retried.

    The closed manager raises on the first `get_session()`; `fail()` must log
    the original detail plus the persistence error and return instead of
    re-entering `_merge_summary()` against the same dead handle.
    """
    session_calls = 0

    def closed_session():
        nonlocal session_calls
        session_calls += 1
        raise RuntimeError(
            "DatabaseManager is closed — get_session() called after close()."
        )

    monkeypatch.setattr(workflow._db, "get_session", closed_session)
    records: list[str] = []
    sink_id = loguru_logger.add(
        lambda message: records.append(str(message)), level="ERROR"
    )
    try:
        persisted = workflow.fail(
            7,
            error_code="batch_failed",
            error_detail="original boom",
            summary={"mode": "batch", "items": []},
        )
    finally:
        loguru_logger.remove(sink_id)

    assert persisted is False
    assert session_calls == 1
    assert any("run 7" in record and "original boom" in record for record in records)
