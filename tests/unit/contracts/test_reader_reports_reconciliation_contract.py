"""Contract tests for the plan 186 reconciliation shapes.

Pure outcome dataclasses shared by the R2 reader (infrastructure), the
reconciliation logic (logic/workflows), the repository (storage) and the
operator script — no DB, no I/O (LAW-B1).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from news_collector.contracts.reader_reports import (
    InvalidReportIntake,
    PersistOutcome,
    R2KeyPage,
    ReaderReportPayload,
    ReconciliationSummary,
    ReportOutcome,
    ValidReportIntake,
)

REPORT_KEY = "reports/2026-10-19/3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90.json"
WORKER_ID = "3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
SUBMITTED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _payload(**overrides: object) -> ReaderReportPayload:
    data: dict[str, object] = {
        "problem_type": "content_factual",
        "article_url": "https://noticiencias.com/posts/example",
    }
    data.update(overrides)
    return ReaderReportPayload(**data)


# ---------------------------------------------------------------------------
# R2KeyPage
# ---------------------------------------------------------------------------


def test_r2_key_page_defaults_and_key_tuple() -> None:
    page = R2KeyPage(keys=("reports/a.json", "reports/b.json"))
    assert page.keys == ("reports/a.json", "reports/b.json")
    assert page.next_cursor is None
    exhausted = R2KeyPage(keys=(), next_cursor="next-cursor-1")
    assert exhausted.next_cursor == "next-cursor-1"


def test_r2_key_page_is_frozen() -> None:
    page = R2KeyPage(keys=("reports/a.json",))
    with pytest.raises(FrozenInstanceError):
        page.keys = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ValidReportIntake / InvalidReportIntake
# ---------------------------------------------------------------------------


def test_valid_report_intake_full_shape() -> None:
    intake = ValidReportIntake(
        key=REPORT_KEY,
        idempotency_key=WORKER_ID,
        payload=_payload(),
        submitted_at=SUBMITTED_AT,
        environment="production",
        user_agent="Mozilla/5.0",
    )
    assert intake.key == REPORT_KEY
    assert intake.idempotency_key == WORKER_ID
    assert intake.payload.problem_type == "content_factual"
    assert intake.submitted_at == SUBMITTED_AT
    assert intake.environment == "production"
    assert intake.user_agent == "Mozilla/5.0"


def test_valid_report_intake_diag_fields_optional() -> None:
    intake = ValidReportIntake(
        key=REPORT_KEY,
        idempotency_key=WORKER_ID,
        payload=_payload(),
        submitted_at=SUBMITTED_AT,
    )
    assert intake.environment is None
    assert intake.user_agent is None


def test_valid_report_intake_is_frozen() -> None:
    intake = ValidReportIntake(
        key=REPORT_KEY,
        idempotency_key=WORKER_ID,
        payload=_payload(),
        submitted_at=SUBMITTED_AT,
    )
    with pytest.raises(FrozenInstanceError):
        intake.idempotency_key = "changed"  # type: ignore[misc]


def test_invalid_report_intake_defaults() -> None:
    bare = InvalidReportIntake(key=REPORT_KEY, reason="invalid_json")
    assert bare.detail == ""
    detailed = InvalidReportIntake(
        key=REPORT_KEY, reason="unknown_field", detail="extra_key"
    )
    assert detailed.detail == "extra_key"
    with pytest.raises(FrozenInstanceError):
        bare.reason = "rewritten"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PersistOutcome
# ---------------------------------------------------------------------------


def test_persist_outcome_statuses() -> None:
    created = PersistOutcome(status="created")
    assert created.status == "created"
    assert created.reason is None
    duplicate = PersistOutcome(status="duplicate")
    assert duplicate.status == "duplicate"
    db_failed = PersistOutcome(status="db_failed", reason="db_down")
    assert db_failed.status == "db_failed"
    assert db_failed.reason == "db_down"


def test_persist_outcome_reason_optional() -> None:
    assert PersistOutcome(status="duplicate").reason is None
    assert PersistOutcome(status="created", reason=None).status == "created"


# ---------------------------------------------------------------------------
# ReportOutcome
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "created",
        "duplicate",
        "invalid",
        "skipped",
        "fetch_failed",
        "persist_failed",
    ],
)
def test_report_outcome_status_vocabulary(status: str) -> None:
    outcome = ReportOutcome(key=REPORT_KEY, status=status)  # type: ignore[arg-type]
    assert outcome.status == status
    assert outcome.idempotency_key is None
    assert outcome.reason is None


def test_report_outcome_with_identifiers_and_reason() -> None:
    outcome = ReportOutcome(
        key=REPORT_KEY,
        status="invalid",
        idempotency_key=WORKER_ID,
        reason="unknown_field:visitor_ip",
    )
    assert outcome.idempotency_key == WORKER_ID
    assert outcome.reason == "unknown_field:visitor_ip"


def test_report_outcome_is_frozen() -> None:
    outcome = ReportOutcome(key=REPORT_KEY, status="created")
    with pytest.raises(FrozenInstanceError):
        outcome.status = "duplicate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ReconciliationSummary
# ---------------------------------------------------------------------------


def test_reconciliation_summary_defaults_are_zeroed() -> None:
    summary = ReconciliationSummary()
    assert summary.listed == 0
    assert summary.fetched == 0
    assert summary.created == 0
    assert summary.duplicates == 0
    assert summary.invalid == 0
    assert summary.skipped == 0
    assert summary.fetch_failed == 0
    assert summary.persist_failed == 0
    assert summary.truncated is False
    assert summary.fatal is None
    assert summary.outcomes == ()
    assert summary.processed == 0


def test_processed_is_complete_partition_counter() -> None:
    summary = ReconciliationSummary(
        listed=10,
        fetched=8,
        created=4,
        duplicates=3,
        invalid=1,
        skipped=2,
        fetch_failed=0,
        persist_failed=0,
    )
    # created + duplicates + invalid + skipped + failures == fetched + skipped
    assert summary.processed == summary.fetched + summary.skipped
    assert summary.processed == 10


def test_processed_counts_failure_buckets_too() -> None:
    summary = ReconciliationSummary(
        listed=3,
        fetched=3,
        created=0,
        duplicates=0,
        invalid=0,
        skipped=0,
        fetch_failed=2,
        persist_failed=1,
    )
    assert summary.processed == 3


def test_reconciliation_summary_is_mutable_accumulator() -> None:
    summary = ReconciliationSummary()
    summary.created += 1
    summary.listed += 5
    summary.truncated = True
    summary.fatal = "list_failed:RuntimeError"
    summary.outcomes = (
        ReportOutcome(key=REPORT_KEY, status="created", idempotency_key=WORKER_ID),
    )
    assert summary.created == 1
    assert summary.listed == 5
    assert summary.truncated is True
    assert summary.fatal is not None
    assert summary.outcomes[0].status == "created"


def test_summary_counters_do_not_include_listed_in_processed() -> None:
    summary = ReconciliationSummary(listed=100)
    assert summary.processed == 0
