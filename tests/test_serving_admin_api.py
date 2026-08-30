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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ScoreLog, Source, WorkflowRun

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

        async def shutdown(self, close_db: bool = True):
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
        # Plan 060 / Phase 4a: a started run is 202, not 200 — and run_id
        # is now the workflow_runs row's own (stringified) integer id, not
        # a "collect-N" in-memory counter.
        assert response.status_code == 202
        body = response.json()
        assert body["run_id"].isdigit()
        assert body["status"] == "queued"

        assert started.wait(timeout=10), "collection thread never started"

        status = api_client.get(
            "/v1/admin/collect/status", headers=_admin_headers()
        ).json()
        assert status["status"] == "running"
        assert status["run_id"] == body["run_id"]

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

        # Regression (Plan 060): the run must not have disposed the shared
        # DatabaseManager singleton — a follow-up admin request still works
        # (before the fix, this 500'd with `SessionLocal is None`).
        after = api_client.get("/v1/admin/articles", headers=_admin_headers())
        assert after.status_code == 200


def test_admin_collect_concurrent_start_yields_one_202_one_409(
    api_client: TestClient, monkeypatch
) -> None:
    """Two collect requests while one is already queued/running must yield
    exactly one 202 (started) and one 409 (already_running, carrying the
    existing run's id in the body) — the master plan's acceptance
    criterion this phase exists to satisfy. The two calls are issued
    sequentially (not spawned as literal OS threads): the first call's
    INSERT commits — durably, before its dispatch thread starts, which is
    this phase's actual durability fix — before the second call's INSERT
    is attempted, so the second call deterministically hits
    `uq_workflow_runs_one_active_collection`. This exercises the identical
    DB-level single-flight enforcement true concurrent requests would hit;
    it does not depend on wall-clock thread interleaving."""
    import threading as _threading

    release = _threading.Event()

    class _FakeSystem:
        def initialize(self) -> bool:
            return True

        async def run_collection_cycle(self, dry_run: bool = False):
            release.wait(timeout=10)
            return {"status": "ok"}

        async def shutdown(self, close_db: bool = True):
            return None

        def export_latest_articles(self, file_path=None, limit=50):
            return {}

    monkeypatch.setattr(
        "news_collector.system.create_system", lambda *a, **k: _FakeSystem()
    )

    try:
        with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
            first = api_client.post(
                "/v1/admin/collect", json={"dry_run": True}, headers=_admin_headers()
            )
            second = api_client.post(
                "/v1/admin/collect", json={"dry_run": True}, headers=_admin_headers()
            )
    finally:
        release.set()

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [202, 409]
    started = first if first.status_code == 202 else second
    conflicted = second if first.status_code == 202 else first
    assert conflicted.json()["status"] == "running"
    assert conflicted.json()["run_id"] == started.json()["run_id"]


def test_admin_collect_status_unknown_run_id_returns_404_not_latest(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """An unrecognized run_id must return 404 and must never fall back to
    the latest run — the exact bug this phase fixes
    (pre-Phase-4a: `target = run_id if run_id in _admin_runs else None`
    fell through to `_latest_run_id` on any miss, returning 200 with the
    wrong run's status)."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        session.add(
            WorkflowRun(
                run_type="collection",
                status="succeeded",
                started_at=now,
                finished_at=now,
            )
        )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/collect/status",
            params={"run_id": "999999"},
            headers=_admin_headers(),
        )

    assert response.status_code == 404
    assert response.json()["run_id"] is None


def test_admin_collect_status_non_numeric_run_id_returns_404(
    api_client: TestClient,
) -> None:
    """A non-numeric run_id (e.g. the pre-Phase-4a "collect-N" format) can
    never match a workflow_runs.id — also 404, not a validation error."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/collect/status",
            params={"run_id": "collect-5"},
            headers=_admin_headers(),
        )
    assert response.status_code == 404


