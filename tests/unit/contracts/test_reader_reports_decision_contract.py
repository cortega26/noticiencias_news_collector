"""Contract tests for the plan-187 admin decision shapes.

Covers the transport-level discipline of ``ReportDecisionRequest`` and
the DTO family: trimming, refusal of blank audit fields, field caps,
privacy guarantees (NO reporter email on list items), and the pure
cross-module context/plan dataclasses.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.contracts.reader_reports import (
    REPORT_ACTION_KIND_VALUES,
    REPORT_DECISION_KIND_VALUES,
    AdminReaderReportDecisionResult,
    AdminReaderReportDetail,
    AdminReaderReportEnvelope,
    AdminReaderReportFilters,
    AdminReaderReportItem,
    DecisionContext,
    PlannedDecision,
    ReaderReportDecisionItem,
    ReportDecisionRequest,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ReportDecisionRequest
# ---------------------------------------------------------------------------


def test_request_defaults_to_decision_kind() -> None:
    request = ReportDecisionRequest.model_validate(
        {"actor": "editor", "notes": "revisado"}
    )
    assert request.kind == "decision"
    assert request.decision is None
    assert request.corrected_at is None
    assert request.duplicate_of_report_id is None


def test_request_trims_actor_and_notes() -> None:
    request = ReportDecisionRequest.model_validate(
        {"actor": "  editor  ", "notes": " \tcon contexto\t "}
    )
    assert request.actor == "editor"
    assert request.notes == "con contexto"


def test_request_strip_works_for_correction_summary() -> None:
    request = ReportDecisionRequest.model_validate(
        {
            "actor": "editor",
            "notes": "n",
            "decision": "accepted",
            "correction_summary": "  valor fijado  ",
        }
    )
    assert request.correction_summary == "valor fijado"


@pytest.mark.parametrize("field", ["actor", "notes"])
def test_request_refuses_blank_audit_fields(field: str) -> None:
    payload: dict[str, str] = {"actor": "editor", "notes": "notas relevantes"}
    payload[field] = "   "
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate(payload)


def test_request_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate(
            {"actor": "editor", "notes": "n", "reporter_email": "x@example.com"}
        )


def test_request_rejects_non_positive_duplicate_of() -> None:
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate(
            {
                "actor": "editor",
                "notes": "n",
                "decision": "duplicate",
                "duplicate_of_report_id": 0,
            }
        )


def test_action_kind_constants() -> None:
    assert REPORT_ACTION_KIND_VALUES == ("triage", "decision")
    assert REPORT_DECISION_KIND_VALUES == (
        "accepted",
        "rejected",
        "duplicate",
        "no_action",
    )


def test_request_kind_literal_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate(
            {"actor": "editor", "notes": "n", "kind": "closure"}
        )


def test_request_caps_actor_and_notes() -> None:
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate({"actor": "x" * 201, "notes": "n"})
    with pytest.raises(ValidationError):
        ReportDecisionRequest.model_validate({"actor": "editor", "notes": "x" * 5001})


# ---------------------------------------------------------------------------
# DTO family / privacy guarantees
# ---------------------------------------------------------------------------


def test_decision_item_round_trip() -> None:
    item = ReaderReportDecisionItem.model_validate(
        {
            "id": 9,
            "decision": "accepted",
            "actor": "editor",
            "notes": "corrección aplicada",
            "corrected_at": NOW.isoformat(),
            "correction_summary": "corregido",
            "publication_ref": None,
            "deploy_evidence": None,
            "duplicate_of_report_id": None,
            "created_at": NOW.isoformat(),
            "closed_at": None,
        }
    )
    assert item.id == 9
    assert item.decision == "accepted"
    assert item.publication_ref is None


def test_list_item_has_no_reporter_email_field() -> None:
    # Privacy: the FIELD does not exist, so no filter bug can leak email.
    fields = set(AdminReaderReportItem.model_fields)
    assert "reporter_email" not in fields


def test_detail_declares_conditional_email_field() -> None:
    fields = set(AdminReaderReportDetail.model_fields)
    assert "reporter_email" in fields
    assert "decisions" in fields


def test_detail_requires_status_vocabulary() -> None:
    with pytest.raises(ValidationError):
        AdminReaderReportDetail.model_validate(
            {
                "id": 1,
                "status": "closed",  # plan 188's value must not render yet
                "resolution_status": "unresolved",
                "problem_type": "content_factual",
            }
        )


def test_pagination_shape() -> None:
    request = ReportDecisionRequest.model_validate({"actor": "a", "notes": "n"})
    item = AdminReaderReportItem(
        id=1,
        status="new",
        resolution_status="unresolved",
        problem_type="content_factual",
    )
    envelope = AdminReaderReportEnvelope(
        data=[item],
        pagination={
            "next_cursor": None,
            "has_more": False,
            "page_size": 20,
            "returned": 1,
        },
        filters=AdminReaderReportFilters(),
        meta={},
    )
    assert envelope.pagination.returned == 1
    assert envelope.data[0].decision_count == 0
    assert request.kind == "decision"


def test_filters_default_to_all() -> None:
    filters = AdminReaderReportFilters.model_validate({})
    assert filters.status == "all"
    assert filters.resolution == "all"
    assert filters.problem_type == "all"


def test_filters_reject_unknown_status() -> None:
    with pytest.raises(ValidationError):
        AdminReaderReportFilters.model_validate({"status": "wobbly"})


def test_decision_result_shape() -> None:
    item = AdminReaderReportItem(
        id=1,
        status="triaged",
        resolution_status="unresolved",
        problem_type="technical_site",
    )
    detail = AdminReaderReportDetail(**item.model_dump(), reporter_email=None)
    result = AdminReaderReportDecisionResult(
        report=detail,
        action="triage",
        inserted_decision_id=None,
        replayed=False,
        replayed_decision_id=None,
    )
    assert result.action == "triage"
    assert result.replayed is False


def test_result_rejects_unknown_action() -> None:
    item = AdminReaderReportItem(
        id=1,
        status="new",
        resolution_status="unresolved",
        problem_type="content_factual",
    )
    detail = AdminReaderReportDetail(**item.model_dump())
    with pytest.raises(ValidationError):
        AdminReaderReportDecisionResult(report=detail, action="closure")


# ---------------------------------------------------------------------------
# Pure cross-module dataclasses
# ---------------------------------------------------------------------------


def test_decision_context_frozen() -> None:
    context = DecisionContext(
        report_id=7,
        current_status="new",
        duplicate_of_exists=True,
        replayed_decision_id=None,
    )
    with pytest.raises(AttributeError):
        context.current_status = "closed"  # type: ignore[misc]


def test_planned_decision_defaults() -> None:
    planned = PlannedDecision(
        report_id=7,
        action="decision",
        current_status="new",
        next_status="rejected",
        insert_decision_row=True,
        decision="rejected",
        actor="editor",
        notes="nothing",
    )
    assert planned.corrected_at is None
    assert planned.replayed_decision_id is None
