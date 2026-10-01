"""Tests for scripts/ops/pull_webhook_receipts.py (ADR-0011).

The replay effects themselves are owned by `handle_webhook_event` /
`publication_callbacks` (covered elsewhere); this module proves the wrapper:
endpoint/token resolution, paging with the id cursor, idempotent replays,
malformed-payload reporting, dry-run behavior and exit codes — against a
real (temporary) SQLite database and an injected page fetcher.
"""

from __future__ import annotations

import sys

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from scripts.ops import pull_webhook_receipts as script

ARTICLE_URL = "https://example.com/inbox-pull"
REFINERY_ID = "refinery-inbox-1"
DEPLOY_URL = "https://noticiencias.com"


@pytest.fixture()
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "inbox.db"})
    yield manager
    manager.close()


def _seed_pr_created(db_manager: DatabaseManager) -> int:
    with db_manager.get_session() as session:
        session.add(
            Article(
                title="Inbox pull test",
                url=ARTICLE_URL,
                summary="A test article",
                source_id="test-source",
                source_name="Test Source",
                category="science",
                processing_status="pending",
            )
        )
    with db_manager.get_session() as session:
        article = session.query(Article).filter_by(url=ARTICLE_URL).first()
        assert article is not None
        article_id = int(article.id)
    db_manager.mark_article_publishing(article_id, "content/update-inbox")
    db_manager.mark_article_published(
        article_id, "https://github.com/cortega26/noticiencias/pull/999", REFINERY_ID
    )
    return article_id


def _publish_payload(publication_ids):
    return {
        "event": "publish_complete",
        "commit_sha": "abc123def",
        "branch": "main",
        "status": "success",
        "diagnostics": [
            {"check": "deploy", "status": "pass", "deploy_url": DEPLOY_URL}
        ],
        "frontend_ref": "abc123def",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
        "publication_ids": publication_ids,
        "delivery_id": "v1:1:publish_complete",
    }


def _receipt(receipt_id: int, payload: dict) -> dict:
    return {
        "id": receipt_id,
        "delivery_key": f"id:v1:{receipt_id}:{payload.get('event')}",
        "event_type": payload.get("event"),
        "status": "processed",  # the hosted handler's outcome is irrelevant here
        "attempts": 1,
        "payload": payload,
    }


def _page_fetcher(pages):
    calls: list[dict] = []

    def fetch(*, endpoint, token, after_id, limit):
        calls.append(
            {"endpoint": endpoint, "token": token, "after_id": after_id, "limit": limit}
        )
        return pages.pop(0) if pages else []

    return fetch, calls


class TestResolveEndpoint:
    def test_explicit_endpoint_wins(self):
        assert (
            script.resolve_endpoint(
                "https://explicit.example/v1/x", "https://admin.example", None
            )
            == "https://explicit.example/v1/x"
        )

    def test_admin_url_gets_the_receipts_path(self):
        assert (
            script.resolve_endpoint(None, "https://api.noticiencias.com/", None)
            == f"https://api.noticiencias.com{script.RECEIPTS_PATH}"
        )

    def test_webhook_origin_is_reused(self):
        assert (
            script.resolve_endpoint(
                None, None, "https://api.noticiencias.com/api/v1/webhook/frontend"
            )
            == f"https://api.noticiencias.com{script.RECEIPTS_PATH}"
        )

    def test_nothing_configured_returns_none(self):
        assert script.resolve_endpoint(None, None, None) is None
        assert script.resolve_endpoint(None, None, "not-a-url") is None


