"""Module role: Reconcile stale publication attempts from stored evidence
(Plan 060 / Phase 5b).

Owns:
- Selecting stale ``PR_CREATED`` publication attempts.
- Replaying unprocessed webhook receipts (``received`` from a crash,
  ``failed`` from a processing exception) whose ``publication_ids`` name a
  candidate, through the same callback effects the serving webhook applies.
- Applying evidence-backed transitions when the legacy article projection
  already reached a terminal state but the durable attempt row did not
  (out-of-order callback / missed dual-write): ``completed`` with a real
  deploy URL -> ``COMPLETED``; ``rejected`` -> ``REJECTED``.
- Persisting one ``workflow_runs`` audit row (``run_type=
  'publication_reconciliation'``) per non-dry run.

Does NOT own:
- Creating pull requests — it never does. A ``PR_CREATED`` attempt already
  has a PR; creating another is the exact failure this phase prevents.
- Publishing without deploy evidence: a legacy-``completed`` article whose
  ``published_url`` is unset stays ``PR_CREATED`` and is reported
  actionable, never marked ``COMPLETED``.
- GitHub/deployment network queries: evidence is the stored receipt, the
  durable attempt row, and the legacy DB projection only.
- Scheduling: invoked on demand by
  ``scripts/ops/reconcile_publication_attempts.py`` (no scheduler exists in
  this repo, same rationale as plan 4a's prune script).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from sqlalchemy import update

from news_collector.contracts.webhook import (
    AnyWebhookEvent,
    PublishCompleteEvent,
    ValidationResultEvent,
    parse_webhook_payload,
)
from news_collector.logic.workflows._run_metadata import json_safe
from news_collector.logic.workflows.publication_callbacks import (
    apply_publish_complete,
    apply_validation_result,
)
from news_collector.storage.models import WorkflowRun
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

RUN_TYPE_PUBLICATION_RECONCILIATION = "publication_reconciliation"

DEFAULT_STALE_MINUTES = 60
DEFAULT_LIMIT = 100
DEFAULT_RECEIPT_LIMIT = 500

ReconciliationOutcome = Literal[
    "completed",
    "rejected",
    "stale_pr_open",
    "missing_deploy_evidence",
    "article_missing",
]


@dataclass(frozen=True)
class ReconciliationAction:
    """One candidate's prospective (dry run) or applied repair."""

    attempt_id: int
    article_id: int
    refinery_id: str
    outcome: ReconciliationOutcome
    detail: str = ""


@dataclass(frozen=True)
class ReconciliationSummary:
    """Result of one reconciliation pass."""

    scanned: int = 0
    completed: int = 0
    rejected: int = 0
    replayable_receipts: int = 0
    replayed: int = 0
    stale_pr_open: int = 0
    missing_deploy_evidence: int = 0
    malformed_payloads: int = 0
    unmatched_receipts: int = 0
    dry_run: bool = False
    actions: tuple[ReconciliationAction, ...] = field(default_factory=tuple)


