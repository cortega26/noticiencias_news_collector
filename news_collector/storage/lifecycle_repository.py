"""Lifecycle repository — typed read/write access to Phase 3a's durable
lineage tables (Plan 060 / Phase 3b; ``publication_events`` added in Phase
5b).

Exposes the two tables that carry state — ``publication_attempts``
(append-only inserts, a raw CAS transition, and the audited
``apply_publication_transition`` that writes the state change and its
``publication_events`` row in one transaction) and ``editorial_decisions``
(append-only inserts). Phase 5b also adds the explicit legal-transition map
and the read queries the reconciler needs (lookup by ``refinery_id``, stale
attempt scan).

``workflow_runs`` and ``workflow_stage_attempts`` still get no methods here:
their owning workflows (``collection_run_workflow``,
``publication_run_workflow``) manage those rows directly, and a read method
with no caller would be dead code. Whichever future phase first needs a
shared read adds it alongside that caller.

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
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, update

from news_collector.utils.logger import get_logger

from .models import PUBLICATION_EVENT_TYPE_VALUES
from .models import EditorialDecision as _EditorialDecisionModel
from .models import PublicationAttemptRecord as _PublicationAttemptModel
from .models import PublicationEvent as _PublicationEventModel

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
# Legal publication-attempt transitions (Plan 060 / Phase 5b)
# ---------------------------------------------------------------------------
#
# The state machine `publication_attempts.state` actually follows in this
# system. `PUBLISHING -> REJECTED`/`COMPLETED` are deliberately legal: a
# webhook callback can race ahead of `mark_article_published`'s own
# best-effort dual-write, leaving the row in PUBLISHING when the validation/
# deploy callback lands (see `test_reject_reads_actual_current_state_not_
# assumed_pr_created`, plan 3c). REJECTED/COMPLETED are terminal — a replay
# must never resurrect or overwrite a finished attempt. Any state not listed
# as a key (including unknown/future values) permits no transition.
LEGAL_PUBLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "PUBLISHING": frozenset({"PR_CREATED", "REJECTED", "COMPLETED"}),
    "PR_CREATED": frozenset({"REJECTED", "COMPLETED"}),
    "REJECTED": frozenset(),
    "COMPLETED": frozenset(),
}

PUBLICATION_ATTEMPT_TERMINAL_STATES = ("REJECTED", "COMPLETED")


def is_legal_publication_transition(from_state: str, to_state: str) -> bool:
    """Pure predicate: is ``from_state -> to_state`` a legal attempt
    transition? Unknown states permit nothing."""
    return to_state in LEGAL_PUBLICATION_TRANSITIONS.get(from_state, frozenset())


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
class PublicationEventView:
    """Read projection of one ``publication_events`` row."""

    id: int
    publication_attempt_id: int
    event_type: str
    occurred_at: datetime
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


def _to_publication_event_view(row: _PublicationEventModel) -> PublicationEventView:
    return PublicationEventView(
        id=row.id,
        publication_attempt_id=row.publication_attempt_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
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

    def apply_publication_transition(
        self,
        attempt_id: int,
        *,
        from_state: str,
        to_state: str,
        event_type: str,
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
        **fields: Any,
    ) -> bool:
        """Legality-checked CAS that appends its ``publication_events`` row
        in the same transaction as the state change (Plan 060 / Phase 5b).

        Returns ``True`` iff both the transition and the event were written.
        An unknown ``event_type`` or an illegal ``from_state -> to_state``
        pair is refused up front (logged, no write at all). A CAS miss is a
        normal ``False`` that appends no event, because nothing changed.
        """
        if not self._audited_transition_is_legal(
            attempt_id,
            from_state=from_state,
            to_state=to_state,
            event_type=event_type,
        ):
            return False
        return self._write_audited_transition(
            attempt_id,
            from_state=from_state,
            to_state=to_state,
            event_type=event_type,
            details=details,
            occurred_at=occurred_at,
            **fields,
        )

    @staticmethod
    def _audited_transition_is_legal(
        attempt_id: int,
        *,
        from_state: str,
        to_state: str,
        event_type: str,
    ) -> bool:
        if event_type not in PUBLICATION_EVENT_TYPE_VALUES:
            logger.error(
                "Refusing audited transition of attempt {} ({} -> {}): "
                "unknown event type {!r}.",
                attempt_id,
                from_state,
                to_state,
                event_type,
            )
            return False
        if not is_legal_publication_transition(from_state, to_state):
            logger.error(
                "Refusing illegal publication-attempt transition {} -> {} "
                "for attempt {} (event_type={!r}).",
                from_state,
                to_state,
                attempt_id,
                event_type,
            )
            return False
        return True

    def _write_audited_transition(
        self,
        attempt_id: int,
        *,
        from_state: str,
        to_state: str,
        event_type: str,
        details: dict[str, Any] | None,
        occurred_at: datetime | None,
        **fields: Any,
    ) -> bool:
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
            if result.rowcount != 1:
                logger.info(
                    "CAS miss in audited transition of publication attempt {} "
                    "({} -> {}): already transitioned or nonexistent.",
                    attempt_id,
                    from_state,
                    to_state,
                )
                return False
            session.add(
                _PublicationEventModel(
                    publication_attempt_id=attempt_id,
                    event_type=event_type,
                    occurred_at=occurred_at or datetime.now(timezone.utc),
                    details=details,
                )
            )
            return True

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

    def find_latest_publication_attempt_by_refinery_id(
        self, refinery_id: str
    ) -> PublicationAttemptView | None:
        """Newest attempt for a ``refinery_id`` (by attempt_number, then id —
        the same deterministic tie-break the dual-writes use), or ``None``.

        Used by callbacks that only know the webhook's ``publication_ids``
        (no ``article_id``) and by the Phase 5b reconciler.
        """
        with self._session() as session:
            row = (
                session.query(_PublicationAttemptModel)
                .filter(_PublicationAttemptModel.refinery_id == refinery_id)
                .order_by(
                    _PublicationAttemptModel.attempt_number.desc(),
                    _PublicationAttemptModel.id.desc(),
                )
                .first()
            )
            return _to_publication_attempt_view(row) if row is not None else None

    def list_stale_publication_attempts(
        self,
        *,
        older_than: datetime,
        state: str = "PR_CREATED",
        limit: int = 100,
    ) -> list[PublicationAttemptView]:
        """Attempts still in ``state`` whose ``started_at`` is strictly older
        than ``older_than``, oldest first (Phase 5b reconciler candidates)."""
        with self._session() as session:
            rows = (
                session.query(_PublicationAttemptModel)
                .filter(
                    _PublicationAttemptModel.state == state,
                    _PublicationAttemptModel.started_at < older_than,
                )
                .order_by(
                    _PublicationAttemptModel.started_at.asc(),
                    _PublicationAttemptModel.id.asc(),
                )
                .limit(limit)
                .all()
            )
            return [_to_publication_attempt_view(r) for r in rows]

    # ------------------------------------------------------------------
    # publication_events — append-only transition audit
    # ------------------------------------------------------------------

    def record_publication_event(
        self,
        publication_attempt_id: int,
        *,
        event_type: str,
        occurred_at: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> PublicationEventView:
        """Append one event row. Raises ``ValueError`` for an unknown event
        type — a programming error, same convention as an invalid enum.

        Callers that record an event *alongside* a state change must use
        :meth:`apply_publication_transition` instead, so the two writes stay
        atomic.
        """
        if event_type not in PUBLICATION_EVENT_TYPE_VALUES:
            raise ValueError(f"Unknown publication event type: {event_type!r}")
        with self._session() as session:
            row = _PublicationEventModel(
                publication_attempt_id=publication_attempt_id,
                event_type=event_type,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                details=details,
            )
            session.add(row)
            session.flush()
            return _to_publication_event_view(row)

    def get_publication_events_for_attempt(
        self, publication_attempt_id: int
    ) -> list[PublicationEventView]:
        with self._session() as session:
            rows = (
                session.query(_PublicationEventModel)
                .filter(
                    _PublicationEventModel.publication_attempt_id
                    == publication_attempt_id
                )
                .order_by(
                    _PublicationEventModel.occurred_at,
                    _PublicationEventModel.id,
                )
                .all()
            )
            return [_to_publication_event_view(r) for r in rows]

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
