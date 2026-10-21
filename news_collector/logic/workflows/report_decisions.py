"""Pure admin-transition rules for reader reports (plan 187).

Decides *whether* an admin action may be applied to a reader report and
what the resulting state must be. An input-only module (LAW-B4): every
fact that would require a database or network read arrives inside the
:class:`DecisionContext` the repository built (duplicate-target
existence, exact-duplicate replay match) — this module never imports
storage, network, or serving, and performs no I/O.

Transition law implemented here (plan 187):

- ``closed`` reports are locked: nothing changes through this surface
  (the status value itself only arrives with plan 188's closure flow —
  the refusal already exists so a later schema change cannot fight its
  way through an admin-route bug).
- ``kind="triage"`` is notes-only and may move ``new → triaged`` and
  nothing else; it never appends a decision row (the ``decision``
  column's CHECK admits only the four final kinds — plan 185 schema —
  and plan 187's migration adds exactly one column, so the triage's own
  audit is the report's ``status``/``updated_at``).
- ``kind="decision"`` requires a final kind; ``accepted`` requires
  ``corrected_at`` AND ``correction_summary`` (publication/deploy
  evidence checks are plan 188 work — acceptance here leaves the report
  in ``accepted``, never ``closed``); ``duplicate`` requires
  ``duplicate_of_report_id`` pointing at an OTHER, existing report.
- Re-decisions (a changed payload) are legal while the report is not
  closed and append a new row + set the new status. Nothing moves a
  report back to ``new`` — the four final kinds only ever set their own
  kind as the status; only the triage action reaches ``triaged``.
- Exact-duplicate payloads are replays: when the repository already
  holds an identical decision row for this report, the plan
  short-circuits to a no-op (no INSERT, no status change) and the
  caller returns the current state — audit conservation for retried
  admin POSTs.

Refusals raise :class:`ReportDecisionRuleViolation` with a stable
machine ``reason``; the serving adapter maps reasons onto typed 409/422
responses.
"""

from __future__ import annotations

from typing import Optional

from news_collector.contracts.reader_reports import (
    DecisionContext,
    PlannedDecision,
    ReportDecisionRequest,
)

# Stable refusal reasons (surfaced in HTTP details verbatim — the signal
# is the code, never user text).
VIOLATION_CLOSED_LOCKED = "closed_locked"
VIOLATION_UNKNOWN_CURRENT_STATUS = "unknown_current_status"
VIOLATION_EMPTY_ACTOR = "empty_actor"
VIOLATION_EMPTY_NOTES = "empty_notes"
VIOLATION_TRIAGE_EXTRA_FIELDS = "triage_extra_fields"
VIOLATION_TRIAGE_ONLY_FROM_NEW = "triage_only_from_new"
VIOLATION_MISSING_DECISION_KIND = "decision_missing"
VIOLATION_DECISION_EXTRA_FIELDS = "decision_extra_fields"
VIOLATION_ACCEPTED_MISSING_CORRECTION = "accepted_missing_correction"
VIOLATION_DUPLICATE_MISSING_REF = "duplicate_missing_ref"
VIOLATION_DUPLICATE_REF_NOT_APPLICABLE = "duplicate_ref_not_applicable"
VIOLATION_DUPLICATE_SELF_REFERENCE = "duplicate_self_reference"
VIOLATION_DUPLICATE_TARGET_MISSING = "duplicate_target_missing"

# The report status plan 188 introduces; nothing may mutate through it.
_STATUS_CLOSED = "closed"
# Statuses decisions may never produce. The four final kinds only set
# their own kind; 'triaged' is producible, but only via the triage
# action from 'new'. 'new' itself is unreachable from any action.
_FORBIDDEN_RESULT_STATUSES = frozenset({"new"})

# The known reader_reports.status vocabulary — mirrors the CHECK in
# storage/models.py (plan 185) so unknown values mean schema drift and
# are refused loudly instead of guessed.
_KNOWN_STATUSES = frozenset(
    {"new", "triaged", "accepted", "rejected", "duplicate", "no_action"}
)


