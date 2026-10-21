"""
Module role: Durable, single-flight lifecycle for admin-triggered
publication ("Refine & Publish") runs (Plan 060 / Phase 4c).

Owns:
- Inserting/transitioning `workflow_runs` rows for `run_type='publication'`
  (queued -> running -> succeeded/failed, or -> interrupted on lease
  recovery).
- Dispatching one Refinery run
  (`news_collector.logic.workflows.publication_pipeline.run_publication_pipeline`)
  in a background thread once a run's row is durably queued.
- Lease-based crash/restart recovery, scoped to `run_type='publication'`.

Does NOT own:
- HTTP request parsing/response mapping (`serving/api.py` stays a thin
  wrapper).
- The Refinery pipeline internals (`RefineryEngine`, `EditorAgent`,
  `GitHubPublisher`) — this module only orchestrates *when* a publish runs
  and records its outcome, exactly as `CollectionRunWorkflow` does for the
  collection cycle.

Why it wraps `run_publication_pipeline(process_id=…)` rather than calling
`RefineryEngine` directly: in `process_id` mode the pipeline skips the
collector and builds its **own** `DatabaseManager()`
(`news_collector/logic/workflows/publication_pipeline.py`), so it
never closes the process-wide singleton the serving API holds — the Phase 4a
`system.shutdown()` defect cannot recur through this path. The pipeline is the
battle-tested flow the Streamlit panel already drives through its thin
`main.main` delegate; reusing it keeps the target-repo clone /
editor / auditor / PR logic in one place.

Design mirrors `collection_run_workflow.py` (Plan 060 / Phase 4a) exactly:
constructor takes explicit `db_manager`, module logger, typed frozen-dataclass
results, state-based CAS on every transition, a `run_type='publication'`
partial unique index (`uq_workflow_runs_one_active_publication`) as the
single-flight enforcement.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from news_collector.logic.workflows._run_metadata import json_safe as _json_safe
from news_collector.logic.workflows.publication_attempts import read_publication_attempt
from news_collector.storage.models import WorkflowRun
from news_collector.storage.publication_checkpoint_repository import (
    PublicationCheckpointRepository,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


RUN_TYPE_PUBLICATION = "publication"
# A Refinery run (editor LLM + auditor LLM + image fetch + git clone/push +
# PR creation) is slower and more variable than a collection cycle; give the
# lease generous headroom. Same rationale as CollectionRunWorkflow: the
# heartbeat cadence is a short fixed interval, independent of this.
DEFAULT_LEASE_TIMEOUT_SECONDS = 3600  # 1 hour
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60


#: Every thread dispatched by :meth:`PublicationRunWorkflow.start` /
#: :meth:`PublicationRunWorkflow.start_batch`, so the owner of the shared
#: ``DatabaseManager`` (tests, process shutdown) can join them before closing
#: it. Guarded by ``_dispatched_threads_lock``; a dispatched thread removes
#: itself when it finishes, and dead entries are pruned on registration so a
#: long-lived serving process never accumulates them.
_dispatched_threads: set[threading.Thread] = set()
_dispatched_threads_lock = threading.Lock()


def join_dispatched_publication_threads(timeout: float | None = None) -> None:
    """Join every dispatched publication thread (single and batch paths).

    This is the only place that waits: ``start()`` / ``start_batch()`` still
    return immediately. Process/test teardown calls this *before* closing the
    shared ``DatabaseManager`` so a batch that is still finishing cannot reach
    ``complete()`` / ``fail()`` against a dead handle (issue #367). Follows the
    heartbeat's join style (``Thread.join(timeout=...)``).
    """
    with _dispatched_threads_lock:
        pending = [
            thread
            for thread in _dispatched_threads
            if thread is not threading.current_thread()
        ]
    for thread in pending:
        thread.join(timeout)


@dataclass(frozen=True)
class PublicationRunStartResult:
    """Result of :meth:`PublicationRunWorkflow.start`."""

    status: Literal[
        "started", "already_running", "invalid_request", "waiting_for_image", "existing"
    ]
    run_id: int
    detail: str = ""


@dataclass(frozen=True)
class PublicationRunStatusResult:
    """Result of :meth:`PublicationRunWorkflow.get_status`."""

    status: Literal["found", "not_found"]
    run_id: int | None = None
    run_status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    typical_seconds: int | None = None


#: How many recent successful single-article runs feed the duration estimate.
TYPICAL_DURATION_SAMPLE = 10


class PublicationRunWorkflow:
    """Owns the durable lifecycle of `workflow_runs` rows for
    `run_type='publication'`. Instantiate once per serving process.
    """

    def __init__(
        self,
        db_manager: Any,
        *,
        lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_SECONDS,
        heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        data_dir: str | Path = "data",
        publication_attempts_dir: (
            str | os.PathLike[str]
        ) = "data/runtime/publication_attempts",
    ) -> None:
        self._db = db_manager
        self._lease_timeout_seconds = lease_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._attempts_dir = Path(publication_attempts_dir)
        self.data_dir = Path(data_dir)
        self._checkpoints = PublicationCheckpointRepository(db_manager)
        self._reconciler_stop = threading.Event()
        self._reconciler_thread: threading.Thread | None = None
        self._dispatch_lock = threading.Lock()

    # ------------------------------------------------------------------
    # start / dispatch
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        article_id: int | None = None,
        article_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> PublicationRunStartResult:
        """Insert a queued `workflow_runs` row and dispatch one Refinery run.

        Exactly one of `article_id` / `article_url` must be given (the route
        maps a bad request to HTTP 422). The partial unique index
        `uq_workflow_runs_one_active_publication` is the single-flight
        enforcement: a second publish while one is queued/running raises
        `IntegrityError`, caught here and returned as a typed
        "already_running" result carrying the active run's id (HTTP 409).
        """
        has_id = article_id is not None
        has_url = bool(article_url)
        if has_id == has_url:
            return PublicationRunStartResult(
                status="invalid_request",
                run_id=0,
                detail="Provide exactly one of article_id or article_url.",
            )

        # Self-healing single-flight (plan 078): reap expired leases here,
        # not only at process boot. A stale `running` row (owner process
        # dead, heartbeat older than the lease) would otherwise 409-block
        # every new publish forever. Queued rows are deliberately excluded:
        # at boot a queued row is definitionally an orphan, but here one
        # may belong to a live in-flight start() — only expiry-proven
        # running rows are safe to reap.
        self.recover_expired_leases(include_queued=False)

        existing = self._checkpoints.reusable_request(
            article_id=article_id, article_url=article_url
        )
        if existing is not None:
            existing_id, complete = existing
            if complete:
                return PublicationRunStartResult(
                    status="existing",
                    run_id=existing_id,
                    detail="Reusing the recorded publication outcome.",
                )
            self._reconcile_waiting_safely()
            state = self.get_status(existing_id).run_status
            return PublicationRunStartResult(
                status=(
                    "waiting_for_image"
                    if state == "waiting_for_image"
                    else "already_running"
                ),
                run_id=existing_id,
                detail=(
                    "Edición completada · esperando imagen"
                    if state == "waiting_for_image"
                    else "Publication resumed."
                ),
            )

        new_id, active_id = self._enqueue(
            {"article_id": article_id, "article_url": article_url},
            idempotency_key=idempotency_key,
        )
        if new_id is None:
            return PublicationRunStartResult(
                status="already_running",
                run_id=active_id,
                detail="A publication run is already queued or running.",
            )

        self._dispatch(new_id, article_id=article_id, article_url=article_url)
        return PublicationRunStartResult(
            status="started", run_id=new_id, detail="Publication started."
        )

    def start_batch(
        self,
        article_ids: list[int] | tuple[int, ...] | None,
    ) -> PublicationRunStartResult:
        """Insert a queued batch row and dispatch one sequential Refinery run.

        One `workflow_runs` row, one daemon thread, one article after another
        (plan 109): the partial unique index
        `uq_workflow_runs_one_active_publication` cannot host parallel
        publication runs, so a batch occupies the single slot and refines
        ids in order. Every id gets an explicit per-item outcome in the run
        summary — a second start (single or batch) while one is active
        returns "already_running" with the active run's id, unchanged.
        """
        ids = list(article_ids or [])
        if not ids:
            return PublicationRunStartResult(
                status="invalid_request",
                run_id=0,
                detail="Provide 1..5 article ids.",
            )

        self.recover_expired_leases(include_queued=False)

        existing = self._checkpoints.reusable_request(article_ids=ids)
        if existing is not None:
            existing_id, complete = existing
            if complete:
                return PublicationRunStartResult(
                    status="existing",
                    run_id=existing_id,
                    detail="Reusing the recorded batch outcome.",
                )
            self._reconcile_waiting_safely()
            state = self.get_status(existing_id).run_status
            return PublicationRunStartResult(
                status=(
                    "waiting_for_image"
                    if state == "waiting_for_image"
                    else "already_running"
                ),
                run_id=existing_id,
                detail=(
                    "Edición completada · esperando imagen"
                    if state == "waiting_for_image"
                    else "Publication resumed."
                ),
            )

        new_id, active_id = self._enqueue({"article_ids": ids, "mode": "batch"})
        if new_id is None:
            return PublicationRunStartResult(
                status="already_running",
                run_id=active_id,
                detail="A publication run is already queued or running.",
            )

        self._dispatch_batch(new_id, article_ids=ids)
        return PublicationRunStartResult(
            status="started",
            run_id=new_id,
            detail=f"Batch publication started for {len(ids)} articles.",
        )

    def join_dispatched_threads(self, timeout: float | None = None) -> None:
        """Join the threads dispatched by this module (see the module helper).

        A convenience wrapper over
        :func:`join_dispatched_publication_threads`; the registry is
        process-wide because teardown holds no workflow instance.
        """
        join_dispatched_publication_threads(timeout)

    def _enqueue(
        self,
        run_metadata: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[int | None, int]:
        """Insert one queued publication row.

        Returns ``(new_id, 0)`` on success, or ``(None, active_id)`` when
        the single-flight index rejects the insert because a publication
        run is already queued/running. Shared by single and batch starts
        so both honor the same slot.
        """
        now = datetime.now(timezone.utc)
        with self._db.get_session() as session:
            self._checkpoints.supersede_changed_waits(
                session,
                article_ids=(
                    [str(i) for i in run_metadata.get("article_ids", [])]
                    if "article_ids" in run_metadata
                    else [str(run_metadata.get("article_id"))]
                ),
                article_url=run_metadata.get("article_url"),
            )
            row = WorkflowRun(
                run_type=RUN_TYPE_PUBLICATION,
                status="queued",
                started_at=now,
                idempotency_key=idempotency_key,
                run_metadata={**run_metadata, "worker_pid": os.getpid()},
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_id = session.execute(
                    select(WorkflowRun.id)
                    .where(
                        WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                        WorkflowRun.status.in_(("queued", "running")),
                    )
                    .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                logger.info(
                    "Publication run start rejected: another publication run "
                    "is already queued/running (id={}).",
                    existing_id,
                )
                return None, int(existing_id) if existing_id is not None else 0
            assert row.id is not None
            return int(row.id), 0

    def _spawn(self, *, target: Any, args: tuple[Any, ...], name: str) -> None:
        """Start one daemon worker and keep it joinable until it finishes.

        Dispatch stays non-blocking: only the thread's *registration* happens
        here. The reference lets
        :func:`join_dispatched_publication_threads` drain the worker before
        its owner closes the shared ``DatabaseManager``. The wrapper removes
        the thread from the registry in ``finally`` (a no-op if it finished
        before registration), and registration prunes any dead leftovers.
        """

        def run() -> None:
            try:
                target(*args)
            finally:
                with _dispatched_threads_lock:
                    _dispatched_threads.discard(thread)

        with self._dispatch_lock:
            if self._reconciler_stop.is_set():
                # A queued claim remains durable for startup recovery; shutdown
                # must not create a new worker after it starts draining threads.
                return
            thread = threading.Thread(target=run, daemon=True, name=name)
            thread.start()
            with _dispatched_threads_lock:
                _dispatched_threads.add(thread)
                finished = [t for t in _dispatched_threads if not t.is_alive()]
                for dead in finished:
                    _dispatched_threads.discard(dead)

    def _dispatch(
        self,
        run_id: int,
        *,
        article_id: int | None,
        article_url: str | None,
    ) -> None:
        self._spawn(
            target=self._run,
            args=(run_id, article_id, article_url),
            name=f"publish-{run_id}",
        )

    def _dispatch_batch(
        self,
        run_id: int,
        *,
        article_ids: list[int],
    ) -> None:
        self._spawn(
            target=self._run_batch,
            args=(run_id, article_ids),
            name=f"publish-batch-{run_id}",
        )

    def _start_heartbeat(self, run_id: int) -> tuple[threading.Event, threading.Thread]:
        """Start the lease-heartbeat thread; caller must set the event and
        join the thread when the run finishes (see `_run`/`_run_batch`)."""
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(run_id, stop_heartbeat),
            daemon=True,
            name=f"publish-{run_id}-heartbeat",
        )
        heartbeat_thread.start()
        return stop_heartbeat, heartbeat_thread

    def _run(
        self,
        run_id: int,
        article_id: int | None,
        article_url: str | None,
    ) -> None:
        if not self._transition(run_id, from_status="queued", to_status="running"):
            logger.error(
                "Publication run {} could not transition queued -> running; "
                "aborting dispatch.",
                run_id,
            )
            return

        stop_heartbeat, heartbeat_thread = self._start_heartbeat(run_id)
        try:
            from news_collector.logic.workflows.publication_pipeline import (
                run_publication_pipeline,
            )

            # `run_publication_pipeline()` in process_id mode skips the
            # collector and uses its own DatabaseManager — it never touches
            # the serving singleton. It is blocking (runs its own asyncio
            # loop internally); fine on this daemon thread, same as
            # CollectionRunWorkflow._run.
            self._reset_progress(run_id, item_index=0, item_count=1)
            result = run_publication_pipeline(
                process_id=str(article_id) if article_id is not None else None,
                article_url=article_url,
                skip_visuals=False,
                stage_listener=self._stage_listener(run_id),
                checkpoint_run_id=run_id,
                checkpoint_repository=self._checkpoints,
            )
            summary = self._collect_publication_summary(
                result,
                run_id=run_id,
                article_id=article_id,
                article_url=article_url,
            )
            if result.get("status") == "waiting_for_image":
                self._checkpoints.park(run_id, summary)
            elif result.get("status") == "success" and result.get("processed_count", 0):
                self.complete(run_id, summary=summary)
            else:
                self.fail(
                    run_id,
                    error_code=str(result.get("error_code") or "publication_failed"),
                    error_detail=(
                        summary.get("message")
                        or result.get("message")
                        or "Publication produced no PR (see summary)."
                    ),
                    summary=summary,
                )
        except Exception as exc:  # pragma: no cover - failure path
            logger.error("Publication run {} failed: {}", run_id, exc)
            self.fail(run_id, error_code="publication_failed", error_detail=str(exc))
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=5)
            self._reconcile_waiting_safely()

    def _run_batch(
        self,
        run_id: int,
        article_ids: list[int],
    ) -> None:
        """Execute one batch run: sequential Refine-Only passes, one per id.

        Run-level outcome: `succeeded` when every item produced an explicit
        outcome and at least one opened a PR path (`success`/`partial`
        from the pipeline wrapper); `failed` when nothing succeeded or the
        batch itself crashed — with the per-item list always present in the
        summary either way (LAW-B6). Per-article identity is untouched:
        each pass resolves its own canonical slug deterministically.
        """
        if not self._transition(run_id, from_status="queued", to_status="running"):
            logger.error(
                "Publication batch run {} could not transition queued -> "
                "running; aborting dispatch.",
                run_id,
            )
            return

        stop_heartbeat, heartbeat_thread = self._start_heartbeat(run_id)
        try:
            from news_collector.logic.workflows.publication_pipeline import (
                run_publication_batch,
            )

            batch = run_publication_batch(
                article_ids,
                skip_visuals=False,
                stage_listener=self._stage_listener(run_id),
                on_item_start=lambda index, count, _id: self._reset_progress(
                    run_id, item_index=index, item_count=count
                ),
                checkpoint_run_id=run_id,
                checkpoint_repository=self._checkpoints,
            )
            items: list[dict[str, Any]] = []
            for entry in batch.get("items", []):
                if not isinstance(entry, dict):
                    continue
                item_id = entry.get("article_id")
                item_result = {
                    "status": (
                        "success"
                        if entry.get("status") == "succeeded"
                        else entry.get("status", "error")
                    ),
                    "processed_count": entry.get("processed_count", 0),
                    "message": entry.get("message"),
                    "error_code": entry.get("error_code"),
                    "article_id": str(item_id),
                    "pr_url": entry.get("pr_url"),
                    "image_reason": entry.get("image_reason"),
                    "image_brief_slug": entry.get("image_brief_slug"),
                }
                item_summary = self._collect_publication_summary(
                    item_result,
                    run_id=run_id,
                    article_id=item_id if isinstance(item_id, int) else None,
                    article_url=None,
                )
                items.append(
                    {
                        "article_id": item_id,
                        "status": entry.get("status"),
                        "pr_url": item_summary.get("pr_url"),
                        "failure_class": item_summary.get("failure_class"),
                        "final_slug": item_summary.get("final_slug"),
                        "message": entry.get("message"),
                        "image_reason": entry.get("image_reason"),
                        "image_brief_slug": entry.get("image_brief_slug"),
                    }
                )
            summary = {
                "mode": "batch",
                "article_ids": list(article_ids),
                "succeeded_count": batch.get("succeeded_count", 0),
                "failed_count": batch.get("failed_count", 0),
                "total_count": batch.get("total_count", len(items)),
                "editorial_completed_count": batch.get("editorial_completed_count", 0),
                "waiting_for_image_count": batch.get("waiting_for_image_count", 0),
                "items": items,
            }
            if batch.get("waiting_for_image_count", 0):
                self._checkpoints.park(run_id, summary)
            elif batch.get("status") in ("success", "partial"):
                self.complete(run_id, summary=summary)
            else:
                self.fail(
                    run_id,
                    error_code=str(batch.get("error_code") or "batch_failed"),
                    error_detail=str(
                        batch.get("message") or "No batch item succeeded."
                    ),
                    summary=summary,
                )
        except Exception as exc:
            logger.error("Publication batch run {} failed: {}", run_id, exc)
            self.fail(
                run_id,
                error_code="batch_failed",
                error_detail=str(exc),
                summary={
                    "mode": "batch",
                    "article_ids": list(article_ids),
                    "items": [],
                },
            )
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=5)
            self._reconcile_waiting_safely()

    def _collect_publication_summary(
        self,
        result: dict[str, Any],
        *,
        run_id: int,
        article_id: int | None,
        article_url: str | None,
    ) -> dict[str, Any]:
        """Merge the pipeline's result dict with the persisted
        `PublicationAttemptSummary` (has `pr_url`, `failure_class`,
        `final_slug`, `branch_name`, `stages`) so the GUI can show the PR
        link or the editorial-rejection reason.

        The artifact is keyed per article, not per run, so evidence is
        merged ONLY when it provably belongs to this run: `generated_at`
        must parse and be strictly later than the run's `started_at` (see
        `_attempt_belongs_to_run`). A no-op run, a crash before any stage
        persisted, or a failed batch item must not inherit the previous
        attempt's `pr_url` / `success: true` (plan 131). The attempt writer
        inside the pipeline does not know the run id, so freshness is the
        authorship signal; every canonical artifact carries `generated_at`.
        Unverifiable artifacts (missing/malformed timestamp) are never
        trusted.
        """
        summary: dict[str, Any] = {
            "status": result.get("status"),
            "processed_count": result.get("processed_count", 0),
            "message": result.get("message"),
            "error_code": result.get("error_code"),
            "article_id": article_id,
            "article_url": article_url,
            "pr_url": result.get("pr_url"),
            "final_slug": result.get("final_slug"),
            "editorial_completed_count": result.get("editorial_completed_count", 0),
            "waiting_for_image_count": result.get("waiting_for_image_count", 0),
            "image_reason": result.get("image_reason"),
            "image_brief_slug": result.get("image_brief_slug"),
        }

        # The pipeline copies manual-ingest extras (incl. the resolved numeric
        # id) onto its result via merge_manual_ingest_context. Only read the
        # attempt file that matches THIS run's article — never fall back to
        # "newest file in the dir", which would splice a previous, unrelated
        # run's PR url / slug / stages into this summary (a noop run has no
        # attempt file at all).
        resolved_id = (
            str(article_id)
            if article_id is not None
            else str(result.get("article_id") or "").strip()
        )
        attempt = (
            self._read_attempt_for_id(resolved_id)
            if resolved_id and result.get("status") != "waiting_for_image"
            else None
        )
        if attempt is not None and not self._attempt_belongs_to_run(run_id, attempt):
            logger.info(
                "Run {}: ignoring attempt evidence for article {} written by a "
                "previous run (generated_at={!r}).",
                run_id,
                resolved_id,
                attempt.get("generated_at"),
            )
            attempt = None
        if attempt:
            for key in (
                "pr_url",
                "branch_name",
                "final_slug",
                "output_filename",
                "failure_class",
                "success",
                "target_repo",
            ):
                if attempt.get(key) is not None:
                    summary[key] = attempt[key]
            summary["stages"] = attempt.get("stages", [])
        safe = _json_safe(summary)
        return safe if isinstance(safe, dict) else {}

    def _attempt_belongs_to_run(self, run_id: int, attempt: dict[str, Any]) -> bool:
        """True only when the persisted attempt provably comes from THIS run.

        The artifact is keyed per article, not per run, so read-back proves
        authorship by freshness: the attempt's `generated_at` must parse and
        be strictly later than the run row's `started_at`. Missing or
        malformed timestamps (legacy/hand-written files cannot prove
        authorship) count as not this run's evidence — never trusted.
        """
        started_at = self._run_started_at(run_id)
        generated_at = _parse_iso_instant(attempt.get("generated_at"))
        if started_at is None or generated_at is None:
            return False
        return generated_at > started_at

    def _run_started_at(self, run_id: int) -> datetime | None:
        """The run row's `started_at` as an aware UTC datetime (SQLite hands
        back naive datetimes, see `_as_utc`); None when the row is gone."""
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
        started_at = row.started_at if row is not None else None
        return _as_utc(started_at) if started_at is not None else None

    def _read_attempt_for_id(self, resolved_id: str) -> dict[str, Any] | None:
        """Read `publication_attempts/{artifact_name(resolved_id)}.json` — the
        summary `PublicationAttempts` persists. Exact match only; a missing
        file means this run wrote no attempt. Callers must gate the result
        on run authorship (see `_attempt_belongs_to_run`): the file is keyed
        per article, not per run.
        """
        return read_publication_attempt(self._attempts_dir, resolved_id)

    # ------------------------------------------------------------------
    # live progress (admin GUI)
    # ------------------------------------------------------------------

    def _stage_listener(self, run_id: int) -> Any:
        def listener(_article_id: str, name: str, _success: bool) -> None:
            self.record_progress_stage(run_id, name)

        return listener

    def _write_progress(self, run_id: int, update_fn: Any) -> None:
        """Read-modify-write `run_metadata['progress']`. Advisory: a failure is
        logged and never affects the run."""
        try:
            with self._db.get_session() as session:
                row = session.get(WorkflowRun, run_id)
                if row is None:
                    return
                metadata = (
                    dict(row.run_metadata) if isinstance(row.run_metadata, dict) else {}
                )
                current = metadata.get("progress")
                progress = dict(current) if isinstance(current, dict) else {}
                update_fn(progress)
                progress["updated_at"] = datetime.now(timezone.utc).isoformat()
                metadata["progress"] = progress
                row.run_metadata = metadata
        except Exception as exc:  # progress is advisory
            logger.warning("Could not record progress for run {}: {}", run_id, exc)

    def _reset_progress(self, run_id: int, *, item_index: int, item_count: int) -> None:
        def reset(progress: dict[str, Any]) -> None:
            progress.update(stages=[], item_index=item_index, item_count=item_count)

        self._write_progress(run_id, reset)

    def record_progress_stage(self, run_id: int, name: str) -> None:
        def append(progress: dict[str, Any]) -> None:
            stages = progress.get("stages")
            progress["stages"] = [*(stages if isinstance(stages, list) else []), name]

        self._write_progress(run_id, append)

    def _typical_seconds(self, session: Any) -> int | None:
        """Median wall time of the most recent successful single-article runs
        (batch runs excluded in SQL, *before* the sample cap, so a window
        dominated by batches can never starve the estimate)."""
        mode = func.json_extract(WorkflowRun.run_metadata, "$.summary.mode")
        rows = session.execute(
            select(
                WorkflowRun.started_at,
                WorkflowRun.finished_at,
            )
            .where(
                WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                WorkflowRun.status == "succeeded",
                WorkflowRun.finished_at.is_not(None),
                or_(mode.is_(None), mode != "batch"),
            )
            .order_by(WorkflowRun.finished_at.desc())
            .limit(TYPICAL_DURATION_SAMPLE)
        ).all()
        durations = [
            seconds
            for started, finished in rows
            if (seconds := _run_duration_seconds(started, finished)) is not None
        ]
        median = _median_seconds(durations)
        return int(round(median)) if median is not None else None

    def _heartbeat_loop(self, run_id: int, stop: threading.Event) -> None:
        interval = max(1, self._heartbeat_interval_seconds)
        while not stop.wait(interval):
            if not self.heartbeat(run_id):
                return

    # ------------------------------------------------------------------
    # transitions
    # ------------------------------------------------------------------

    def _transition(
        self,
        run_id: int,
        *,
        from_status: str,
        to_status: str,
        **fields: Any,
    ) -> bool:
        with self._db.get_session() as session:
            values: dict[str, Any] = {
                "status": to_status,
                "updated_at": datetime.now(timezone.utc),
                **fields,
            }
            if to_status == "running":
                # A request can wait for days. Its original started_at is
                # history, so grant the resumed owner a fresh lease immediately.
                values["heartbeat_at"] = datetime.now(timezone.utc)
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == from_status)
                .values(**values)
            )
            updated = bool(result.rowcount == 1)
            if not updated:
                logger.info(
                    "CAS miss transitioning publication run {} ({} -> {}): "
                    "already transitioned or nonexistent.",
                    run_id,
                    from_status,
                    to_status,
                )
            return updated

    def heartbeat(self, run_id: int) -> bool:
        with self._db.get_session() as session:
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                .values(
                    heartbeat_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return bool(result.rowcount == 1)

    def _merge_summary(self, run_id: int, summary: dict[str, Any]) -> dict[str, Any]:
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            existing = (
                row.run_metadata
                if row is not None and isinstance(row.run_metadata, dict)
                else {}
            )
        return {**existing, "summary": _json_safe(summary)}

    def complete(self, run_id: int, *, summary: dict[str, Any]) -> bool:
        """CAS transition running -> succeeded, merging `summary` into
        `run_metadata` (keeps the request payload start() wrote)."""
        merged = self._merge_summary(run_id, summary)
        with self._db.get_session() as session:
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                .values(
                    status="succeeded",
                    updated_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    run_metadata=merged,
                )
            )
            updated = bool(result.rowcount == 1)
            if not updated:
                logger.info(
                    "CAS miss transitioning publication run {} (running -> "
                    "succeeded): already transitioned or nonexistent.",
                    run_id,
                )
            return updated

    def fail(
        self,
        run_id: int,
        *,
        error_code: str,
        error_detail: str,
        summary: dict[str, Any] | None = None,
    ) -> bool:
        """CAS transition running -> failed. Unlike the collection workflow,
        this also stores the (partial) summary — an editorial/auditor
        rejection is a "failed" run the operator still needs the details of
        (which stage, which policy)."""
        fields: dict[str, Any] = {
            "finished_at": datetime.now(timezone.utc),
            "error_code": error_code,
            "error_detail": error_detail,
        }
        try:
            if summary is not None:
                fields["run_metadata"] = self._merge_summary(run_id, summary)
            return self._transition(
                run_id, from_status="running", to_status="failed", **fields
            )
        except (SQLAlchemyError, RuntimeError) as exc:
            # The run row is unreachable (typically: the manager was closed
            # while this batch was finishing). Re-entering the DB would just
            # retry the same dead handle and mask the original failure, so
            # record both errors and stop; the caller already logged the
            # original exception before calling fail().
            logger.error(
                "Could not persist failure for publication run {}: {} "
                "(persistence error: {})",
                run_id,
                error_detail,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # lease recovery
    # ------------------------------------------------------------------

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Same-host probe; Windows and permission failures defer to the lease.

        Matches collection recovery's single-writer deployment contract.
        PID reuse can delay recovery but cannot interrupt a live process.
        """
        if os.name == "nt":  # pragma: no cover - Windows uses lease recovery
            return True
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def recover_expired_leases(self, *, include_queued: bool = True) -> list[int]:
        """Recover stale/dead publication owners; preserve resumable checkpoints.
        Scoped to publication runs — must not touch collection rows. Queued
        rows are only definitionally orphans at process startup, so
        `start()` passes `include_queued=False` (a fresh queued row may
        belong to a live in-flight start); startup keeps the default.
        Called once at process startup, same as `CollectionRunWorkflow`,
        and from `start()` for expired running rows."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._lease_timeout_seconds
        )
        running_stale = (WorkflowRun.status == "running") & (
            (WorkflowRun.heartbeat_at < cutoff)
            # No heartbeat yet: only stale if the run never beat within a
            # full lease (a live run beats ~60s after transitioning; a fresh
            # NULL row may belong to a thread mid-transition — reaping it
            # would murder a live run and break single-flight).
            | (WorkflowRun.heartbeat_at.is_(None) & (WorkflowRun.started_at < cutoff))
        )
        status_filter = (
            running_stale | (WorkflowRun.status == "queued")
            if include_queued
            else running_stale
        )
        with self._db.get_session() as session:
            stale = (
                session.execute(
                    select(
                        WorkflowRun.id, WorkflowRun.status, WorkflowRun.run_metadata
                    ).where(
                        WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                        status_filter,
                    )
                )
                .tuples()
                .all()
            )
            running = (
                session.execute(
                    select(
                        WorkflowRun.id,
                        WorkflowRun.status,
                        WorkflowRun.run_metadata,
                    ).where(
                        WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                        WorkflowRun.status == "running",
                    )
                )
                .tuples()
                .all()
            )

        stale_ids = {int(row[0]) for row in stale}
        dead_workers = set()
        for row in running:
            pid = (row.run_metadata or {}).get("worker_pid")
            if isinstance(pid, int) and not self._pid_alive(pid):
                dead_workers.add(int(row.id))
                if int(row.id) not in stale_ids:
                    stale.append(row)

        recovered: list[int] = []
        for stale_id, stale_status, metadata in stale:
            has_checkpoint = bool((metadata or {}).get("checkpoints"))
            has_outcomes = bool((metadata or {}).get("item_outcomes"))
            resumable = has_checkpoint or has_outcomes
            detail = (
                "Recovered at startup: heartbeat was stale or missing."
                if stale_status == "running"
                else "Recovered at startup: row was still queued."
            )
            # Recheck the expiry predicate in the UPDATE: a heartbeat may
            # have renewed the lease after the initial SELECT.
            with self._db.get_session() as session:
                result = session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == stale_id,
                        WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                        WorkflowRun.status == stale_status,
                        (
                            WorkflowRun.run_metadata == metadata
                            if int(stale_id) in dead_workers
                            else status_filter
                        ),
                    )
                    .values(
                        status="waiting_for_image" if resumable else "interrupted",
                        heartbeat_at=None,
                        finished_at=None if resumable else datetime.now(timezone.utc),
                        error_code=None if resumable else "process_restarted",
                        error_detail=None if resumable else detail,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                changed = result.rowcount == 1
            if changed:
                recovered.append(int(stale_id))

        if recovered:
            logger.warning(
                "Recovered {} expired publication-run lease(s) at startup: {}",
                len(recovered),
                recovered,
            )
        return recovered

    # ------------------------------------------------------------------
    # status lookup
    # ------------------------------------------------------------------

    def get_status(self, run_id: int | None) -> PublicationRunStatusResult:
        """Look up a run by id — typed "not_found" (never latest) if a given
        id doesn't exist. Returns the most recent `run_type='publication'`
        run only when `run_id` is None."""
        with self._db.get_session() as session:
            if run_id is not None:
                row = session.get(WorkflowRun, run_id)
            else:
                row = session.execute(
                    select(WorkflowRun)
                    .where(WorkflowRun.run_type == RUN_TYPE_PUBLICATION)
                    .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
                    .limit(1)
                ).scalar_one_or_none()

            if row is None:
                return PublicationRunStatusResult(status="not_found")

            metadata = row.run_metadata or {}
            summary = metadata.get("summary") if isinstance(metadata, dict) else None
            progress = metadata.get("progress") if isinstance(metadata, dict) else None
            typical = (
                self._typical_seconds(session)
                if row.status in ("queued", "running")
                else None
            )
            return PublicationRunStatusResult(
                status="found",
                run_id=row.id,
                run_status=row.status,
                started_at=row.started_at,
                finished_at=row.finished_at,
                heartbeat_at=row.heartbeat_at,
                error_code=row.error_code,
                error_detail=row.error_detail,
                summary=summary if isinstance(summary, dict) else {},
                progress=progress if isinstance(progress, dict) else {},
                typical_seconds=typical,
            )

    @staticmethod
    def generate_idempotency_key() -> str:
        return uuid.uuid4().hex

    def _find_waiting_request(
        self, article_id: int | None, article_url: str | None
    ) -> int | None:
        result = self._checkpoints.reusable_request(
            article_id=article_id, article_url=article_url
        )
        return result[0] if result is not None else None

    def _reconcile_waiting_safely(self) -> int:
        """Best-effort scheduling never masks a completed worker's outcome."""
        try:
            return self.reconcile_waiting()
        except Exception:
            logger.exception(
                "Image-wait reconciliation unavailable; durable requests retained"
            )
            return 0

    def reconcile_waiting(self) -> int:
        """Claim one ready request; the DB index arbitrates every race."""
        if self._reconciler_stop.is_set():
            return 0
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(self.data_dir, read_only=True)
        for run_id, metadata in self._checkpoints.waiting():
            try:
                checkpoints = self._checkpoints.all(run_id)
                outcomes = self._checkpoints.outcomes(run_id)
                if not checkpoints and not outcomes:
                    raise ValueError(
                        "Parked publication has no checkpoint or item evidence"
                    )
            except ValueError as exc:
                logger.error(
                    "Publication run {} cannot resume invalid evidence: {}", run_id, exc
                )
                self._checkpoints.reject_invalid_wait(run_id, str(exc))
                continue
            # ready means the process died after preparation and before image
            # resolution; terminal-only evidence can replay without LLMs too.
            pending = [
                cp for cp in checkpoints.values() if cp.status == "waiting_for_image"
            ]
            if (
                pending
                and not any(store.ready_for_article(cp.article_id) for cp in pending)
                and not any(cp.status == "ready" for cp in checkpoints.values())
            ):
                continue
            if self._reconciler_stop.is_set():
                return 0
            if not self._checkpoints.claim(run_id):
                return 0
            ids = metadata.get("article_ids")
            if metadata.get("mode") == "batch" or (
                metadata.get("standalone") and len(ids or []) > 1
            ):
                self._dispatch_batch(run_id, article_ids=[int(i) for i in (ids or [])])
            else:
                article_id = metadata.get("article_id")
                if article_id is None and checkpoints:
                    candidate_id = next(iter(checkpoints))
                    article_id = int(candidate_id) if candidate_id.isdecimal() else None
                self._dispatch(
                    run_id,
                    article_id=article_id,
                    article_url=(
                        metadata.get("article_url") if article_id is None else None
                    ),
                )
            return 1
        return 0

    def start_reconciler(self) -> None:
        if self._reconciler_thread and self._reconciler_thread.is_alive():
            return
        self._reconciler_stop.clear()
        self._reconcile_waiting_safely()

        def loop() -> None:
            while not self._reconciler_stop.wait(15):
                self._reconcile_waiting_safely()

        self._reconciler_thread = threading.Thread(
            target=loop, name="publication-image-reconciler", daemon=True
        )
        self._reconciler_thread.start()

    def stop_reconciler(self) -> None:
        """Stop scheduling and boundedly drain registered workers.

        A slow provider may outlive the join timeout. Its durable checkpoint and
        worker PID remain recoverable on restart; failure persistence contains
        closed-database errors if the process owner closes the manager meanwhile.
        """
        with self._dispatch_lock:
            self._reconciler_stop.set()
        if self._reconciler_thread:
            self._reconciler_thread.join(timeout=5)
        self.join_dispatched_threads(timeout=10)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_iso_instant(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime; None when the
    value is absent, not a string, or malformed (unverifiable evidence must
    never be trusted)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _run_duration_seconds(
    started: datetime | None,
    finished: datetime | None,
) -> float | None:
    """Wall time of a completed run, or None when it must not contribute:
    a missing timestamp or a non-positive duration."""
    if started is None or finished is None:
        return None
    seconds = (_as_utc(finished) - _as_utc(started)).total_seconds()
    return seconds if seconds > 0 else None


def _median_seconds(durations: list[float]) -> float | None:
    """Median of the samples, or None when there are no samples."""
    if not durations:
        return None
    durations.sort()
    mid = len(durations) // 2
    if len(durations) % 2:
        return durations[mid]
    return (durations[mid - 1] + durations[mid]) / 2
