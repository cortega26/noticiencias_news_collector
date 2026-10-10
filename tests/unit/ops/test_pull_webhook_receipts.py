"""Tests for scripts/ops/pull_webhook_receipts.py (ADR-0011).

The replay effects themselves are owned by `handle_webhook_event` /
`publication_callbacks` (covered elsewhere); this module proves the wrapper:
endpoint/token resolution, paging with the id cursor, idempotent replays,
malformed-payload reporting, dry-run behavior and exit codes — against a
real (temporary) SQLite database and an injected page fetcher.
"""

from __future__ import annotations

import hashlib
import sys

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from scripts.ops import pull_webhook_receipts as script

ARTICLE_URL = "https://example.com/inbox-pull"
REFINERY_ID = "refinery-inbox-1"
DEPLOY_URL = "https://noticiencias.com"
PUBLICATION_ATTEMPT_ID = "inbox-test-attempt"
PULL_REQUEST_NUMBER = 999
CONTENT_SHA256 = hashlib.sha256(b"inbox fixture post").hexdigest()


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
    db_manager.mark_article_publishing(
        article_id,
        "content/update-inbox",
        publication_attempt_id=PUBLICATION_ATTEMPT_ID,
    )
    db_manager.mark_article_published(
        article_id,
        f"https://github.com/cortega26/noticiencias/pull/{PULL_REQUEST_NUMBER}",
        REFINERY_ID,
        publication_attempt_id=PUBLICATION_ATTEMPT_ID,
        content_sha256=CONTENT_SHA256,
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
        "publication_attempt_refs": (
            [
                {
                    "refinery_id": REFINERY_ID,
                    "pull_request_number": PULL_REQUEST_NUMBER,
                    "content_sha256": CONTENT_SHA256,
                }
            ]
            if REFINERY_ID in publication_ids
            else []
        ),
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
        # A second hosted delivery with the same delivery key must be a no-op.
        fetch, _ = _page_fetcher([[_receipt(8, payload)]])
        summary = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=fetch,
        )

        assert summary.fetched == 1
        assert summary.duplicates == 1
        assert summary.replayed == 0

    def test_failed_staged_event_retries_after_cursor_advances(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        outcomes = iter(
            [
                {"processed": False},
                {"result": {"action": "noop"}},
            ]
        )
        monkeypatch.setattr(
            script,
            "handle_webhook_event",
            lambda _event, _db, **_kwargs: next(outcomes),
        )
        payload = _publish_payload([])

        first = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=lambda **_kwargs: [_receipt(1, payload)],
        )
        second = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=lambda **_kwargs: [],
        )

        assert first.failed == 1
        assert first.pending == 1
        assert second.fetched == 0
        assert second.replayed == 1
        assert second.pending == 0
        staged = db_manager.webhook_pull_receipts.get_receipt(
            script._endpoint_key("https://api.example/v1/admin/webhook/receipts"), 1
        )
        assert staged is not None
        assert staged.status == "processed"
        assert staged.attempts == 2
        assert staged.payload is None

    def test_failed_event_blocks_later_ids_until_recovery(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        first_payload = _publish_payload([])
        first_payload["commit_sha"] = "first-event"
        second_payload = _publish_payload([])
        second_payload["commit_sha"] = "second-event"
        calls: list[str] = []

        def handler(event, _db, **_kwargs):
            calls.append(event.commit_sha)
            if len(calls) == 1:
                return {"processed": False}
            return {"result": {"action": "noop"}}

        monkeypatch.setattr(script, "handle_webhook_event", handler)
        first_pass = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=lambda **_kwargs: [
                _receipt(1, first_payload),
                _receipt(2, second_payload),
            ],
        )
        later = db_manager.webhook_pull_receipts.get_receipt(
            script._endpoint_key("https://api.example/v1/admin/webhook/receipts"), 2
        )
        assert first_pass.failed == 1
        assert first_pass.pending == 2
        assert calls == ["first-event"]
        assert later is not None
        assert later.status == "received"
        assert later.attempts == 0

        recovered = script.pull_receipts(
            db_manager,
            endpoint="https://api.example/v1/admin/webhook/receipts",
            token="token",
            fetcher=lambda **_kwargs: [],
        )
        assert recovered.replayed == 2
        assert recovered.pending == 0
        assert calls == ["first-event", "first-event", "second-event"]

    def test_retryable_unmatched_callback_reconverges_after_attempt_is_recorded(
        self, db_manager: DatabaseManager
    ):
        endpoint = "https://api.example/v1/admin/webhook/receipts"
        payload = _publish_payload([REFINERY_ID])
        fetch, _ = _page_fetcher([[_receipt(7, payload)]])

        first = script.pull_receipts(
            db_manager,
            endpoint=endpoint,
            token="token",
            fetcher=fetch,
        )

        assert first.fetched == 1
        assert first.business_attention == 1
        assert first.failed == 1
        assert first.pending == 1

        # The callback arrived before local PR state was committed. Once the
        # exact attempt exists, ordinary retry of the staged receipt converges.
        article_id = _seed_pr_created(db_manager)
        retry = script.pull_receipts(
            db_manager,
            endpoint=endpoint,
            token="token",
            fetcher=lambda **_kwargs: [],
        )

        assert retry.fetched == 0
        assert retry.replayed == 1
        assert retry.business_attention == 0
        assert retry.failed == 0
        assert retry.pending == 0
        with db_manager.get_session() as session:
            article = session.query(Article).filter_by(id=article_id).first()
            assert article is not None
            assert article.processing_status == "completed"
            assert article.published_at is not None
            assert article.published_url == DEPLOY_URL
        [attempt] = db_manager.lifecycle.get_publication_attempts_for_article(
            article_id
        )
        assert attempt.state == "COMPLETED"

        receipt = db_manager.webhook_receipts.get_receipt("id:v1:1:publish_complete")
        assert receipt is not None
        assert receipt.status == "processed"
        assert receipt.result["needs_attention"] is False

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

    def test_repeated_capped_passes_progress_past_the_previous_window(
        self, db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ):
        # A small cap exercises the same repeated-window boundary as the
        # production default (2000) without creating thousands of SQLite rows
        # under the unit-test timeout.
        history_size = 9
        max_per_pass = 4
        page_size = 2
        payload = _publish_payload([])
        seen_ids: list[int] = []

        def fetch(*, endpoint, token, after_id, limit):
            start = (after_id or 0) + 1
            rows = [
                _receipt(receipt_id, payload)
                for receipt_id in range(start, min(start + limit, history_size + 1))
            ]
            seen_ids.extend(row["id"] for row in rows)
            return rows

        monkeypatch.setattr(
            script,
            "handle_webhook_event",
            lambda _event, _db, **_kwargs: {"result": {"action": "noop"}},
        )

        for _ in range(3):
            script.pull_receipts(
                db_manager,
                endpoint="https://api.example/v1/admin/webhook/receipts",
                token="token",
                limit=page_size,
                max_receipts=max_per_pass,
                fetcher=fetch,
            )

        assert seen_ids == list(range(1, history_size + 1))

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