def test_admin_collect_restart_recovers_stale_running_row_to_interrupted(
    db_manager: DatabaseManager,
) -> None:
    """A process restart (simulated by constructing a fresh app and
    entering it as `with TestClient(app) as client:` — which actually
    triggers FastAPI's `lifespan` startup hook, unlike the bare
    `TestClient(app)` the shared `api_client` fixture uses, verified
    empirically not to run lifespan at all) deterministically recovers a
    stale `running` row to `interrupted` — not timer-dependent, exercised
    through the real app-startup boundary rather than by calling
    `CollectionRunWorkflow.recover_expired_leases()` directly."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        stale = WorkflowRun(
            run_type="collection",
            status="running",
            started_at=now - timedelta(hours=3),
            heartbeat_at=None,  # never heartbeat once — e.g. crashed immediately
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id

    app = create_app(database_manager=db_manager)
    with TestClient(app) as client:
        with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
            response = client.get(
                "/v1/admin/collect/status",
                params={"run_id": str(stale_id)},
                headers=_admin_headers(),
            )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interrupted"
    assert body["active"] is False


# ---------------------------------------------------------------------------
# Phase 4c: POST /v1/admin/publish + GET /v1/admin/publish/status
# ---------------------------------------------------------------------------


def test_admin_publish_requires_exactly_one_of_id_or_url(
    api_client: TestClient,
) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        neither = api_client.post(
            "/v1/admin/publish", json={}, headers=_admin_headers()
        )
        both = api_client.post(
            "/v1/admin/publish",
            json={"article_id": 1, "article_url": "https://x"},
            headers=_admin_headers(),
        )
    assert neither.status_code == 422
    assert both.status_code == 422


def test_admin_publish_lifecycle_and_db_survives(
    api_client: TestClient, monkeypatch, tmp_path
) -> None:
    """A publish run reaches `succeeded` with the PR url surfaced, and a
    follow-up admin request still works (Phase 4a regression guard)."""
    import threading as _threading

    release = _threading.Event()
    monkeypatch.chdir(tmp_path)  # workflow + fake both resolve the same rel path
    attempts = tmp_path / "data" / "runtime" / "publication_attempts"
    attempts.mkdir(parents=True)

    def _fake_main(**kwargs):
        release.wait(timeout=10)
        (attempts / "77.json").write_text(
            json.dumps(
                {
                    "article_id": "77",
                    "success": True,
                    "pr_url": "https://github.com/org/noticiencias/pull/9",
                    "final_slug": "x",
                    "stages": [],
                }
            ),
            encoding="utf-8",
        )
        return {"status": "success", "processed_count": 1}

    monkeypatch.setattr("apps.refinery.main.main", _fake_main, raising=False)

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        started = api_client.post(
            "/v1/admin/publish", json={"article_id": 77}, headers=_admin_headers()
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        running = api_client.get(
            "/v1/admin/publish/status",
            params={"run_id": run_id},
            headers=_admin_headers(),
        ).json()
        assert running["status"] in ("queued", "running")

        release.set()
        for _ in range(50):
            st = api_client.get(
                "/v1/admin/publish/status",
                params={"run_id": run_id},
                headers=_admin_headers(),
            ).json()
            if st["status"] == "succeeded":
                break
            time.sleep(0.1)
        assert st["status"] == "succeeded"
        assert st["pr_url"] == "https://github.com/org/noticiencias/pull/9"

        after = api_client.get("/v1/admin/articles", headers=_admin_headers())
        assert after.status_code == 200


def test_admin_publish_concurrent_yields_one_202_one_409(
    api_client: TestClient, monkeypatch
) -> None:
    import threading as _threading

    release = _threading.Event()
    monkeypatch.setattr(
        "apps.refinery.main.main",
        lambda **kw: (
            release.wait(timeout=10),
            {"status": "success", "processed_count": 1},
        )[1],
        raising=False,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        first = api_client.post(
            "/v1/admin/publish", json={"article_id": 1}, headers=_admin_headers()
        )
        second = api_client.post(
            "/v1/admin/publish",
            json={"article_url": "https://example.com/x"},
            headers=_admin_headers(),
        )

        assert sorted([first.status_code, second.status_code]) == [202, 409]
        conflicted = second if first.status_code == 202 else first
        assert conflicted.json()["status"] == "running"

        # let the dispatched run finish before the fixture DB closes
        release.set()
        started = first if first.status_code == 202 else second
        for _ in range(50):
            st = api_client.get(
                "/v1/admin/publish/status",
                params={"run_id": started.json()["run_id"]},
                headers=_admin_headers(),
            ).json()
            if st["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)


def test_admin_publish_status_unknown_run_id_returns_404(
    api_client: TestClient,
) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.get(
            "/v1/admin/publish/status",
            params={"run_id": "999999"},
            headers=_admin_headers(),
        )
    assert response.status_code == 404


def test_admin_articles_marks_export_candidates_publishable(
    api_client: TestClient, db_manager: DatabaseManager, monkeypatch, tmp_path
) -> None:
    """`publishable` is True only for pending articles in the current
    `latest_articles.json` shortlist."""
    from news_collector.serving import api as serving_api

    with db_manager.get_session() as session:
        for aid, title in [(501, "in export"), (502, "not in export")]:
            session.add(
                Article(
                    id=aid,
                    title=title,
                    url=f"https://example.com/{aid}",
                    source_id="nature",
                    source_name="Nature",
                    processing_status="pending",
                    final_score=0.9,
                )
            )
        session.commit()

    export = tmp_path / "latest_articles.json"
    export.write_text(json.dumps({"articles": [{"id": 501, "score": 0.9}]}), "utf-8")
    monkeypatch.setattr(serving_api, "_EXPORT_ARTIFACT_PATH", export, raising=False)

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        rows = {
            r["id"]: r
            for r in api_client.get(
                "/v1/admin/articles", headers=_admin_headers()
            ).json()["data"]
        }
    assert rows[501]["publishable"] is True
    assert rows[501]["export_score"] == 0.9
    assert rows[502]["publishable"] is False


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


def test_admin_collect_status_uses_true_recency_not_lexical_order(
    api_client: TestClient, db_manager: DatabaseManager
) -> None:
    """Regression (Plan 060 / Phase 4a): recency must reflect true
    chronological/id order, not a lexicographic string comparison — the
    pre-Phase-4a bug this test used to guard against was "collect-10" <
    "collect-9" under `str.split("-")` + lexicographic max. `run_id` is now
    a DB autoincrement integer (see CollectionRunWorkflow.get_status),
    so ordering by it (or started_at) is correct by construction — proven
    here by actually crossing the two-digit id boundary, not just assumed.

    The old "registry bounded to 2 most recent runs" concern this test used
    to also cover no longer applies: the module-global bounded dict
    (`_admin_runs`/`_prune_collect_runs`) is deleted outright. Retention is
    now the terminal-only 90-day cleanup (Design §4) — unbounded by count,
    and provably never touches active rows — see
    tests/unit/storage/test_prune_workflow_runs.py.
    """
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        for i in range(11):
            session.add(
                WorkflowRun(
                    run_type="collection",
                    status="succeeded",
                    started_at=now + timedelta(seconds=i),
                    finished_at=now + timedelta(seconds=i),
                )
            )

    with db_manager.get_session() as session:
        latest_id = (
            session.query(WorkflowRun.id)
            .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
            .first()[0]
        )
    # Crossed the two-digit boundary the old lexicographic bug tripped on.
    assert latest_id >= 10

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        status = api_client.get(
            "/v1/admin/collect/status", headers=_admin_headers()
        ).json()

    assert status["run_id"] == str(latest_id)


def test_admin_prompts_save_is_atomic(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    """Regression: prompts.yaml must be written atomically (no truncated
    file on crash) — save to a temp file then os.replace."""
    from news_collector.serving import api as serving_api

    prompts_file = tmp_path / "prompts.yaml"
    prompts_file.write_text("auditor:\n  system: original\n", encoding="utf-8")

    real_path = serving_api.Path

    def _fake_path(*a, **k):
        if a and "prompts.yaml" in str(a[0]):
            return prompts_file
        return real_path(*a, **k)

    monkeypatch.setattr(serving_api, "Path", _fake_path)
    monkeypatch.setattr(serving_api, "os", __import__("os"))

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/prompts",
            json={"prompts": {"editor": {"system": "nuevo"}}},
            headers=_admin_headers(),
        )
        assert response.status_code == 200

    # The temp file must not remain behind; the target must be complete.
    leftovers = list(tmp_path.glob(".prompts-*"))
    assert leftovers == [], f"temp files left behind: {leftovers}"
    assert "editor" in prompts_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 4: parity gaps (unpublish, image brief edit/upload, source delete)
# ---------------------------------------------------------------------------


def test_admin_unpublish_article(
    api_client: TestClient, db_manager: DatabaseManager, monkeypatch
) -> None:
    """DELETE /v1/admin/content/{id} dispatches to reset_one_article."""
    import apps.refinery.published_content as pc_mod
    from news_collector.serving import api as serving_api

    reset_calls: list[str] = []
    snapshot = SimpleNamespace(
        repo_root=Path("/tmp/fake-target"),
        posts_dir=Path("/tmp/fake-target/posts"),
        source_label="fake",
        freshness_label="fake",
    )

    monkeypatch.setattr(
        "apps.refinery.published_content.resolve_published_content_snapshot",
        lambda **k: snapshot,
    )
    monkeypatch.setattr(
        "apps.refinery.published_content.find_published_article_by_refinery_id",
        lambda posts_dir, refinery_id: SimpleNamespace(
            file_path=Path("/tmp/fake-target/posts/2026-01-01-x.md"),
            file_name="2026-01-01-x.md",
            refinery_id=refinery_id,
        ),
    )
    monkeypatch.setattr(
        "apps.refinery.published_content.reset_one_article",
        lambda repo_root, article, db: reset_calls.append(article.refinery_id),
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.delete(
            "/v1/admin/content/2026-01-01-x", headers=_admin_headers()
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    assert reset_calls == ["2026-01-01-x"]


def test_admin_unpublish_unknown_404(api_client: TestClient, monkeypatch) -> None:
    from news_collector.serving import api as serving_api

    snapshot = SimpleNamespace(
        repo_root=Path("/tmp/fake-target"),
        posts_dir=Path("/tmp/fake-target/posts"),
        source_label="fake",
        freshness_label="fake",
    )
    monkeypatch.setattr(
        "apps.refinery.published_content.resolve_published_content_snapshot",
        lambda **k: snapshot,
    )
    monkeypatch.setattr(
        "apps.refinery.published_content.find_published_article_by_refinery_id",
        lambda *a, **k: None,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.delete("/v1/admin/content/nope", headers=_admin_headers())
        assert response.status_code == 404


def test_admin_bulk_reset_reports_per_item(api_client: TestClient, monkeypatch) -> None:
    from news_collector.serving import api as serving_api

    snapshot = SimpleNamespace(
        repo_root=Path("/tmp/fake-target"),
        posts_dir=Path("/tmp/fake-target/posts"),
        source_label="fake",
        freshness_label="fake",
    )
    monkeypatch.setattr(
        "apps.refinery.published_content.resolve_published_content_snapshot",
        lambda **k: snapshot,
    )

    def _fake_find(posts_dir, refinery_id):
        if refinery_id == "missing":
            return None
        return SimpleNamespace(
            file_path=Path(f"/tmp/fake-target/posts/{refinery_id}.md"),
            file_name=f"{refinery_id}.md",
            refinery_id=refinery_id,
        )

    monkeypatch.setattr(
        "apps.refinery.published_content.find_published_article_by_refinery_id",
        _fake_find,
    )
    reset_calls: list[str] = []
    monkeypatch.setattr(
        "apps.refinery.published_content.reset_one_article",
        lambda repo_root, article, db: reset_calls.append(article.refinery_id),
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/content/bulk-reset",
            json={"refinery_ids": ["a", "missing", "b"]},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert sorted(body["succeeded"]) == ["a", "b"]
        assert body["failed"][0]["refinery_id"] == "missing"
        assert "No published article" in body["failed"][0]["error"]
        assert "succeeded" in body["summary"]


def test_admin_bulk_reset_all_whitespace_ids_returns_422(
    api_client: TestClient,
) -> None:
    """AdminBulkResetRequest._ids_non_empty must reject a refinery_ids list
    that strips down to nothing (all blank/whitespace entries) — the one
    validation branch this contract has, otherwise never exercised."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/content/bulk-reset",
            json={"refinery_ids": ["   ", ""]},
            headers=_admin_headers(),
        )
    assert response.status_code == 422


