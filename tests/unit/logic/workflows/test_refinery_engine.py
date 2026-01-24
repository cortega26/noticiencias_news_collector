import sys
from unittest.mock import MagicMock, patch

# Import moved to test/setup to allow patching
# from news_collector.logic.workflows.refinery_engine import RefineryEngine


import unittest

class TestRefineryEngine(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_git = MagicMock()
        self.mock_editor = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.target_repo_url = "http://github.com/target"

        # Safe patching context
        self.git_patch = patch.dict(sys.modules, {"git": self.mock_git})
        self.git_patch.start()
        
        # Import inside patch context
        from news_collector.logic.workflows.refinery_engine import RefineryEngine
        self.engine = RefineryEngine(
            self.mock_db, self.mock_git, self.mock_editor, self.mock_config
        )

    def tearDown(self):
        self.git_patch.stop()

    def test_extract_slug(self):
        content = "---\nslug: my-slug\n---"
        self.assertEqual(self.engine._extract_slug(content, "123"), "my-slug")

        content_no_slug = "Just content"
        self.assertEqual(
            self.engine._extract_slug(content_no_slug, "123"), "article-123"
        )

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_success(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"

        # Setup Inputs
        article = {"id": "123", "title": "Test Title"}
        mock_repo = MagicMock()
        mock_target_dir = MagicMock()
        mock_target_dir / "src/content/posts"

        # Setup Editor
        self.mock_editor.process_article.return_value = (
            "---\nslug: test-slug\n---\nContent"
        )

        # Setup Git
        self.mock_git.create_branch.return_value = "content/add/test-branch"
        self.mock_git.create_pull_request.return_value = "http://pr.url"

        # Run
        result = self.engine.process_single_article(article, mock_repo, mock_target_dir)

        # Assertions
        self.assertTrue(result)
        self.mock_editor.process_article.assert_called_with(article)
        self.mock_git.create_branch.assert_called()
        self.mock_git.commit_and_push.assert_called()
        self.mock_git.create_pull_request.assert_called()

        # Check output file write (indirectly via mock path)
        # Note: mocking pathlib iterface is tricky, usually we trust write_text works or use tmp_path fixture.
        # Here we just check logical flow.
        self.mock_db.mark_article_published.assert_called_with(123, "http://pr.url")

    def test_process_articles_batch(self):
        articles = [{"id": "1"}, {"id": "2"}]
        self.engine.process_single_article = MagicMock(side_effect=[True, False])

        summary = self.engine.process_articles(articles, MagicMock(), MagicMock())

        self.assertEqual(summary["processed_count"], 1)
        self.assertEqual(
            len(summary["errors"]), 0
        )  # Returns False generally doesn't mean Exception unless raised

        # If one raises exception
        self.engine.process_single_article = MagicMock(side_effect=Exception("Boom"))
        summary = self.engine.process_articles([{"id": "3"}], MagicMock(), MagicMock())
        self.assertEqual(len(summary["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
