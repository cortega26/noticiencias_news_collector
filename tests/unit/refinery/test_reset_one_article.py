"""
Plan 017 — reset_one_article divergence-bug fix tests.

Tests that the per-item Reset action (``reset_one_article``) only deletes
DB rows *after* the git push succeeds, preventing the DB/file/git
divergence that the rejected UI slice had.

Uses mocks — no real git or DB operations are performed.

Run: .venv/bin/python -m pytest tests/unit/refinery/test_reset_one_article.py -q
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.refinery.published_content import PublishedArticleRecord, reset_one_article


def _make_article(
    tmp_path: Path,
    file_name: str = "test.md",
    refinery_id: str | None = "2026-01-15-test",
):
    """Create a temporary article file and return a record."""
    file_path = tmp_path / file_name
    file_path.write_text("# Test\n")
    from datetime import datetime, UTC

    return PublishedArticleRecord(
        file_path=file_path,
        file_name=file_name,
        title="Test Article",
        refinery_id=refinery_id,
        frontmatter={"title": "Test"},
        modified_at=datetime.now(UTC),
    )


class TestResetOneArticle:
    """Tests for the per-item Reset action."""

    def test_successful_reset_deletes_db_rows_after_push(self, tmp_path: Path):
        """DB rows are deleted only after the push succeeds."""
        article = _make_article(tmp_path)
        mock_repo = MagicMock()
        mock_db = MagicMock()

        with patch("apps.refinery.published_content.git.Repo", return_value=mock_repo):
            reset_one_article(tmp_path, article, mock_db)

        # Git operations happened in order
        mock_repo.index.remove.assert_called_once()
        assert not article.file_path.exists()  # file was unlinked
        mock_repo.index.commit.assert_called_once()
        mock_repo.remotes.origin.push.assert_called_once()

        # DB rows were deleted (after push succeeded)
        assert mock_db.delete_article.call_count == 2
        mock_db.delete_article.assert_any_call("2026-01-15-test")
        mock_db.delete_article.assert_any_call("2026-01-15-test.md")

    def test_db_rows_not_deleted_if_push_fails(self, tmp_path: Path):
        """
        Divergence-bug fix: if the push fails, DB rows are NOT deleted.
        The article can be retried because the DB still has its rows.
        """
        article = _make_article(tmp_path)
        mock_repo = MagicMock()
        mock_repo.remotes.origin.push.side_effect = RuntimeError("network error")
        mock_db = MagicMock()

        with patch("apps.refinery.published_content.git.Repo", return_value=mock_repo):
            with pytest.raises(RuntimeError, match="network error"):
                reset_one_article(tmp_path, article, mock_db)

        # Git index.remove and unlink happened
        mock_repo.index.remove.assert_called_once()
        assert not article.file_path.exists()
        # Commit happened (local)
        mock_repo.index.commit.assert_called_once()
        # Push failed
        mock_repo.remotes.origin.push.assert_called_once()
        # DB rows were NOT deleted — the divergence-bug fix
        mock_db.delete_article.assert_not_called()

    def test_db_rows_not_deleted_if_unlink_fails(self, tmp_path: Path):
        """
        If the file unlink fails, neither commit, push, nor DB delete happen.
        """
        article = _make_article(tmp_path)
        mock_repo = MagicMock()
        mock_db = MagicMock()

        # Make unlink fail by pointing to a non-existent file
        article_no_file = PublishedArticleRecord(
            file_path=tmp_path / "nonexistent.md",
            file_name="nonexistent.md",
            title="Test",
            refinery_id="2026-01-15-test",
            frontmatter={},
            modified_at=article.modified_at,
        )

        with patch("apps.refinery.published_content.git.Repo", return_value=mock_repo):
            with pytest.raises(FileNotFoundError):
                reset_one_article(tmp_path, article_no_file, mock_db)

        # index.remove was called but commit/push/DB delete were not
        mock_repo.index.remove.assert_called_once()
        mock_repo.index.commit.assert_not_called()
        mock_repo.remotes.origin.push.assert_not_called()
        mock_db.delete_article.assert_not_called()

    def test_no_refinery_id_skips_db_delete(self, tmp_path: Path):
        """If the article has no refinery_id, DB delete is skipped."""
        article = _make_article(tmp_path, refinery_id=None)
        mock_repo = MagicMock()
        mock_db = MagicMock()

        with patch("apps.refinery.published_content.git.Repo", return_value=mock_repo):
            reset_one_article(tmp_path, article, mock_db)

        # Git operations happened
        mock_repo.index.remove.assert_called_once()
        mock_repo.index.commit.assert_called_once()
        mock_repo.remotes.origin.push.assert_called_once()
        # DB rows were NOT deleted (no refinery_id)
        mock_db.delete_article.assert_not_called()
