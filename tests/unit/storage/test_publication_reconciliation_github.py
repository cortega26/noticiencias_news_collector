"""Plan 198: close stale ``PR_CREATED`` attempts from GitHub PR evidence.

Real SQLite through ``DatabaseManager``; the PR reader is a fake callable, so
no network is involved. ``GitHubPublisher.get_pull_request_state`` is covered
separately with a mocked ``requests.get``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import requests

from news_collector.components.publishing.github_publisher import GitHubPublisher
from news_collector.logic.workflows.publication_reconciliation import (
    PublicationReconciliationWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, PublicationAttemptRecord

PR_NUMBER = 77
PR_URL = f"https://github.com/cortega26/noticiencias/pull/{PR_NUMBER}"
SHA = hashlib.sha256(b"generated post").hexdigest()
MERGED_AT = "2026-10-12T15:30:00Z"


@pytest.fixture()
def db_manager(tmp_path) -> Iterator[DatabaseManager]:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "gh.db"})
    yield manager
    manager.close()


def _later() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _article(db: DatabaseManager, suffix: str) -> int:
    with db.get_session() as session:
        article = Article(
            title=f"GitHub reconcile {suffix}",
            url=f"https://example.com/gh/{suffix}",
            summary="s",
            source_id="test-source",
            source_name="Test Source",
            category="science",
            processing_status="pending",
        )
        session.add(article)
        session.flush()
        return int(article.id)


def _pr_created(db: DatabaseManager, suffix: str = "a", *, token: bool = True) -> int:
    article_id = _article(db, suffix)
    attempt_token = f"attempt-{suffix}" if token else None
    db.mark_article_publishing(
        article_id, f"content/update-{suffix}", publication_attempt_id=attempt_token
    )
    db.mark_article_published(
        article_id,
        PR_URL,
        f"refinery-{suffix}",
        publication_attempt_id=attempt_token,
        content_sha256=SHA,
    )
    return article_id


def _attempt(db: DatabaseManager, article_id: int):
    return db.lifecycle.get_publication_attempts_for_article(article_id)[-1]


def _reader(state: dict[str, Any] | None):
    calls: list[str] = []

    def read(pr_url: str) -> dict[str, Any] | None:
        calls.append(pr_url)
        return state

    read.calls = calls  # type: ignore[attr-defined]
    return read


MERGED = {
    "state": "closed",
    "merged": True,
    "merged_at": MERGED_AT,
    "closed_at": MERGED_AT,
    "merge_commit_sha": "deadbeef",
}
CLOSED = {
    "state": "closed",
    "merged": False,
    "merged_at": None,
    "closed_at": "2026-10-13T10:00:00Z",
    "merge_commit_sha": None,
}


def _run(db: DatabaseManager, reader, *, dry_run: bool = False):
    return PublicationReconciliationWorkflow(db, pull_request_state=reader).run(
        dry_run=dry_run, now=_later()
    )


def test_merged_pr_completes_attempt_and_article(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)

    summary = _run(db_manager, _reader(MERGED))

    assert summary.completed == 1
    assert _attempt(db_manager, article_id).state == "COMPLETED"
    article = db_manager.articles.get_article_by_id(article_id)
    assert article.processing_status == "completed"
    assert article.published_url == "https://noticiencias.com/"
    published_at = article.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    assert published_at == datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)
    events = db_manager.lifecycle.get_publication_events_for_attempt(
        _attempt(db_manager, article_id).id
    )
    deployed = [e for e in events if e.event_type == "deployed"]
    assert deployed and deployed[0].details["source"] == "github_reconciliation"
    assert deployed[0].details["merge_commit_sha"] == "deadbeef"
    assert deployed[0].details["content_sha256"] == SHA


def test_closed_unmerged_pr_rejects_attempt_and_article(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)

    summary = _run(db_manager, _reader(CLOSED))

    assert summary.rejected == 1
    assert _attempt(db_manager, article_id).state == "REJECTED"
    article = db_manager.articles.get_article_by_id(article_id)
    assert article.processing_status == "rejected"
    assert article.published_at is None


@pytest.mark.parametrize(
    "state",
    [
        {"state": "open", "merged": False},
        None,
        {"state": "closed", "merged": True, "merged_at": None},
        {"state": "weird"},
    ],
)
def test_open_or_ambiguous_pr_changes_nothing(db_manager: DatabaseManager, state):
    article_id = _pr_created(db_manager)

    summary = _run(db_manager, _reader(state))

    assert summary.completed == summary.rejected == 0
    assert summary.stale_pr_open == 1
    assert _attempt(db_manager, article_id).state == "PR_CREATED"
    assert (
        db_manager.articles.get_article_by_id(article_id).processing_status
        == "publishing"
    )


def test_legacy_attempt_without_token_projects_when_latest(
    db_manager: DatabaseManager,
):
    article_id = _pr_created(db_manager, "legacy", token=False)

    _run(db_manager, _reader(MERGED))

    assert _attempt(db_manager, article_id).state == "COMPLETED"
    assert (
        db_manager.articles.get_article_by_id(article_id).processing_status
        == "completed"
    )


def test_non_current_attempt_updates_attempt_only(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)
    with db_manager.get_session() as session:
        article = session.get(Article, article_id)
        metadata = dict(article.article_metadata or {})
        metadata["publication_attempt_id"] = "a-newer-attempt"
        article.article_metadata = metadata

    _run(db_manager, _reader(MERGED))

    assert _attempt(db_manager, article_id).state == "COMPLETED"
    article = db_manager.articles.get_article_by_id(article_id)
    assert article.processing_status == "publishing"
    assert article.published_at is None


def test_dry_run_writes_nothing(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)

    summary = _run(db_manager, _reader(MERGED), dry_run=True)

    assert summary.completed == 1
    assert _attempt(db_manager, article_id).state == "PR_CREATED"
    assert (
        db_manager.articles.get_article_by_id(article_id).processing_status
        == "publishing"
    )


def test_second_pass_is_idempotent(db_manager: DatabaseManager):
    _pr_created(db_manager)
    reader = _reader(MERGED)
    _run(db_manager, reader)

    second = _run(db_manager, reader)

    assert second.scanned == 0
    assert len(reader.calls) == 1


def test_without_reader_behaviour_is_unchanged(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)

    summary = PublicationReconciliationWorkflow(db_manager).run(now=_later())

    assert summary.stale_pr_open == 1
    assert _attempt(db_manager, article_id).state == "PR_CREATED"


def test_repository_refuses_non_pr_created_attempt(db_manager: DatabaseManager):
    article_id = _pr_created(db_manager)
    attempt_id = _attempt(db_manager, article_id).id
    with db_manager.get_session() as session:
        session.get(PublicationAttemptRecord, attempt_id).state = "REJECTED"

    result = db_manager.lifecycle.apply_reconciled_pull_request_outcome(
        attempt_id,
        target_state="COMPLETED",
        evidence={"source": "github_reconciliation"},
        deploy_url="https://noticiencias.com/",
        occurred_at=datetime.now(timezone.utc),
    )

    assert result.transitioned is False
    assert _attempt(db_manager, article_id).state == "REJECTED"


class _Response:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self) -> Any:
        return self._payload


def test_get_pull_request_state_parses_merged(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    def fake_get(url, **kwargs):
        seen.append(url)
        return _Response(
            {
                "state": "closed",
                "merged_at": MERGED_AT,
                "closed_at": MERGED_AT,
                "merge_commit_sha": "abc",
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)

    state = GitHubPublisher(github_token="t").get_pull_request_state(PR_URL)

    assert seen == [
        f"https://api.github.com/repos/cortega26/noticiencias/pulls/{PR_NUMBER}"
    ]
    assert state == {
        "state": "closed",
        "merged": True,
        "merged_at": MERGED_AT,
        "closed_at": MERGED_AT,
        "merge_commit_sha": "abc",
    }


@pytest.mark.parametrize(
    "url", ["", "https://gitlab.com/a/b/pull/1", "https://github.com/a/b/issues/1"]
)
def test_get_pull_request_state_rejects_non_pr_urls(
    monkeypatch: pytest.MonkeyPatch, url: str
):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no call"))

    assert GitHubPublisher(github_token="t").get_pull_request_state(url) is None


def test_get_pull_request_state_returns_none_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response({}, status=404))

    assert GitHubPublisher(github_token="t").get_pull_request_state(PR_URL) is None


def test_get_pull_request_state_without_token_sends_no_authorization(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[dict[str, str]] = []

    def fake_get(url, **kwargs):
        seen.append(kwargs["headers"])
        return _Response({"state": "open", "merged_at": None})

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(requests, "get", fake_get)

    state = GitHubPublisher().get_pull_request_state(PR_URL)

    assert state is not None and state["state"] == "open"
    assert "Authorization" not in seen[0]
