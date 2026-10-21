"""Storage tests for the plan-187 reader-report decision repository.

Real SQLite via ``DatabaseManager`` so the CHECK constraints, the audit
row order, the CAS behavior and the one-transaction coupling are exercised
by the actual engine. The core promises on trial:

- one admin action = one transaction (CAS'd status + append-only row),
- a retried POST with the identical payload writes nothing (replay),
- a lost race raises ``StaleReportStateConflict`` instead of corrupting
  the audit trail, and
- contact rows are never touched by decision writes (plan 185 privacy).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import func, select, update

from news_collector.contracts.reader_reports import (
    PlannedDecision,
    ReportDecisionRequest,
)
from news_collector.logic.workflows import report_decisions as decision_rules
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    ReaderReport,
    ReaderReportContact,
    ReaderReportDecision,
)
from news_collector.storage.report_decision_repository import (
    StaleReportStateConflict,
    apply_report_decision,
    build_decision_context,
    duplicate_target_exists,
    list_report_decisions,
    load_reader_report,
)

NOW = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
NOTES = "la dosis del metformina está mal"


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "reports.db"})
    yield manager
    manager.close()


def _request(**overrides: object) -> ReportDecisionRequest:
    fields: dict[str, object] = {"actor": "alaria", "notes": NOTES}
    fields.update(overrides)
    return ReportDecisionRequest.model_validate(fields)


def _plan(session, report: ReaderReport, request: ReportDecisionRequest):
    """The honest plan path: repository context -> pure rules."""
    context = build_decision_context(session, report, request)
    return decision_rules.plan_decision(context, request)


def _seed_report(
    db_manager: DatabaseManager,
    *,
    key: str = "idem-1",
    status: str = "new",
    with_contact: bool = False,
) -> int:
    with db_manager.SessionLocal() as session:
        report = ReaderReport(
            idempotency_key=key,
            problem_type="content_factual",
            status=status,
        )
        if with_contact:
            report.contact = ReaderReportContact(email="reader@example.com")
        session.add(report)
        session.commit()
        return int(report.id)


def _count(session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


# ---------------------------------------------------------------------------
# SELECT helpers the rules consume
# ---------------------------------------------------------------------------


class TestLoadAndReference:
    def test_load_reader_report_finds_the_fresh_row(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)

        with db_manager.SessionLocal() as session:
            loaded = load_reader_report(session, report_id)
            assert loaded is not None
            assert loaded.id == report_id
            assert loaded.status == "new"

    def test_load_reader_report_missing_id_is_none(
        self, db_manager: DatabaseManager
    ) -> None:
        _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            assert load_reader_report(session, 4242) is None

    def test_duplicate_target_exists_follows_the_table(
        self, db_manager: DatabaseManager
    ) -> None:
        target_id = _seed_report(db_manager, key="idem-2")

        with db_manager.SessionLocal() as session:
            assert duplicate_target_exists(session, target_id) is True
            assert duplicate_target_exists(session, 9999) is False


class TestBuildContext:
    def test_exact_replay_payload_matches_the_existing_row(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager, status="no_action")
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=report_id,
                    decision="no_action",
                    actor="alaria",
                    notes=NOTES,
                )
            )
            session.commit()
            existing = load_reader_report(session, report_id)
            assert existing is not None

            request = _request(kind="decision", decision="no_action")
            context = build_decision_context(session, existing, request)
            assert context.replayed_decision_id is not None

    def test_changed_notes_do_not_replay(self, db_manager: DatabaseManager) -> None:
        report_id = _seed_report(db_manager, status="no_action")
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=report_id,
                    decision="no_action",
                    actor="alaria",
                    notes="otra cosa",
                )
            )
            session.commit()
            report = load_reader_report(session, report_id)
            assert report is not None

            request = _request(kind="decision", decision="no_action")
            context = build_decision_context(session, report, request)
            assert context.replayed_decision_id is None

    def test_triage_request_never_matches_a_decision_row(
        self, db_manager: DatabaseManager
    ) -> None:
        # The triage echo carries decision=None while every persisted row has
        # a non-null decision (CHECK constraint), so a triage can never be
        # a replay even with identical actor/notes.
        report_id = _seed_report(db_manager, status="triaged")
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=report_id,
                    decision="no_action",
                    actor="alaria",
                    notes=NOTES,
                )
            )
            session.commit()
            report = load_reader_report(session, report_id)
            assert report is not None

            triage = _request(kind="triage")
            context = build_decision_context(session, report, triage)
            assert context.replayed_decision_id is None
            assert context.duplicate_of_exists is None

    def test_duplicate_reference_not_requested_leaves_exists_unset(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            context = build_decision_context(session, report, _request())
            assert context.duplicate_of_exists is None

    def test_duplicate_reference_is_checked_against_other_reports(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        target_id = _seed_report(db_manager, key="idem-2")

        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            existing = build_decision_context(
                session,
                report,
                _request(
                    kind="decision",
                    decision="duplicate",
                    duplicate_of_report_id=target_id,
                ),
            )
            assert existing.duplicate_of_exists is True

            missing = build_decision_context(
                session,
                report,
                _request(
                    kind="decision", decision="duplicate", duplicate_of_report_id=9999
                ),
            )
            assert missing.duplicate_of_exists is False


# ---------------------------------------------------------------------------
# Append-only history
# ---------------------------------------------------------------------------


class TestListDecisions:
    def test_lists_all_rows_oldest_first_with_id_tiebreak(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager, status="no_action")
        with db_manager.SessionLocal() as session:
            for decision, notes in (
                ("no_action", "primera"),
                ("rejected", "segunda"),
                ("accepted", "tercera"),
            ):
                session.add(
                    ReaderReportDecision(
                        report_id=report_id,
                        decision=decision,
                        actor="alaria",
                        notes=notes,
                    )
                )
            session.commit()

            history = list_report_decisions(session, report_id)
            assert [int(row.id) for row in history] == sorted(
                int(row.id) for row in history
            )
            assert [row.decision for row in history] == [
                "no_action",
                "rejected",
                "accepted",
            ]

    def test_scope_is_only_this_report(self, db_manager: DatabaseManager) -> None:
        other_id = _seed_report(db_manager, key="idem-2")
        mine_id = _seed_report(db_manager, status="rejected")
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=other_id, decision="no_action", actor="alaria"
                )
            )
            session.commit()

            assert list_report_decisions(session, mine_id) == []


# ---------------------------------------------------------------------------
# One transaction: CAS + append
# ---------------------------------------------------------------------------


class TestApplyTriage:
    def test_triage_updates_status_and_appends_no_row(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            planned = _plan(session, report, _request(kind="triage"))
            assert planned.next_status == "triaged"
            assert planned.insert_decision_row is False

            result = apply_report_decision(session, planned)
            session.commit()

            assert result.inserted_decision is None
            assert result.replayed_decision_id is None
            assert result.report.status == "triaged"

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportDecision) == 0
            row = session.get(ReaderReport, report_id)
            assert row is not None
            assert row.status == "triaged"


class TestApplyDecision:
    def test_no_action_appends_row_and_sets_status(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            planned = _plan(
                session, report, _request(kind="decision", decision="no_action")
            )

            result = apply_report_decision(session, planned)
            session.commit()

            inserted = result.inserted_decision
            assert inserted is not None
            assert inserted.decision == "no_action"
            assert inserted.actor == "alaria"
            assert inserted.notes == NOTES
            assert inserted.duplicate_of_report_id is None
            assert inserted.report_id == report_id
            assert result.replayed_decision_id is None

        with db_manager.SessionLocal() as session:
            row = session.get(ReaderReport, report_id)
            assert row is not None
            assert row.status == "no_action"
            assert _count(session, ReaderReportDecision) == 1

    def test_accepted_persists_the_correction_evidence(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            planned = _plan(
                session,
                report,
                _request(
                    kind="decision",
                    decision="accepted",
                    corrected_at=NOW,
                    correction_summary="la dosis era 1 mg",
                ),
            )
            result = apply_report_decision(session, planned)
            session.commit()
            assert result.inserted_decision is not None

        # Fresh session readback (identity map would echo the input object).
        with db_manager.SessionLocal() as session:
            row = session.get(ReaderReportDecision, result.inserted_decision.id)
            assert row is not None
            assert row.corrected_at == datetime(2026, 10, 20, 9, 30)
            assert row.correction_summary == "la dosis era 1 mg"

            report = session.get(ReaderReport, report_id)
            assert report is not None
            assert report.status == "accepted"

    def test_duplicate_row_carries_the_reference(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        target_id = _seed_report(db_manager, key="idem-2")
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            planned = _plan(
                session,
                report,
                _request(
                    kind="decision",
                    decision="duplicate",
                    duplicate_of_report_id=target_id,
                ),
            )
            assert planned.duplicate_of_report_id == target_id

            result = apply_report_decision(session, planned)
            session.commit()
            inserted = result.inserted_decision
            assert inserted is not None
            assert inserted.duplicate_of_report_id == target_id

        with db_manager.SessionLocal() as session:
            row = session.get(ReaderReport, report_id)
            assert row is not None
            assert row.status == "duplicate"

    def test_redecision_appends_a_new_row_and_moves_the_status(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            first = apply_report_decision(
                session,
                _plan(session, report, _request(kind="decision", decision="no_action")),
            )
            session.commit()
            assert first.inserted_decision is not None
            first_row_id = int(first.inserted_decision.id)

        with db_manager.SessionLocal() as session:
            row = load_reader_report(session, report_id)
            assert row is not None
            second = apply_report_decision(
                session,
                _plan(session, row, _request(kind="decision", decision="rejected")),
            )
            session.commit()
            assert second.inserted_decision is not None
            assert int(second.inserted_decision.id) != first_row_id

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportDecision) == 2
            report = session.get(ReaderReport, report_id)
            assert report is not None
            assert report.status == "rejected"
            history = list_report_decisions(session, report_id)
            assert [row.decision for row in history] == ["no_action", "rejected"]

    def test_exact_replay_writes_nothing_and_returns_current_state(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            request = _request(kind="decision", decision="no_action")
            first = apply_report_decision(session, _plan(session, report, request))
            session.commit()
            assert first.inserted_decision is not None
            first_row_id = int(first.inserted_decision.id)

        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            context = build_decision_context(session, report, request)
            planned = decision_rules.plan_decision(context, request)
            assert context.replayed_decision_id == first_row_id
            assert planned.next_status is None
            assert planned.insert_decision_row is False

            replayed = apply_report_decision(session, planned)
            session.commit()

            assert replayed.inserted_decision is None
            assert replayed.replayed_decision_id == first_row_id
            assert replayed.report.status == "no_action"  # CURRENT state

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportDecision) == 1

    def test_contact_row_is_untouched_by_decision_writes(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager, with_contact=True)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            apply_report_decision(
                session, _plan(session, report, _request(kind="triage"))
            )
            apply_report_decision(
                session,
                _plan(session, report, _request(kind="decision", decision="no_action")),
            )
            session.commit()

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportContact) == 1
            contact = session.get(ReaderReportContact, 1)
            assert contact is not None
            assert contact.email == "reader@example.com"
            report = session.get(ReaderReport, report_id)
            assert report is not None
            assert report.contact_purged_at is None


class TestApplyConflicts:
    def test_stale_current_status_raises_and_writes_nothing(
        self, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            report = load_reader_report(session, report_id)
            assert report is not None
            planned = _plan(
                session, report, _request(kind="decision", decision="no_action")
            )
            assert planned.current_status == "new"

            # Simulate the concurrent change: the report is no longer 'new'
            # when the CAS runs, so no audit row may appear.
            session.execute(
                update(ReaderReport)
                .where(ReaderReport.id == report_id)
                .values(status="triaged")
            )
            with pytest.raises(StaleReportStateConflict) as exc_info:
                apply_report_decision(session, planned)

            assert exc_info.value.expected_status == "new"
            assert exc_info.value.report_id == report_id
            session.rollback()

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportDecision) == 0
            row = session.get(ReaderReport, report_id)
            assert row is not None
            assert row.status == "new"

    def test_apply_refuses_a_missing_report(self, db_manager: DatabaseManager) -> None:
        fabricated = PlannedDecision(
            report_id=9999,
            action="decision",
            current_status="new",
            next_status="no_action",
            insert_decision_row=True,
            decision="no_action",
            actor="alaria",
            notes=NOTES,
        )
        with db_manager.SessionLocal() as session:
            with pytest.raises(ValueError, match="9999"):
                apply_report_decision(session, fabricated)

        _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            with pytest.raises(ValueError, match="9999"):
                apply_report_decision(session, fabricated)

    def test_apply_never_writes_closed(self, db_manager: DatabaseManager) -> None:
        # Plan 188 owns closure; even a hand-crafted plan cannot route a
        # status change to 'closed' through the apply path.
        fabricated = PlannedDecision(
            report_id=1,
            action="decision",
            current_status="new",
            next_status="closed",
            insert_decision_row=False,
            actor="alaria",
            notes=NOTES,
        )
        _seed_report(db_manager)
        with db_manager.SessionLocal() as session:
            with pytest.raises(ValueError, match="closed"):
                apply_report_decision(session, fabricated)

        with db_manager.SessionLocal() as session:
            row = session.get(ReaderReport, 1)
            assert row is not None
            assert row.status == "new"
