"""Tests for the frontend CI webhook endpoint."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

pytestmark = pytest.mark.e2e


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    """SQLite database with a test article in 'publishing' state."""
    db_path = tmp_path / "webhook.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    with manager.get_session() as session:
        article = Article(
            title="Test Article for Webhook",
            url="https://example.com/test-webhook",
            summary="A test article",
            source_id="test-source",
            source_name="Test Source",
            category="science",
            processing_status="publishing",
            article_metadata={
                "publishing_branch": "publish/test-article-123",
                "publication": {
                    "state": "PR_CREATED",
                    "pr_url": "https://github.com/cortega26/noticiencias/pull/99",
                },
            },
        )
        session.add(article)
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture()
def api_client(db_manager: DatabaseManager) -> TestClient:
    """FastAPI TestClient wired to the test database."""
    app = create_app(database_manager=db_manager)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_webhook_auth_valid_token(api_client: TestClient) -> None:
    """202 when Bearer token matches WEBHOOK_API_KEY."""
    with patch.dict(os.environ, {"WEBHOOK_API_KEY": "secret-token"}):
        payload = _make_publish_payload()
        response = api_client.post(
            "/api/v1/webhook/frontend",
            json=payload,
            headers={"Authorization": "Bearer secret-token"},
        )
        assert response.status_code == 202


def test_webhook_auth_invalid_token(api_client: TestClient) -> None:
    """403 when Bearer token does not match."""
    with patch.dict(os.environ, {"WEBHOOK_API_KEY": "secret-token"}):
        payload = _make_publish_payload()
        response = api_client.post(
            "/api/v1/webhook/frontend",
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 403


def test_webhook_auth_missing_header(api_client: TestClient) -> None:
    """401 when Authorization header is missing and key is configured."""
    with patch.dict(os.environ, {"WEBHOOK_API_KEY": "secret-token"}):
        payload = _make_validation_payload("pass")
        response = api_client.post(
            "/api/v1/webhook/frontend",
            json=payload,
        )
        assert response.status_code == 401


def test_webhook_no_auth_in_dev_mode(api_client: TestClient) -> None:
    """202 without auth when WEBHOOK_API_KEY is not set (dev mode)."""
    with patch.dict(os.environ, clear=True):
        payload = _make_validation_payload("pass")
        response = api_client.post(
            "/api/v1/webhook/frontend",
            json=payload,
        )
        assert response.status_code == 202


# ---------------------------------------------------------------------------
# Event processing tests
# ---------------------------------------------------------------------------


def test_validation_result_fail_rejects_articles(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Articles in publishing state are marked as rejected on fail."""
    payload = _make_validation_payload("fail")

    response = api_client.post("/api/v1/webhook/frontend", json=payload)

    assert response.status_code == 202
    assert response.json()["event"] == "validation_result"

    with db_manager.get_session() as session:
        article = session.query(Article).first()
        assert article is not None
        assert article.processing_status == "rejected"