class TestPullReceipts:
    def test_replays_a_delivery_and_completes_the_local_publication(
        self, db_manager: DatabaseManager
    ):
        article_id = _seed_pr_created(db_manager)
        payload = _publish_payload([REFINERY_ID])
        fetch, calls = _page_fetcher([[_receipt(7, payload)]])

        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=fetch,
        )

        assert summary.fetched == 1
        assert summary.replayed == 1
        assert summary.duplicates == 0
        assert summary.malformed == 0
        assert calls[0]["after_id"] is None

        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "completed"
            assert article.published_url == DEPLOY_URL
            assert article.published_at is not None
        attempts = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
        assert attempts[0].state == "COMPLETED"

    def test_second_pass_is_a_duplicate_no_op(self, db_manager: DatabaseManager):
        _seed_pr_created(db_manager)
        payload = _publish_payload([REFINERY_ID])

        script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=_page_fetcher([[_receipt(7, payload)]])[0],
        )
        fetch, _ = _page_fetcher([[_receipt(7, payload)]])
        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=fetch,
        )

        assert summary.fetched == 1
        assert summary.duplicates == 1
        assert summary.replayed == 0

    def test_pages_forward_with_after_id_and_stops_on_a_short_page(
        self, db_manager: DatabaseManager
    ):
        noop = {
            "event": "validation_result",
            "commit_sha": "abc",
            "branch": "main",
            "status": "pass",
            "diagnostics": [],
            "frontend_ref": "abc",
            "run_url": "https://github.com/x/y/actions/runs/1",
            "publication_ids": [],
        }
        # limit=2: first page full (ids 1, 2), second page short (id 3).
        fetch, calls = _page_fetcher(
            [
                [_receipt(1, noop), _receipt(2, noop)],
                [_receipt(3, noop)],
            ]
        )

        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            limit=2,
            fetcher=fetch,
        )

        assert summary.fetched == 3
        assert [c["after_id"] for c in calls] == [None, 2]
        assert len(calls) == 2  # short page stops the loop

    def test_malformed_payload_is_reported_and_never_applied(
        self, db_manager: DatabaseManager
    ):
        fetch, _ = _page_fetcher([[_receipt(1, {"event": "bogus"})]])

        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=fetch,
        )

        assert summary.malformed == 1
        assert summary.replayed == 0
        assert db_manager.webhook_receipts.list_receipts() == []

    def test_max_receipts_caps_the_pass(self, db_manager: DatabaseManager):
        noop = {
            "event": "validation_result",
            "commit_sha": "abc",
            "branch": "main",
            "status": "pass",
            "diagnostics": [],
            "frontend_ref": "abc",
            "run_url": "https://github.com/x/y/actions/runs/1",
            "publication_ids": [],
        }
        fetch, calls = _page_fetcher(
            [
                [_receipt(1, noop), _receipt(2, noop)],
            ]
        )

        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            limit=2,
            max_receipts=2,
            fetcher=fetch,
        )

        assert summary.fetched == 2
        assert len(calls) == 1

    def test_dry_run_writes_nothing(self, db_manager: DatabaseManager):
        article_id = _seed_pr_created(db_manager)
        fetch, _ = _page_fetcher([[_receipt(7, _publish_payload([REFINERY_ID]))]])

        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            dry_run=True,
            fetcher=fetch,
        )

        assert summary.replayed == 1
        assert db_manager.webhook_receipts.list_receipts() == []
        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "publishing"


class TestMain:
    def test_missing_endpoint_and_token_exit_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        for name in ("BACKEND_ADMIN_URL", "BACKEND_WEBHOOK_URL", "ADMIN_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(sys, "argv", ["pull_webhook_receipts.py"])

        assert script.main() == 1
        assert "no endpoint" in capsys.readouterr().err

    def test_fetch_failure_exits_one_with_summary_message(
        self,
        db_manager: DatabaseManager,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        def boom(**_kwargs):
            raise script.PullError("connection refused")

        monkeypatch.setattr(script, "DatabaseManager", lambda: db_manager)
        monkeypatch.setattr(script, "fetch_page", boom)
        monkeypatch.setenv(
            "BACKEND_WEBHOOK_URL", "https://api.example/api/v1/webhook/frontend"
        )
        monkeypatch.setenv("ADMIN_API_KEY", "token")
        monkeypatch.setattr(sys, "argv", ["pull_webhook_receipts.py"])

        assert script.main() == 1
        assert "FAILED" in capsys.readouterr().err

    def test_successful_pass_exits_zero_with_summary(
        self,
        db_manager: DatabaseManager,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.setattr(script, "DatabaseManager", lambda: db_manager)
        monkeypatch.setattr(
            script, "fetch_page", lambda **_kwargs: [_receipt(1, _publish_payload([]))]
        )
        monkeypatch.setenv("ADMIN_API_KEY", "token")
        monkeypatch.setenv("BACKEND_ADMIN_URL", "https://api.example")
        monkeypatch.setattr(sys, "argv", ["pull_webhook_receipts.py"])

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "[pull-webhooks] fetched=1" in out
        assert "[pull-webhooks] replayed=1" in out
