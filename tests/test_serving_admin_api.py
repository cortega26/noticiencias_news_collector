"""Tests for the admin API surface (`/v1/admin/*`).

Phase 1 of the Refinery GUI decoupling: a typed, authenticated, read-oriented
HTTP surface that the GUI can consume instead of reaching into the backend
in-process. Auth mirrors the webhook pattern (constant-time Bearer,
fail-closed outside development) with a distinct `ADMIN_API_KEY`.
"""

from __future__ import annotations

import json
import os
import time
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
# CORS (Phase 2: separate static GUI calling the admin surface)
# ---------------------------------------------------------------------------


def test_admin_cors_allowslisted_origin_gets_headers(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/analytics",
            headers={**_admin_headers(), "Origin": "http://localhost:4322"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:4322"
        )

        preflight = api_client.options(
            "/v1/admin/articles",
            headers={
                "Origin": "http://localhost:4322",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert (
            preflight.headers.get("access-control-allow-origin")
            == "http://localhost:4322"
        )
        assert (
            "authorization"
            in preflight.headers.get("access-control-allow-headers", "").lower()
        )


def test_admin_cors_nonallowlisted_origin_no_header(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/analytics",
            headers={**_admin_headers(), "Origin": "http://evil.example"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


def test_admin_cors_env_override(db_manager: DatabaseManager, tmp_path) -> None:
    from fastapi.testclient import TestClient as _TestClient

    from news_collector.serving import create_app as _create_app

    with (
        patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "dev-admin-token",
                "ADMIN_CORS_ORIGINS": "http://gui.local",
            },
        ),
    ):
        app = _create_app(database_manager=db_manager)
        client = _TestClient(app)
        response = client.get(
            "/v1/admin/analytics",
            headers={**_admin_headers(), "Origin": "http://gui.local"},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://gui.local"


# ---------------------------------------------------------------------------
# Triage list
# ---------------------------------------------------------------------------


def test_admin_articles_tolerates_null_score_components(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Regression: production data carries null component values (e.g.
    "engagement": null). The admin payload must not 500 on them — the
    contract allows Optional[float] component values."""
    with db_manager.get_session() as session:
        article = (
            session.query(Article)
            .filter(Article.processing_status == "pending")
            .first()
        )
        components = dict(article.score_components or {})
        components["engagement"] = None
        article.score_components = components
        session.add(article)

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/articles", params={"status": "pending"}, headers=_admin_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"][0]["score_components"]["engagement"] is None


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


# ---------------------------------------------------------------------------
# Phase 3: operational surface
# ---------------------------------------------------------------------------


def test_admin_reprocess_resets_to_pending(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    with db_manager.get_session() as session:
        article = (
            session.query(Article)
            .filter(Article.processing_status == "completed")
            .first()
        )
        article_id = article.id
        article.error_message = "boom"
        article.article_metadata = {
            "audit": {"state": "failed"},
            "publication": {"state": "REJECTED"},
        }
        session.add(article)

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            f"/v1/admin/articles/{article_id}/reprocess",
            json={},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        assert article.processing_status == "pending"
        assert article.error_message is None
        assert "audit" not in article.article_metadata
        assert "publication" not in article.article_metadata


def test_admin_reprocess_unknown_id_404(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/articles/9999/reprocess", json={}, headers=_admin_headers()
        )
        assert response.status_code == 404


def test_admin_collect_starts_and_status_lifecycle(
    api_client: TestClient, monkeypatch
) -> None:
    import threading

    from news_collector.serving import api as serving_api

    started = threading.Event()
    release = threading.Event()

    class _FakeSystem:
        def initialize(self) -> bool:
            started.set()
            return True

        async def run_collection_cycle(self, dry_run: bool = False):
            release.wait(timeout=10)
            return {"status": "ok", "sources_processed": 3}

        async def shutdown(self):
            return None

        def export_latest_articles(self, file_path=None, limit=50):
            return {}

    def _fake_create_system(*args, **kwargs):
        return _FakeSystem()

    monkeypatch.setattr(
        "news_collector.system.create_system", _fake_create_system, raising=False
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/collect", json={"dry_run": True}, headers=_admin_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["run_id"].startswith("collect-")
        assert body["status"] == "queued"

        assert started.wait(timeout=10), "collection thread never started"

        status = api_client.get(
            "/v1/admin/collect/status", headers=_admin_headers()
        ).json()
        assert status["status"] == "running"

        release.set()
        # The thread finishes async; poll until done.
        for _ in range(50):
            status = api_client.get(
                "/v1/admin/collect/status", headers=_admin_headers()
            ).json()
            if status["status"] == "succeeded":
                break
            time.sleep(0.1)
        assert status["status"] == "succeeded"
        assert status["summary"].get("sources_processed") == 3


def test_admin_sources_list_toggle_reset(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    # ALL_SOURCES comes from config/sources.yaml; pick a real id and seed
    # its circuit row so toggle/reset have something to act on.
    from news_collector.config.sources import ALL_SOURCES

    source_id = next(iter(sorted(ALL_SOURCES)))
    with db_manager.get_session() as session:
        src = session.query(Source).filter(Source.id == source_id).first()
        if src is None:
            session.add(
                Source(
                    id=source_id,
                    name=str(ALL_SOURCES[source_id].get("name", source_id)),
                    url=str(ALL_SOURCES[source_id].get("url", "https://example.com")),
                    credibility_score=0.5,
                    category="science",
                )
            )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/sources", headers=_admin_headers())
        assert response.status_code == 200
        body = response.json()
        ids = [s["source_id"] for s in body["sources"]]
        assert source_id in ids

        response = api_client.post(
            f"/v1/admin/sources/{source_id}/toggle",
            json={"active": False},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        with db_manager.get_session() as session:
            src = session.query(Source).filter(Source.id == source_id).first()
            assert src.is_active is False

        response = api_client.post(
            f"/v1/admin/sources/{source_id}/reset", json={}, headers=_admin_headers()
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        response = api_client.post(
            "/v1/admin/sources/nope/toggle",
            json={"active": True},
            headers=_admin_headers(),
        )
        assert response.status_code == 404


def test_admin_prompts_roundtrip(api_client: TestClient, tmp_path, monkeypatch) -> None:
    import yaml

    from news_collector.serving import api as serving_api

    prompts_file = tmp_path / "prompts.yaml"
    prompts_file.write_text(
        yaml.safe_dump({"auditor": {"system": "Eres un auditor."}}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        serving_api,
        "Path",
        lambda *a, **k: prompts_file if "prompts" in str(a[0]) else Path(*a),
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/prompts", headers=_admin_headers())
        assert response.status_code == 200
        assert response.json()["prompts"]["auditor"]["system"] == "Eres un auditor."

        response = api_client.post(
            "/v1/admin/prompts",
            json={"prompts": {"editor": {"system": "Nuevo prompt."}}},
            headers=_admin_headers(),
        )
        assert response.status_code == 200

        reloaded = yaml.safe_load(prompts_file.read_text(encoding="utf-8"))
        assert reloaded["editor"]["system"] == "Nuevo prompt."


def test_admin_images_queue_reads_briefs(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    from pathlib import Path as _Path

    from news_collector.contracts.image_brief import ImageBriefModel
    from news_collector.logic.workflows.image_briefs import ImageBriefStore
    from news_collector.serving import api as serving_api

    store = ImageBriefStore(tmp_path)
    store.save_brief(
        ImageBriefModel(
            slug="test-brief",
            article_id="123",
            reason="missing_source_image",
            topic="salud",
            news_angle="nuevo hallazgo",
            scientific_domain="medicina",
            subject_scene="laboratorio",
            tone="informativo",
            draft_alt_text="Imagen de laboratorio",
            generated_prompt="Genera una imagen de un laboratorio moderno con un hallazgo medico.",
            updated_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.image_briefs.ImageBriefStore",
        lambda *a: store,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get("/v1/admin/images", headers=_admin_headers())
        assert response.status_code == 200
        briefs = response.json()["briefs"]
        assert any(b["slug"] == "test-brief" for b in briefs)


def test_admin_config_save_roundtrip_and_secret_drop(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    """Regression: POST /v1/admin/config must accept the full config dict,
    validate it through the schema (not a partial model_copy that mangles
    nested sections), never persist secrets, and report the snapshot meta."""
    import copy

    from noticiencias.config_manager import load_config as _load

    from news_collector.config import settings as _settings
    from news_collector.serving import api as serving_api

    # Point the serving endpoint's config IO at a tmp file.
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        Path("config.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    real_load = serving_api.load_config
    real_save = _settings.refresh_runtime_config

    monkeypatch.setattr(serving_api, "load_config", lambda: _load(cfg_file))

    def _fake_save(validated):
        _save_config_to(cfg_file, validated)

    # save_config writes to metadata.config_path; wire it to the tmp file.
    def _save_config_to(path, validated):
        from noticiencias.config_manager import save_config

        save_config(validated, path)

    monkeypatch.setattr(
        _settings, "refresh_runtime_config", lambda cfg=None: real_save(real_load())
    )

    full = _load(cfg_file).model_dump(mode="python")
    # A real client sends JSON: paths become strings, Path objects drop out.
    full = json.loads(json.dumps(full, default=str))
    full["github"]["token"] = "SHOULD-NOT-PERSIST"
    full["app"]["environment"] = "development"

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/config", json=full, headers=_admin_headers()
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["environment"] == "development"

    saved = cfg_file.read_text(encoding="utf-8")
    assert "SHOULD-NOT-PERSIST" not in saved
    assert "[paths]" in saved  # full sections preserved, not mangled

    # Invalid full config → 422 and no file write.
    bad = copy.deepcopy(full)
    bad["scoring"]["weights"]["source_credibility"] = 1.5  # sum > 1
    before = cfg_file.read_text(encoding="utf-8")
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/config", json=bad, headers=_admin_headers()
        )
        assert response.status_code == 422
    assert cfg_file.read_text(encoding="utf-8") == before


def test_admin_config_partial_patch_merges(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    """A partial payload (only github) must merge over the current full
    config and save without mangling other sections."""
    from noticiencias.config_manager import load_config as _load

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        Path("config.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    from news_collector.serving import api as serving_api

    monkeypatch.setattr(serving_api, "load_config", lambda: _load(cfg_file))

    from noticiencias.config_manager import save_config as _save_config

    real_save = _save_config
    real_refresh = __import__(
        "news_collector.config.settings", fromlist=["refresh_runtime_config"]
    ).refresh_runtime_config

    def _save_to_tmp(validated, path=None):
        return real_save(validated, cfg_file)

    monkeypatch.setattr("noticiencias.config_manager.save_config", _save_to_tmp)
    monkeypatch.setattr(
        "news_collector.config.settings.refresh_runtime_config",
        lambda cfg=None: real_refresh(_load()),
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/config",
            json={
                "github": {
                    "target_repo_url": "https://github.com/cortega26/noticiencias.git"
                }
            },
            headers=_admin_headers(),
        )
        assert response.status_code == 200, response.text

    saved = cfg_file.read_text(encoding="utf-8")
    assert "[paths]" in saved
    assert "[scoring]" in saved
    assert "[database]" in saved
