from unittest.mock import MagicMock

import pytest
from news_collector.logic.workflows.refinery_engine import RefineryEngine


class TestRefineryCanonical:
    """
    Verifies S2-A Canonical URL Integrity constraints.
    """

    @pytest.fixture
    def engine(self, tmp_path):
        # Mock dependencies
        db = MagicMock()
        db.get_canonical_slug.return_value = None  # Default: No locked identity
        git = MagicMock()
        editor = MagicMock()
        config = MagicMock()
        config.app.policy_integrity_mode = "disabled"

        # Configure output of editor
        editor.process_article.return_value = (
            '---\ntitle: Test\nrefinery_id: "101"\n---\nContent'
        )

        return RefineryEngine(db, git, editor, config)

    def test_preserves_existing_filename(self, engine, tmp_path):
        """
        Scenario: Article 101 was published yesterday as '2025-01-01-old-slug.md'.
        Today is 2026-01-25. Re-running should reuse '2025-01-01-old-slug.md'.
        """
        target_dir = tmp_path / "target"
        posts_dir = target_dir / "src/content/posts"
        posts_dir.mkdir(parents=True)

        # Setup existing file
        existing_file = posts_dir / "2025-01-01-old-slug.md"
        existing_file.write_text('---\nrefinery_id: "101"\n---\nOld Content')

        article_payload = {
            "id": "101",
            "title": "New Title",
            "published_date": "2026-01-25",
        }

        # Execute
        engine.process_single_article(article_payload, MagicMock(), target_dir)

        # Assertions
        # 1. New file should NOT exist
        assert not (posts_dir / "2026-01-25-article-101.md").exists()

        # 2. Old file SHOULD be updated
        assert existing_file.exists()
        assert "Content" in existing_file.read_text()  # Content updated

        # 3. Editor called with preserved date
        engine.editor.process_article.assert_called_with(
            article_payload, override_date="2025-01-01"
        )

    def test_creates_deterministic_filename_new(self, engine, tmp_path):
        """
        Scenario: New article 102. published_date in payload is 2025-12-25.
        Filename should use that date, NOT today's date.
        """
        target_dir = tmp_path / "target"
        posts_dir = target_dir / "src/content/posts"

        article_payload = {
            "id": "102",
            "title": "Xmas",
            "published_date": "2025-12-25T10:00:00Z",
        }

        # Execute
        engine.process_single_article(article_payload, MagicMock(), target_dir)

        # Check expected filename
        expected_file = posts_dir / "2025-12-25-article-102.md"
        assert expected_file.exists()

        # Verify date passed to editor
        engine.editor.process_article.assert_called_with(
            article_payload, override_date="2025-12-25"
        )
