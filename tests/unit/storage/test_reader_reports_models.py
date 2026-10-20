"""Storage tests for reader reports (plan 185).

Uses a real SQLite database through ``DatabaseManager`` so PKs, CHECK
constraints, unique indexes and FK cascades are exercised by the actual
engine (including the manager's ``PRAGMA foreign_keys=ON``).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    ReaderReport,
    ReaderReportContact,
    ReaderReportDecision,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "reports.db"})
    yield manager
    manager.close()


def _report(**overrides: object) -> ReaderReport:
    fields: dict[str, object] = {
        "idempotency_key": "delivery-1",
        "problem_type": "content_factual",
        "article_url": "https://noticiencias.com/posts/example",
        "description": "The dose is wrong.",
        "status": "new",
        "resolution_status": "unresolved",
    }
    fields.update(overrides)
    return ReaderReport(**fields)


def _count(session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


class TestRoundTrip:
    def test_report_contact_decision_round_trip(self, db_manager: DatabaseManager):
        with db_manager.SessionLocal() as session:
            report = _report(
                content_snippet="10 mg",
                evidence_url="https://example.com/paper",
                tech_browser="Firefox",
                tech_os="Linux",
                resolution_status="resolved",
                resolved_refinery_id="42",
                resolved_content_sha256="b" * 64,
                resolution_reason="matched_published_url",
            )
            session.add(report)
            session.flush()

            session.add(ReaderReportContact(report_id=report.id, email="r@example.com"))
            session.add(
                ReaderReportDecision(
                    report_id=report.id,
                    decision="accepted",
                    actor="editor@noticiencias.com",
                    notes="Fix the dose.",
                    corrected_at=NOW,
                    correction_summary="Corrected 10 mg to 1 mg.",
                    publication_ref="pr-123",
                    deploy_evidence="https://noticiencias.com/posts/example",
                    closed_at=NOW,
                )
            )
            session.commit()

            loaded = session.get(ReaderReport, report.id)
            assert loaded is not None
            assert loaded.status == "new"
            assert loaded.resolution_status == "resolved"
            assert loaded.resolved_refinery_id == "42"
            assert loaded.resolved_content_sha256 == "b" * 64
            assert loaded.created_at is not None
            assert loaded.updated_at is not None
            assert loaded.contact_purged_at is None

            assert loaded.contact is not None
            assert loaded.contact.email == "r@example.com"
            assert len(loaded.decisions) == 1
            decision = loaded.decisions[0]
            assert decision.decision == "accepted"
            assert decision.actor == "editor@noticiencias.com"
            assert decision.notes == "Fix the dose."
            assert decision.corrected_at is not None
            assert decision.correction_summary == "Corrected 10 mg to 1 mg."
            assert decision.publication_ref == "pr-123"
            assert decision.deploy_evidence == "https://noticiencias.com/posts/example"
            assert decision.created_at is not None
            assert decision.closed_at is not None

    def test_status_defaults_are_new_and_unresolved(self, db_manager: DatabaseManager):
        with db_manager.SessionLocal() as session:
            report = ReaderReport(
                idempotency_key="delivery-default",
                problem_type="technical_site",
            )
            session.add(report)
            session.commit()
            assert report.status == "new"
            assert report.resolution_status == "unresolved"


class TestIdempotencyAndUniqueness:
    def test_idempotency_key_is_unique(self, db_manager: DatabaseManager):
        with db_manager.SessionLocal() as session:
            session.add(_report(idempotency_key="same-delivery"))
            session.commit()

            session.add(_report(idempotency_key="same-delivery"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

    def test_contact_is_one_per_report(self, db_manager: DatabaseManager):
        with db_manager.SessionLocal() as session:
            report = _report()
            session.add(report)
            session.commit()

            session.add(ReaderReportContact(report_id=report.id, email="a@example.com"))
            session.commit()

            session.add(ReaderReportContact(report_id=report.id, email="b@example.com"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("status", "pending"),
            ("resolution_status", "maybe"),
        ],
    )
    def test_report_vocabulary_is_constrained(
        self, db_manager: DatabaseManager, field: str, value: str
    ):
        with db_manager.SessionLocal() as session:
            session.add(_report(**{field: value}))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

    def test_decision_vocabulary_is_constrained(self, db_manager: DatabaseManager):
        with db_manager.SessionLocal() as session:
            report = _report()
            session.add(report)
            session.commit()

            session.add(
                ReaderReportDecision(
                    report_id=report.id,
                    decision="maybe",
                    actor="editor",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


class TestPrivacySeparation:
    def test_email_exists_only_on_the_contact_table(self) -> None:
        assert "email" in ReaderReportContact.__table__.columns
        assert "email" not in ReaderReport.__table__.columns
        assert not hasattr(ReaderReport, "email")

    def test_purging_contact_keeps_report_and_decisions(
        self, db_manager: DatabaseManager
    ):
        with db_manager.SessionLocal() as session:
            report = _report()
            session.add(report)
            session.flush()
            session.add(ReaderReportContact(report_id=report.id, email="r@example.com"))
            session.add(
                ReaderReportDecision(
                    report_id=report.id,
                    decision="no_action",
                    actor="editor",
                )
            )
            session.commit()

            report.contact_purged_at = NOW
            session.delete(report.contact)
            session.commit()
            session.expire_all()

            loaded = session.get(ReaderReport, report.id)
            assert loaded is not None
            assert loaded.contact is None
            assert loaded.contact_purged_at is not None
            assert len(loaded.decisions) == 1


class TestCascade:
    def test_orm_delete_cascades_to_contact_and_decisions(
        self, db_manager: DatabaseManager
    ):
        with db_manager.SessionLocal() as session:
            report = _report()
            session.add(report)
            session.flush()
            session.add(ReaderReportContact(report_id=report.id, email="r@example.com"))
            session.add(
                ReaderReportDecision(
                    report_id=report.id,
                    decision="rejected",
                    actor="editor",
                )
            )
            session.commit()

            session.delete(report)
            session.commit()

            assert _count(session, ReaderReportContact) == 0
            assert _count(session, ReaderReportDecision) == 0

    def test_database_delete_cascades_without_orm_relationship_loading(
        self, db_manager: DatabaseManager
    ):
        """The FK's ON DELETE CASCADE must work on its own, not only via the
        ORM's ``delete-orphan`` cascade."""
        with db_manager.SessionLocal() as session:
            report = _report()
            session.add(report)
            session.flush()
            report_id = report.id
            session.add(ReaderReportContact(report_id=report_id, email="r@example.com"))
            session.add(
                ReaderReportDecision(
                    report_id=report_id,
                    decision="duplicate",
                    actor="editor",
                )
            )
            session.commit()

            session.execute(delete(ReaderReport).where(ReaderReport.id == report_id))
            session.commit()

            assert session.get(ReaderReport, report_id) is None
            assert _count(session, ReaderReportContact) == 0
            assert _count(session, ReaderReportDecision) == 0
