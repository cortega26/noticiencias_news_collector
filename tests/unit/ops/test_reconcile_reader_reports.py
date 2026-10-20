"""Tests for scripts/reconcile_reader_reports.py (plan 186).

The R2 feed is fake; the database, the identity resolver, the repository
and the script's wiring are real, so the end-to-end idempotency promise
(same object twice -> exactly one row + contact) is engine-verified.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import pytest
from sqlalchemy import func, select

import scripts.reconcile_reader_reports as script
from news_collector.contracts.reader_reports import R2KeyPage
from news_collector.infrastructure.r2_client import (
    ACCOUNT_ID_ENV,
    TOKEN_ENV,
    R2ConfigurationError,
    R2Credentials,
    R2ObjectMissing,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ReaderReport, ReaderReportContact
from scripts.reconcile_reader_reports import parse_since, run_reconciliation

REPORT_KEY = "reports/2026-10-19/3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90.json"
REPORT_ID = "3fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
PUBLISHED_URL = "https://noticiencias.com/posts/example"

CREDENTIALS = R2Credentials(
    account_id="acct", api_token="tok", bucket="noticiencias-reports"
)


def _record_body(**overrides: object) -> bytes:
    fields: Dict[str, object] = {
        "id": REPORT_ID,
        "problem_type": "content_factual",
        "article_url": PUBLISHED_URL,
        "description": "The dose is wrong.",
        "content_snippet": None,
        "evidence_url": None,
        "tech_browser": None,
        "tech_os": None,
        "reporter_email": "reader@example.com",
        "submitted_at": "2026-10-19T12:00:00.000Z",
        "environment": "production",
        "user_agent": "Mozilla/5.0",
    }
    fields.update(overrides)
    return json.dumps(fields, indent=2).encode("utf-8")


class _FakeFeed:
    def __init__(
        self,
        objects: Optional[Dict[str, bytes]] = None,
        *,
        fail_list: bool = False,
    ) -> None:
        self.objects: Dict[str, bytes] = dict(objects or {})
        self.fail_list = fail_list

    def list_report_keys(
        self, *, prefix: str, limit: int, cursor: Optional[str] = None
    ) -> R2KeyPage:
        if self.fail_list:
            raise RuntimeError("listing broken")
        keys = tuple(k for k in sorted(self.objects) if k.startswith(prefix))
        return R2KeyPage(keys=keys, next_cursor=None)

    def get_object(self, key: str) -> bytes:
        return self.objects[key]

    def close(self) -> None:
        return None


@pytest.fixture
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "script.db"})
    yield manager
    manager.close()


def _fresh_manager(tmp_path) -> DatabaseManager:
    """Main() closes its manager; tests reopen the same file when needed."""
    return DatabaseManager({"type": "sqlite", "path": tmp_path / "script.db"})


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


def _total_counts(tmp_path) -> Tuple[int, int]:
    """Count rows on the script database (main() closes its manager)."""
    manager = _fresh_manager(tmp_path)
    try:
        with manager.SessionLocal() as session:
            reports: int = int(
                session.execute(
                    select(func.count()).select_from(ReaderReport)
                ).scalar_one()
            )
            contacts: int = int(
                session.execute(
                    select(func.count()).select_from(ReaderReportContact)
                ).scalar_one()
            )
    finally:
        manager.close()
    return reports, contacts


# ---------------------------------------------------------------------------
# run_reconciliation
# ---------------------------------------------------------------------------


class TestRunReconciliation:
    def test_end_to_end_create_then_duplicate(
        self, db_manager: DatabaseManager, tmp_path, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_published_article(db_manager)
        feed = _FakeFeed({REPORT_KEY: _record_body()})

        first = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=False
        )
        assert first.fatal is None
        assert first.created == 1

        second = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=False
        )
        assert second.duplicates == 1
        assert second.created == 0

        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (1, 1)

    def test_dry_run_writes_nothing(
        self, db_manager: DatabaseManager, tmp_path
    ) -> None:
        _seed_published_article(db_manager)
        feed = _FakeFeed(
            {
                REPORT_KEY: _record_body(),
                "reports/2026-10-18/older.json": _record_body(
                    id="4fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
                ),
            }
        )

        summary = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=True
        )

        assert summary.created == 2  # both reports would be stored
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (0, 0)  # nothing was written

        # A real run after the dry-run stores exactly once — dry-run left no
        # half-state behind.
        real = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=False
        )
        assert real.created == 2
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (2, 2)

    def test_invalid_and_transport_failures_counted(
        self, db_manager: DatabaseManager, tmp_path
    ) -> None:
        _seed_published_article(db_manager)
        broken_key = "reports/2026-10-19/broken.json"
        missing_key = "reports/2026-10-19/gone.json"

        class _MixedFeed(_FakeFeed):
            def get_object(self, key: str) -> bytes:
                if key == missing_key:
                    raise R2ObjectMissing(key)
                return super().get_object(key)

        feed = _MixedFeed(
            {
                REPORT_KEY: _record_body(),
                broken_key: b"{not json",
            }
        )
        feed.objects[missing_key] = _record_body(
            id="5fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90"
        )

        summary = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=False
        )

        assert summary.created == 1
        assert summary.invalid == 1
        assert summary.fetch_failed == 1
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (1, 1)

    def test_listing_failure_is_fatal(self, db_manager: DatabaseManager) -> None:
        feed = _FakeFeed({}, fail_list=True)

        summary = run_reconciliation(
            db_manager, credentials=CREDENTIALS, feed=feed, dry_run=False
        )

        assert summary.fatal is not None
        assert summary.created == 0

    def test_since_skips_intake_before_cut(
        self, db_manager: DatabaseManager, tmp_path
    ) -> None:
        _seed_published_article(db_manager)
        newer_key = "reports/2026-10-20/newer.json"
        feed = _FakeFeed(
            {
                newer_key: _record_body(
                    id="6fe0a2f8-1d0e-4b6a-9c1e-2f5a6b7c8d90",
                    submitted_at="2026-10-20T09:00:00.000Z",
                ),
                REPORT_KEY: _record_body(),  # 2026-10-19T12:00Z
            }
        )

        summary = run_reconciliation(
            db_manager,
            credentials=CREDENTIALS,
            feed=feed,
            since=datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc),
            dry_run=False,
        )

        assert summary.skipped == 1
        assert summary.created == 1
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (1, 1)


# ---------------------------------------------------------------------------
# main() — argv wiring, exit codes
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        feed: _FakeFeed,
        *,
        raise_on_creds: Optional[Exception] = None,
    ) -> None:
        # main() builds its own manager on the shared sqlite file, then
        # closes it — the factory pattern is what makes each invocation
        # independent, exactly like production wiring.
        monkeypatch.setattr(script, "DatabaseManager", lambda: _fresh_manager(tmp_path))

        def _fake_client(_credentials: R2Credentials) -> _FakeFeed:
            return feed

        monkeypatch.setattr(script, "R2ReportClient", _fake_client)
        if raise_on_creds is not None:

            def _raise() -> Any:
                raise raise_on_creds

            monkeypatch.setattr(script, "load_r2_credentials", _raise)
        else:
            monkeypatch.setattr(script, "load_r2_credentials", lambda: CREDENTIALS)

    def test_main_missing_creds_exits_2_before_any_io(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        self._patch(
            monkeypatch,
            tmp_path,
            _FakeFeed({}),
            raise_on_creds=R2ConfigurationError("credentials missing"),
        )
        monkeypatch.setattr("sys.argv", ["reconcile_reader_reports.py", "--dry-run"])

        exit_code = script.main()

        assert exit_code == 2
        assert "credentials missing" in capsys.readouterr().err
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (0, 0)

    def test_main_dry_run_exit_zero_writes_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_manager: DatabaseManager,
        tmp_path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _seed_published_article(db_manager)
        self._patch(monkeypatch, tmp_path, _FakeFeed({REPORT_KEY: _record_body()}))
        monkeypatch.setattr("sys.argv", ["reconcile_reader_reports.py", "--dry-run"])

        exit_code = script.main()
        result = capsys.readouterr()

        assert exit_code == 0
        assert "no rows were written" in result.err
        # stdout stays pure machine-parsable JSON.
        payload = json.loads(result.out)
        assert payload["created"] == 1
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (0, 0)

    def test_main_real_run_exit_zero_and_prints_json_summary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_manager: DatabaseManager,
        tmp_path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _seed_published_article(db_manager)
        self._patch(monkeypatch, tmp_path, _FakeFeed({REPORT_KEY: _record_body()}))
        monkeypatch.setattr("sys.argv", ["reconcile_reader_reports.py"])

        exit_code = script.main()
        captured = capsys.readouterr().out

        assert exit_code == 0
        payload = json.loads(captured)
        assert payload["created"] == 1
        assert payload["by_reason"] == {}
        reports, contacts = _total_counts(tmp_path)
        assert (reports, contacts) == (1, 1)

    def test_main_listing_failure_exits_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        self._patch(monkeypatch, tmp_path, _FakeFeed({}, fail_list=True))
        monkeypatch.setattr("sys.argv", ["reconcile_reader_reports.py"])

        exit_code = script.main()

        assert exit_code == 1
        assert "list_failed" in capsys.readouterr().err

    def test_main_invalid_since_exits_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        self._patch(monkeypatch, tmp_path, _FakeFeed({}))
        monkeypatch.setattr(
            "sys.argv", ["reconcile_reader_reports.py", "--since", "not-a-date"]
        )

        exit_code = script.main()

        assert exit_code == 1
        assert "invalid --since" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------


class TestParseSince:
    def test_date_only_is_start_of_utc_day(self) -> None:
        assert parse_since("2026-10-19") == datetime(
            2026, 10, 19, 0, 0, tzinfo=timezone.utc
        )

    def test_full_iso_datetime_is_utc_normalized(self) -> None:
        assert parse_since("2026-10-19T12:30:00+02:00") == datetime(
            2026, 10, 19, 10, 30, tzinfo=timezone.utc
        )

    def test_naive_datetime_is_utc(self) -> None:
        assert parse_since("2026-10-19T12:30:00") == datetime(
            2026, 10, 19, 12, 30, tzinfo=timezone.utc
        )

    def test_invalid_value_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_since("not-a-date")

    def test_empty_and_none_are_no_filter(self) -> None:
        assert parse_since(None) is None
        assert parse_since("") is None
