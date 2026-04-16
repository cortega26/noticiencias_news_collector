"""
tests/decompose_refinery/test_engine_regression.py

End-to-end regression tests for the full RefineryEngine pipeline after decomposition.
All collaborators are exercised via mocked I/O boundaries (spec §6.3 E2E-01..05).

These tests verify that:
1. The full article → PR flow produces correct side-effects.
2. No existing behaviour changed during the refactor.
3. Each collaborator participates correctly when wired through the engine.

These tests use RefineryEngine directly (no change to its public interface).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.refinery_engine import RefineryEngine


# ---------------------------------------------------------------------------
# Shared engine factory
# ---------------------------------------------------------------------------

def _make_engine(tmp_path: Path) -> RefineryEngine:
    """
    Construct a RefineryEngine with all external I/O mocked.
    Mirrors the fixture pattern used in existing integration tests.
    """
    db = MagicMock()
    db.get_canonical_slug.return_value = None
    db.get_publishing_state.return_value = None
    db.set_canonical_slug.return_value = True
    db.mark_article_published.return_value = None
    db.mark_article_publishing.return_value = None

    git = MagicMock()
    git.create_branch.return_value = "content/update-2024-01-25-test-article"
    git.commit_and_push.return_value = None
    git.create_pull_request.return_value = "https://github.com/org/repo/pull/1"

    editor = MagicMock()
    editor.process_article.return_value = (
        "---\ntitle: Test\nslug: test-article\ndate: 2024-01-25\n---\nContent"
    )

    config = SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled",
            editorial_mode="standard",
        ),
        paths=SimpleNamespace(data_dir=str(tmp_path / "data")),
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
    )

    engine = RefineryEngine(db, git, editor, config)
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 10.0}
    engine.auditor.should_run_fast.return_value = False
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False

    return engine


def _make_article(
    article_id: str = "42",
    image_url: str = "https://example.com/image.jpg",
    published_date: datetime | None = None,
) -> dict:
    return {
        "id": article_id,
        "title": "Test Article Title",
        "url": "https://example.com/article",
        "summary": "A sufficiently long summary for the article being processed.",
        "image_url": image_url,
        "published_date": published_date or datetime(2024, 1, 25),
        "source_id": "src",
        "source_name": "Source Name",
        "category": "science",
        "source_metadata": {},
    }


def _mock_http_image_client(*, content: bytes = b"image-bytes", content_type: str = "image/jpeg"):
    """Context-manager patch that makes HTTP image downloads succeed."""
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    response = MagicMock()
    response.content = content
    response.headers = {"Content-Type": content_type}
    mock_client.get.return_value = response
    return patch(
        "news_collector.infrastructure.requests_client.RobustRequestsClient",
        return_value=mock_client,
    )


# ---------------------------------------------------------------------------
# E2E-01: Happy path — article with HTTP image → PR created, file written
# ---------------------------------------------------------------------------

class TestE2EHappyPath:
    def test_e2e_01_full_pipeline_pr_created(self, tmp_path):
        """E2E-01: Article with HTTP image → file written, manifest updated, DB marked, PR URL returned."""
        engine = _make_engine(tmp_path)
        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()
        posts_dir = target_dir / "src/content/posts"
        posts_dir.mkdir(parents=True)

        article = _make_article()

        with _mock_http_image_client():
            result = engine.process_single_article(article, MagicMock(), target_dir)

        assert result is True

        # File must exist in posts_dir
        md_files = list(posts_dir.glob("*.md"))
        assert len(md_files) == 1

        # Manifest must contain the article
        manifest_path = posts_dir / "refinery_manifest.json"
        assert manifest_path.exists()

        # DB must have been marked as published
        engine.db.mark_article_published.assert_called_once()

        # git PR must have been created
        engine.git.create_pull_request.assert_called_once()

    def test_e2e_01_batch_processes_multiple_articles(self, tmp_path):
        """E2E-01 batch: process_articles returns correct processed_count."""
        engine = _make_engine(tmp_path)
        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()

        articles = [_make_article(str(i), published_date=datetime(2024, 1, i + 1)) for i in range(1, 4)]

        with _mock_http_image_client():
            summary = engine.process_articles(articles, MagicMock(), target_dir)

        assert summary["processed_count"] == 3
        assert summary["errors"] == []


# ---------------------------------------------------------------------------
# E2E-02: Idempotency — re-processing reuses identical filename
# ---------------------------------------------------------------------------

class TestE2EIdempotency:
    def test_e2e_02_reprocess_reuses_filename(self, tmp_path):
        """E2E-02: Article already published (DB slug locked) → same filename reused."""
        engine = _make_engine(tmp_path)
        engine.db.get_canonical_slug.return_value = "2025-01-01-locked-slug"

        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()
        posts_dir = target_dir / "src/content/posts"
        posts_dir.mkdir(parents=True)

        with _mock_http_image_client():
            result = engine.process_single_article(_make_article(), MagicMock(), target_dir)

        assert result is True
        assert (posts_dir / "2025-01-01-locked-slug.md").exists()
        assert not list(posts_dir.glob("2024-01-25-*.md")), "Must not create a new file for locked identity"


# ---------------------------------------------------------------------------
# E2E-03: Publishing-state recovery
# ---------------------------------------------------------------------------

class TestE2ERecovery:
    def test_e2e_03_stuck_in_publishing_recovery_returns_true(self, tmp_path):
        """E2E-03: Article stuck in publishing → recovery path returns True."""
        from datetime import timezone, timedelta

        engine = _make_engine(tmp_path)
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        engine.db.get_publishing_state.return_value = {
            "publishing_started_at": recent_time,
            "publishing_branch": "content/update-2024-01-25-test",
        }

        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()

        result = engine.process_single_article(_make_article(), MagicMock(), target_dir)

        assert result is True


# ---------------------------------------------------------------------------
# E2E-04: Image download failure → process_single_article returns False
# ---------------------------------------------------------------------------

class TestE2EImageFailure:
    def test_e2e_04_image_failure_returns_false_no_file_written(self, tmp_path):
        """E2E-04: Image download fails → returns False, no .md file written."""
        engine = _make_engine(tmp_path)

        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()
        posts_dir = target_dir / "src/content/posts"
        posts_dir.mkdir(parents=True)

        with patch(
            "news_collector.infrastructure.requests_client.RobustRequestsClient",
        ) as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.get.side_effect = ConnectionError("timeout")

            result = engine.process_single_article(_make_article(), MagicMock(), target_dir)

        assert result is False
        assert list(posts_dir.glob("*.md")) == []


# ---------------------------------------------------------------------------
# E2E-05: Editorial policy rejection → returns False before file write
# ---------------------------------------------------------------------------

class TestE2EPolicyRejection:
    def test_e2e_05_policy_rejection_returns_false(self, tmp_path):
        """E2E-05: Auditor score below threshold → returns False, no file written."""
        engine = _make_engine(tmp_path)
        # Set a high threshold so the article is rejected
        engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 0.1}
        engine.policy.auditor_threshold = 5.0

        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()
        posts_dir = target_dir / "src/content/posts"
        posts_dir.mkdir(parents=True)

        with _mock_http_image_client():
            result = engine.process_single_article(_make_article(), MagicMock(), target_dir)

        assert result is False
        assert list(posts_dir.glob("*.md")) == []
        engine.git.create_pull_request.assert_not_called()


# ---------------------------------------------------------------------------
# E2E guard: All four collaborators are reachable from the engine instance
# ---------------------------------------------------------------------------

class TestCollaboratorWiring:
    def test_engine_has_identity_resolver(self, tmp_path):
        """After decomposition, engine must expose identity_resolver attribute."""
        engine = _make_engine(tmp_path)
        assert hasattr(engine, "identity_resolver"), (
            "RefineryEngine must have an identity_resolver attribute after Phase 1"
        )

    def test_engine_has_writer(self, tmp_path):
        """After decomposition, engine must expose writer attribute."""
        engine = _make_engine(tmp_path)
        assert hasattr(engine, "writer"), (
            "RefineryEngine must have a writer attribute after Phase 2"
        )

    def test_engine_has_image_handler(self, tmp_path):
        """After decomposition, engine must expose image_handler attribute."""
        engine = _make_engine(tmp_path)
        assert hasattr(engine, "image_handler"), (
            "RefineryEngine must have an image_handler attribute after Phase 3"
        )

    def test_engine_has_pr_orchestrator(self, tmp_path):
        """After decomposition, engine must expose pr_orchestrator attribute."""
        engine = _make_engine(tmp_path)
        assert hasattr(engine, "pr_orchestrator"), (
            "RefineryEngine must have a r_orchestrator attribute after Phase 4"
        )
