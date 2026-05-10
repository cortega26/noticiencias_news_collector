import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import json

# Import moved to test/setup to allow patching
# from news_collector.logic.workflows.refinery_engine import RefineryEngine


class TestRefineryEngine(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_git = MagicMock()
        self.mock_git.create_branch.return_value = "content/update/test-branch"
        self.mock_git.create_pull_request.return_value = "https://github.com/owner/repo/pull/1"
        self.mock_editor = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.github = SimpleNamespace(target_repo_url="http://github.com/target")
        self.mock_config.app.policy_integrity_mode = "disabled"

        # B-01: Ensure publishing recovery does not interfere with normal tests
        self.mock_db.get_publishing_state.return_value = None

        # Safe patching context
        self.git_patch = patch.dict(sys.modules, {"git": self.mock_git})
        self.git_patch.start()
        self.auditor_patch = patch(
            "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
        )
        self.mock_auditor_cls = self.auditor_patch.start()
        self.mock_auditor = MagicMock()
        self.mock_auditor.should_run_fast.return_value = False
        self.mock_auditor.get_cached_score.return_value = None
        self.mock_auditor_cls.return_value = self.mock_auditor

        # Import inside patch context
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        self.engine = RefineryEngine(
            self.mock_db, self.mock_git, self.mock_editor, self.mock_config
        )
        self.engine._download_image = MagicMock(
            return_value="~/assets/images/test-image.png"
        )

    def tearDown(self):
        self.auditor_patch.stop()
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
        mock_dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

        # Setup Inputs
        article = {
            "id": "123",
            "title": "Test valid title",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for refinery validation.",
            "image_url": "https://example.com/test-image.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        mock_repo = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            target_dir / "src/content/posts"

            # Setup Editor
            self.mock_editor.process_article.return_value = (
                "---\nslug: test-slug\n---\nContent"
            )

            # Setup Git
            self.mock_git.create_branch.return_value = "content/add/test-branch"
            self.mock_git.create_pull_request.return_value = "http://pr.url"

            # Configure DB to simulate no existing slug
            self.mock_db.get_canonical_slug.return_value = None

            # Run
            result = self.engine.process_single_article(article, mock_repo, target_dir)

            # Assertions
            self.assertTrue(result)
            # We now pass override_date="2026-01-01" because src date is not provided, so it uses now()
            self.assertEqual(
                self.mock_editor.process_article.call_args.kwargs["override_date"],
                "2024-01-01",
            )
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

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_no_file_write_if_branch_setup_fails(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        article = {
            "id": "123",
            "title": "Test valid title",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for refinery validation.",
            "image_url": "https://example.com/test-image.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        mock_repo = MagicMock()
        self.mock_editor.process_article.return_value = (
            "---\nslug: test-slug\n---\nContent"
        )
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_git.create_branch.side_effect = RuntimeError("fetch failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            expected_file = target_dir / "src/content/posts/2024-01-01-test-slug.md"
            with patch("pathlib.Path.write_text") as write_mock:
                with self.assertRaises(RuntimeError):
                    self.engine.process_single_article(article, mock_repo, target_dir)

            write_mock.assert_not_called()
            self.assertFalse(expected_file.exists())
            self.mock_git.commit_and_push.assert_not_called()

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_no_file_write_if_branch_sync_rebase_fails(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        article = {
            "id": "124",
            "title": "Test Title 2",
            "url": "http://x",
            "summary": "This is another sufficiently long summary for refinery validation.",
            "image_url": "https://example.com/test-image-2.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        mock_repo = MagicMock()
        self.mock_editor.process_article.return_value = (
            "---\nslug: test-slug-sync\n---\nContent"
        )
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_git.create_branch.side_effect = RuntimeError("rebase failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            expected_file = (
                target_dir / "src/content/posts/2024-01-01-test-slug-sync.md"
            )
            with patch("pathlib.Path.write_text") as write_mock:
                with self.assertRaises(RuntimeError):
                    self.engine.process_single_article(article, mock_repo, target_dir)

            write_mock.assert_not_called()
            self.assertFalse(expected_file.exists())
            self.mock_git.commit_and_push.assert_not_called()

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_override_date_strictly_follows_payload_published_date(self, mock_dt):
        # We mock system time to 2050 to prove it is IGNORED in favor of payload
        mock_dt.now.return_value.strftime.return_value = "2050-01-01"
        mock_dt.now.return_value.isoformat.return_value = "2050-01-01T12:00:00"

        article = {
            "id": "1999-id",
            "title": "A vintage article",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for vintage refinery validation.",
            "image_url": "https://example.com/vintage.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(1999, 12, 31),
            "source_metadata": {},
        }
        mock_repo = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            target_dir / "src/content/posts"

            self.mock_editor.process_article.return_value = (
                "---\nslug: test-slug\n---\nContent"
            )
            self.mock_db.get_canonical_slug.return_value = None

            result = self.engine.process_single_article(article, mock_repo, target_dir)

            self.assertTrue(result)
            self.assertEqual(
                self.mock_editor.process_article.call_args.kwargs["override_date"],
                "1999-12-31",
            )

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_uses_image_url_from_article_metadata(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        article = {
            "id": "125",
            "title": "Test Title With Metadata Image",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for metadata image handling.",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "article_metadata": {"image_url": "https://example.com/test.png"},
            "source_metadata": {},
        }
        mock_repo = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            self.mock_editor.process_article.return_value = (
                "---\nslug: image-test\n---\nContent"
            )
            self.mock_db.get_canonical_slug.return_value = None
            self.mock_git.create_branch.return_value = "content/add/image-test"
            self.mock_git.create_pull_request.return_value = "http://pr.url/image"
            self.engine._download_image = MagicMock(
                return_value="~/assets/images/image-test.png"
            )

            result = self.engine.process_single_article(article, mock_repo, target_dir)

            self.assertTrue(result)
            self.engine._download_image.assert_called_once_with(
                "https://example.com/test.png",
                "2024-01-01-test-title-with-metadata-image",
                target_dir,
            )
            editor_payload = self.mock_editor.process_article.call_args.args[0]
            self.assertEqual(
                editor_payload["image_url"],
                "~/assets/images/image-test.png",
            )

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_blocks_quoted_date_only_frontmatter_before_git(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

        article = {
            "id": "125",
            "title": "Quoted date should be blocked",
            "url": "http://x",
            "summary": "sum",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        mock_repo = MagicMock()
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.return_value = (
            "---\n" "slug: test-slug\n" "date: '2026-03-02'\n" "---\n" "Content"
        )

        result = self.engine.process_single_article(article, mock_repo, Path("/tmp"))

        self.assertFalse(result)
        self.mock_git.create_branch.assert_not_called()
        self.mock_git.commit_and_push.assert_not_called()
        self.mock_git.create_pull_request.assert_not_called()

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_returns_false_for_placeholder_block(self, mock_dt):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

        from news_collector.components.editorial.ai_editor import (
            GeneratedArticleValidationError,
        )

        article = {
            "id": "127",
            "title": "Placeholder blocked article",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for placeholder blocking.",
            "image_url": "https://example.com/test-image-4.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }

        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.side_effect = GeneratedArticleValidationError(
            "Generated article body contains placeholder/error language and cannot be published."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            result = self.engine.process_single_article(article, MagicMock(), target_dir)

        self.assertFalse(result)
        self.assertEqual(
            self.engine._last_blocked_error["error_code"],
            "editorial_placeholder_blocked",
        )
        self.mock_git.create_branch.assert_not_called()
        self.mock_git.commit_and_push.assert_not_called()
        self.mock_git.create_pull_request.assert_not_called()

    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_prunes_stale_hero_placeholder_allowlist(
        self, mock_dt
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

        article = {
            "id": "126",
            "title": "Test Title With Real Hero",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for allowlist cleanup.",
            "image_url": "https://example.com/test-image-3.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        mock_repo = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            allowlist_path = (
                target_dir / "data" / "hero-image-placeholder-allowlist.json"
            )
            allowlist_path.parent.mkdir(parents=True, exist_ok=True)
            allowlist_path.write_text(
                '{\n'
                '  "allowedPlaceholders": {\n'
                '    "src/content/posts/2024-01-01-real-hero.md": "Old placeholder."\n'
                "  }\n"
                '}\n',
                encoding="utf-8",
            )

            self.mock_editor.process_article.return_value = (
                "---\n"
                "slug: real-hero\n"
                'image: "~/assets/images/real-hero.png"\n'
                "image_alt: Real hero image\n"
                "---\n"
                "Content"
            )
            self.mock_db.get_canonical_slug.return_value = None
            self.mock_git.create_branch.return_value = "content/update/real-hero"
            self.mock_git.create_pull_request.return_value = "http://pr.url/real-hero"
            self.engine._download_image = MagicMock(
                return_value="~/assets/images/real-hero.png"
            )

            result = self.engine.process_single_article(article, mock_repo, target_dir)

            self.assertTrue(result)
            synced_allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
            self.assertEqual(synced_allowlist["allowedPlaceholders"], {})


if __name__ == "__main__":
    unittest.main()