class TestPageValidation:
    def test_diagnostics_and_cursor_identity_redact_endpoint_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        endpoint = (
            "https://user:password@example.test/v1/receipts"
            "?token=query-secret#private-fragment"
        )
        safe_endpoint = "https://example.test/v1/receipts"

        assert script._endpoint_key(endpoint) == safe_endpoint

        class Response:
            status_code = 404

        with pytest.raises(script.PullError) as response_error:
            script._decode_receipts(Response(), endpoint)
        assert safe_endpoint in str(response_error.value)
        assert "password" not in str(response_error.value)
        assert "query-secret" not in str(response_error.value)
        assert "private-fragment" not in str(response_error.value)

        def fail_request(_endpoint, **_kwargs):
            raise script.requests.ConnectionError(f"failed request to {endpoint}")

        monkeypatch.setattr(script.requests, "get", fail_request)
        with pytest.raises(script.PullError) as transport_error:
            script._request_page(endpoint, "header-secret", {})
        assert safe_endpoint in str(transport_error.value)
        assert all(
            secret not in str(transport_error.value)
            for secret in (
                "password",
                "query-secret",
                "private-fragment",
                "header-secret",
            )
        )

    def test_ids_must_be_strictly_ascending(self):
        with pytest.raises(script.PullError, match="strictly ordered"):
            script._validate_page([_receipt(2, {}), _receipt(1, {})], None)

    def test_page_cannot_repeat_or_rewind_the_cursor(self):
        with pytest.raises(script.PullError, match="strictly ordered"):
            script._validate_page([_receipt(5, {})], 5)

    def test_non_object_receipts_are_not_silently_dropped(self):
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"receipts": [_receipt(1, {}), "invalid"]}

        with pytest.raises(script.PullError, match="non-object receipt"):
            script._decode_receipts(Response(), "https://api.example/receipts")

    def test_error_body_is_not_copied_into_pull_error(self):
        class Response:
            status_code = 500
            text = "private receipt payload"

        with pytest.raises(script.PullError) as exc_info:
            script._decode_receipts(Response(), "https://api.example/receipts")
        assert "private receipt payload" not in str(exc_info.value)

    def test_failed_event_does_not_return_success(
        self,
        db_manager: DatabaseManager,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.setattr(script, "DatabaseManager", lambda: db_manager)
        monkeypatch.setattr(
            script,
            "fetch_page",
            lambda **_kwargs: [_receipt(1, _publish_payload([]))],
        )
        monkeypatch.setattr(
            script,
            "handle_webhook_event",
            lambda _event, _db, **_kwargs: {"processed": False, "error": "injected"},
        )
        monkeypatch.setenv("ADMIN_API_KEY", "token")
        monkeypatch.setenv("BACKEND_ADMIN_URL", "https://api.example")
        monkeypatch.setattr(sys, "argv", ["pull_webhook_receipts.py"])

        assert script.main() != 0
        assert "failed=1" in capsys.readouterr().out
