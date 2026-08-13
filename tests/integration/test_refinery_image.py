from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.refinery_engine import RefineryEngine


@pytest.fixture
def mock_refinery_engine(tmp_path):
    db_manager = MagicMock()
    git_handler = MagicMock()
    git_handler.create_branch.return_value = "content/update/test"
    git_handler.create_pull_request.return_value = "https://github.com/org/repo/pull/1"
    editor_agent = MagicMock()
    # Mock process_article simply to return content with frontmatter
    editor_agent.process_article.return_value = (
        "---\ntitle: Test\nimage: ~/assets/images/test-slug.jpg\n---\nContent"
    )

    config = SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled", editorial_mode="standard"
        ),
        paths=SimpleNamespace(data_dir=tmp_path / "data"),
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
    )

    engine = RefineryEngine(db_manager, git_handler, editor_agent, config)
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 10.0}
    engine.auditor.should_run_fast.return_value = False
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False

    # Configure mock defaults to avoid TypeErrors
    db_manager.get_canonical_slug.return_value = None

    return engine


def test_download_image_integration(mock_refinery_engine, tmp_path):
    # Setup
    target_dir = tmp_path / "target_repo"
    target_dir.mkdir()

    article = {
        "id": "test-123",
        "title": "Test Article",
        "url": "http://x",
        "summary": "sum",
        "source_id": "src",
        "source_name": "src",
        "category": "cat",
        "source_metadata": {},
        "published_date": __import__("datetime").datetime(2024, 1, 1),
        "image_url": "https://example.com/image.jpg",
    }

    # Mock Requests Client
    with patch(
        "news_collector.infrastructure.requests_client.RobustRequestsClient"
    ) as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.__enter__.return_value = mock_instance

        # Mock Response
        mock_response = MagicMock()
        mock_response.content = b"fake-image-data"
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_instance.get.return_value = mock_response

        # Execute
        mock_refinery_engine.process_single_article(article, MagicMock(), target_dir)

        # Verify
        # 1. Check if image file exists
        # Slug logic uses the payload published_date (LAW-B5: deterministic)
        expected_image_path = (
            target_dir / "src/assets/images/2024-01-01-test-article.jpg"
        )
        assert expected_image_path.exists()
        assert expected_image_path.read_bytes() == b"fake-image-data"

        # 2. Check if EditorAgent was called with updated image_url
        mock_refinery_engine.editor.process_article.assert_called_once()
        call_args = mock_refinery_engine.editor.process_article.call_args
        passed_article = call_args[0][0]
        assert (
            passed_article["image_url"] == "~/assets/images/2024-01-01-test-article.jpg"
        )


def test_missing_image_creates_editorial_brief_and_stops_publish(
    mock_refinery_engine, tmp_path
):
    target_dir = tmp_path / "target_repo"
    target_dir.mkdir()

    article = {
        "id": "test-124",
        "title": "Test Article Without Image",
        "url": "https://example.com/no-image",
        "summary": "A valid summary for an article that needs editorial image support.",
        "source_id": "src",
        "source_name": "src",
        "category": "science",
        "source_metadata": {},
        "published_date": datetime(2024, 1, 2),
    }

    result = mock_refinery_engine.process_single_article(
        article, MagicMock(), target_dir
    )

    assert result is False
    mock_refinery_engine.editor.process_article.assert_not_called()

    brief_path = (
        Path(mock_refinery_engine.data_dir)
        / "image-briefs"
        / "2024-01-02-test-article-without-image.json"
    )
    assert brief_path.exists()
    brief_text = brief_path.read_text(encoding="utf-8")
    assert '"status": "needs_editorial_image"' in brief_text
    assert '"reason": "missing_source_image"' in brief_text
    assert "Test Article Without Image" in brief_text


def test_resolved_editorial_brief_materializes_asset_for_publish(
    mock_refinery_engine, tmp_path
):
    target_dir = tmp_path / "target_repo"
    target_dir.mkdir()

    article = {
        "id": "test-125",
        "title": "Test Article Ready For Editorial Image",
        "url": "https://example.com/editorial-image",
        "summary": "A valid summary for an article that should use a staged manual image.",
        "source_id": "src",
        "source_name": "src",
        "category": "science",
        "source_metadata": {},
        "published_date": datetime(2024, 1, 3),
    }

    slug = "2024-01-03-test-article-ready-for-editorial-image"
    brief = mock_refinery_engine.image_briefs.build_brief(
        article=article,
        slug=slug,
        reason="missing_source_image",
    )
    ready_brief = mock_refinery_engine.image_briefs.stage_upload(
        brief=brief,
        filename="editorial.png",
        content=b"manual-image-data",
        draft_alt_text="Imagen editorial del artículo de prueba",
        topic=brief.topic,
        news_angle=brief.news_angle,
        scientific_domain=brief.scientific_domain,
        subject_scene=brief.subject_scene,
    )

    result = mock_refinery_engine.process_single_article(
        article, MagicMock(), target_dir
    )

    assert result is True
    expected_image_path = (
        target_dir
        / "src/assets/images/2024-01-03-test-article-ready-for-editorial-image.png"
    )
    assert expected_image_path.exists()
    assert expected_image_path.read_bytes() == b"manual-image-data"

    call_args = mock_refinery_engine.editor.process_article.call_args
    passed_article = call_args[0][0]
    assert (
        passed_article["image_url"]
        == "~/assets/images/2024-01-03-test-article-ready-for-editorial-image.png"
    )
    assert passed_article["image_alt"] == ready_brief.draft_alt_text
