"""Pure reconciliation logic tests (plan 186).

No real network: the R2 feed is an injected stand-in. Idempotency is
proved against a real (temporary) SQLite database through the plan 185
resolver and the real repository, so row/contact counts and constraints
are engine-verified, not asserted against mocks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence

import pytest
from sqlalchemy import func, select

from news_collector.contracts.reader_reports import (
    InvalidReportIntake,
    PersistOutcome,
    R2KeyPage,
    ReportIdentity,
    ValidReportIntake,
)
from news_collector.infrastructure.r2_client import R2ObjectMissing
from news_collector.logic.workflows.reader_reports import (
    REASON_RESOLVED,
    resolve_report_identity,
)
from news_collector.logic.workflows.report_reconciliation import (
    REASON_BEFORE_SINCE,
    REASON_FETCH_MISSING,
    REASON_FETCH_TRANSPORT,
    REASON_INVALID_JSON,
    REASON_INVALID_PAYLOAD_PREFIX,
    REASON_INVALID_REPORT_ID,
    REASON_INVALID_SUBMITTED_AT,
    REASON_MISSING_ID,
    REASON_MISSING_SUBMITTED_AT,
    REASON_RECORD_NOT_AN_OBJECT,
    REASON_UNKNOWN_FIELD_PREFIX,
    parse_report_object,
    reconcile_report_objects,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ReaderReport, ReaderReportContact
from news_collector.storage.reader_report_repository import upsert_reader_report

REPORT_KEY = "reports/2026-10-19/3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90.json"
REPORT_ID = "3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
OTHER_ID = "4fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
PUBLISHED_URL = "https://noticiencias.com/posts/example"

UNRESOLVED_IDENTITY = ReportIdentity(status="unresolved", reason="invalid_article_url")


def _record_body(**overrides: object) -> bytes:
    """Pretty-printed Worker record (like ``JSON.stringify(rec, null, 2)``)."""
    fields: Dict[str, object] = {
        "id": REPORT_ID,
        "problem_type": "content_factual",
        "article_url": PUBLISHED_URL,
        "description": "The dose is wrong.",
        "content_snippet": None,
        "evidence_url": None,
        "tech_browser": "Firefox",
        "tech_os": "Debian",
        "reporter_email": "reader@example.com",
        "submitted_at": "2026-10-19T12:00:00.000Z",
        "environment": "production",
        "user_agent": "Mozilla/5.0",
    }
    fields.update(overrides)
    return json.dumps(fields, indent=2).encode("utf-8")


@dataclass
class _FakeFeed:
    """In-memory R2 stand-in: deterministic pages and typed failures."""

    objects: Dict[str, bytes]
    missing: frozenset[str] = frozenset()
    transport_failures: frozenset[str] = frozenset()
    page_split: Optional[Sequence[Sequence[str]]] = None
    fail_list: bool = False
    list_calls: list = field(default_factory=list)

    def list_report_keys(
        self, *, prefix: str, limit: int, cursor: Optional[str] = None
    ) -> R2KeyPage:
        self.list_calls.append({"prefix": prefix, "limit": limit, "cursor": cursor})
        if self.fail_list:
            raise RuntimeError("listing broken")
        if self.page_split is None:
            keys = tuple(k for k in sorted(self.objects) if k.startswith(prefix))
            return R2KeyPage(keys=keys, next_cursor=None)
        index = 0 if cursor is None else int(cursor)
        page = self.page_split[index]
        has_more = index + 1 < len(self.page_split)
        return R2KeyPage(
            keys=tuple(page), next_cursor=f"{index + 1}" if has_more else None
        )

    def get_object(self, key: str) -> bytes:
        if key in self.missing:
            raise R2ObjectMissing(key)
        if key in self.transport_failures:
            raise RuntimeError("transport")
        return self.objects[key]


@pytest.fixture
def db_factory(tmp_path):
    """New DatabaseManager per call, sharing the tmp_path database file."""

    def factory() -> DatabaseManager:
        return DatabaseManager({"type": "sqlite", "path": tmp_path / "reconcile.db"})

    return factory


@pytest.fixture
def db_manager(db_factory) -> DatabaseManager:
    manager = db_factory()
    yield manager
    manager.close()


def _seed_published_article(db_manager: DatabaseManager) -> int:
    with db_manager.SessionLocal() as session:
        article = Article(
            url="https://example.com/source",
            title="Example article",
            source_id="test_source",
            source_name="Test Source",
            published_url=PUBLISHED_URL,
            content_hash="e" * 64,
        )
        session.add(article)
        session.commit()
        return int(article.id)


def _repository_persister(db_manager: DatabaseManager):
    """Real-repository persistence wiring, one transaction per object."""

    def persist(intake: ValidReportIntake, identity: ReportIdentity) -> PersistOutcome:
        with db_manager.SessionLocal() as session:
            report, created = upsert_reader_report(
                session,
                idempotency_key=intake.idempotency_key,
                payload=intake.payload,
                submitted_at=intake.submitted_at,
                identity=identity,
                reporter_email=intake.payload.reporter_email,
            )
            session.commit()
        return PersistOutcome(status="created" if created else "duplicate")

    return persist


def _row_counts(db_manager: DatabaseManager) -> tuple[int, int]:
    with db_manager.SessionLocal() as session:
        reports: int = int(
            session.execute(select(func.count()).select_from(ReaderReport)).scalar_one()
        )
        contacts: int = int(
            session.execute(
                select(func.count()).select_from(ReaderReportContact)
            ).scalar_one()
        )
    return reports, contacts


# ---------------------------------------------------------------------------
# parse_report_object — typed intake outcomes
# ---------------------------------------------------------------------------


class TestParseValidIntake:
    def test_full_record_is_valid_with_all_fields(self) -> None:
        intake = parse_report_object(REPORT_KEY, _record_body())

        assert isinstance(intake, ValidReportIntake)
        assert intake.key == REPORT_KEY
        assert intake.idempotency_key == REPORT_ID
        assert intake.payload.problem_type == "content_factual"
        assert intake.payload.description == "The dose is wrong."
        assert intake.payload.tech_browser == "Firefox"
        assert intake.payload.reporter_email == "reader@example.com"
        assert intake.submitted_at == datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        assert intake.environment == "production"
        assert intake.user_agent == "Mozilla/5.0"

    def test_minimal_record_is_valid_without_optional_fields(self) -> None:
        body = _record_body(
            article_url=None,
            description=None,
            content_snippet=None,
            evidence_url=None,
            tech_browser=None,
            tech_os=None,
            reporter_email=None,
            environment=None,
            user_agent=None,
        )

        intake = parse_report_object(REPORT_KEY, body)

        assert isinstance(intake, ValidReportIntake)
        assert intake.payload.article_url is None
        assert intake.payload.reporter_email is None
        assert intake.environment is None
        assert intake.user_agent is None
        assert intake.submitted_at == datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def test_unicode_and_boundary_lengths_accepted(self) -> None:
        description = "café ☕" * 833 + "ab"  # exactly 5000 chars
        assert len(description) == 5000
        body = _record_body(
            description=description,
            article_url=f"https://noticiencias.com/posts/{'é' * 100}",
        )

        intake = parse_report_object(REPORT_KEY, body)

        assert isinstance(intake, ValidReportIntake)
        assert intake.payload.description is not None
        assert len(intake.payload.description) == 5000

    def test_draft_machinery_unused_field_is_none_safety(self) -> None:
        """Empty optional strings normalize to None (Worker parity)."""
        intake = parse_report_object(
            REPORT_KEY, _record_body(description="", tech_os="")
        )
        assert isinstance(intake, ValidReportIntake)
        assert intake.payload.description is None
        assert intake.payload.tech_os is None

    def test_submitted_at_without_timezone_is_utc_normalized(self) -> None:
        intake = parse_report_object(
            REPORT_KEY, _record_body(submitted_at="2026-10-19T12:00:00")
        )
        assert isinstance(intake, ValidReportIntake)
        assert intake.submitted_at.tzinfo == timezone.utc

    def test_id_is_canonicalized_per_format(self) -> None:
        intake = parse_report_object(REPORT_KEY, _record_body(id=REPORT_ID.upper()))
        assert isinstance(intake, ValidReportIntake)
        assert intake.idempotency_key == REPORT_ID


class TestParseInvalidIntake:
    def test_invalid_json_is_typed(self) -> None:
        outcome = parse_report_object(REPORT_KEY, b"not json at all")
        assert outcome == InvalidReportIntake(
            key=REPORT_KEY, reason=REASON_INVALID_JSON
        )

    def test_non_utf8_body_is_typed(self) -> None:
        outcome = parse_report_object(REPORT_KEY, b"\xff\xfe\xfa")
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_INVALID_JSON

    def test_json_scalar_is_not_a_record(self) -> None:
        outcome = parse_report_object(REPORT_KEY, b"[1, 2, 3]")
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_RECORD_NOT_AN_OBJECT

    def test_missing_id_is_typed(self) -> None:
        body = _record_body()
        record = json.loads(body)
        del record["id"]
        outcome = parse_report_object(REPORT_KEY, json.dumps(record).encode())
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_MISSING_ID

    def test_non_uuid_id_is_typed(self) -> None:
        outcome = parse_report_object(REPORT_KEY, _record_body(id="delivery-key-1"))
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_INVALID_REPORT_ID

    def test_missing_submitted_at_is_typed(self) -> None:
        record = json.loads(_record_body())
        del record["submitted_at"]
        outcome = parse_report_object(REPORT_KEY, json.dumps(record).encode())
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_MISSING_SUBMITTED_AT

    def test_malformed_submitted_at_is_typed(self) -> None:
        outcome = parse_report_object(
            REPORT_KEY, _record_body(submitted_at="not-a-date")
        )
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == REASON_INVALID_SUBMITTED_AT

    def test_unknown_field_is_record_shape_drift(self) -> None:
        outcome = parse_report_object(REPORT_KEY, _record_body(captcha_pass=True))
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason == f"{REASON_UNKNOWN_FIELD_PREFIX}captcha_pass"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"problem_type": "unknown_problem"},
            {"description": "x" * 5001},
            {"article_url": "https://example.com/foreign"},
            {"article_url": "not-a-url"},
            {"reporter_email": "nope"},
        ],
    )
    def test_payload_contract_violations_are_typed_invalid(
        self, overrides: Dict[str, object]
    ) -> None:
        outcome = parse_report_object(REPORT_KEY, _record_body(**overrides))
        assert isinstance(outcome, InvalidReportIntake)
        assert outcome.reason.startswith(REASON_INVALID_PAYLOAD_PREFIX)
        assert len(outcome.reason) <= 200


# ---------------------------------------------------------------------------
# reconcile_report_objects — orchestration with injected collaborators
# ---------------------------------------------------------------------------


class TestOrchestrationMatrix:
    def test_valid_record_resolves_and_persists_with_identity_stamped(
        self, db_manager: DatabaseManager
    ) -> None:
        _seed_published_article(db_manager)
        article_id = 42  # the resolver stub matches this refinery id
        resolved = ReportIdentity(
            status="resolved",
            canonical_url=PUBLISHED_URL,
            refinery_id=str(article_id),
            content_sha256="a" * 64,
            reason=REASON_RESOLVED,
        )
        feed = _FakeFeed({REPORT_KEY: _record_body()})
        outcomes = []

        def capture(
            intake: ValidReportIntake, identity: ReportIdentity
        ) -> PersistOutcome:
            outcomes.append((intake, identity))
            return PersistOutcome(status="created")

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: dict(
                {PUBLISHED_URL: resolved, "": UNRESOLVED_IDENTITY}
            )[url],
            persist_report=capture,
        )

        assert summary.fatal is None
        assert summary.created == 1
        intake, identity = outcomes[0]
        assert intake.idempotency_key == REPORT_ID
        assert identity.status == "resolved"
        assert identity.reason == REASON_RESOLVED
        assert identity.refinery_id == str(article_id)

    def test_no_url_report_resolves_to_typed_unresolved(
        self, db_manager: DatabaseManager
    ) -> None:
        _seed_published_article(db_manager)
        feed = _FakeFeed({REPORT_KEY: _record_body(article_url=None)})
        seen_identities = []

        def capture(
            intake: ValidReportIntake, identity: ReportIdentity
        ) -> PersistOutcome:
            seen_identities.append(identity)
            return PersistOutcome(status="created")

        reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=capture,
        )

        assert seen_identities[0].status == "unresolved"
        assert seen_identities[0].reason == "invalid_article_url"

    def test_resolved_identity_through_real_resolver_with_seeded_article(
        self, db_manager: DatabaseManager
    ) -> None:
        article_id = _seed_published_article(db_manager)
        feed = _FakeFeed({REPORT_KEY: _record_body()})
        seen_identities = []

        def capture(
            intake: ValidReportIntake, identity: ReportIdentity
        ) -> PersistOutcome:
            seen_identities.append(identity)
            return PersistOutcome(status="created")

        reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=capture,
        )

        identity = seen_identities[0]
        assert identity.status == "resolved"
        assert identity.refinery_id == str(article_id)
        assert identity.content_sha256 == "e" * 64

    def test_per_object_failures_are_outcomes_and_run_continues(self) -> None:
        good_key = "reports/2026-10-19/good.json"
        feed = _FakeFeed(
            {
                good_key: _record_body(id=OTHER_ID),
                REPORT_KEY: b"broken{",
            },
            missing=("reports/2026-10-19/gone.json",),
            transport_failures=("reports/2026-10-19/net.json",),
        )
        feed.objects["reports/2026-10-19/net.json"] = _record_body(
            id="5fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
        )
        feed.objects["reports/2026-10-19/gone.json"] = _record_body(
            id="6fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
        )

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="created"),
        )

        assert summary.fatal is None
        assert summary.created == 1
        assert summary.invalid == 1
        assert summary.fetch_failed == 2
        statuses = {o.key: o.status for o in summary.outcomes}
        assert statuses[REPORT_KEY] == "invalid"
        assert statuses["reports/2026-10-19/gone.json"] == "fetch_failed"
        assert statuses["reports/2026-10-19/net.json"] == "fetch_failed"
        missing_reason = {o.key: o.reason for o in summary.outcomes}[
            "reports/2026-10-19/gone.json"
        ]
        assert missing_reason == REASON_FETCH_MISSING
        transport_reason = {o.key: o.reason for o in summary.outcomes}[
            "reports/2026-10-19/net.json"
        ]
        assert transport_reason == REASON_FETCH_TRANSPORT

    def test_persister_failure_is_a_typed_outcome(self) -> None:
        feed = _FakeFeed({REPORT_KEY: _record_body()})

        def persist(
            intake: ValidReportIntake, identity: ReportIdentity
        ) -> PersistOutcome:
            raise RuntimeError("db down")

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=persist,
        )

        assert summary.persist_failed == 1
        outcome = summary.outcomes[0]
        assert outcome.status == "persist_failed"
        assert outcome.idempotency_key == REPORT_ID

    def test_listing_failure_sets_fatal_and_stops(self) -> None:
        feed = _FakeFeed({}, fail_list=True)

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="created"),
        )

        assert summary.fatal == "list_failed:RuntimeError"
        assert summary.created == 0
        assert summary.listed == 0

    def test_limit_truncates_with_flag_and_pages(self) -> None:
        keys = [f"reports/2026-10-19/{i}.json" for i in range(4)]
        feed = _FakeFeed(
            {
                key: _record_body(id=f"{i}fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90")
                for i, key in enumerate(keys)
            },
            page_split=(tuple(keys[:2]), tuple(keys[2:])),
        )

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="created"),
            prefix="reports/",
            limit=3,
        )

        assert summary.listed == 4  # both pages seen
        assert summary.created == 3
        assert summary.truncated is True
        assert feed.list_calls == [
            {"prefix": "reports/", "limit": 3, "cursor": None},
            {"prefix": "reports/", "limit": 1, "cursor": "1"},
        ]

    def test_limit_reached_exact_end_is_not_truncated(self) -> None:
        keys = [f"reports/2026-10-19/{i}.json" for i in range(2)]
        feed = _FakeFeed(
            {
                key: _record_body(id=f"{i}fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90")
                for i, key in enumerate(keys)
            },
            page_split=(tuple(keys),),
        )

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="created"),
            limit=2,
        )

        assert summary.created == 2
        assert summary.truncated is False

    def test_since_filter_skips_older_submissions(self) -> None:
        newer_key = "reports/2026-10-20/newer.json"
        older_key = "reports/2026-10-18/older.json"
        feed = _FakeFeed(
            {
                newer_key: _record_body(
                    id=OTHER_ID,
                    submitted_at="2026-10-20T09:00:00.000Z",
                ),
                older_key: _record_body(
                    id="7fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90",
                    submitted_at="2026-10-18T09:00:00.000Z",
                ),
            }
        )

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="created"),
            since=datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc),
        )

        assert summary.skipped == 1
        assert summary.created == 1
        # Sorted keys put the older submission first.
        assert summary.outcomes[0].reason == REASON_BEFORE_SINCE
        assert summary.outcomes[0].status == "skipped"
        assert summary.outcomes[1].status == "created"
        assert summary.outcomes[1].reason is None

    def test_since_naive_datetime_is_treated_as_utc(self) -> None:
        feed = _FakeFeed({REPORT_KEY: _record_body()})

        summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=lambda url: UNRESOLVED_IDENTITY,
            persist_report=lambda intake, identity: PersistOutcome(status="duplicate"),
            since=datetime(2026, 10, 20, 0, 0),
        )

        assert summary.skipped == 1

    def test_limit_below_one_is_rejected(self) -> None:
        feed = _FakeFeed({})
        with pytest.raises(ValueError):
            reconcile_report_objects(
                feed=feed,
                resolve_identity=lambda url: UNRESOLVED_IDENTITY,
                persist_report=lambda intake, identity: PersistOutcome(
                    status="created"
                ),
                limit=0,
            )


def resolve_report_identity_bound(db_manager: DatabaseManager):
    """The script wiring: resolver bound to its database manager."""

    def resolve(url: str) -> ReportIdentity:
        return resolve_report_identity(url, db_manager)

    return resolve


# ---------------------------------------------------------------------------
# Idempotency integration: same object twice -> one row, duplicates counted
# ---------------------------------------------------------------------------


class TestIdempotentReconciliation:
    def test_reconciling_same_record_twice_yields_one_report_and_one_contact(
        self, db_manager: DatabaseManager
    ) -> None:
        _seed_published_article(db_manager)
        objects = {REPORT_KEY: _record_body()}
        feed = _FakeFeed(objects)
        persist = _repository_persister(db_manager)

        first = reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=persist,
        )
        second = reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=persist,
        )

        assert first.created == 1
        assert second.duplicates == 1
        reports, contacts = _row_counts(db_manager)
        assert reports == 1
        assert contacts == 1
        with db_manager.SessionLocal() as session:
            report = session.execute(select(ReaderReport)).scalar_one()
            assert report.idempotency_key == REPORT_ID
            # SQLite drops tzinfo on readback; the aware-UTC instant matches.
            assert report.submitted_at == datetime(2026, 10, 19, 12, 0)
            assert report.resolution_status == "resolved"
            original_resolution = report.resolution_reason
            original_created = report.created_at
        # Third pass: still one row, resolution untouched (no rewrite).
        third = reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=persist,
        )
        assert third.duplicates == 1
        with db_manager.SessionLocal() as session:
            report = session.execute(select(ReaderReport)).scalar_one()
            assert report.resolution_reason == original_resolution
            assert report.created_at == original_created

    def test_duplicate_run_counts_outcome_never_copies_payload(
        self, db_manager: DatabaseManager
    ) -> None:
        _seed_published_article(db_manager)
        feed = _FakeFeed({REPORT_KEY: _record_body()})
        persist = _repository_persister(db_manager)

        first_summary = reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=persist,
            limit=1,
        )
        assert first_summary.created == 1

        # Change the R2 body AND the resolver answer; the stored row must
        # survive first-seen, and the replay must still be a duplicate.
        feed.objects[REPORT_KEY] = _record_body(
            description="tampered after the fact", environment="staging"
        )

        replay = reconcile_report_objects(
            feed=feed,
            resolve_identity=resolve_report_identity_bound(db_manager),
            persist_report=persist,
            limit=1,
        )

        assert replay.duplicates == 1
        assert replay.created == 0
        reports, contacts = _row_counts(db_manager)
        assert (reports, contacts) == (1, 1)
        with db_manager.SessionLocal() as session:
            report = session.execute(select(ReaderReport)).scalar_one()
            assert report.description == "The dose is wrong."
            assert report.submitted_at is not None
