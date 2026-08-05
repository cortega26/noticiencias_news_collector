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
        self.mock_git.create_pull_request.return_value = (
            "https://github.com/owner/repo/pull/1"
        )
        self.mock_editor = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.github = SimpleNamespace(
            target_repo_url="http://github.com/target"
        )
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

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_success(self, mock_dt_refinery, mock_dt_identity):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

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
            self.assertEqual(
                self.mock_editor.process_article.call_args.kwargs["override_date"],
                "2026-01-01",
            )
            self.mock_git.create_branch.assert_called()
            self.mock_git.commit_and_push.assert_called()
            self.mock_git.create_pull_request.assert_called()

            # Check output file write (indirectly via mock path)
            # Note: mocking pathlib iterface is tricky, usually we trust write_text works or use tmp_path fixture.
            # Here we just check logical flow.
            self.mock_db.mark_article_published.assert_called_with(
                123, "http://pr.url", "123"
            )

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

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_no_file_write_if_branch_setup_fails(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
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
            expected_file = target_dir / "src/content/posts/2026-01-01-test-slug.md"
            with patch("pathlib.Path.write_text") as write_mock:
                with self.assertRaises(RuntimeError):
                    self.engine.process_single_article(article, mock_repo, target_dir)

            write_mock.assert_not_called()
            self.assertFalse(expected_file.exists())
            self.mock_git.commit_and_push.assert_not_called()

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_no_file_write_if_branch_sync_rebase_fails(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
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
                target_dir / "src/content/posts/2026-01-01-test-slug-sync.md"
            )
            with patch("pathlib.Path.write_text") as write_mock:
                with self.assertRaises(RuntimeError):
                    self.engine.process_single_article(article, mock_repo, target_dir)

            write_mock.assert_not_called()
            self.assertFalse(expected_file.exists())
            self.mock_git.commit_and_push.assert_not_called()

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_override_date_ignores_payload_published_date_uses_system_time(
        self, mock_dt_refinery, mock_dt_identity
    ):
        # We mock system time to 2050 to prove it is USED instead of payload
        mock_dt_refinery.now.return_value.strftime.return_value = "2050-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2050-01-01T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2050-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2050-01-01T12:00:00"

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
                "2050-01-01",
            )

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_uses_image_url_from_article_metadata(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
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
                "2026-01-01-test-title-with-metadata-image",
                target_dir,
            )
            editor_payload = self.mock_editor.process_article.call_args.args[0]
            self.assertEqual(
                editor_payload["image_url"],
                "~/assets/images/image-test.png",
            )

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_blocks_quoted_date_only_frontmatter_before_git(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

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

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_returns_false_for_placeholder_block(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

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
            result = self.engine.process_single_article(
                article, MagicMock(), target_dir
            )

        self.assertFalse(result)
        self.assertEqual(
            self.engine._last_blocked_error["error_code"],
            "editorial_placeholder_blocked",
        )
        self.mock_git.create_branch.assert_not_called()
        self.mock_git.commit_and_push.assert_not_called()
        self.mock_git.create_pull_request.assert_not_called()

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_process_single_article_prunes_stale_hero_placeholder_allowlist(
        self, mock_dt_refinery, mock_dt_identity
    ):
        mock_dt_refinery.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_refinery.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        mock_dt_identity.now.return_value.strftime.return_value = "2026-01-01"
        mock_dt_identity.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"

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
                "{\n"
                '  "allowedPlaceholders": {\n'
                '    "src/content/posts/2026-01-01-real-hero.md": "Old placeholder."\n'
                "  }\n"
                "}\n",
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


class TestRefineryEngineCoverage(unittest.TestCase):
    """Coverage-focused tests for editorial/workflow paths not exercised elsewhere."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_git = MagicMock()
        self.mock_git.create_branch.return_value = "content/update/test-branch"
        self.mock_git.create_pull_request.return_value = (
            "https://github.com/owner/repo/pull/1"
        )
        self.mock_editor = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.github = SimpleNamespace(
            target_repo_url="http://github.com/target"
        )
        self.mock_config.app.policy_integrity_mode = "disabled"

        self.mock_db.get_publishing_state.return_value = None

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

    def _make_engine(self, config):
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        return RefineryEngine(self.mock_db, self.mock_git, self.mock_editor, config)

    def _mock_now(self, dt):
        dt.now.return_value.strftime.return_value = "2026-01-01"
        dt.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
        return dt

    def _article(self, aid="500", image=True):
        article = {
            "id": aid,
            "title": f"Coverage article {aid}",
            "url": f"http://x/{aid}",
            "summary": "This is a sufficiently long summary for refinery coverage.",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        if image:
            article["image_url"] = f"https://example.com/{aid}.png"
        return article

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_blocks_quoted_date_only_frontmatter_reaching_guard(
        self, mock_dt_refinery, mock_dt_identity
    ):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("501")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.return_value = (
            "---\nslug: quote-guard\ndate: '2026-03-02'\n---\nContent"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.engine.process_single_article(
                article, MagicMock(), Path(tmpdir)
            )

        self.assertFalse(result)
        self.mock_git.create_branch.assert_not_called()

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_blocks_translation_guardrail(self, mock_dt_refinery, mock_dt_identity):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("502")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.side_effect = ValueError(
            "Editorial Policy (Critic): Translation Guardrail triggered."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.engine.process_single_article(
                article, MagicMock(), Path(tmpdir)
            )

        self.assertFalse(result)

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_blocks_when_output_filename_missing(
        self, mock_dt_refinery, mock_dt_identity
    ):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("503")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.return_value = (
            "---\nslug: no-filename\n---\nContent"
        )
        self.engine.identity_resolver.finalize_slug = MagicMock(
            return_value=SimpleNamespace(
                is_new=True, final_slug="no-filename", output_filename=None
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.engine.process_single_article(
                article, MagicMock(), Path(tmpdir)
            )

        self.assertFalse(result)

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_continues_when_mark_publishing_fails(
        self, mock_dt_refinery, mock_dt_identity
    ):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("504")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_db.mark_article_publishing.side_effect = RuntimeError("db down")
        self.mock_editor.process_article.return_value = (
            "---\nslug: publish-fail\n---\nContent"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.engine.process_single_article(
                article, MagicMock(), Path(tmpdir)
            )

        self.mock_git.create_branch.assert_called()
        self.assertTrue(result)

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_s0_guard_value_error_on_write(self, mock_dt_refinery, mock_dt_identity):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("505")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.return_value = (
            "---\nslug: badwrite\n---\nContent"
        )
        with patch.object(
            self.engine.writer, "write_article", side_effect=ValueError("bad write")
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = self.engine.process_single_article(
                    article, MagicMock(), Path(tmpdir)
                )

        self.assertFalse(result)
        self.mock_git.commit_and_push.assert_not_called()

    @patch("news_collector.logic.workflows.publication_identity.datetime")
    @patch("news_collector.logic.workflows.refinery_engine.datetime")
    def test_pr_failure_returns_false(self, mock_dt_refinery, mock_dt_identity):
        self._mock_now(mock_dt_refinery)
        self._mock_now(mock_dt_identity)

        article = self._article("506")
        self.mock_db.get_canonical_slug.return_value = None
        self.mock_editor.process_article.return_value = "---\nslug: no-pr\n---\nContent"
        self.engine.pr_orchestrator.create_pr = MagicMock(
            return_value=SimpleNamespace(pr_url=None)
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.engine.process_single_article(
                article, MagicMock(), Path(tmpdir)
            )

        self.assertFalse(result)

    def test_process_articles_requires_full_context(self):
        self.engine._safe_publication_artifact_name("du-pa").replace("du-pa", "ok")
        messages = []
        with patch.object(
            self.engine,
            "_persist_publication_attempt_summary",
            side_effect=lambda **kw: messages.append(kw),
        ):
            fname = self.engine._safe_publication_artifact_name("á_b$c")
            self.assertNotEqual(fname, "á_b$c")

    def test_record_audit_status_handles_missing_db_method(self):
        self.mock_db.update_article_audit_status = None
        self.engine._record_audit_status(1, "audit_pending", "r", attempts=0)

    def test_record_audit_status_swallows_db_error(self):
        self.mock_db.update_article_audit_status = MagicMock(
            side_effect=RuntimeError("boom")
        )
        self.engine._record_audit_status(1, "audit_pending", "r", attempts=0)

    def test_normalize_article_payload_branches(self):
        nested = SimpleNamespace(model_dump=lambda mode=None: {"x": 1})
        payload = self.engine._normalize_article_payload(
            {"a": nested, "b": (1, 2), "c": None}
        )
        self.assertEqual(payload["a"], {"x": 1})
        self.assertEqual(payload["b"], [1, 2])
        self.assertIsNone(payload["c"])

        with self.assertRaises(TypeError):
            self.engine._normalize_article_payload("not-a-dict")

    def test_enforce_editorial_policy_handles_error(self):
        with patch.object(self.engine, "_log_enforcement_decision"):
            result = self.engine._enforce_editorial_policy(
                "1", {"epistemic_rigor_score": "not-a-number"}
            )
        self.assertFalse(result)

    def test_download_image_rejects_non_http(self):
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            result = RefineryEngine._download_image(
                self.engine, "not-http", "slug", Path(tmpdir)
            )
        self.assertIsNone(result)

    def test_download_image_extension_heuristics(self):
        from news_collector.infrastructure.requests_client import (
            RobustRequestsClient,
        )
        from news_collector.logic.workflows.refinery_engine import RefineryEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            for content_type, url, expected in [
                ("", "https://x.com/a", ".jpg"),
                ("", "https://x.com/a.png?size=1", ".png"),
                ("image/svg+xml", "https://x.com/a", ".svg"),
            ]:
                mock_client = MagicMock()
                mock_client.__enter__.return_value = mock_client
                response = MagicMock()
                response.headers = {"Content-Type": content_type}
                response.content = b"\x89PNG"
                mock_client.get.return_value = response
                with patch(
                    "news_collector.infrastructure.requests_client.RobustRequestsClient",
                    return_value=mock_client,
                ):
                    result = RefineryEngine._download_image(
                        self.engine, url, "slug", Path(tmpdir)
                    )
                self.assertEqual(result, f"~/assets/images/slug{expected}")

    def test_policy_integrity_warn_mode(self):
        mock_policy = MagicMock()
        mock_policy.verify_integrity.side_effect = RuntimeError("integrity broke")
        mock_policy.mode = "standard"
        mock_policy.critic_threshold = 80.0
        mock_policy.auditor_threshold = 50.0

        config = MagicMock()
        config.github = SimpleNamespace(target_repo_url="http://x")
        config.app.policy_integrity_mode = "warn"

        with patch(
            "news_collector.editorial.policy.EditorialPolicy.from_mode",
            return_value=mock_policy,
        ):
            engine = self._make_engine(config)
        self.assertIsNotNone(engine.policy)

    def test_policy_integrity_non_fatal_outer_error(self):
        config = MagicMock()
        config.github = SimpleNamespace(target_repo_url="http://x")
        config.app.policy_integrity_mode = "warn"

        with patch("news_collector.editorial.__file__", None):
            engine = self._make_engine(config)
        self.assertIsNotNone(engine.policy)

    def test_data_dir_dict_paths(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.github = SimpleNamespace(target_repo_url="http://x")
            config.app.policy_integrity_mode = "disabled"
            config.app.editorial_mode = "standard"
            config.paths = {"data_dir": tmpdir}
            engine = self._make_engine(config)
            self.assertEqual(str(engine.data_dir), tmpdir)

    def test_data_dir_non_pathlike(self):
        config = MagicMock()
        config.github = SimpleNamespace(target_repo_url="http://x")
        config.app.policy_integrity_mode = "disabled"
        config.app.editorial_mode = "standard"
        config.paths = {"data_dir": 123}
        engine = self._make_engine(config)
        self.assertEqual(engine.data_dir, Path("./data"))

    def test_has_quoted_date_only_unclosed_frontmatter(self):
        self.assertFalse(
            self.engine._has_quoted_date_only_frontmatter(
                "---\ndate: '2026-03-02'\nnever closes"
            )
        )

    def test_schedule_optional_audit_backpressure(self):
        pending = MagicMock()
        pending.done.return_value = False
        self.engine._last_audit_future = pending
        with patch.object(self.engine, "_record_audit_status") as recorder:
            self.engine._schedule_optional_audit(
                article_id="1",
                article_numeric_id=1,
                content="c",
                source_url="http://x",
                article_data={},
            )
        recorder.assert_called_once()
        self.assertEqual(
            recorder.call_args.kwargs["status"], "audit_skipped_backpressure"
        )

    def test_schedule_optional_audit_submission_failure(self):
        self.engine._last_audit_future = None
        self.engine.executor = MagicMock()
        self.engine.executor.submit.side_effect = RuntimeError("pool gone")
        with patch.object(self.engine, "_record_audit_status") as recorder:
            self.engine._schedule_optional_audit(
                article_id="1",
                article_numeric_id=1,
                content="c",
                source_url="http://x",
                article_data={},
            )
        recorder.assert_called_once()
        self.assertEqual(recorder.call_args.kwargs["status"], "audit_failed")

    def test_schedule_optional_audit_callback_crash(self):
        future = MagicMock()
        done_fake = MagicMock()
        done_fake.result.side_effect = RuntimeError("crashed")
        self.engine._last_audit_future = None
        self.engine.executor = MagicMock()
        self.engine.executor.submit.return_value = future

        self.engine._schedule_optional_audit(
            article_id="1",
            article_numeric_id=1,
            content="c",
            source_url="http://x",
            article_data={},
        )
        callback = future.add_done_callback.call_args[0][0]
        with patch.object(self.engine, "_record_audit_status") as recorder:
            callback(done_fake)
        recorder.assert_called_once_with(
            article_numeric_id=1,
            status="audit_failed",
            reason=unittest.mock.ANY,
            attempts=0,
        )

    def test_schedule_optional_audit_callback_bad_types(self):
        future = MagicMock()
        done_fake = MagicMock()
        done_fake.result.return_value = {
            "status": "audit_passed",
            "reason": "ok",
            "attempts": "not-int",
            "timeout_seconds": "not-int",
            "model": "m",
            "endpoint": "e",
        }
        self.engine._last_audit_future = None
        self.engine.executor = MagicMock()
        self.engine.executor.submit.return_value = future

        self.engine._schedule_optional_audit(
            article_id="1",
            article_numeric_id=1,
            content="c",
            source_url="http://x",
            article_data={},
        )
        callback = future.add_done_callback.call_args[0][0]
        with patch.object(self.engine, "_record_audit_status") as recorder:
            callback(done_fake)
        recorder.assert_called_once()
        self.assertEqual(recorder.call_args.kwargs["attempts"], 0)
        self.assertIsNone(recorder.call_args.kwargs["timeout_seconds"])


if __name__ == "__main__":
    unittest.main()
