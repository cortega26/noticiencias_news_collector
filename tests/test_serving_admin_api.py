"""Tests for the admin API surface (`/v1/admin/*`).

Phase 1 of the Refinery GUI decoupling: a typed, authenticated, read-oriented
HTTP surface that the GUI can consume instead of reaching into the backend
in-process. Auth mirrors the webhook pattern (constant-time Bearer,
fail-closed outside development) with a distinct `ADMIN_API_KEY`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ScoreLog, Source

pytestmark = pytest.mark.e2e


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    """SQLite database with articles in mixed processing states."""
    db_path = tmp_path / "admin_api.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    with manager.get_session() as session:
        session.add_all(
            [
                Source(
                    id="nature",
                    name="Nature",
                    url="https://nature.com",
                    credibility_score=0.95,
                    category="science",
                ),
                Source(
                    id="esa",
                    name="ESA",
                    url="https://esa.int",
                    credibility_score=0.9,
                    category="science",
                ),
                Source(
                    id="nejm",
                    name="NEJM",
                    url="https://nejm.org",
                    credibility_score=0.92,
                    category="health",
                ),
                Source(
                    id="mit_news",
                    name="MIT News",
                    url="https://news.mit.edu",
                    credibility_score=0.88,
                    category="science",
                ),
            ]
        )
        base_time = datetime.now(timezone.utc)
        seed = [
            {
                "title": "Pending CRISPR milestone",
                "url": "https://example.com/crispr-pending",
                "summary": "CRISPR trial advances",
                "source_id": "nature",
                "source_name": "Nature",
                "category": "science",
                "final_score": 0.91,
                "collected_date": base_time - timedelta(hours=2),
                "processing_status": "pending",
                "topics": ["science"],
                "components": {
                    "source_credibility": 0.95,
                    "recency": 0.88,
                    "content_quality": 0.9,
                    "engagement_potential": 0.8,
                },
                "strengths": ["Fuente altamente confiable"],
                "refinery_id": "refinery-pending-1",
            },
            {
                "title": "Rejected telescope survey",
                "url": "https://example.com/space-rejected",
                "summary": "Survey rejected by editor",
                "source_id": "esa",
                "source_name": "ESA",
                "category": "science",
                "final_score": 0.4,
                "collected_date": base_time - timedelta(days=1),
                "processing_status": "rejected",
                "topics": ["space"],
                "components": {
                    "source_credibility": 0.6,
                    "recency": 0.4,
                    "content_quality": 0.5,
                    "engagement_potential": 0.2,
                },
                "strengths": [],
                "refinery_id": "refinery-rejected-1",
            },
            {
                "title": "Completed metabolic study",
                "url": "https://example.com/health-completed",
                "summary": "Clinical trial results",
                "source_id": "nejm",
                "source_name": "NEJM",
                "category": "health",
                "final_score": 0.82,
                "collected_date": base_time - timedelta(days=2),
                "processing_status": "completed",
                "topics": ["health"],
                "components": {
                    "source_credibility": 0.92,
                    "recency": 0.55,
                    "content_quality": 0.8,
                    "engagement_potential": 0.76,
                },
                "strengths": ["Estudio clínico revisado por pares"],
                "refinery_id": None,
            },
            {
                "title": "In-flight fusion paper",
                "url": "https://example.com/fusion-publishing",
                "summary": "PR open, awaiting frontend checks",
                "source_id": "mit_news",
                "source_name": "MIT News",
                "category": "science",
                "final_score": 0.88,
                "collected_date": base_time - timedelta(hours=5),
                "processing_status": "publishing",
                "topics": ["energy"],
                "components": {
                    "source_credibility": 0.9,
                    "recency": 0.9,
                    "content_quality": 0.85,
                    "engagement_potential": 0.8,
                },
                "strengths": ["Cobertura exclusiva"],
                "refinery_id": "refinery-publishing-1",
            },
        ]
        for payload in seed:
            article = Article(
                title=payload["title"],
                url=payload["url"],
                summary=payload["summary"],
                source_id=payload["source_id"],
                source_name=payload["source_name"],
                category=payload["category"],
                final_score=payload["final_score"],
                collected_date=payload["collected_date"],
                processing_status=payload["processing_status"],
                article_metadata={
                    "enrichment": {"topics": payload["topics"]},
                    "publication": (
                        {"refinery_id": payload["refinery_id"], "state": "PR_CREATED"}
                        if payload["refinery_id"]
                        else {}
                    ),
                },
                score_components=payload["components"],
            )
            session.add(article)
            session.flush()
            session.add(
                ScoreLog(
                    article_id=article.id,
                    score_version="1.0",
                    final_score=payload["final_score"],
                    score_explanation={
                        "key_strengths": payload["strengths"],
                        "component_breakdown": {},
                    },
                    algorithm_weights={
                        "source_credibility": 0.25,
                        "recency": 0.25,
                        "content_quality": 0.25,
                        "engagement_potential": 0.25,
                    },
                )
            )
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture()
def api_client(db_manager: DatabaseManager) -> TestClient:
    app = create_app(database_manager=db_manager)
    return TestClient(app)


def _admin_headers(token: str = "dev-admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth (mirrors verify_webhook_token, distinct ADMIN_API_KEY)
# ---------------------------------------------------------------------------


def test_admin_auth_valid_token(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/analytics", headers=_admin_headers())
        assert response.status_code == 200


def test_admin_auth_invalid_token(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/analytics", headers=_admin_headers("wrong-token")
        )
        assert response.status_code == 403


def test_admin_auth_missing_header(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/analytics")
        assert response.status_code == 401


def test_admin_fails_closed_outside_development_without_key(
    api_client: TestClient,
) -> None:
    fake_runtime = MagicMock()
    fake_runtime.environment = "production"
    with (
        patch.dict(os.environ, clear=True),
        patch(
            "news_collector.serving.api.get_runtime_config", return_value=fake_runtime
        ),
    ):
        response = api_client.get("/v1/admin/analytics", headers=_admin_headers())
        assert response.status_code == 503


def test_admin_dev_mode_allows_without_key(api_client: TestClient) -> None:
    """Explicit development tier: unset key is the documented fail-open."""
    with patch.dict(os.environ, clear=True):
        response = api_client.get("/v1/admin/analytics", headers=_admin_headers())
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Triage list
# ---------------------------------------------------------------------------


def test_admin_articles_status_filter(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/articles", params={"status": "pending"}, headers=_admin_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "Pending CRISPR milestone"
        assert body["data"][0]["processing_status"] == "pending"
        assert body["data"][0]["refinery_id"] == "refinery-pending-1"
        assert "score_components" in body["data"][0]
        assert body["data"][0]["why_ranked"]
        assert body["filters"]["status"] == "pending"


def test_admin_articles_rejected_status(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/articles",
            params={"status": "rejected"},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "Rejected telescope survey"


def test_admin_articles_default_status_is_pending(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/articles", headers=_admin_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["filters"]["status"] == "pending"
        assert all(item["processing_status"] == "pending" for item in body["data"])


def test_admin_articles_pagination_is_deterministic(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        seen: set[int] = set()
        cursor = None
        while True:
            params = {"status": "completed", "page_size": 1}
            if cursor:
                params["cursor"] = cursor
            response = api_client.get(
                "/v1/admin/articles", params=params, headers=_admin_headers()
            )
            assert response.status_code == 200
            body = response.json()
            for item in body["data"]:
                assert item["id"] not in seen, f"Duplicate article {item['id']}"
                seen.add(item["id"])
            cursor = body["pagination"].get("next_cursor")
            if not cursor or body["pagination"]["returned"] < 1:
                break
        assert len(seen) == 1


def test_admin_articles_unknown_status_returns_422(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/articles",
            params={"status": "bogus"},
            headers=_admin_headers(),
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def test_admin_article_detail(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    with db_manager.get_session() as session:
        article = (
            session.query(Article)
            .filter(Article.processing_status == "pending")
            .first()
        )
        article_id = article.id
        article.content = "Full body of the pending article"
        metadata = dict(article.article_metadata or {})
        metadata["audit"] = {
            "state": "passed",
            "reason": "ok",
            "updated_at": "2026-08-13T00:00:00Z",
        }
        article.article_metadata = metadata
        session.add(article)

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            f"/v1/admin/articles/{article_id}", headers=_admin_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == article_id
        assert body["content"] == "Full body of the pending article"
        assert body["publication"]["refinery_id"] == "refinery-pending-1"
        assert body["audit"]["state"] == "passed"
        assert body["latest_score"] == 0.91


def test_admin_article_detail_unknown_id_returns_404(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/articles/9999", headers=_admin_headers())
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Source health
# ---------------------------------------------------------------------------


def test_admin_source_health_reads_export(
    api_client: TestClient, db_manager: DatabaseManager, tmp_path, monkeypatch
) -> None:
    export = {
        "nature": {
            "source_id": "nature",
            "source_name": "Nature",
            "feed_ok": True,
            "pipeline_ok": True,
            "content_ok": True,
            "articles_found": 12,
            "articles_saved": 10,
            "save_ratio": 0.833,
            "operational_state": "healthy_full_text",
        }
    }
    health_path = tmp_path / "exports" / "source_health.json"
    health_path.parent.mkdir(parents=True)
    health_path.write_text(json.dumps(export), encoding="utf-8")
    monkeypatch.setattr(
        "news_collector.serving.api.ADMIN_SOURCE_HEALTH_PATH", str(health_path)
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/sources/health", headers=_admin_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["sources"][0]["source_id"] == "nature"
        assert body["sources"][0]["articles_saved"] == 10


def test_admin_source_health_missing_file_returns_empty(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    missing = tmp_path / "nonexistent" / "source_health.json"
    monkeypatch.setattr(
        "news_collector.serving.api.ADMIN_SOURCE_HEALTH_PATH", str(missing)
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/sources/health", headers=_admin_headers())
        assert response.status_code == 200
        assert response.json()["sources"] == []


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_admin_analytics_envelope(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/analytics", headers=_admin_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["total_articles"] == 4
        assert body["stats"]
        assert body["source_perf"]
        assert isinstance(body["avg_score_overall"], float)
        assert "as_of" in body


# ---------------------------------------------------------------------------
# Config (sanitized allowlist)
# ---------------------------------------------------------------------------


def test_admin_config_excludes_secrets(api_client: TestClient) -> None:
    fake_config = MagicMock()
    fake_config.app.environment = "development"
    fake_config.app.debug = False
    fake_config.app.timezone = "UTC"
    fake_config.github.token = "PLANTED-SECRET"
    fake_config.github.target_repo_url = "https://github.com/cortega26/noticiencias"
    fake_config.github.source_repo_url = "https://github.com/cortega26/noticiencias"
    fake_config.ollama.model = "qwen3-next:80b"
    fake_config.scoring.weights = {"source_credibility": 0.25}

    with (
        patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}),
        patch("news_collector.serving.api.load_config", return_value=fake_config),
    ):
        response = api_client.get("/v1/admin/config", headers=_admin_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["environment"] == "development"
        assert body["github"]["target_repo_url"]
        assert body["ollama"]["model"]
        raw = json.dumps(body)
        assert "PLANTED-SECRET" not in raw
        assert "token" not in body["github"]


# ---------------------------------------------------------------------------
# Mutations (dispatch to existing idempotent storage transitions)
# ---------------------------------------------------------------------------


def test_admin_audit_status_update(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    with db_manager.get_session() as session:
        article = (
            session.query(Article)
            .filter(Article.processing_status == "pending")
            .first()
        )
        article_id = article.id

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            f"/v1/admin/articles/{article_id}/audit-status",
            json={"audit_status": "failed", "reason": "low signal"},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        assert article.article_metadata["audit"]["state"] == "failed"
        assert article.article_metadata["audit"]["reason"] == "low signal"


def test_admin_audit_status_unknown_id(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/articles/9999/audit-status",
            json={"audit_status": "failed"},
            headers=_admin_headers(),
        )
        assert response.status_code == 404


def test_admin_reject_by_refinery_id(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    with db_manager.get_session() as session:
        publishing = (
            session.query(Article)
            .filter(Article.processing_status == "publishing")
            .first()
        )
        publishing_id = publishing.id
        assert publishing_id == 4

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            f"/v1/admin/articles/{publishing_id}/reject",
            json={"reason": "duplicate content"},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == publishing_id).first()
        assert article.processing_status == "rejected"
        assert article.article_metadata["publication"]["state"] == "REJECTED"


def test_admin_reject_already_rejected_is_noop(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/articles/4/reject", json={}, headers=_admin_headers()
        )
        assert response.status_code == 200
        first = response.json()
        assert first["status"] == "ok"

        response = api_client.post(
            "/v1/admin/articles/4/reject", json={}, headers=_admin_headers()
        )
        assert response.status_code == 200
        assert response.json()["status"] == "noop"
