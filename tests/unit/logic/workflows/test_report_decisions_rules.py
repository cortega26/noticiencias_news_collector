"""Transition-matrix tests for the plan-187 decision rules.

The rules are pure (LAW-B4): every refusal and every authorized plan is
asserted against constructed ``DecisionContext`` inputs — no database,
no network, no serving. Every stable reason appears here with a direct
assert about the intended plan (no assertion-free tests).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from news_collector.contracts.reader_reports import (
    DecisionContext,
    ReportDecisionRequest,
)
from news_collector.logic.workflows import report_decisions as rules

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _request(**overrides: object) -> ReportDecisionRequest:
    fields: dict[str, object] = {"actor": "editor", "notes": "reviso la fuente"}
    fields.update(overrides)
    return ReportDecisionRequest.model_validate(fields)


def _context(status: str = "new", **extras: object) -> DecisionContext:
    return DecisionContext(report_id=7, current_status=status, **extras)


# ---------------------------------------------------------------------------
# Authorized plans
# ---------------------------------------------------------------------------


def test_triage_moves_new_to_triaged_without_row() -> None:
    planned = rules.plan_decision(_context("new"), _request(kind="triage"))
    assert planned.action == "triage"
    assert planned.current_status == "new"
    assert planned.next_status == "triaged"
    # Triage appends NO decision row: the decision column's 185 CHECK
    # admits only the four final kinds; the migration stays one column.
    assert planned.insert_decision_row is False
    assert planned.decision is None
    assert planned.replayed_decision_id is None


@pytest.mark.parametrize("decision", ["accepted", "rejected", "duplicate", "no_action"])
def test_final_decision_sets_its_own_status(decision: str) -> None:
    context = _context("new", duplicate_of_exists=True)
    # Each kind carries only its own evidence; a duplicate reference on a
    # non-duplicate kind is refused (duplicate_ref_not_applicable), so the
    # payload is built per kind.
    request = _request(decision=decision)
    if decision == "accepted":
        request = _request(
            decision="accepted",
            corrected_at=NOW,
            correction_summary="corregido",
        )
    elif decision == "duplicate":
        request = _request(decision="duplicate", duplicate_of_report_id=3)
    planned = rules.plan_decision(context, request)
    assert planned.next_status == decision
    assert planned.insert_decision_row is True
    assert planned.current_status == "new"


def test_redecision_from_final_status_changes_status() -> None:
    # accepted → rejected with a CHANGED payload appends a row and moves
    # the status; 'closed' is the only locked state.
    planned = rules.plan_decision(_context("accepted"), _request(decision="rejected"))
    assert planned.next_status == "rejected"
    assert planned.insert_decision_row is True


def test_decision_from_triaged_is_legal() -> None:
    planned = rules.plan_decision(_context("triaged"), _request(decision="no_action"))
    assert planned.next_status == "no_action"
    assert planned.insert_decision_row is True


def test_duplicate_decision_appends_row_with_reference() -> None:
    planned = rules.plan_decision(
        _context("new", duplicate_of_exists=True),
        _request(decision="duplicate", duplicate_of_report_id=3),
    )
    assert planned.next_status == "duplicate"
    assert planned.insert_decision_row is True
    assert planned.duplicate_of_report_id == 3


def test_accepted_decision_requires_correction_fields_present() -> None:
    planned = rules.plan_decision(
        _context("triaged"),
        _request(
            decision="accepted",
            corrected_at=NOW,
            correction_summary="la dosis era 1 mg",
        ),
    )
    assert planned.next_status == "accepted"
    assert planned.corrected_at == NOW
    assert planned.correction_summary == "la dosis era 1 mg"


# ---------------------------------------------------------------------------
# Exact-duplicate replay
# ---------------------------------------------------------------------------


def test_exact_duplicate_replay_short_circuits_to_no_op() -> None:
    context = _context("new", replayed_decision_id=11)
    planned = rules.plan_decision(context, _request(decision="no_action"))
    assert planned.next_status is None
    assert planned.insert_decision_row is False
    assert planned.replayed_decision_id == 11
    # The request echo is preserved so the repository can log/answer with
    # the current state.
    assert planned.actor == "editor"
    assert planned.decision == "no_action"


def test_replay_even_beats_illegal_current_state() -> None:
    # A retried POST after a lost response must stay a no-op even if the
    # report meanwhile moved on.
    context = _context("no_action", replayed_decision_id=4)
    planned = rules.plan_decision(context, _request(decision="no_action"))
    assert planned.next_status is None
    assert planned.insert_decision_row is False


@pytest.mark.parametrize("status", ["triaged", "accepted"])
def test_replay_from_other_statuses_is_no_op(status: str) -> None:
    planned = rules.plan_decision(
        _context(status, replayed_decision_id=5), _request(decision="rejected")
    )
    assert planned.next_status is None
    assert planned.insert_decision_row is False


# ---------------------------------------------------------------------------
# Refusals — every stable reason
# ---------------------------------------------------------------------------


def _violation(context: DecisionContext, request: ReportDecisionRequest):
    with pytest.raises(rules.ReportDecisionRuleViolation) as exc_info:
        rules.plan_decision(context, request)
    return exc_info.value


def test_closed_is_locked_for_triage() -> None:
    violation = _violation(_context("closed"), _request(kind="triage"))
    assert violation.reason == rules.VIOLATION_CLOSED_LOCKED


def test_closed_is_locked_for_every_decision_kind() -> None:
    for decision in ("accepted", "rejected", "duplicate", "no_action"):
        request = _request(decision=decision, duplicate_of_report_id=2)
        violation = _violation(_context("closed"), request)
        assert violation.reason == rules.VIOLATION_CLOSED_LOCKED


def test_unknown_current_status_refused() -> None:
    violation = _violation(_context("mysterioso"), _request(decision="rejected"))
    assert violation.reason == rules.VIOLATION_UNKNOWN_CURRENT_STATUS


def test_empty_actor_refused() -> None:
    # The transport contract refuses a blank actor at validation time;
    # model_construct bypasses that refusal so the rules' own audit gate
    # is exercised directly (defense-in-depth for repository callers).
    raw = ReportDecisionRequest.model_construct(actor="", notes="n")
    violation = _violation(_context("new"), raw)
    assert violation.reason == rules.VIOLATION_EMPTY_ACTOR


def test_empty_notes_refused() -> None:
    raw = ReportDecisionRequest.model_construct(actor="editora", notes="")
    violation = _violation(_context("new"), raw)
    assert violation.reason == rules.VIOLATION_EMPTY_NOTES


def test_triage_refuses_decision_fields() -> None:
    for extras in (
        {"decision": "no_action"},
        {"corrected_at": NOW},
        {"correction_summary": "algo"},
        {"duplicate_of_report_id": 3},
    ):
        request = _request(kind="triage", **extras)
        violation = _violation(_context("new"), request)
        assert violation.reason == rules.VIOLATION_TRIAGE_EXTRA_FIELDS


@pytest.mark.parametrize(
    "status", ["triaged", "accepted", "duplicate", "rejected", "no_action"]
)
def test_triage_only_works_from_new(status: str) -> None:
    violation = _violation(_context(status), _request(kind="triage"))
    assert violation.reason == rules.VIOLATION_TRIAGE_ONLY_FROM_NEW


def test_decision_kind_missing_refused() -> None:
    violation = _violation(_context("new"), _request())
    assert violation.reason == rules.VIOLATION_MISSING_DECISION_KIND


def test_decision_extra_fields_refused_for_non_accepted() -> None:
    for extras in ({"corrected_at": NOW}, {"correction_summary": "algo"}):
        violation = _violation(_context("new"), _request(decision="rejected", **extras))
        assert violation.reason == rules.VIOLATION_DECISION_EXTRA_FIELDS


def test_accepted_requires_both_correction_fields() -> None:
    for extras in ({}, {"corrected_at": NOW}, {"correction_summary": "algo"}):
        request = _request(decision="accepted", **extras)
        violation = _violation(_context("new"), request)
        assert violation.reason == rules.VIOLATION_ACCEPTED_MISSING_CORRECTION


def test_duplicate_without_reference_refused() -> None:
    violation = _violation(_context("new"), _request(decision="duplicate"))
    assert violation.reason == rules.VIOLATION_DUPLICATE_MISSING_REF


def test_duplicate_of_self_refused() -> None:
    violation = _violation(
        _context("new"), _request(decision="duplicate", duplicate_of_report_id=7)
    )
    assert violation.reason == rules.VIOLATION_DUPLICATE_SELF_REFERENCE
    # 7 == context.report_id


def test_duplicate_target_missing_refused_on_false() -> None:
    violation = _violation(
        _context("new", duplicate_of_exists=False),
        _request(decision="duplicate", duplicate_of_report_id=99),
    )
    assert violation.reason == rules.VIOLATION_DUPLICATE_TARGET_MISSING


def test_duplicate_target_missing_refused_when_unchecked() -> None:
    violation = _violation(
        _context("new", duplicate_of_exists=None),
        _request(decision="duplicate", duplicate_of_report_id=99),
    )
    assert violation.reason == rules.VIOLATION_DUPLICATE_TARGET_MISSING


def test_duplicate_ref_not_applicable_for_other_kinds() -> None:
    violation = _violation(
        _context("new"), _request(decision="rejected", duplicate_of_report_id=3)
    )
    assert violation.reason == rules.VIOLATION_DUPLICATE_REF_NOT_APPLICABLE


def test_decisions_never_move_report_to_new_structurally() -> None:
    # The invariant guard: even a hand-crafted context cannot make a final
    # decision produce status 'new' — the four kinds only set their own kind.
    for decision in ("accepted", "rejected", "duplicate", "no_action"):
        request = _request(decision=decision)
        if decision == "accepted":
            request = _request(
                decision="accepted", corrected_at=NOW, correction_summary="s"
            )
        elif decision == "duplicate":
            request = _request(decision="duplicate", duplicate_of_report_id=2)
        planned = rules.plan_decision(
            _context("new", duplicate_of_exists=True), request
        )
        assert planned.next_status != "new"
