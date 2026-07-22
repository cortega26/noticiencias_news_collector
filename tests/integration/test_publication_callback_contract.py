"""Plan 021 Step 5: a true cross-repo publication-callback contract test.

Calls the frontend's *real* sender code (`backend-notify.js`'s
`buildEnvelope`, via a Node subprocess reading the actual sibling-repo
file — not a Python re-implementation of the JS logic) to build a
realistic envelope, validates it through the real backend Pydantic
models, then replays it through the real webhook handler against a real
(SQLite) database after a real PR-created state transition
(`DatabaseManager.mark_article_published`). No network access anywhere —
Node runs as a local subprocess and its stdout is captured directly.

Skips (does not fail) when Node or the sibling ``../noticiencias`` repo
checkout isn't available, since this genuinely cannot run without both
repos present side by side.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from news_collector.contracts.webhook import parse_webhook_payload
from news_collector.serving import create_app
from news_collector.serving.webhook_handler import (
    process_publish_complete,
    process_validation_result,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

FRONTEND_REPO = Path(os.environ.get("FRONTEND_REPO_PATH", "../noticiencias")).resolve()
BACKEND_NOTIFY_SCRIPT = FRONTEND_REPO / "scripts" / "backend-notify.js"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        shutil.which("node") is None or not BACKEND_NOTIFY_SCRIPT.exists(),
        reason=(
            "Requires Node and the sibling ../noticiencias checkout to build a "
            "real sender envelope — this is a genuine cross-repo test, not "
            "something a Python-only environment can run."
        ),
    ),
]


def _build_envelope_via_frontend(
    *,
    event: str,
    status: str,
    diagnostics: Any,
    publication_ids: list[str],
    github_env: dict[str, str] | None = None,
) -> dict:
    """Invoke the frontend's real buildEnvelope() in a Node subprocess.

    This is the actual sender code the frontend ships, imported directly
    from the sibling repo — not a hand-copied Python stand-in that could
    silently drift from what the real sender produces.
    """
    script = (
        "import { buildEnvelope } from "
        f"{json.dumps(str(BACKEND_NOTIFY_SCRIPT))};\n"
        "const envelope = buildEnvelope({\n"
        f"  event: {json.dumps(event)},\n"
        f"  status: {json.dumps(status)},\n"
        f"  diagnostics: {json.dumps(diagnostics)},\n"
        f"  publicationIds: {json.dumps(publication_ids)},\n"
        f"  githubEnv: {json.dumps(github_env or {})},\n"
        "});\n"
        "console.log(JSON.stringify(envelope));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "cross_repo_contract.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    yield manager
    manager.close()


@pytest.fixture()
def api_client(db_manager: DatabaseManager) -> TestClient:
    app = create_app(database_manager=db_manager)
    return TestClient(app)


def _create_pr_created_article(
    db_manager: DatabaseManager, *, refinery_id: str, url_suffix: str
) -> int:
    """Insert an article and drive it through the *real* PR-created
    transition (mark_article_published), exactly like PROrchestrator does."""
    with db_manager.get_session() as session:
        article = Article(
            title=f"Cross-repo contract test article {refinery_id}",
            url=f"https://example.com/{url_suffix}",
            summary="A test article for the cross-repo contract test.",
            source_id="test-source",
            source_name="Test Source",
            category="science",
            processing_status="pending",
        )
        session.add(article)
        session.flush()
        article_id = article.id

    db_manager.mark_article_publishing(article_id, f"content/update-{refinery_id}")
    db_manager.mark_article_published(
        article_id,
        f"https://github.com/cortega26/noticiencias/pull/{refinery_id}",
        refinery_id,
    )
    return article_id


def _article_state(db_manager: DatabaseManager, article_id: int) -> dict:
    with db_manager.get_session() as session:
        row = session.query(Article).filter(Article.id == article_id).first()
        return {
            "processing_status": row.processing_status,
            "published_url": row.published_url,
            "published_at": row.published_at,
            "publication_state": (row.article_metadata or {})
            .get("publication", {})
            .get("state"),
        }


class TestPRFailure:
    def test_content_guard_failure_rejects_the_named_article(self, db_manager):
        article_id = _create_pr_created_article(
            db_manager, refinery_id="cg-fail-1", url_suffix="cg-fail-1"
        )

        envelope = _build_envelope_via_frontend(
            event="validation_result",
            status="fail",
            diagnostics=[
                {"check": "frontmatter-dates", "status": "fail", "errors": ["bad date"]}
            ],
            publication_ids=["cg-fail-1"],
            github_env={
                "GITHUB_SHA": "abc123",
                "GITHUB_REF_NAME": "content/update-cg-fail-1",
            },
        )

        event = parse_webhook_payload(envelope)
        process_validation_result(event, db_manager)

        state = _article_state(db_manager, article_id)
        assert state["processing_status"] == "rejected"
        assert state["publication_state"] == "REJECTED"


class TestDeploySuccess:
    def test_deploy_success_completes_the_named_article(self, db_manager):
        article_id = _create_pr_created_article(
            db_manager, refinery_id="deploy-ok-1", url_suffix="deploy-ok-1"
        )

        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={
                "check": "deploy",
                "status": "pass",
                "article_count": 1,
                "deploy_url": "https://noticiencias.com/deploy-ok-1",
            },
            publication_ids=["deploy-ok-1"],
            github_env={"GITHUB_SHA": "def456", "GITHUB_REF_NAME": "main"},
        )

        event = parse_webhook_payload(envelope)
        process_publish_complete(event, db_manager)

        state = _article_state(db_manager, article_id)
        assert state["processing_status"] == "completed"
        assert state["published_url"] == "https://noticiencias.com/deploy-ok-1"
        assert state["published_at"] is not None
        assert state["publication_state"] == "COMPLETED"


class TestReplay:
    def test_replaying_a_completed_callback_is_a_no_op(self, db_manager):
        article_id = _create_pr_created_article(
            db_manager, refinery_id="replay-1", url_suffix="replay-1"
        )

        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={
                "check": "deploy",
                "status": "pass",
                "deploy_url": "https://noticiencias.com/replay-1",
            },
            publication_ids=["replay-1"],
        )
        event = parse_webhook_payload(envelope)

        process_publish_complete(event, db_manager)
        first_state = _article_state(db_manager, article_id)

        # Replay the identical callback again — the article is no longer
        # "publishing", so it must not be matched or mutated a second time.
        process_publish_complete(event, db_manager)
        second_state = _article_state(db_manager, article_id)

        assert first_state == second_state


class TestUnrelatedId:
    def test_an_id_naming_a_different_article_does_not_touch_this_one(self, db_manager):
        article_id = _create_pr_created_article(
            db_manager, refinery_id="mine-1", url_suffix="unrelated-mine-1"
        )

        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={"check": "deploy", "status": "pass"},
            publication_ids=["someone-elses-id"],
        )
        event = parse_webhook_payload(envelope)
        process_publish_complete(event, db_manager)

        state = _article_state(db_manager, article_id)
        assert state["processing_status"] == "publishing"
        assert state["published_url"] is None


class TestAuthEnabled:
    def test_a_real_envelope_is_accepted_through_the_authenticated_http_endpoint(
        self, api_client: TestClient, db_manager: DatabaseManager
    ):
        article_id = _create_pr_created_article(
            db_manager, refinery_id="auth-ok-1", url_suffix="auth-ok-1"
        )

        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={
                "check": "deploy",
                "status": "pass",
                "deploy_url": "https://noticiencias.com/auth-ok-1",
            },
            publication_ids=["auth-ok-1"],
        )

        with patch.dict(os.environ, {"WEBHOOK_API_KEY": "cross-repo-secret"}):
            response = api_client.post(
                "/api/v1/webhook/frontend",
                json=envelope,
                headers={"Authorization": "Bearer cross-repo-secret"},
            )

        assert response.status_code == 202
        state = _article_state(db_manager, article_id)
        assert state["processing_status"] == "completed"

    def test_a_real_envelope_without_a_token_is_rejected_when_a_key_is_configured(
        self, api_client: TestClient
    ):
        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={"check": "deploy", "status": "pass"},
            publication_ids=["auth-missing-token"],
        )

        with patch.dict(os.environ, {"WEBHOOK_API_KEY": "cross-repo-secret"}):
            response = api_client.post("/api/v1/webhook/frontend", json=envelope)

        assert response.status_code == 401


class TestMalformedEnvelope:
    def test_an_envelope_missing_a_required_field_is_rejected_by_the_real_schema(self):
        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={"check": "deploy", "status": "pass"},
            publication_ids=["whatever"],
        )
        del envelope["run_url"]  # a required field per FrontendWebhookEvent

        with pytest.raises(Exception):
            parse_webhook_payload(envelope)

    def test_an_envelope_with_bad_publication_ids_is_rejected_by_the_real_schema(self):
        envelope = _build_envelope_via_frontend(
            event="publish_complete",
            status="success",
            diagnostics={"check": "deploy", "status": "pass"},
            publication_ids=["ok-id"],
        )
        envelope["publication_ids"] = [
            "ok-id",
            "   ",
        ]  # blank string, real validator rejects

        with pytest.raises(Exception):
            parse_webhook_payload(envelope)
