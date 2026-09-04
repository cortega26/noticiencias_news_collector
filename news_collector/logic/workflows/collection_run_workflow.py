"""
Module role: Durable, single-flight lifecycle for admin-triggered
collection runs (Plan 060 / Phase 4a).

Owns:
- Inserting/transitioning `workflow_runs` rows for `run_type='collection'`
  (queued -> running -> succeeded/failed, or -> interrupted on lease
  recovery).
- Dispatching the actual collection cycle in a background thread once a
  run's row is durably queued.
- Lease-based crash/restart recovery: a `running` row whose `heartbeat_at`
  is older than `lease_timeout_seconds` (or never set) is stale and gets
  CAS-transitioned to `interrupted` at process startup.

Does NOT own:
- HTTP request parsing/response mapping/status-code mapping (`serving/api.py`
  stays a thin wrapper — this is the actual workflow logic the master plan's
  work item 5 says does not belong in `serving/`).
- The collection pipeline's own internals (`news_collector.system.create_system`,
  `run_collection_cycle`) — this module only orchestrates *when* that work
  runs and records its outcome, matching `PROrchestrator`/`RefineryEngine`'s
  own "owns the workflow, not the domain logic" split.

Design (see `plans/060/phase-4a-collection-run-workflow/spec.md` Design §2):
constructor takes explicit dependencies (`db_manager`, never a global),
module-level logger via `get_logger().create_module_logger(...)`, public
methods return a typed result (frozen dataclass with a `status` field)
rather than raising for *expected* failure modes ("already running",
"not found") — matching `LifecycleRepository.transition_publication_attempt`'s
"CAS miss is not an error" convention. No `version` column: single-flight
and every state transition here is a state-based CAS
(`UPDATE ... WHERE id=? AND status=expected`, checking `rowcount == 1`),
the one CAS pattern this codebase actually has precedent for.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from news_collector.logic.workflows._run_metadata import json_safe as _json_safe
from news_collector.storage.models import WorkflowRun
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


RUN_TYPE_COLLECTION = "collection"
DEFAULT_LEASE_TIMEOUT_SECONDS = 3600  # 1 hour — a collection cycle's own
# outer timeout is expected to be well under this; see
# spec.md Design §2's recover_expired_leases() note.
# Deliberately NOT derived from lease_timeout_seconds (e.g. a fraction of
# it): a typical collection cycle finishes in well under an hour, so tying
# the heartbeat cadence to the lease timeout left the timeout-based branch
# of recover_expired_leases() essentially untested by any real run — only
# the "never heartbeated at all" branch ever fired in practice. A short,
# fixed interval keeps heartbeat_at genuinely current throughout a run
# without changing how aggressively a stale lease gets reclaimed (still
# governed by lease_timeout_seconds alone).
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class CollectionRunStartResult:
    """Result of :meth:`CollectionRunWorkflow.start`."""

    status: Literal["started", "already_running"]
    run_id: int
    detail: str = ""


@dataclass(frozen=True)
class CollectionRunStatusResult:
    """Result of :meth:`CollectionRunWorkflow.get_status`."""

    status: Literal["found", "not_found"]
    run_id: int | None = None
    run_status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


class CollectionRunWorkflow:
    """Owns the durable lifecycle of `workflow_runs` rows for
    `run_type='collection'`.

    Instantiate once per serving process (mirrors `PROrchestrator`:
    "Instantiate once per RefineryEngine").
    """

    def __init__(
        self,
        db_manager: Any,
        *,
        lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_SECONDS,
        heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._db = db_manager
        self._lease_timeout_seconds = lease_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    # ------------------------------------------------------------------
    # start / dispatch
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        dry_run: bool,
        idempotency_key: str | None = None,
    ) -> CollectionRunStartResult:
        """Insert a queued `workflow_runs` row and dispatch the collection
        cycle in a background thread.

        The partial unique index `uq_workflow_runs_one_active_collection`
        (status IN ('queued', 'running')) is the actual single-flight
        enforcement: if another collection run is already queued/running,
        the INSERT raises `IntegrityError`, which this method catches and
        turns into a typed "already_running" result carrying the existing
        run's id — never an exception the caller has to handle as control
        flow (same convention as
        `LifecycleRepository.transition_publication_attempt`'s CAS miss).
        """
        now = datetime.now(timezone.utc)
        run_id: int | None = None
        # Self-healing single-flight (plan 078): reap expired running
        # leases here, not only at boot — but never queued rows, which may
        # belong to a live concurrent start.
        self.recover_expired_leases(include_queued=False)
        with self._db.get_session() as session:
            row = WorkflowRun(
                run_type=RUN_TYPE_COLLECTION,
                status="queued",
                started_at=now,
                idempotency_key=idempotency_key,
                run_metadata={"dry_run": dry_run},
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_id = session.execute(
                    select(WorkflowRun.id)
                    .where(
                        WorkflowRun.run_type == RUN_TYPE_COLLECTION,
                        WorkflowRun.status.in_(("queued", "running")),
                    )
                    .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                logger.info(
                    "Collection run start rejected: another collection run "
                    "is already queued/running (id={}).",
                    existing_id,
                )
                # existing_id should always be present here (the INSERT only
                # fails because such a row exists) — but a defensive 0
                # keeps the typed result's `run_id: int` contract even in
                # the pathological case of a row disappearing between the
                # failed INSERT and this SELECT (e.g. concurrently pruned).
                return CollectionRunStartResult(
                    status="already_running",
                    run_id=int(existing_id) if existing_id is not None else 0,
                    detail="A collection run is already queued or running.",
                )
            run_id = row.id

        self._dispatch(run_id, dry_run=dry_run)
        return CollectionRunStartResult(
            status="started", run_id=run_id, detail="Collection started."
        )

    def _dispatch(self, run_id: int, *, dry_run: bool) -> None:
        """Launch the collection cycle in a daemon thread. The DB row
        already exists (inserted by `start()` before this is called) —
        that is the durability fix this phase makes; the dispatch
        mechanism itself (a background thread) is unchanged from the
        pre-Phase-4a code, per spec.md's own explicit note that the
        single-writer deployment topology does not require redesigning
        this part."""
        threading.Thread(
            target=self._run,
            args=(run_id, dry_run),
            daemon=True,
            name=f"collect-{run_id}",
        ).start()

    def _run(self, run_id: int, dry_run: bool) -> None:
        if not self._transition(run_id, from_status="queued", to_status="running"):
            # Nothing else could have raced this (single-writer topology,
            # this thread is the only writer for this row's queued->running
            # step) — but if it ever happens, there is no run left to
            # execute against.
            logger.error(
                "Collection run {} could not transition queued -> running; "
                "aborting dispatch.",
                run_id,
            )
            return

        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(run_id, stop_heartbeat),
            daemon=True,
            name=f"collect-{run_id}-heartbeat",
        )
        heartbeat_thread.start()
        try:
            from news_collector.system import create_system

            system = create_system()
            if not system.initialize():
                raise RuntimeError("System initialization failed")

            async def _cycle():
                try:
                    summary = await system.run_collection_cycle(dry_run=dry_run)
                    if not dry_run:
                        await asyncio.to_thread(
                            system.export_latest_articles,
                            file_path="data/exports/latest_articles.json",
                            limit=50,
                        )
                    return summary
                finally:
                    # close_db=False: build_database() hands back the
                    # process-wide DatabaseManager singleton, which this same
                    # process's serving API keeps using. Closing it here left
                    # `complete()`/`fail()` below — and every later
                    # `/v1/admin/*` request — hitting `SessionLocal is None`.
                    # The serving process owns the engine lifetime; a run
                    # only borrows it.
                    await system.shutdown(close_db=False)

            summary = asyncio.run(_cycle())
            self.complete(run_id, summary=summary or {})
        except Exception as exc:  # pragma: no cover - failure path
            logger.error("Collection run {} failed: {}", run_id, exc)
            self.fail(run_id, error_code="collection_failed", error_detail=str(exc))
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=5)

    def _heartbeat_loop(self, run_id: int, stop: threading.Event) -> None:
        interval = max(1, self._heartbeat_interval_seconds)
        while not stop.wait(interval):
            if not self.heartbeat(run_id):
                # No longer ours to heartbeat (already transitioned away,
                # e.g. recovered as an expired lease by another path) —
                # stop, per spec.md's "caller should treat this as stop,
                # someone else owns this now."
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
        """State-based CAS transition, same shape as
        `LifecycleRepository.transition_publication_attempt`:
        `UPDATE workflow_runs SET status=to_status, ... WHERE id=run_id AND
        status=from_status`. Returns True iff exactly one row was updated."""
        with self._db.get_session() as session:
            values: dict[str, Any] = {
                "status": to_status,
                "updated_at": datetime.now(timezone.utc),
                **fields,
            }
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == from_status)
                .values(**values)
            )
            updated = bool(result.rowcount == 1)
            if not updated:
                logger.info(
                    "CAS miss transitioning workflow run {} ({} -> {}): "
                    "already transitioned or nonexistent.",
                    run_id,
                    from_status,
                    to_status,
                )
            return updated

    def heartbeat(self, run_id: int) -> bool:
        """Update `heartbeat_at`/`updated_at` on a `running` row. Returns
        False (not an exception) if the row is no longer `running` — the
        caller should treat this as "stop, someone else owns this now."
        """
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

    def complete(self, run_id: int, *, summary: dict[str, Any]) -> bool:
        """CAS transition running -> succeeded.

        Merges `summary` into the row's *existing* `run_metadata` (set by
        `start()` to the request payload, e.g. `{"dry_run": ...}`) rather
        than replacing it — spec.md Design §1 is explicit that
        `run_metadata` "stays as the catch-all for the run's request
        payload and success summary", both, not summary only. A plain
        `_transition(..., run_metadata={"summary": summary})` would
        silently drop `dry_run` on every successful run while `fail()`
        (which never touches `run_metadata`) leaves it — an accidental,
        confusing asymmetry this avoids.
        """
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            existing_metadata = (
                row.run_metadata
                if row is not None and isinstance(row.run_metadata, dict)
                else {}
            )
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                .values(
                    status="succeeded",
                    updated_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    run_metadata={
                        **existing_metadata,
                        "summary": _json_safe(summary),
                    },
                )
            )
            updated = bool(result.rowcount == 1)
            if not updated:
                logger.info(
                    "CAS miss transitioning workflow run {} (running -> "
                    "succeeded): already transitioned or nonexistent.",
                    run_id,
                )
            return updated

    def fail(self, run_id: int, *, error_code: str, error_detail: str) -> bool:
        """CAS transition running -> failed."""
        return self._transition(
            run_id,
            from_status="running",
            to_status="failed",
            finished_at=datetime.now(timezone.utc),
            error_code=error_code,
            error_detail=error_detail,
        )

    # ------------------------------------------------------------------
    # lease recovery
    # ------------------------------------------------------------------

    def recover_expired_leases(self, *, include_queued: bool = True) -> list[int]:
        """Find every `running` `run_type='collection'` row whose
        `heartbeat_at` is older than the lease timeout (or NULL — started
        but never heartbeat once, e.g. crashed immediately) and
        CAS-transition each to `interrupted`.

        Scoped to `run_type='collection'` deliberately, same as
        `get_status`'s "latest run" lookup: this is a
        `CollectionRunWorkflow`, and it must not reach into other
        subsystems' `workflow_runs` rows (e.g. a future refinery-run
        writer) just because they happen to share this table. Today that
        scoping is inert — nothing else writes `workflow_runs` yet — but
        it stops this class from silently interrupting another
        subsystem's in-flight row the moment something else starts
        writing here.

        Called once at process startup (this phase's answer to "restart
        recovery is deterministic") — not on a timer, since the only
        process that could be holding a stale lease is the one that just
        restarted. Returns the list of recovered run ids for
        logging/alerting.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._lease_timeout_seconds
        )
        with self._db.get_session() as session:
            # `running` rows: stale if the heartbeat is missing or too old.
            # `queued` rows: a queued row only exists momentarily, between
            # start()'s INSERT and _dispatch()'s thread flipping it to
            # `running` — at process *startup* no such in-flight call can
            # exist, so any `queued` row found here is definitionally an
            # orphan from a process that crashed between those two steps
            # (no heartbeat/cutoff check needed or possible: queued rows
            # never get a heartbeat_at at all). Both statuses are covered
            # here because the active-collection partial index treats
            # queued the same as running — an orphaned queued row would
            # otherwise permanently block every future collection request
            # with 409, with no process left able to finish or recover it.
            # `include_queued=False` (used by `start()`) skips the queued
            # clause: at startup no in-flight call can exist, but here a
            # fresh queued row may belong to a live concurrent start.
            running_stale = (WorkflowRun.status == "running") & (
                (WorkflowRun.heartbeat_at < cutoff)
                # No heartbeat yet: only stale if the run never beat within
                # a full lease (a live run beats ~60s after transitioning; a
                # fresh NULL row may belong to a thread mid-transition).
                | (
                    WorkflowRun.heartbeat_at.is_(None)
                    & (WorkflowRun.started_at < cutoff)
                )
            )
            status_filter = (
                running_stale | (WorkflowRun.status == "queued")
                if include_queued
                else running_stale
            )
            stale = (
                session.execute(
                    select(WorkflowRun.id, WorkflowRun.status).where(
                        WorkflowRun.run_type == RUN_TYPE_COLLECTION,
                        status_filter,
                    )
                )
                .tuples()
                .all()
            )

        recovered: list[int] = []
        for stale_id, stale_status in stale:
            detail = (
                "Recovered at startup: heartbeat was stale or missing, "
                "indicating the previous process exited without "
                "completing this run."
                if stale_status == "running"
                else (
                    "Recovered at startup: row was still queued, indicating "
                    "the previous process exited between inserting this run "
                    "and dispatching it."
                )
            )
            if self._transition(
                int(stale_id),
                from_status=stale_status,
                to_status="interrupted",
                finished_at=datetime.now(timezone.utc),
                error_code="process_restarted",
                error_detail=detail,
            ):
                recovered.append(int(stale_id))

        if recovered:
            logger.warning(
                "Recovered {} expired collection-run lease(s) at startup: {}",
                len(recovered),
                recovered,
            )
        return recovered

    # ------------------------------------------------------------------
    # status lookup
    # ------------------------------------------------------------------

    def get_status(self, run_id: int | None) -> CollectionRunStatusResult:
        """Look up a specific run by id if given — returns a typed
        "not_found" result (never the latest run) if `run_id` is given but
        doesn't exist. Only returns the most recent `run_type='collection'`
        run when `run_id` is None."""
        with self._db.get_session() as session:
            if run_id is not None:
                row = session.get(WorkflowRun, run_id)
            else:
                row = session.execute(
                    select(WorkflowRun)
                    .where(WorkflowRun.run_type == RUN_TYPE_COLLECTION)
                    .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
                    .limit(1)
                ).scalar_one_or_none()

            if row is None:
                return CollectionRunStatusResult(status="not_found")

            metadata = row.run_metadata or {}
            summary = metadata.get("summary") if isinstance(metadata, dict) else None
            return CollectionRunStatusResult(
                status="found",
                run_id=row.id,
                run_status=row.status,
                started_at=row.started_at,
                finished_at=row.finished_at,
                heartbeat_at=row.heartbeat_at,
                error_code=row.error_code,
                error_detail=row.error_detail,
                summary=summary if isinstance(summary, dict) else {},
            )

    @staticmethod
    def generate_idempotency_key() -> str:
        """Server-generated idempotency key for callers that don't supply
        their own (spec.md Design §1: "caller-supplied or server-generated
        key")."""
        return uuid.uuid4().hex
