from unittest.mock import MagicMock, patch

import pytest
from news_collector.logic.workflows.refinery_engine import RefineryEngine


@pytest.fixture
def mock_refinery_engine(tmp_path):
    db_manager = MagicMock()
    git_handler = MagicMock()
    editor_agent = MagicMock()
    # Mock process_article simply to return content with frontmatter
    editor_agent.process_article.return_value = (
        "---\ntitle: Test\nimage: ~/assets/images/test-slug.jpg\n---\nContent"
    )

    config = MagicMock()
    config.app.policy_integrity_mode = "disabled"

    engine = RefineryEngine(db_manager, git_handler, editor_agent, config)

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
        "published_date": "2024-01-01",
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
        mock_instance.get.return_value = mock_response

        # Execute
        mock_refinery_engine.process_single_article(article, MagicMock(), target_dir)

        # Verify
        # 1. Check if image file exists
        # Slug logic: Date (2024-01-01) - SafeID (test-123) -> 2024-01-01-test-123.jpg
        expected_image_path = target_dir / "src/assets/images/2024-01-01-test-123.jpg"
        assert expected_image_path.exists()
        assert expected_image_path.read_bytes() == b"fake-image-data"

        # 2. Check if EditorAgent was called with updated image_url
        mock_refinery_engine.editor.process_article.assert_called_once()
        call_args = mock_refinery_engine.editor.process_article.call_args
        passed_article = call_args[0][0]
        assert passed_article["image_url"] == "~/assets/images/2024-01-01-test-123.jpg"
