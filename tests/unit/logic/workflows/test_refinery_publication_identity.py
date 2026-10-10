"""Focused Refinery publication identity regression tests."""

import hashlib
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_process_single_article_records_attempt_and_exact_artifact_hash(tmp_path):
    mock_db = MagicMock()
    mock_db.get_publishing_state.return_value = None
    mock_db.get_canonical_slug.return_value = None
    mock_git = MagicMock()
    mock_git.create_branch.return_value = "content/add/test-branch"
    mock_git.create_pull_request.return_value = "http://pr.url"
    mock_editor = MagicMock()
    mock_editor.process_article.return_value = "---\nslug: test-slug\n---\nContent"
    mock_config = MagicMock()
    mock_config.github = SimpleNamespace(target_repo_url="http://github.com/target")
    mock_config.app.policy_integrity_mode = "disabled"

    article = {
        "id": "123",
        "title": "Test valid title",
        "url": "http://x",
        "summary": "This is a sufficiently long summary for refinery validation.",
        "image_url": "https://example.com/test-image.png",
        "image_alt": "Fotografía de prueba para la suite.",
        "source_id": "src",
        "source_name": "src",
        "category": "cat",
        "published_date": datetime(2024, 1, 1),
        "source_metadata": {},
    }
    mock_repo = MagicMock()
    target_dir = tmp_path / "target"

    with patch.dict(sys.modules, {"git": mock_git}):
        with patch(
            "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
        ) as auditor_cls:
            auditor = MagicMock()
            auditor.should_run_fast.return_value = False
            auditor.get_cached_score.return_value = None
            auditor_cls.return_value = auditor
            from news_collector.logic.workflows.refinery_engine import RefineryEngine

            engine = RefineryEngine(mock_db, mock_git, mock_editor, mock_config)
            engine._download_image = MagicMock(
                return_value="~/assets/images/test-image.png"
            )
            with patch(
                "news_collector.logic.workflows.refinery_engine.datetime"
            ) as clock:
                clock.now.return_value.strftime.return_value = "2026-01-01"
                clock.now.return_value.isoformat.return_value = "2026-05-10T12:00:00"
                result = engine.process_single_article(article, mock_repo, target_dir)

    assert result
    assert engine._extract_slug("---\nslug: my-slug\n---", "123") == "my-slug"
    assert engine._extract_slug("Just content", "123") == "article-123"
    assert mock_editor.process_article.call_args.kwargs["override_date"] == "2024-01-01"
    mock_git.create_branch.assert_called()
    mock_git.commit_and_push.assert_called()
    mock_git.create_pull_request.assert_called()

    published_call = mock_db.mark_article_published.call_args
    assert published_call.args == (123, "http://pr.url", "123")
    attempt_id = published_call.kwargs["publication_attempt_id"]
    assert (
        mock_db.mark_article_publishing.call_args.kwargs["publication_attempt_id"]
        == attempt_id
    )
    markdown_files = list((target_dir / "src/content/posts").glob("*.md"))
    assert len(markdown_files) == 1
    assert (
        published_call.kwargs["content_sha256"]
        == hashlib.sha256(markdown_files[0].read_bytes()).hexdigest()
    )
