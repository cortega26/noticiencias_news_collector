"""Lifecycle repository — typed read/write access to Phase 3a's durable
lineage tables (Plan 060 / Phase 3b).

Exposes the two tables this phase actually populates — ``publication_attempts``
and ``editorial_decisions`` — through append-only inserts and a single
compare-and-set (CAS) transition method. The other three Phase 3a tables
(``workflow_runs``, ``workflow_stage_attempts``, ``publication_events``) get
no query/write methods here: nothing writes to them in this phase, so there
is nothing for a read method to return yet. Whichever future phase first
writes to one of those tables should add its own read methods alongside
that write.

Return types are plain frozen dataclasses, not the SQLAlchemy ORM model
instances and not raw dicts — these are backend-internal lifecycle records
with no cross-repo/frontend relevance, so (per this repo's own
``contracts/`` convention — contracts are explicitly cross-repo) they do
not belong in ``contracts/``.

CAS design note: this codebase has no existing "version column" precedent
anywhere. Every other write method (``mark_article_published`` and
neighbors in ``article_repository.py``) does a plain read-then-write, with
``reject_publication_attempts``/``complete_publication_attempts`` filtering
candidates by current state before touching them as the closest existing
analog. ``transition_publication_attempt`` below follows that same pattern
as a real ``UPDATE ... WHERE id = ... AND state = ...`` with a rowcount
check — no schema change, no new ``version`` column.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, update

from news_collector.utils.logger import get_logger

from .models import EditorialDecision as _EditorialDecisionModel
from .models import PublicationAttemptRecord as _PublicationAttemptModel

logger = get_logger().create_module_logger(__name__)


# ---------------------------------------------------------------------------
# Legacy audit-state vocabulary
# ---------------------------------------------------------------------------
#
# `article_metadata["audit"]["state"]` is a free-form string: the admin API
# (`AdminAuditStatusUpdate.audit_status`) accepts any value with no
# validator, and `RefineryEngine._record_audit_status` itself writes several
# distinct values (`audit_pending`, `audit_skipped`,
# `audit_skipped_backpressure`, `audit_failed`, `audit_passed`).
# `editorial_decisions.outcome` is constrained by a CHECK to exactly
# `pass`/`fail`/`accept`/`reject` (see `EDITORIAL_DECISION_OUTCOME_VALUES`
# in models.py), so — unlike `publication_attempts.state`, whose three
# legacy values already match `PUBLICATION_ATTEMPT_STATE_VALUES` exactly —
# the legacy audit vocabulary cannot be stored verbatim.
#
# This is an explicit, closed mapping, not substring matching: a free-form
# value must never be silently guessed into an outcome. Anything not in
# this map — including `audit_pending`/`audit_skipped*`, which are not
# decisions at all, just in-progress or skipped states — maps to `None`:
# "no decision to record," not "reject."
AUDIT_LEGACY_STATE_TO_OUTCOME: dict[str, str] = {
    "audit_passed": "pass",
    "passed": "pass",
    "audit_failed": "fail",
    "failed": "fail",
}


def map_legacy_audit_outcome(state: str | None) -> str | None:
    """Map a legacy ``article_metadata["audit"]["state"]`` value to an
    ``editorial_decisions.outcome`` enum value.

    Returns ``None`` when ``state`` does not represent a completed
    decision (non-terminal, e.g. ``"audit_pending"``, or unrecognized) —
    callers must treat that as "nothing to record here," never as an
    implicit reject.
    """
    if state is None:
        return None
    return AUDIT_LEGACY_STATE_TO_OUTCOME.get(state)


# ---------------------------------------------------------------------------
# Read-side dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublicationAttemptView:
    """Read projection of one ``publication_attempts`` row."""

    id: int
    article_id: int
    refinery_id: str
    attempt_number: int
    state: str
    pr_url: str | None
    branch_name: str | None
    started_at: datetime
    finished_at: datetime | None
    details: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True)
class EditorialDecisionView:
    """Read projection of one ``editorial_decisions`` row."""

    id: int
    article_id: int | None
    decision_type: str
    outcome: str
    reason: str | None
    decided_at: datetime
    details: dict[str, Any] | None
    created_at: datetime


def _to_publication_attempt_view(
    row: _PublicationAttemptModel,
) -> PublicationAttemptView:
    return PublicationAttemptView(
        id=row.id,
        article_id=row.article_id,
        refinery_id=row.refinery_id,
        attempt_number=row.attempt_number,
        state=row.state,
        pr_url=row.pr_url,
        branch_name=row.branch_name,
        started_at=row.started_at,
        finished_at=row.finished_at,
        details=row.details,
        created_at=row.created_at,
    )


def _to_editorial_decision_view(row: _EditorialDecisionModel) -> EditorialDecisionView:
    return EditorialDecisionView(
        id=row.id,
        article_id=row.article_id,
        decision_type=row.decision_type,
        outcome=row.outcome,
        reason=row.reason,
        decided_at=row.decided_at,
        details=row.details,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class LifecycleRepository:
    """Typed repository for the durable lifecycle tables Phase 3a added.

    Receives a DatabaseManager (or any object with ``get_session()``) as its
    session provider, matching
    :class:`~news_collector.storage.article_repository.ArticleRepository`
    and :class:`~news_collector.storage.source_repository.SourceRepository`.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    @contextmanager
    def _session(self):
        with self._db.get_session() as session:
            yield session

    # ------------------------------------------------------------------
    # publication_attempts — append-only inserts + CAS transition
    # ------------------------------------------------------------------

    def record_publication_attempt(
        self,
        article_id: int,
        *,
        refinery_id: str,
        state: str,
        started_at: datetime,
        pr_url: str | None = None,
        branch_name: str | None = None,
        finished_at: datetime | None = None,
        details: dict[str, Any] | None = None,
        attempt_number: int | None = None,
    ) -> PublicationAttemptView:
        """Insert a new ``publication_attempts`` row (append pattern: each
        real attempt is its own row).

        ``attempt_number`` defaults to ``COUNT(*) + 1`` scoped to
        ``article_id`` when omitted — the real-attempt path, for future
        (Phase 3c) callers. The Phase 3b backfill is always attempt 1 by
        construction (legacy ``article_metadata["publication"]`` only ever
        records the article's *current* state, never a history of prior
        attempts) and passes ``attempt_number=1`` explicitly rather than
        relying on this default.
        """
        with self._session() as session:
            if attempt_number is None:
                count = (
                    session.query(func.count(_PublicationAttemptModel.id))
                    .filter(_PublicationAttemptModel.article_id == article_id)
                    .scalar()
                )
                attempt_number = int(count or 0) + 1

            row = _PublicationAttemptModel(
                article_id=article_id,
                refinery_id=refinery_id,
                attempt_number=attempt_number,
                state=state,
                pr_url=pr_url,
                branch_name=branch_name,
                started_at=started_at,
                finished_at=finished_at,
                details=details,
            )
            session.add(row)
            session.flush()
            view = _to_publication_attempt_view(row)
            logger.info(
                "Recorded publication attempt {} for article {} (state={})",
                view.id,
                article_id,
                state,
            )
            return view

    def transition_publication_attempt(
        self,
        attempt_id: int,
        *,
        from_state: str,
        to_state: str,
        **fields: Any,
    ) -> bool:
        """Compare-and-set state transition:
        ``UPDATE publication_attempts SET state = to_state, ... WHERE id =
        attempt_id AND state = from_state``.

        Returns ``True`` iff exactly one row was updated, ``False`` for an
        already-transitioned or nonexistent row — a normal CAS miss, which
        this method does not raise for. The caller decides how to handle
        ``False``.
        """
        with self._session() as session:
            values: dict[str, Any] = {"state": to_state, **fields}
            result = session.execute(
                update(_PublicationAttemptModel)
                .where(
                    _PublicationAttemptModel.id == attempt_id,
                    _PublicationAttemptModel.state == from_state,
                )
                .values(**values)
            )
            updated = bool(result.rowcount == 1)
            if not updated:
                logger.info(
                    "CAS miss transitioning publication attempt {} ({} -> {}): "
                    "already transitioned or nonexistent.",
                    attempt_id,
                    from_state,
                    to_state,
                )
            return updated

    def publication_attempt_exists(self, article_id: int, refinery_id: str) -> bool:
        """Idempotency check: does a ``publication_attempts`` row already
        exist for this ``(article_id, refinery_id)`` pair?

        This — not a count — is the intended idempotency key for the Phase
        3b backfill: keying off ``COUNT(*) + 1`` for ``attempt_number``
        would make a re-run insert a second row instead of no-op'ing.
        """
        with self._session() as session:
            return bool(
                session.query(
                    session.query(_PublicationAttemptModel)
                    .filter_by(article_id=article_id, refinery_id=refinery_id)
                    .exists()
                ).scalar()
            )

    def get_publication_attempts_for_article(
        self, article_id: int
    ) -> list[PublicationAttemptView]:
        with self._session() as session:
            rows = (
                session.query(_PublicationAttemptModel)
                .filter(_PublicationAttemptModel.article_id == article_id)
                .order_by(_PublicationAttemptModel.attempt_number)
                .all()
            )
            return [_to_publication_attempt_view(r) for r in rows]

    # ------------------------------------------------------------------
    # editorial_decisions — append-only inserts (no CAS: genuinely
    # append-only, nothing transitions a decision in place)
    # ------------------------------------------------------------------

    def record_editorial_decision(
        self,
        *,
        decision_type: str,
        outcome: str,
        decided_at: datetime,
        article_id: int | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> EditorialDecisionView:
        with self._session() as session:
            row = _EditorialDecisionModel(
                article_id=article_id,
                decision_type=decision_type,
                outcome=outcome,
                reason=reason,
                decided_at=decided_at,
                details=details,
            )
            session.add(row)
            session.flush()
            view = _to_editorial_decision_view(row)
            logger.info(
                "Recorded editorial decision {} for article {} "
                "(decision_type={}, outcome={})",
                view.id,
                article_id,
                decision_type,
                outcome,
            )
            return view

    def editorial_decision_exists(self, article_id: int, decision_type: str) -> bool:
        """Idempotency check: does an ``editorial_decisions`` row already
        exist for this ``(article_id, decision_type)`` pair?"""
        with self._session() as session:
            return bool(
                session.query(
                    session.query(_EditorialDecisionModel)
                    .filter_by(article_id=article_id, decision_type=decision_type)
                    .exists()
                ).scalar()
            )

    def get_editorial_decisions_for_article(
        self, article_id: int
    ) -> list[EditorialDecisionView]:
        with self._session() as session:
            rows = (
                session.query(_EditorialDecisionModel)
                .filter(_EditorialDecisionModel.article_id == article_id)
                .order_by(_EditorialDecisionModel.decided_at)
                .all()
            )
            return [_to_editorial_decision_view(r) for r in rows]