def test_validation_result_pass_does_not_change_articles(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Articles remain in publishing state when validation passes."""
    payload = _make_validation_payload("pass")

    response = api_client.post("/api/v1/webhook/frontend", json=payload)

    assert response.status_code == 202

    with db_manager.get_session() as session:
        article = session.query(Article).first()
        assert article.processing_status == "publishing"


def test_publish_complete_marks_articles_live(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Articles are marked completed with published_at and published_url."""
    payload = _make_publish_payload()

    response = api_client.post("/api/v1/webhook/frontend", json=payload)

    assert response.status_code == 202

    with db_manager.get_session() as session:
        article = session.query(Article).first()
        assert article is not None
        assert article.processing_status == "completed"
        assert article.published_at is not None
        assert article.published_url == "https://noticiencias.com"


def test_webhook_branch_no_match_does_not_change_articles(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Articles on a different branch are not affected."""
    payload = _make_publish_payload(branch="some-other-branch")

    response = api_client.post("/api/v1/webhook/frontend", json=payload)

    assert response.status_code == 202

    with db_manager.get_session() as session:
        article = session.query(Article).first()
        # Branch doesn't match, so article should still be publishing
        assert article.processing_status == "publishing"
        assert article.published_at is None


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


def test_webhook_unknown_event(api_client: TestClient) -> None:
    """422 when event type is not recognized."""
    payload = {
        "event": "unknown_event_type",
        "commit_sha": "abc123",
        "branch": "main",
        "status": "pass",
        "diagnostics": [],
        "frontend_ref": "abc123",
        "run_url": "https://github.com/org/repo/actions/runs/1",
    }
    response = api_client.post("/api/v1/webhook/frontend", json=payload)
    assert response.status_code == 422


def test_webhook_missing_required_fields(api_client: TestClient) -> None:
    """422 when required fields are missing from payload."""
    payload: dict = {"event": "validation_result"}
    response = api_client.post("/api/v1/webhook/frontend", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def _make_validation_payload(
    status: str, branch: str = "publish/test-article-123"
) -> dict:
    """Build a valid validation_result payload."""
    return {
        "event": "validation_result",
        "commit_sha": "abc123def",
        "branch": branch,
        "status": status,
        "diagnostics": [
            {
                "check": "frontmatter-dates",
                "status": status,
                "filesCount": 12,
                "errors": (
                    ["Invalid date in article.md"] if status == "fail" else []
                ),
            }
        ],
        "frontend_ref": "abc123def",
        "run_url": (
            "https://github.com/cortega26/noticiencias/actions/runs/123"
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _make_publish_payload(
    branch: str = "publish/test-article-123",
) -> dict:
    """Build a valid publish_complete payload."""
    return {
        "event": "publish_complete",
        "commit_sha": "abc123def",
        "branch": branch,
        "status": "success",
        "diagnostics": [
            {
                "check": "deploy",
                "status": "pass",
                "article_count": 387,
                "deploy_url": "https://noticiencias.com",
            }
        ],
        "frontend_ref": "abc123def",
        "run_url": (
            "https://github.com/cortega26/noticiencias/actions/runs/456"
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Publication-identity contract tests (Plan 021 Step 1)
# ---------------------------------------------------------------------------


def test_publication_ids_valid_list_accepted() -> None:
    """Valid publication_ids list passes validation."""
    from news_collector.contracts.webhook import ValidationResultEvent

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = ["refinery-abc", "refinery-def"]
    event = ValidationResultEvent.model_validate(payload)
    assert event.publication_ids == ["refinery-abc", "refinery-def"]


def test_publication_ids_empty_list_accepted() -> None:
    """Empty publication_ids is accepted (optional for non-mutation callbacks)."""
    from news_collector.contracts.webhook import ValidationResultEvent

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = []
    event = ValidationResultEvent.model_validate(payload)
    assert event.publication_ids == []


def test_publication_ids_rejects_non_strings() -> None:
    """Non-string entries in publication_ids are rejected."""
    from news_collector.contracts.webhook import ValidationResultEvent
    from pydantic import ValidationError

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = [42]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)


def test_publication_ids_rejects_empty_strings() -> None:
    """Empty strings in publication_ids are rejected."""
    from news_collector.contracts.webhook import ValidationResultEvent
    from pydantic import ValidationError

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = ["  "]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)


def test_publication_ids_rejects_oversized_list() -> None:
    """Lists exceeding MAX_PUBLICATION_IDS are rejected."""
    from news_collector.contracts.webhook import ValidationResultEvent
    from pydantic import ValidationError

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = [f"id-{i}" for i in range(201)]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)


def test_publication_ids_preserves_commit_sha_as_audit_context() -> None:
    """commit_sha and branch are preserved alongside publication_ids."""
    from news_collector.contracts.webhook import ValidationResultEvent

    payload = _make_validation_payload("pass")
    payload["publication_ids"] = ["refinery-1"]
    event = ValidationResultEvent.model_validate(payload)
    assert event.commit_sha == "abc123def"
    assert event.branch == "publish/test-article-123"
    assert event.publication_ids == ["refinery-1"]
