"""
tests/decompose_refinery/test_image_handler.py

Verifies ArticleImageHandler and ImageResolution (spec §3.2, §6.3 IMG-01..08).

Import path after implementation:
    from news_collector.logic.workflows.image_handler import (
        ArticleImageHandler,
        ImageResolution,
    )
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.image_handler import (
    ArticleImageHandler,
    ImageResolution,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def image_briefs_stub() -> MagicMock:
    stub = MagicMock()
    stub.find_for_article.return_value = None
    stub.build_brief.return_value = MagicMock(slug="2024-01-25-test", status="queued")
    stub.save_brief.return_value = Path("/tmp/briefs/2024-01-25-test.json")
    stub.materialize_uploaded_asset.return_value = "~/assets/images/staged.jpg"
    return stub


@pytest.fixture
def handler(image_briefs_stub) -> ArticleImageHandler:
    return ArticleImageHandler(image_briefs=image_briefs_stub)


@pytest.fixture
def target_dir(tmp_path) -> Path:
    d = tmp_path / "target_repo"
    d.mkdir()
    return d


def _make_mock_http_response(
    *, content: bytes = b"fake-image", content_type: str = "image/jpeg"
):
    response = MagicMock()
    response.content = content
    response.headers = {"Content-Type": content_type}
    return response


def _patch_http_client(response):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = response

    return patch(
        "news_collector.infrastructure.requests_client.RobustRequestsClient",
        return_value=mock_client,
    )


# ---------------------------------------------------------------------------
# IMG-01: download saves file with Content-Type-derived extension
# ---------------------------------------------------------------------------


class TestDownload:
    def test_img_01_jpeg_content_type(self, handler, target_dir):
        """IMG-01: Content-Type image/jpeg → .jpg file saved."""
        response = _make_mock_http_response(
            content=b"jpegdata", content_type="image/jpeg"
        )
        with _patch_http_client(response):
            result = handler.download(
                url="https://example.com/photo.jpeg",
                slug="2024-01-25-test",
                target_dir=target_dir,
            )

        assert result == "~/assets/images/2024-01-25-test.jpg"
        saved = target_dir / "src/assets/images/2024-01-25-test.jpg"
        assert saved.exists()
        assert saved.read_bytes() == b"jpegdata"

    def test_img_01_png_content_type(self, handler, target_dir):
        """IMG-01: Content-Type image/png → .png file saved."""
        response = _make_mock_http_response(
            content=b"pngdata", content_type="image/png"
        )
        with _patch_http_client(response):
            result = handler.download(
                url="https://example.com/photo.png",
                slug="2024-01-25-png",
                target_dir=target_dir,
            )

        assert result == "~/assets/images/2024-01-25-png.png"

    def test_img_01_avif_content_type(self, handler, target_dir):
        """IMG-01: Content-Type image/avif → .avif file saved."""
        response = _make_mock_http_response(
            content=b"avifdata", content_type="image/avif"
        )
        with _patch_http_client(response):
            result = handler.download(
                url="https://example.com/photo",
                slug="2024-01-25-avif",
                target_dir=target_dir,
            )

        assert result == "~/assets/images/2024-01-25-avif.avif"

    def test_img_02_url_heuristic_fallback(self, handler, target_dir):
        """IMG-02: Unknown Content-Type → URL heuristic (.png suffix in URL)."""
        response = _make_mock_http_response(
            content=b"data", content_type="application/octet-stream"
        )
        with _patch_http_client(response):
            result = handler.download(
                url="https://cdn.example.com/image.png?v=1",
                slug="2024-01-25-heuristic",
                target_dir=target_dir,
            )

        assert result == "~/assets/images/2024-01-25-heuristic.png"

    def test_img_03_http_error_returns_none(self, handler, target_dir):
        """IMG-03: HTTP error → returns None, no crash."""
        with patch(
            "news_collector.infrastructure.requests_client.RobustRequestsClient",
        ) as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.get.side_effect = ConnectionError("network failure")

            result = handler.download(
                url="https://example.com/broken.jpg",
                slug="slug",
                target_dir=target_dir,
            )

        assert result is None

    def test_download_rejects_non_http_url(self, handler, target_dir):
        """download returns None for non-HTTP URLs without making a network call."""
        result = handler.download(
            url="file:///etc/passwd", slug="slug", target_dir=target_dir
        )
        assert result is None


# ---------------------------------------------------------------------------
# IMG-04: resolve with editorial_image_ready brief → resolved=True
# ---------------------------------------------------------------------------


class TestResolve:
    def _make_article(
        self, image_url: str | None = "https://example.com/img.jpg"
    ) -> dict:
        return {
            "id": "42",
            "title": "Test Article",
            "url": "https://example.com/article",
            "summary": "Summary",
            "image_url": image_url,
            "published_date": datetime(2024, 1, 25),
        }

    def test_img_04_brief_ready_returns_resolved(
        self, handler, image_briefs_stub, target_dir
    ):
        """IMG-04: Brief in editorial_image_ready status → resolved=True, asset materialized."""
        brief = MagicMock()
        brief.status = "editorial_image_ready"
        brief.draft_alt_text = "A staged image"
        image_briefs_stub.find_for_article.return_value = brief
        image_briefs_stub.materialize_uploaded_asset.return_value = (
            "~/assets/images/staged.jpg"
        )

        result = handler.resolve(
            article=self._make_article(),
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
        )

        assert result.resolved is True
        assert result.image_url == "~/assets/images/staged.jpg"
        assert result.image_alt == "A staged image"
        assert result.queued_brief is False

    def test_img_05_http_url_downloaded(self, handler, image_briefs_stub, target_dir):
        """IMG-05: HTTP URL present → download called → resolved=True."""
        image_briefs_stub.find_for_article.return_value = None
        response = _make_mock_http_response(content=b"img", content_type="image/jpeg")

        with _patch_http_client(response):
            result = handler.resolve(
                article=self._make_article("https://example.com/photo.jpg"),
                article_id="42",
                canonical_date="2024-01-25",
                preferred_slug=None,
                target_dir=target_dir,
            )

        assert result.resolved is True
        assert result.image_url is not None
        assert result.image_url.startswith("~/assets/images/")
        assert result.queued_brief is False

    def test_img_06_download_failure_queues_brief(
        self, handler, image_briefs_stub, target_dir
    ):
        """IMG-06: Download fails → brief queued, resolved=False."""
        image_briefs_stub.find_for_article.return_value = None

        with patch(
            "news_collector.infrastructure.requests_client.RobustRequestsClient",
        ) as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.get.side_effect = ConnectionError("timeout")

            result = handler.resolve(
                article=self._make_article("https://broken.example.com/img.jpg"),
                article_id="42",
                canonical_date="2024-01-25",
                preferred_slug=None,
                target_dir=target_dir,
            )

        assert result.resolved is False
        assert result.queued_brief is True
        image_briefs_stub.save_brief.assert_called_once()

    def test_img_07_missing_image_url_queues_brief(
        self, handler, image_briefs_stub, target_dir
    ):
        """IMG-07: No image_url → brief queued, resolved=False."""
        image_briefs_stub.find_for_article.return_value = None

        result = handler.resolve(
            article=self._make_article(image_url=None),
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
        )

        assert result.resolved is False
        assert result.queued_brief is True

    def test_img_08_default_placeholder_queues_brief(
        self, handler, image_briefs_stub, target_dir
    ):
        """IMG-08: Placeholder URL → brief queued, resolved=False."""
        image_briefs_stub.find_for_article.return_value = None

        result = handler.resolve(
            article=self._make_article("~/assets/images/default.png"),
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
        )

        assert result.resolved is False
        assert result.queued_brief is True

    def test_img_auto_alt_text_set_when_missing(
        self, handler, image_briefs_stub, target_dir
    ):
        """resolve sets a fallback alt text when image resolved but no alt provided."""
        image_briefs_stub.find_for_article.return_value = None
        response = _make_mock_http_response(content=b"img", content_type="image/jpeg")

        with _patch_http_client(response):
            result = handler.resolve(
                article=self._make_article("https://example.com/photo.jpg"),
                article_id="42",
                canonical_date="2024-01-25",
                preferred_slug=None,
                target_dir=target_dir,
            )

        assert result.resolved is True
        # Alt text must be non-empty when image is resolved
        assert result.image_alt
