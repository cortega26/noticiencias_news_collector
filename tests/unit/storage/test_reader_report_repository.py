"""Storage tests for the reader-report reconciliation repository (plan 186).

Real SQLite via ``DatabaseManager`` so PKs, unique indexes, FK cascades and
CHECK constraints are exercised by the actual engine. The core promise on
trial: the same idempotency key reconciled N times yields exactly one
``reader_reports`` row and at most one contact row, with first-seen data
preserved and the email never copied onto the report row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from news_collector.contracts.reader_reports import ReaderReportPayload, ReportIdentity
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    ReaderReport,
    ReaderReportContact,
    ReaderReportDecision,
)
from news_collector.storage.reader_report_repository import (
    report_exists,
    upsert_reader_report,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
KEY = "3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
RESOLVED = ReportIdentity(
    status="resolved",
    canonical_url="https://noticiencias.com/posts/example",
    refinery_id="42",
    content_sha256="a" * 64,
    reason="matched_published_url",
)
UNRESOLVED = ReportIdentity(status="unresolved", reason="invalid_article_url")


def _payload(**overrides: object) -> ReaderReportPayload:
    fields: dict[str, object] = {
        "problem_type": "content_factual",
        "article_url": "https://noticiencias.com/posts/example",
        "description": "The dose is wrong.",
        "content_snippet": "10 mg",
        "evidence_url": "https://example.com/paper",
        "tech_browser": "Firefox",
        "tech_os": "Debian",
        "reporter_email": "reader@example.com",
    }
    fields.update(overrides)
    return ReaderReportPayload.model_validate(fields)


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "reports.db"})
    yield manager
    manager.close()


def _count(session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def _upsert(
    db_manager: DatabaseManager,
    *,
    payload: Optional[ReaderReportPayload] = None,
    identity: ReportIdentity = UNRESOLVED,
    reporter_email: Optional[str] = "reader@example.com",
    idempotency_key: str = KEY,
    commit: bool = True,
) -> tuple[ReaderReport, bool]:
    body = payload if payload is not None else _payload()
    with db_manager.SessionLocal() as session:
        report, created = upsert_reader_report(
            session,
            idempotency_key=idempotency_key,
            payload=body,
            submitted_at=NOW,
            identity=identity,
            reporter_email=reporter_email,
        )
        report_id = int(report.id)
        if commit:
            session.commit()
    with db_manager.SessionLocal() as session:
        loaded = session.get(ReaderReport, report_id)
        assert loaded is not None
        loaded.contact_email = (
            loaded.contact.email if loaded.contact is not None else None
        )
        _ = loaded.idempotency_key
    return loaded, created  # type: ignore[return-value]


class TestInsert:
    def test_insert_stamps_body_identity_and_submitted_at(
        self, db_manager: DatabaseManager
    ) -> None:
        report, created = _upsert(db_manager, identity=RESOLVED)

        assert created is True
        assert report.idempotency_key == KEY
        assert report.problem_type == "content_factual"
        assert report.article_url == "https://noticiencias.com/posts/example"
        assert report.description == "The dose is wrong."
        assert report.content_snippet == "10 mg"
        assert report.evidence_url == "https://example.com/paper"
        assert report.tech_browser == "Firefox"
        assert report.tech_os == "Debian"
        assert report.status == "new"
        assert report.resolution_status == "resolved"
        assert report.resolved_refinery_id == "42"
        assert report.resolved_content_sha256 == "a" * 64
        assert report.resolution_reason == "matched_published_url"
        # SQLite drops tzinfo on readback; the aware-UTC instant matches.
        assert report.submitted_at == datetime(2026, 10, 19, 12, 0)
        assert report.contact_purged_at is None

    def test_email_lands_only_on_the_contact_row(
        self, db_manager: DatabaseManager
    ) -> None:
        report, created = _upsert(db_manager, identity=RESOLVED)

        assert created is True
        assert report.contact is not None
        assert report.contact_email == "reader@example.com"
        # The report row carries no email column at all — the payload's
        # transport field reaches persistence only via the explicit
        # ``reporter_email`` argument, never by copying the body.
        assert not any(
            "email" in column.name for column in ReaderReport.__table__.columns
        )
        assert report.contact.report_id == report.id

    def test_no_email_argument_means_no_contact_row_despite_payload(
        self, db_manager: DatabaseManager
    ) -> None:
        # The payload carries reporter_email, but the caller passes none:
        # trust lands on the explicit argument, not on the body.
        report, created = _upsert(db_manager, payload=_payload(), reporter_email=None)

        assert created is True
        assert report.contact_email is None
        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReportContact) == 0

    def test_whitespace_email_argument_is_ignored(
        self, db_manager: DatabaseManager
    ) -> None:
        report, created = _upsert(db_manager, reporter_email="   ")

        assert created is True
        assert report.contact_email is None


class TestIdempotentUpsert:
    def test_same_key_twice_yields_one_row_and_no_contact_duplication(
        self, db_manager: DatabaseManager
    ) -> None:
        first, created_first = _upsert(db_manager)
        second, created_second = _upsert(db_manager)  # replay

        assert created_first is True
        assert created_second is False
        assert second.id == first.id
        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReport) == 1
            assert _count(session, ReaderReportContact) == 1
            assert _count(session, ReaderReportDecision) == 0

    def test_replay_keeps_first_seen_resolution_and_body(
        self, db_manager: DatabaseManager
    ) -> None:
        first, _ = _upsert(db_manager, identity=RESOLVED)
        first_created_at = first.created_at
        first_updated_at = first.updated_at

        # A re-run with different payload/identity must NOT rewrite history.
        winner, created = _upsert(
            db_manager,
            payload=_payload(description="tampered", evidence_url=None),
            identity=UNRESOLVED,
        )

        assert created is False
        assert winner.id == first.id
        assert winner.description == "The dose is wrong."
        assert winner.evidence_url == "https://example.com/paper"
        assert winner.resolution_status == "resolved"
        assert winner.resolved_refinery_id == "42"
        assert winner.resolution_reason == "matched_published_url"
        assert winner.created_at == first_created_at
        assert winner.updated_at == first_updated_at

    def test_select_then_insert_race_reports_duplicate(
        self, db_manager: DatabaseManager
    ) -> None:
        """A concurrent winner (unique index) is read, never rewritten."""
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReport(idempotency_key=KEY, problem_type="technical_site")
            )
            session.commit()

        report, created = _upsert(
            db_manager,
            payload=_payload(problem_type="content_factual"),
            identity=RESOLVED,
        )

        assert created is False
        assert report.problem_type == "technical_site"  # first-seen wins
        assert report.resolution_status == "unresolved"  # untouched
        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReport) == 1
            assert _count(session, ReaderReportContact) == 0

    def test_idempotency_key_is_unique_at_the_engine_level(
        self, db_manager: DatabaseManager
    ) -> None:
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReport(idempotency_key=KEY, problem_type="technical_site")
            )
            session.add(
                ReaderReport(idempotency_key=KEY, problem_type="technical_site")
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_report_exists_is_select_only(self, db_manager: DatabaseManager) -> None:
        with db_manager.SessionLocal() as session:
            assert report_exists(session, idempotency_key=KEY) is False
        _upsert(db_manager)
        with db_manager.SessionLocal() as session:
            assert report_exists(session, idempotency_key=KEY) is True
            assert report_exists(session, idempotency_key="not-stored-key") is False


class TestCascade:
    def test_contact_and_decisions_follow_the_report_out(
        self, db_manager: DatabaseManager
    ) -> None:
        report, _ = _upsert(db_manager)
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=report.id,
                    decision="accepted",
                    actor="editor@noticiencias.com",
                )
            )
            session.commit()

        with db_manager.SessionLocal() as session:
            session.delete(session.get(ReaderReport, report.id))
            session.commit()

        with db_manager.SessionLocal() as session:
            assert _count(session, ReaderReport) == 0
            assert _count(session, ReaderReportContact) == 0
            assert _count(session, ReaderReportDecision) == 0