class ReportDecisionRuleViolation(Exception):
    """A rule refusal with a stable machine ``reason``.

    ``detail`` is the human suffix for operators; it carries request/
    state context (ids, status values) rather than raw user quotes.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _planned(
    context: DecisionContext,
    *,
    request: ReportDecisionRequest,
    next_status: Optional[str],
    insert_decision_row: bool,
) -> PlannedDecision:
    """Assemble the authorized plan (single construction point)."""
    planned = PlannedDecision(
        report_id=context.report_id,
        action=request.kind,
        current_status=context.current_status,
        next_status=next_status,
        insert_decision_row=insert_decision_row,
        decision=request.decision,
        actor=request.actor,
        notes=request.notes,
        corrected_at=request.corrected_at,
        correction_summary=request.correction_summary,
        duplicate_of_report_id=request.duplicate_of_report_id,
        replayed_decision_id=context.replayed_decision_id,
    )
    if (
        planned.next_status is not None
        and planned.next_status in _FORBIDDEN_RESULT_STATUSES
    ):  # pragma: no cover — invariant guard, unreachable by construction
        raise ReportDecisionRuleViolation(
            VIOLATION_UNKNOWN_CURRENT_STATUS,
            f"an admin action may never set status {planned.next_status!r}",
        )
    return planned


def plan_decision(  # noqa: C901
    context: DecisionContext,
    request: ReportDecisionRequest,
) -> PlannedDecision:
    """Plan one admin action against one report; refuses illegal ones.

    The context must have been built in the same transaction that applies
    the returned plan; the CAS update in
    ``storage/report_decision_repository.apply_report_decision`` is what
    makes the plan safe against concurrent status changes.
    """
    # 1. Audit discipline: actor and notes must be present (the transport
    # contract enforces this too; direct repository callers may bypass it).
    if not request.actor.strip():
        raise ReportDecisionRuleViolation(
            VIOLATION_EMPTY_ACTOR, "actor is required for every admin action"
        )
    if not request.notes.strip():
        raise ReportDecisionRuleViolation(
            VIOLATION_EMPTY_NOTES, "notes are required for every admin action"
        )

    # 2. closed is unchangeable — refuse before anything else looks at the
    # status (plan 188 owns the closure flow; this surface never reaches it).
    if context.current_status == _STATUS_CLOSED:
        raise ReportDecisionRuleViolation(
            VIOLATION_CLOSED_LOCKED,
            "report is closed; no admin action may change it",
        )

    # 3. Unknown statuses mean schema drift — refuse loudly, never guess.
    if context.current_status not in _KNOWN_STATUSES:
        raise ReportDecisionRuleViolation(
            VIOLATION_UNKNOWN_CURRENT_STATUS,
            f"current status {context.current_status!r} is not a known report status",
        )

    # 4. Exact-duplicate replay: the repository matched an existing row
    # with the identical payload — no-op, return the current state.
    if context.replayed_decision_id is not None:
        return _planned(
            context, request=request, next_status=None, insert_decision_row=False
        )

    # 5. Triage: notes-only, new → triaged, and nothing else.
    if request.kind == "triage":
        if (
            request.decision is not None
            or request.corrected_at is not None
            or request.correction_summary is not None
            or request.duplicate_of_report_id is not None
        ):
            raise ReportDecisionRuleViolation(
                VIOLATION_TRIAGE_EXTRA_FIELDS,
                "triage is notes-only; decision fields must be absent",
            )
        if context.current_status != "new":
            raise ReportDecisionRuleViolation(
                VIOLATION_TRIAGE_ONLY_FROM_NEW,
                f"a triage may only move a 'new' report (found {context.current_status!r})",
            )
        return _planned(
            context,
            request=request,
            next_status="triaged",
            insert_decision_row=False,
        )

    # 6. Decision: a final kind is required (never defaults silently).
    decision = request.decision
    if decision is None:
        raise ReportDecisionRuleViolation(
            VIOLATION_MISSING_DECISION_KIND,
            "kind='decision' requires a decision value",
        )

    if decision != "accepted" and (
        request.corrected_at is not None or request.correction_summary is not None
    ):
        raise ReportDecisionRuleViolation(
            VIOLATION_DECISION_EXTRA_FIELDS,
            "corrected_at/correction_summary belong to 'accepted' decisions",
        )

    if decision == "accepted" and (
        request.corrected_at is None or request.correction_summary is None
    ):
        raise ReportDecisionRuleViolation(
            VIOLATION_ACCEPTED_MISSING_CORRECTION,
            "an accepted decision requires corrected_at and correction_summary "
            "(publication/deploy evidence checks remain plan 188's)",
        )

    if decision == "duplicate":
        if request.duplicate_of_report_id is None:
            raise ReportDecisionRuleViolation(
                VIOLATION_DUPLICATE_MISSING_REF,
                "a duplicate decision requires duplicate_of_report_id",
            )
        if request.duplicate_of_report_id == context.report_id:
            raise ReportDecisionRuleViolation(
                VIOLATION_DUPLICATE_SELF_REFERENCE,
                "a report cannot duplicate itself",
            )
        if context.duplicate_of_exists is not True:
            raise ReportDecisionRuleViolation(
                VIOLATION_DUPLICATE_TARGET_MISSING,
                "duplicate_of_report_id must point at an existing other report",
            )
    elif request.duplicate_of_report_id is not None:
        raise ReportDecisionRuleViolation(
            VIOLATION_DUPLICATE_REF_NOT_APPLICABLE,
            "duplicate_of_report_id belongs to 'duplicate' decisions",
        )

    return _planned(
        context,
        request=request,
        next_status=decision,
        insert_decision_row=True,
    )