def test_admin_image_brief_update_roundtrip(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    from news_collector.contracts.image_brief import ImageBriefModel
    from news_collector.logic.workflows.image_briefs import ImageBriefStore
    from news_collector.serving import api as serving_api

    store = ImageBriefStore(tmp_path)
    store.save_brief(_make_brief("brief-update"))
    monkeypatch.setattr(
        "news_collector.logic.workflows.image_briefs.ImageBriefStore",
        lambda *a: store,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.put(
            "/v1/admin/images/brief-update",
            json={"topic": "nuevo tema"},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["brief"]["topic"] == "nuevo tema"

    reloaded = store.load_brief("brief-update")
    assert reloaded.topic == "nuevo tema"


def test_admin_image_brief_update_unknown_404(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    from news_collector.logic.workflows.image_briefs import ImageBriefStore
    from news_collector.serving import api as serving_api

    store = ImageBriefStore(tmp_path)
    monkeypatch.setattr(
        "news_collector.logic.workflows.image_briefs.ImageBriefStore",
        lambda *a: store,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.put(
            "/v1/admin/images/nope", json={"topic": "x"}, headers=_admin_headers()
        )
        assert response.status_code == 404


def test_admin_image_brief_upload_stages_asset(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    from news_collector.logic.workflows.image_briefs import ImageBriefStore
    from news_collector.serving import api as serving_api

    store = ImageBriefStore(tmp_path)
    store.save_brief(_make_brief("brief-upload"))
    monkeypatch.setattr(
        "news_collector.logic.workflows.image_briefs.ImageBriefStore",
        lambda *a: store,
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/images/brief-upload/upload",
            files={"file": ("hero.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            data={"draft_alt_text": "Imagen de laboratorio"},
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["brief"]["status"] == "editorial_image_ready"
        assert body["asset_path"].endswith(".png")

    staged = store.load_brief("brief-upload")
    assert staged.status == "editorial_image_ready"
    assert staged.uploaded_asset_path


def test_admin_delete_source_removes_yaml_and_db(
    api_client: TestClient, db_manager: DatabaseManager, tmp_path, monkeypatch
) -> None:
    from news_collector.config import sources as sources_mod
    from news_collector.serving import api as serving_api

    # Point ALL_SOURCES at a tmp yaml so we don't touch the real config.
    fake_sources = {
        "delete_me": {
            "name": "Delete Me",
            "url": "https://example.com/feed",
            "category": "science",
        }
    }
    monkeypatch.setattr(sources_mod, "ALL_SOURCES", fake_sources)
    yaml_path = tmp_path / "sources.yaml"
    monkeypatch.setattr(
        sources_mod, "save_sources", lambda srcs: yaml_path.write_text(str(srcs))
    )
    # The endpoint imports ALL_SOURCES/save_sources from
    # news_collector.config.sources at call time — patch there.
    monkeypatch.setattr("news_collector.config.sources.ALL_SOURCES", fake_sources)
    monkeypatch.setattr(
        "news_collector.config.sources.save_sources", sources_mod.save_sources
    )

    with db_manager.get_session() as session:
        session.add(
            Source(
                id="delete_me",
                name="Delete Me",
                url="https://example.com/feed",
                credibility_score=0.5,
                category="science",
            )
        )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.delete(
            "/v1/admin/sources/delete_me", headers=_admin_headers()
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    assert "delete_me" not in sources_mod.ALL_SOURCES
    with db_manager.get_session() as session:
        assert session.query(Source).filter(Source.id == "delete_me").first() is None


def test_admin_delete_source_unknown_404(api_client: TestClient) -> None:
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.delete(
            "/v1/admin/sources/definitely_not_real", headers=_admin_headers()
        )
        assert response.status_code == 404


def _make_brief(slug: str):
    from news_collector.contracts.image_brief import ImageBriefModel

    return ImageBriefModel(
        slug=slug,
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


# ---------------------------------------------------------------------------
# Phase 4 addendum: source editor (add / update)
# ---------------------------------------------------------------------------


def test_admin_upsert_source_creates(
    api_client: TestClient, db_manager: DatabaseManager, tmp_path, monkeypatch
) -> None:
    from news_collector.config import sources as sources_mod
    from news_collector.serving import api as serving_api

    fake_sources: dict = {}
    monkeypatch.setattr(sources_mod, "ALL_SOURCES", fake_sources)
    yaml_path = tmp_path / "sources.yaml"
    monkeypatch.setattr(
        sources_mod, "save_sources", lambda srcs: yaml_path.write_text(str(srcs))
    )
    # The endpoint imports from news_collector.config.sources at call time.
    monkeypatch.setattr("news_collector.config.sources.ALL_SOURCES", fake_sources)
    monkeypatch.setattr(
        "news_collector.config.sources.save_sources", sources_mod.save_sources
    )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/sources",
            json={
                "source_id": "new_source",
                "name": "New Source",
                "url": "https://example.com/feed",
                "credibility_score": 0.7,
                "category": "science",
                "update_frequency": "daily",
                "group": "CUSTOM",
            },
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "created" in response.json()["detail"]

    entry = fake_sources["new_source"]
    assert entry["name"] == "New Source"
    assert entry["language"] == "en"  # create defaults
    assert entry["_group"] == "CUSTOM"

    with db_manager.get_session() as session:
        row = session.query(Source).filter(Source.id == "new_source").first()
        assert row is not None
        assert row.url == "https://example.com/feed"


def test_admin_upsert_source_update_preserves_existing_keys(
    api_client: TestClient, db_manager: DatabaseManager, tmp_path, monkeypatch
) -> None:
    from news_collector.config import sources as sources_mod
    from news_collector.serving import api as serving_api

    fake_sources = {
        "existing": {
            "name": "Old Name",
            "url": "https://old.example.com/feed",
            "credibility_score": 0.5,
            "category": "technology",
            "blacklisted": True,
            "blacklist_reason": "spam",
            "etag": "abc123",
        }
    }
    monkeypatch.setattr(sources_mod, "ALL_SOURCES", fake_sources)
    yaml_path = tmp_path / "sources.yaml"
    monkeypatch.setattr(
        sources_mod, "save_sources", lambda srcs: yaml_path.write_text(str(srcs))
    )
    monkeypatch.setattr("news_collector.config.sources.ALL_SOURCES", fake_sources)
    monkeypatch.setattr(
        "news_collector.config.sources.save_sources", sources_mod.save_sources
    )

    with db_manager.get_session() as session:
        session.add(
            Source(
                id="existing",
                name="Old Name",
                url="https://old.example.com/feed",
                credibility_score=0.5,
                category="technology",
            )
        )

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/sources",
            json={
                "source_id": "existing",
                "name": "New Name",
                "url": "https://new.example.com/feed",
                "category": "science",
                "update_frequency": "hourly",
            },
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        assert "updated" in response.json()["detail"]

    entry = fake_sources["existing"]
    assert entry["name"] == "New Name"
    assert entry["url"] == "https://new.example.com/feed"
    assert entry["blacklisted"] is True  # preserved
    assert entry["etag"] == "abc123"  # preserved

    with db_manager.get_session() as session:
        row = session.query(Source).filter(Source.id == "existing").first()
        assert row.name == "New Name"


def test_admin_upsert_source_validation_422(
    api_client: TestClient, monkeypatch
) -> None:
    from news_collector.config import sources as sources_mod

    monkeypatch.setattr(sources_mod, "ALL_SOURCES", {})

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        # Missing name
        response = api_client.post(
            "/v1/admin/sources",
            json={"source_id": "bad", "url": "https://x.com"},
            headers=_admin_headers(),
        )
        assert response.status_code == 422

        # Bad category
        response = api_client.post(
            "/v1/admin/sources",
            json={
                "source_id": "bad2",
                "name": "x",
                "url": "https://x.com",
                "category": "nope",
            },
            headers=_admin_headers(),
        )
        assert response.status_code == 422

        # Credibility out of range
        response = api_client.post(
            "/v1/admin/sources",
            json={
                "source_id": "bad3",
                "name": "x",
                "url": "https://x.com",
                "credibility_score": 1.5,
            },
            headers=_admin_headers(),
        )
        assert response.status_code == 422


def test_admin_cors_allows_put_delete_preflight(
    api_client: TestClient,
) -> None:
    """Phase 4 regression: PUT (image brief) and DELETE (unpublish/source)
    preflights must be allowed, not just GET/POST."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        for method in ("PUT", "DELETE"):
            preflight = api_client.options(
                "/v1/admin/images/slug/upload",
                headers={
                    "Origin": "http://localhost:4322",
                    "Access-Control-Request-Method": method,
                },
            )
            assert preflight.status_code == 200
            allow = preflight.headers.get("access-control-allow-methods", "")
            assert method in allow, f"{method} missing from {allow}"


def test_admin_config_save_accepts_snapshot_shape(
    api_client: TestClient, tmp_path, monkeypatch
) -> None:
    """Regression: the GUI submits the sanitized snapshot returned by GET
    /v1/admin/config (top-level environment/debug/timezone, sources/meta
    extras, empty-string optionals). The save endpoint must normalize it
    into the Config shape instead of 422ing."""
    from noticiencias.config_manager import load_config as _load

    from news_collector.serving import api as serving_api

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        Path("config.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.setattr(serving_api, "load_config", lambda: _load(cfg_file))

    import noticiencias.config_manager as _cm

    real_save = _cm.save_config

    def _save_to_tmp(validated, path=None):
        return real_save(validated, cfg_file)

    monkeypatch.setattr("noticiencias.config_manager.save_config", _save_to_tmp)

    # Round-trip: GET the snapshot, tweak a scoring weight, POST it back.
    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        got = api_client.get("/v1/admin/config", headers=_admin_headers())
        assert got.status_code == 200
        snapshot = got.json()

    snapshot["scoring"]["weights"]["recency"] = 0.30
    # Re-normalize weights sum back to 1.0 so business validation passes.
    weights = snapshot["scoring"]["weights"]
    weights["source_credibility"] = 0.1
    weights["content_quality"] = 0.3
    weights["engagement_potential"] = 0.3

    with patch.dict(os.environ, {"ADMIN_API_KEY": "dev-admin-token"}):
        response = api_client.post(
            "/v1/admin/config", json=snapshot, headers=_admin_headers()
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scoring"]["weights"]["recency"] == 0.30

    saved = cfg_file.read_text(encoding="utf-8")
    assert "recency = 0.3" in saved
    assert "[paths]" in saved
