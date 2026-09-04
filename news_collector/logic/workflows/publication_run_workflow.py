"""
Module role: Durable, single-flight lifecycle for admin-triggered
publication ("Refine & Publish") runs (Plan 060 / Phase 4c).

Owns:
- Inserting/transitioning `workflow_runs` rows for `run_type='publication'`
  (queued -> running -> succeeded/failed, or -> interrupted on lease
  recovery).
- Dispatching one Refinery run (`apps.refinery.main.main`) in a background
  thread once a run's row is durably queued.
- Lease-based crash/restart recovery, scoped to `run_type='publication'`.

Does NOT own:
- HTTP request parsing/response mapping (`serving/api.py` stays a thin
  wrapper).
- The Refinery pipeline internals (`RefineryEngine`, `EditorAgent`,
  `GitHubPublisher`) — this module only orchestrates *when* a publish runs
  and records its outcome, exactly as `CollectionRunWorkflow` does for the
  collection cycle.

Why it wraps `apps.refinery.main.main(process_id=…)` rather than calling
`RefineryEngine` directly: in `process_id` mode `main()` skips the collector
and builds its **own** `DatabaseManager()` (`apps/refinery/main.py`), so it
never closes the process-wide singleton the serving API holds — the Phase 4a
`system.shutdown()` defect cannot recur through this path. `main()` is the
battle-tested wrapper the Streamlit panel already drives; reusing it keeps
the target-repo clone / editor / auditor / PR logic in one place.

Design mirrors `collection_run_workflow.py` (Plan 060 / Phase 4a) exactly:
constructor takes explicit `db_manager`, module logger, typed frozen-dataclass
results, state-based CAS on every transition, a `run_type='publication'`
partial unique index (`uq_workflow_runs_one_active_publication`) as the
single-flight enforcement.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from news_collector.logic.workflows._run_metadata import json_safe as _json_safe
from news_collector.storage.models import WorkflowRun
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


RUN_TYPE_PUBLICATION = "publication"
# A Refinery run (editor LLM + auditor LLM + image fetch + git clone/push +
# PR creation) is slower and more variable than a collection cycle; give the
# lease generous headroom. Same rationale as CollectionRunWorkflow: the
# heartbeat cadence is a short fixed interval, independent of this.
DEFAULT_LEASE_TIMEOUT_SECONDS = 3600  # 1 hour
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class PublicationRunStartResult:
    """Result of :meth:`PublicationRunWorkflow.start`."""

    status: Literal["started", "already_running", "invalid_request"]
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
        publication_attempts_dir: (
            str | os.PathLike[str]
        ) = "data/runtime/publication_attempts",
    ) -> None:
        self._db = db_manager
        self._lease_timeout_seconds = lease_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._attempts_dir = Path(publication_attempts_dir)

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

        now = datetime.now(timezone.utc)
        run_id: int | None = None
        with self._db.get_session() as session:
            row = WorkflowRun(
                run_type=RUN_TYPE_PUBLICATION,
                status="queued",
                started_at=now,
                idempotency_key=idempotency_key,
                run_metadata={
                    "article_id": article_id,
                    "article_url": article_url,
                },
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
                return PublicationRunStartResult(
                    status="already_running",
                    run_id=int(existing_id) if existing_id is not None else 0,
                    detail="A publication run is already queued or running.",
                )
            run_id = row.id

        self._dispatch(run_id, article_id=article_id, article_url=article_url)
        return PublicationRunStartResult(
            status="started", run_id=run_id, detail="Publication started."
        )

    def _dispatch(
        self,
        run_id: int,
        *,
        article_id: int | None,
        article_url: str | None,
    ) -> None:
        threading.Thread(
            target=self._run,
            args=(run_id, article_id, article_url),
            daemon=True,
            name=f"publish-{run_id}",
        ).start()

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

        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(run_id, stop_heartbeat),
            daemon=True,
            name=f"publish-{run_id}-heartbeat",
        )
        heartbeat_thread.start()
        try:
            from apps.refinery.main import main as run_refinery

            # `main()` in process_id mode skips the collector and uses its
            # own DatabaseManager — it never touches the serving singleton.
            # It is blocking (runs its own asyncio loop internally); fine on
            # this daemon thread, same as CollectionRunWorkflow._run.
            result = run_refinery(
                process_id=str(article_id) if article_id is not None else None,
                article_url=article_url,
                skip_visuals=False,
            )
            summary = self._collect_publication_summary(
                result, article_id=article_id, article_url=article_url
            )
            if result.get("status") == "success" and result.get("processed_count", 0):
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

    def _collect_publication_summary(
        self,
        result: dict[str, Any],
        *,
        article_id: int | None,
        article_url: str | None,
    ) -> dict[str, Any]:
        """Merge `main()`'s result dict with the persisted
        `PublicationAttemptSummary` (has `pr_url`, `failure_class`,
        `final_slug`, `branch_name`, `stages`) so the GUI can show the PR
        link or the editorial-rejection reason.
        """
        summary: dict[str, Any] = {
            "status": result.get("status"),
            "processed_count": result.get("processed_count", 0),
            "message": result.get("message"),
            "error_code": result.get("error_code"),
            "article_id": article_id,
            "article_url": article_url,
        }

        # main() copies manual-ingest extras (incl. the resolved numeric id)
        # onto its result via merge_manual_ingest_context. Only read the
        # attempt file that matches THIS run's article — never fall back to
        # "newest file in the dir", which would splice a previous, unrelated
        # run's PR url / slug / stages into this summary (a noop run has no
        # attempt file at all).
        resolved_id = (
            str(article_id)
            if article_id is not None
            else str(result.get("article_id") or "").strip()
        )
        attempt = self._read_attempt_for_id(resolved_id) if resolved_id else None
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

    def _read_attempt_for_id(self, resolved_id: str) -> dict[str, Any] | None:
        """Read `publication_attempts/{safe_id}.json` — the summary
        `RefineryEngine._persist_publication_attempt_summary` writes, keyed
        by `RefineryEngine._safe_publication_artifact_name(article_id)`.
        Exact match only; a missing file means this run wrote no attempt.
        """
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        safe = RefineryEngine._safe_publication_artifact_name(resolved_id)
        path = self._attempts_dir / f"{safe}.json"
        try:
            if not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError) as exc:
            logger.warning("Could not read publication attempt summary: {}", exc)
            return None

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
        if summary is not None:
            fields["run_metadata"] = self._merge_summary(run_id, summary)
        return self._transition(
            run_id, from_status="running", to_status="failed", **fields
        )

    # ------------------------------------------------------------------
    # lease recovery
    # ------------------------------------------------------------------

    def recover_expired_leases(self) -> list[int]:
        """CAS every stale `run_type='publication'` row to `interrupted`.
        Scoped to publication runs — must not touch collection rows. Called
        once at process startup, same as `CollectionRunWorkflow`."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._lease_timeout_seconds
        )
        with self._db.get_session() as session:
            stale = (
                session.execute(
                    select(WorkflowRun.id, WorkflowRun.status).where(
                        WorkflowRun.run_type == RUN_TYPE_PUBLICATION,
                        (
                            (WorkflowRun.status == "running")
                            & (
                                WorkflowRun.heartbeat_at.is_(None)
                                | (WorkflowRun.heartbeat_at < cutoff)
                            )
                        )
                        | (WorkflowRun.status == "queued"),
                    )
                )
                .tuples()
                .all()
            )

        recovered: list[int] = []
        for stale_id, stale_status in stale:
            detail = (
                "Recovered at startup: heartbeat was stale or missing."
                if stale_status == "running"
                else "Recovered at startup: row was still queued."
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
            )

    @staticmethod
    def generate_idempotency_key() -> str:
        return uuid.uuid4().hex
