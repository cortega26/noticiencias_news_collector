"""
tests/decompose_refinery/test_pr_orchestrator.py

Verifies PROrchestrator and PRResult (spec §3.4, §6.3 PR-01..10).

Import path after implementation:
    from news_collector.logic.workflows.pr_orchestrator import (
        PROrchestrator,
        PRResult,
    )
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from news_collector.logic.workflows.pr_orchestrator import (
    PROrchestrator,
    PRResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_git():
    git = MagicMock()
    git.create_pull_request.return_value = "https://github.com/org/repo/pull/1"
    return git


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_publishing_state.return_value = None
    db.mark_article_published.return_value = None
    return db


@pytest.fixture
def config_obj():
    return SimpleNamespace(
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
        app=SimpleNamespace(policy_integrity_mode="disabled"),
    )


@pytest.fixture
def config_dict():
    return {"target_repo_url": "https://github.com/org/repo"}


def make_article(article_id="42"):
    return {
        "id": article_id,
        "title": "Test Article",
        "url": "https://example.com/article",
        "source_id": "src",
        "source_name": "Test Source",
    }


# ---------------------------------------------------------------------------
# PR-01: create_pr calls git.create_pull_request with correct repo_url
# ---------------------------------------------------------------------------

class TestCreatePR:
    def test_pr_01_calls_git_with_repo_url(self, mock_git, mock_db, config_obj):
        """PR-01: create_pr calls git.create_pull_request with resolved repo_url."""
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.create_pr(
            article_id="42",
            article=make_article(),
            branch_name="content/update-2024-01-25-test",
            output_filename="2024-01-25-test.md",
        )

        mock_git.create_pull_request.assert_called_once()
        call_kwargs = mock_git.create_pull_request.call_args
        # repo_url must match config
        assert call_kwargs.kwargs.get("repo_url") == "https://github.com/org/repo" or \
               call_kwargs.args[0] == "https://github.com/org/repo"

    def test_pr_02_marks_article_published_on_success(self, mock_git, mock_db, config_obj):
        """PR-02: create_pr calls db.mark_article_published on success."""
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.create_pr(
            article_id="42",
            article=make_article(),
            branch_name="content/update-2024-01-25-test",
            output_filename="2024-01-25-test.md",
        )

        assert result.pr_url == "https://github.com/org/repo/pull/1"
        mock_db.mark_article_published.assert_called_once()

    def test_pr_03_returns_none_pr_url_when_git_fails(self, mock_db, config_obj):
        """PR-03: create_pr returns PRResult(pr_url=None) when git call fails."""
        mock_git = MagicMock()
        mock_git.create_pull_request.return_value = None

        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.create_pr(
            article_id="42",
            article=make_article(),
            branch_name="content/update-test",
            output_filename="2024-01-25-test.md",
        )

        assert result.pr_url is None
        mock_db.mark_article_published.assert_not_called()

    def test_pr_10_pr_body_contains_required_fields(self, mock_git, mock_db, config_obj):
        """PR-10: PR body contains article_id, source_id, source_name."""
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        orchestrator.create_pr(
            article_id="42",
            article=make_article("42"),
            branch_name="content/update-test",
            output_filename="2024-01-25-test.md",
        )

        # Capture the body passed to create_pull_request
        call_kwargs = mock_git.create_pull_request.call_args
        body = call_kwargs.kwargs.get("body") or (call_kwargs.args[2] if len(call_kwargs.args) > 2 else "")

        assert "42" in body          # article_id
        assert "src" in body         # source_id
        assert "Test Source" in body # source_name


# ---------------------------------------------------------------------------
# PR-04/05/06: resolve_repo_url from different config shapes
# ---------------------------------------------------------------------------

class TestResolveRepoUrl:
    def test_pr_04_from_config_obj_attribute(self, mock_git, mock_db):
        """PR-04: resolve_repo_url reads from config.github.target_repo_url (object)."""
        config = SimpleNamespace(
            github=SimpleNamespace(target_repo_url="https://github.com/a/b")
        )
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config)
        assert orchestrator.resolve_repo_url() == "https://github.com/a/b"

    def test_pr_05_from_config_github_dict(self, mock_git, mock_db):
        """PR-05: resolve_repo_url reads from config.github["target_repo_url"] (dict)."""
        config = SimpleNamespace(github={"target_repo_url": "https://github.com/c/d"})
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config)
        assert orchestrator.resolve_repo_url() == "https://github.com/c/d"

    def test_pr_06_from_config_flat_attribute(self, mock_git, mock_db):
        """PR-06: resolve_repo_url reads from config.target_repo_url (legacy flat)."""
        config = SimpleNamespace(target_repo_url="https://github.com/e/f")
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config)
        assert orchestrator.resolve_repo_url() == "https://github.com/e/f"

    def test_pr_06_from_config_flat_dict(self, mock_git, mock_db):
        """PR-06 edge: resolve_repo_url reads from dict config."""
        config = {"target_repo_url": "https://github.com/g/h"}
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config)
        assert orchestrator.resolve_repo_url() == "https://github.com/g/h"

    def test_resolve_returns_none_when_missing(self, mock_git, mock_db):
        """resolve_repo_url returns None when no repo_url is configured."""
        config = SimpleNamespace(app=SimpleNamespace())  # no github, no target_repo_url
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config)
        assert orchestrator.resolve_repo_url() is None


# ---------------------------------------------------------------------------
# PR-07/08/09: attempt_recovery
# ---------------------------------------------------------------------------

class TestAttemptRecovery:
    def test_pr_07_no_publishing_state_returns_none(self, mock_git, mock_db, config_obj):
        """PR-07: Article not in publishing state → attempt_recovery returns None."""
        mock_db.get_publishing_state.return_value = None
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        assert result is None

    def test_pr_08_timeout_exceeded_returns_none(self, mock_git, mock_db, config_obj):
        """PR-08: Publishing timeout exceeded → attempt_recovery returns None (allows retry)."""
        # More than 1 hour ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": old_time,
            "publishing_branch": "content/update-2024-01-01-old",
        }
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        assert result is None

    def test_pr_09_recovery_succeeds(self, mock_git, mock_db, config_obj):
        """PR-09: Article in publishing state within timeout → recovery PR created."""
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": recent_time,
            "publishing_branch": "content/update-2024-01-01-test",
        }
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        assert result is not None
        assert result.pr_url == "https://github.com/org/repo/pull/1"
        assert result.recovered is True

    def test_pr_09_recovery_calls_mark_published(self, mock_git, mock_db, config_obj):
        """PR-09: Recovery success calls db.mark_article_published."""
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": recent_time,
            "publishing_branch": "content/update-2024-01-01-test",
        }
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        mock_db.mark_article_published.assert_called_once()

    def test_attempt_recovery_no_branch_info_returns_none(self, mock_git, mock_db, config_obj):
        """attempt_recovery returns None when publishing state has no branch info."""
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": recent_time,
            "publishing_branch": None,
        }
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        assert result is None

    def test_attempt_recovery_git_failure_returns_none(self, mock_db, config_obj):
        """attempt_recovery returns None when PR creation raises an exception."""
        mock_git = MagicMock()
        mock_git.create_pull_request.side_effect = RuntimeError("API error")

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        mock_db.get_publishing_state.return_value = {
            "publishing_started_at": recent_time,
            "publishing_branch": "content/update-2024-01-01-test",
        }
        orchestrator = PROrchestrator(git=mock_git, db=mock_db, config=config_obj)

        result = orchestrator.attempt_recovery(
            numeric_id=42,
            article_id="42",
            article=make_article(),
        )

        assert result is None
