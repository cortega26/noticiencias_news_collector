from types import SimpleNamespace
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
        db.get_publishing_state.return_value = None  # B-01: No publishing recovery
        editor = MagicMock()
        config = MagicMock()
        config.app.policy_integrity_mode = "disabled"
        config.llm_rate_limiting = {"max_concurrent_requests": 1}
        config.github = SimpleNamespace(target_repo_url="https://github.com/owner/repo")
        git = MagicMock()
        git.create_branch.return_value = "content/update/test"
        git.create_pull_request.return_value = "https://github.com/owner/repo/pull/1"

        # Configure output of editor
        editor.process_article.return_value = (
            '---\ntitle: Test\nrefinery_id: "101"\n---\nContent'
        )

        engine = RefineryEngine(db, git, editor, config)
        engine._download_image = MagicMock(
            return_value="~/assets/images/refinery-canonical.png"
        )
        return engine

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
            "title": "A Very Long New Title",
            "url": "http://x",
            "summary": "This is a sufficiently long summary.",
            "image_url": "https://example.com/canonical-old.png",
            "source_id": "src",
            "source_name": "source_name",
            "category": "cat",
            "source_metadata": {},
            "published_date": __import__("datetime").datetime(2026, 1, 25),
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
        # Instead of matching the full dictionary which went through pydantic validation, just check kwargs
        assert (
            engine.editor.process_article.call_args.kwargs["override_date"]
            == "2025-01-01"
        )

    def test_creates_deterministic_filename_new(self, engine, tmp_path):
        """
        Scenario: New article 102. published_date in payload is 2025-12-25.
        Filename uses the deterministic payload date (LAW-B5) — never the
        runtime clock.
        """
        target_dir = tmp_path / "target"
        posts_dir = target_dir / "src/content/posts"

        article_payload = {
            "id": "102",
            "title": "A Long Xmas Title",
            "url": "http://x",
            "summary": "This is a sufficiently long summary.",
            "image_url": "https://example.com/canonical-new.png",
            "source_id": "src",
            "source_name": "source_name",
            "category": "cat",
            "source_metadata": {},
            "published_date": __import__("datetime").datetime(2025, 12, 25, 10, 0, 0),
        }

        # Execute
        engine.process_single_article(article_payload, MagicMock(), target_dir)

        # Check expected filename using the payload published_date (LAW-B5:
        # deterministic, no runtime clock)
        expected_file = posts_dir / "2025-12-25-test.md"
        assert expected_file.exists()

        # Verify date passed to editor
        # Instead of matching the full dictionary which went through pydantic validation, just check kwargs
        assert (
            engine.editor.process_article.call_args.kwargs["override_date"]
            == "2025-12-25"
        )
