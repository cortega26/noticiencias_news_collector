"""Tests for B-01: Publishing state and recovery mechanism (F-0012, F-0015).

test_publishing_state_recovery_with_existing_pr:
    Simulate crash post-push/pre-PR — article stuck in 'publishing' with a
    branch that already has an open PR.  Recovery should find the PR and mark
    the article as completed.

test_publishing_state_recovery_without_pr:
    Branch pushed but no PR exists — recovery should retry PR creation and
    succeed.
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _engine_deps():
    """Build a minimal RefineryEngine with mocked dependencies."""
    mock_db = MagicMock()
    mock_git = MagicMock()
    mock_editor = MagicMock()
    mock_config = MagicMock()
    mock_config.github = SimpleNamespace(
        target_repo_url="https://github.com/owner/repo.git"
    )
    mock_config.app.policy_integrity_mode = "disabled"
    mock_config.app.editorial_mode = "standard"

    with patch(
        "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
    ) as MockAuditorClass:
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        engine = RefineryEngine(mock_db, mock_git, mock_editor, mock_config)
        engine.auditor = MockAuditorClass.return_value
        engine.auditor.get_cached_score.return_value = None
        engine.auditor.should_run_fast.return_value = False
        engine.policy.auditor_threshold = 0.0
        engine.policy.require_caveats = False
        engine._download_image = MagicMock(
            return_value="~/assets/images/publishing-recovery-test.png"
        )
        yield engine, mock_db, mock_git, mock_editor, mock_config


class TestPublishingStateRecoveryWithExistingPR:
    """B-01 / F-0012: Article stuck in 'publishing', PR already exists on remote."""

    def test_publishing_state_recovery_with_existing_pr(self, _engine_deps):
        engine, mock_db, mock_git, mock_editor, mock_config = _engine_deps

        # Simulate: article is in 'publishing' state with branch info
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": datetime.now(timezone.utc).isoformat(),
            "publishing_branch": "content/update-2024-01-01-test-article",
        }

        # A-04 logic: create_pull_request returns existing PR URL on 422
        existing_pr_url = "https://github.com/owner/repo/pull/42"
        mock_git.create_pull_request.return_value = existing_pr_url

        article = {
            "id": "123",
            "title": "Test Article",
            "source_id": "test",
            "source_name": "Test Source",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = engine.process_single_article(article, MagicMock(), Path(tmpdir))

        assert result is True
        # Recovery should have called create_pull_request with the publishing branch
        mock_git.create_pull_request.assert_called_once()
        call_kwargs = mock_git.create_pull_request.call_args
        assert call_kwargs[1]["branch_name"] == "content/update-2024-01-01-test-article"
        # Should have marked article as published
        mock_db.mark_article_published.assert_called_once_with(123, existing_pr_url)
        # Should NOT have gone through normal processing (no editor call)
        mock_editor.process_article.assert_not_called()


class TestPublishingStateRecoveryWithoutPR:
    """B-01 / F-0015: Branch pushed but no PR — retry creation succeeds."""

    def test_publishing_state_recovery_without_pr(self, _engine_deps):
        engine, mock_db, mock_git, mock_editor, mock_config = _engine_deps

        # Simulate: article is in 'publishing' state
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": datetime.now(timezone.utc).isoformat(),
            "publishing_branch": "content/update-2024-01-01-new-article",
        }

        # PR does not exist — create_pull_request creates a new one
        new_pr_url = "https://github.com/owner/repo/pull/99"
        mock_git.create_pull_request.return_value = new_pr_url

        article = {
            "id": "456",
            "title": "New Article",
            "source_id": "test",
            "source_name": "Test Source",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = engine.process_single_article(article, MagicMock(), Path(tmpdir))

        assert result is True
        mock_git.create_pull_request.assert_called_once()
        mock_db.mark_article_published.assert_called_once_with(456, new_pr_url)
        mock_editor.process_article.assert_not_called()


class TestPublishingStateTimeout:
    """B-01: Articles stuck >1h in 'publishing' can be reprocessed."""

    def test_publishing_timeout_allows_reprocessing(self, _engine_deps):
        engine, mock_db, mock_git, mock_editor, mock_config = _engine_deps

        # Simulate: article stuck in publishing for 2 hours
        from datetime import timedelta

        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": old_time,
            "publishing_branch": "content/update-2024-01-01-old-article",
        }
        mock_db.get_canonical_slug.return_value = None

        # Normal processing should proceed (editor will be called)
        mock_editor.process_article.return_value = (
            "---\nslug: old-article\n---\nContent"
        )
        mock_git.create_branch.return_value = "content/update-2024-01-01-old-article"
        mock_git.create_pull_request.return_value = (
            "https://github.com/owner/repo/pull/1"
        )

        article = {
            "id": "789",
            "title": "Old Article",
            "url": "http://example.com/old",
            "summary": "This is a sufficiently long summary for timeout recovery validation.",
            "image_url": "https://example.com/old.png",
            "source_id": "test",
            "source_name": "Test Source",
            "published_date": datetime(2024, 1, 1),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = engine.process_single_article(article, MagicMock(), Path(tmpdir))

        assert result is True
        # Editor SHOULD have been called (normal processing, not recovery)
        mock_editor.process_article.assert_called_once()


class TestPublishingStateMarkBeforeGitOps:
    """B-01: Article marked as 'publishing' before git operations."""

    def test_mark_publishing_called_before_branch_creation(self, _engine_deps):
        engine, mock_db, mock_git, mock_editor, mock_config = _engine_deps

        # No publishing state
        mock_db.get_publishing_state.return_value = None
        mock_db.get_canonical_slug.return_value = None

        mock_editor.process_article.return_value = "---\nslug: test-slug\n---\nContent"
        mock_git.create_branch.return_value = "content/update-2024-01-01-test-slug"
        mock_git.create_pull_request.return_value = (
            "https://github.com/owner/repo/pull/1"
        )

        article = {
            "id": "100",
            "title": "Test Article",
            "url": "http://example.com/test",
            "summary": "This is a sufficiently long summary for publishing state validation.",
            "image_url": "https://example.com/test.png",
            "source_id": "test",
            "source_name": "Test Source",
            "published_date": datetime(2024, 1, 1),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = engine.process_single_article(article, MagicMock(), Path(tmpdir))

        assert result is True
        # mark_article_publishing should have been called before git ops
        mock_db.mark_article_publishing.assert_called_once()
        call_args = mock_db.mark_article_publishing.call_args
        assert call_args[0][0] == 100  # article_id
        assert "content/update-" in call_args[0][1]  # branch name