class PublicationReconciliationWorkflow:
    """Manual/scheduled pass over stale publication attempts. Instantiate
    per invocation (it is synchronous and request-scoped, unlike the
    long-lived run workflows)."""

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        stale_minutes: int = DEFAULT_STALE_MINUTES,
        limit: int = DEFAULT_LIMIT,
        receipt_limit: int = DEFAULT_RECEIPT_LIMIT,
        dry_run: bool = False,
        now: Optional[datetime] = None,
    ) -> ReconciliationSummary:
        """Scan, replay and repair; returns the typed summary.

        ``dry_run`` performs the same analysis with zero writes (no
        transitions, no receipt mutation, no audit row).
        """
        reference = now or datetime.now(timezone.utc)
        cutoff = reference - timedelta(minutes=stale_minutes)

        audit_run_id: int | None = None
        if not dry_run:
            audit_run_id = self._start_audit_run(
                stale_minutes=stale_minutes, limit=limit
            )
        try:
            summary = self._reconcile(
                cutoff=cutoff,
                limit=limit,
                receipt_limit=receipt_limit,
                dry_run=dry_run,
            )
        except Exception as exc:
            if audit_run_id is not None:
                self._fail_audit_run(audit_run_id, f"{type(exc).__name__}: {exc}")
            raise
        if audit_run_id is not None:
            self._complete_audit_run(audit_run_id, summary)
        return summary

    # ------------------------------------------------------------------
    # core pass
    # ------------------------------------------------------------------

    def _reconcile(
        self,
        *,
        cutoff: datetime,
        limit: int,
        receipt_limit: int,
        dry_run: bool,
    ) -> ReconciliationSummary:
        candidates = self._db.lifecycle.list_stale_publication_attempts(
            older_than=cutoff, state="PR_CREATED", limit=limit
        )
        if not candidates:
            return ReconciliationSummary(dry_run=dry_run)

        candidates_by_refinery: dict[str, list[Any]] = {}
        for attempt in candidates:
            candidates_by_refinery.setdefault(attempt.refinery_id, []).append(attempt)

        replayable, malformed, unmatched = self._select_replayable_receipts(
            candidates_by_refinery, receipt_limit=receipt_limit
        )
        replayed = 0 if dry_run else self._replay(replayable)

        actions: list[ReconciliationAction] = []
        for attempt in candidates:
            action = self._repair_candidate(attempt, dry_run=dry_run)
            if action is not None:
                actions.append(action)

        counts: dict[str, int] = {}
        for action in actions:
            counts[action.outcome] = counts.get(action.outcome, 0) + 1

        return ReconciliationSummary(
            scanned=len(candidates),
            completed=counts.get("completed", 0),
            rejected=counts.get("rejected", 0),
            replayable_receipts=len(replayable),
            replayed=replayed,
            stale_pr_open=counts.get("stale_pr_open", 0),
            missing_deploy_evidence=counts.get("missing_deploy_evidence", 0),
            malformed_payloads=malformed,
            unmatched_receipts=unmatched,
            dry_run=dry_run,
            actions=tuple(actions),
        )

    def _select_replayable_receipts(
        self, candidates_by_refinery: dict[str, list[Any]], *, receipt_limit: int
    ) -> tuple[list[tuple[Any, AnyWebhookEvent]], int, int]:
        """Split the unprocessed queue into (replayable, malformed, unmatched).

        A malformed stored payload or a receipt naming no candidate is never
        guessed into a repair — it is counted and left untouched.
        """
        replayable: list[tuple[Any, AnyWebhookEvent]] = []
        malformed = 0
        unmatched = 0
        receipts = self._db.webhook_receipts.list_unprocessed_receipts(
            limit=receipt_limit
        )
        for receipt in receipts:
            try:
                event = parse_webhook_payload(receipt.payload)
            except ValueError:
                logger.warning(
                    "Stored webhook receipt {} has a malformed payload; "
                    "leaving it for operator review.",
                    receipt.delivery_key,
                )
                malformed += 1
                continue
            if not any(
                refinery_id in candidates_by_refinery
                for refinery_id in event.publication_ids
            ):
                unmatched += 1
                continue
            replayable.append((receipt, event))
        return replayable, malformed, unmatched

    def _replay(self, replayable: list[tuple[Any, AnyWebhookEvent]]) -> int:
        """Re-run matching receipts through the real callback effects,
        updating each receipt's own processing status. Returns the number
        successfully processed."""
        replayed = 0
        for receipt, event in replayable:
            self._db.webhook_receipts.mark_processing(receipt.delivery_key)
            try:
                result = self._apply(event)
            except Exception as exc:
                logger.error(
                    "Replay of receipt {} failed: {}",
                    receipt.delivery_key,
                    exc,
                    exc_info=True,
                )
                self._db.webhook_receipts.mark_failed(
                    receipt.delivery_key, f"{type(exc).__name__}: {exc}"
                )
                continue
            self._db.webhook_receipts.mark_processed(receipt.delivery_key, result)
            replayed += 1
        return replayed

    def _apply(self, event: AnyWebhookEvent) -> dict[str, Any]:
        if isinstance(event, ValidationResultEvent):
            return apply_validation_result(event, self._db)
        if isinstance(event, PublishCompleteEvent):
            return apply_publish_complete(event, self._db)
        return {"action": "noop", "reason": "unhandled_event_type"}

    def _repair_candidate(
        self, attempt: Any, *, dry_run: bool
    ) -> ReconciliationAction | None:
        """Apply (or, in dry-run, compute) the evidence-backed repair for one
        candidate. Returns None when the attempt no longer exists."""
        base = {
            "attempt_id": attempt.id,
            "article_id": attempt.article_id,
            "refinery_id": attempt.refinery_id,
        }

        current = self._current_attempt(attempt.article_id, attempt.id)
        if current is None:
            return None
        if current.state == "COMPLETED":
            return ReconciliationAction(
                **base,
                outcome="completed",
                detail="resolved by replaying a stored callback",
            )
        if current.state == "REJECTED":
            return ReconciliationAction(
                **base,
                outcome="rejected",
                detail="resolved by replaying a stored callback",
            )
        if current.state != "PR_CREATED":
            return None

        article = self._db.articles.get_article_by_id(attempt.article_id)
        if article is None:
            return ReconciliationAction(
                **base,
                outcome="article_missing",
                detail="legacy article row no longer exists",
            )

        repaired = self._repair_from_legacy_projection(
            base, current, article, dry_run=dry_run
        )
        if repaired is not None:
            return repaired

        return ReconciliationAction(
            **base,
            outcome="stale_pr_open",
            detail=f"article processing_status={article.processing_status}",
        )

    def _repair_from_legacy_projection(
        self, base: dict[str, Any], current: Any, article: Any, *, dry_run: bool
    ) -> ReconciliationAction | None:
        if article.processing_status == "completed":
            return self._complete_from_legacy_evidence(
                base, current, article, dry_run=dry_run
            )
        if article.processing_status == "rejected":
            return self._reject_from_legacy_evidence(
                base, current, article, dry_run=dry_run
            )
        return None

    def _complete_from_legacy_evidence(
        self, base: dict[str, Any], current: Any, article: Any, *, dry_run: bool
    ) -> ReconciliationAction:
        if not article.published_url:
            return ReconciliationAction(
                **base,
                outcome="missing_deploy_evidence",
                detail=(
                    "legacy article is completed but has no published_url — "
                    "refusing to mark the attempt COMPLETED without deploy "
                    "evidence"
                ),
            )
        if not dry_run:
            self._db.lifecycle.apply_publication_transition(
                current.id,
                from_state="PR_CREATED",
                to_state="COMPLETED",
                event_type="deployed",
                details={
                    "deploy_url": article.published_url,
                    "source": "legacy_projection",
                },
                finished_at=datetime.now(timezone.utc),
            )
        return ReconciliationAction(
            **base, outcome="completed", detail=str(article.published_url)
        )

    def _reject_from_legacy_evidence(
        self, base: dict[str, Any], current: Any, article: Any, *, dry_run: bool
    ) -> ReconciliationAction:
        reason = self._legacy_rejection_reason(article)
        if not dry_run:
            self._db.lifecycle.apply_publication_transition(
                current.id,
                from_state="PR_CREATED",
                to_state="REJECTED",
                event_type="rejected",
                details={"reason": reason, "source": "legacy_projection"},
                finished_at=datetime.now(timezone.utc),
            )
        return ReconciliationAction(**base, outcome="rejected", detail=reason)

    def _current_attempt(self, article_id: int, attempt_id: int) -> Any | None:
        for candidate in self._db.lifecycle.get_publication_attempts_for_article(
            article_id
        ):
            if candidate.id == attempt_id:
                return candidate
        return None

    @staticmethod
    def _legacy_rejection_reason(article: Any) -> str:
        metadata = article.article_metadata or {}
        publication = metadata.get("publication") or {}
        reason = publication.get("reason")
        return str(reason)[:500] if reason else "rejected in legacy projection"

    # ------------------------------------------------------------------
    # workflow_runs audit row
    # ------------------------------------------------------------------

    def _start_audit_run(self, *, stale_minutes: int, limit: int) -> int:
        now = datetime.now(timezone.utc)
        with self._db.get_session() as session:
            row = WorkflowRun(
                run_type=RUN_TYPE_PUBLICATION_RECONCILIATION,
                status="queued",
                started_at=now,
                run_metadata={"stale_minutes": stale_minutes, "limit": limit},
            )
            session.add(row)
            session.flush()
            run_id = int(row.id)
        with self._db.get_session() as session:
            result = session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.status == "queued",
                )
                .values(status="running", heartbeat_at=now, updated_at=now)
            )
            if result.rowcount != 1:
                logger.warning(
                    "Reconciliation run {} could not transition queued -> "
                    "running; the audit row will be completed anyway.",
                    run_id,
                )
        return run_id

    def _complete_audit_run(self, run_id: int, summary: ReconciliationSummary) -> None:
        now = datetime.now(timezone.utc)
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            existing = (
                row.run_metadata
                if row is not None and isinstance(row.run_metadata, dict)
                else {}
            )
            merged = {**existing, "summary": json_safe(asdict(summary))}
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                .values(
                    status="succeeded",
                    finished_at=now,
                    updated_at=now,
                    run_metadata=merged,
                )
            )
            if result.rowcount != 1:
                logger.warning(
                    "Reconciliation run {} CAS miss (running -> succeeded).",
                    run_id,
                )

    def _fail_audit_run(self, run_id: int, error_detail: str) -> None:
        now = datetime.now(timezone.utc)
        with self._db.get_session() as session:
            session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                .values(
                    status="failed",
                    finished_at=now,
                    updated_at=now,
                    error_code="reconciliation_failed",
                    error_detail=error_detail,
                )
            )
