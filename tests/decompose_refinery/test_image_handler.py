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

import re
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows import image_handler as image_handler_module
from news_collector.logic.workflows.image_handler import (
    ArticleImageHandler,
    ImageResolution,
    publication_safe_image_alt,
)

# Captured at import time, before the session-wide autouse fixture in
# tests/conftest.py temporarily allows example.com for the publication tests.
SHIPPED_REMOTE_IMAGE_ALLOWLIST = image_handler_module.REMOTE_IMAGE_ALLOWLIST

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


@pytest.mark.parametrize("value", [None, "", "Imagen de Un título", "imagen de prueba"])
def test_publication_safe_image_alt_repairs_missing_or_generic_text(value):
    assert publication_safe_image_alt(value, "Un título") == (
        "Ilustración editorial relacionada con Un título"
    )


def test_publication_safe_image_alt_preserves_descriptive_text():
    descriptive = "Un hombre observa el mar desde la playa"
    assert publication_safe_image_alt(descriptive, "Un título") == descriptive


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
        """IMG-05: HTTP URL present + descriptive source alt → download called → resolved=True."""
        image_briefs_stub.find_for_article.return_value = None
        response = _make_mock_http_response(content=b"img", content_type="image/jpeg")

        with _patch_http_client(response):
            article = self._make_article("https://example.com/photo.jpg")
            article["image_alt"] = "Fotografía de un laboratorio con microscopios."
            result = handler.resolve(
                article=article,
                article_id="42",
                canonical_date="2024-01-25",
                preferred_slug=None,
                target_dir=target_dir,
            )

        assert result.resolved is True
        assert result.image_url is not None
        assert result.image_url.startswith("~/assets/images/")
        assert result.image_alt == "Fotografía de un laboratorio con microscopios."
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
        """Missing source alt no longer blocks: the image resolves with the
        placeholder and a missing_alt_text brief is queued for the desk."""
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
        assert result.queued_brief is True
        assert result.image_url is not None
        assert result.image_alt == publication_safe_image_alt(None, "Test Article")
        image_briefs_stub.save_brief.assert_called_once()

    def test_site_logo_image_skips_download_and_queues_brief(
        self, handler, image_briefs_stub, target_dir
    ):
        """A brand-logo image_url is never downloaded or published."""
        image_briefs_stub.find_for_article.return_value = None
        download = MagicMock()

        result = handler.resolve(
            article=self._make_article(
                "https://www.biorxiv.org/sites/default/files/images/biorxiv_logo_homepage7-5-small.png"
            ),
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
            download_fn=download,
        )

        assert result.resolved is False
        assert result.queued_brief is True
        download.assert_not_called()

    def _alt_brief(self, alt="Fotografía real del experimento."):
        brief = MagicMock()
        brief.reason = "missing_alt_text"
        brief.draft_alt_text = alt
        return brief

    def test_img_09_boilerplate_alt_with_usable_alt_brief_resolves(
        self, handler, image_briefs_stub, target_dir
    ):
        """Boilerplate source alt + descriptive alt-brief → downloaded URL with the brief alt."""
        image_briefs_stub.find_for_article.return_value = self._alt_brief()
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
        assert result.image_url.startswith("~/assets/images/")
        assert result.image_alt == "Fotografía real del experimento."
        assert result.queued_brief is False
        image_briefs_stub.save_brief.assert_not_called()

    def test_img_10_boilerplate_alt_without_brief_resolves_and_queues_advisory(
        self, handler, image_briefs_stub, target_dir
    ):
        """Boilerplate source alt + no brief → missing_alt_text brief queued,
        yet the image resolves so publication never fails over alt text."""
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
        assert result.queued_brief is True
        assert result.image_url.startswith("~/assets/images/")
        assert result.image_alt == publication_safe_image_alt(None, "Test Article")
        saved = image_briefs_stub.build_brief.call_args
        assert saved is not None and saved.kwargs.get("reason") == "missing_alt_text"

    def test_img_11_boilerplate_brief_alt_does_not_self_accept(
        self, handler, image_briefs_stub, target_dir
    ):
        """An alt-brief carrying boilerplate text is unusable: keeps the
        fallback alt and queues the advisory, never resolves with it."""
        image_briefs_stub.find_for_article.return_value = self._alt_brief(
            alt="Ilustración editorial relacionada con Algo"
        )
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
        assert result.queued_brief is True
        assert result.image_alt == publication_safe_image_alt(None, "Test Article")


class TestThirdPartyImagePolicy:
    """A source outlet's lead image is not reused unless its host is allowlisted."""

    def _article(self, image_url: str) -> dict:
        return {
            "id": "42",
            "title": "Test Article",
            "url": "https://example.com/article",
            "summary": "Summary",
            "image_url": image_url,
            "published_date": datetime(2024, 1, 25),
        }

    def _resolve(self, handler, target_dir, image_url, download_fn=None):
        return handler.resolve(
            article=self._article(image_url),
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
            download_fn=download_fn,
        )

    def test_shipped_allowlist_is_empty(self):
        """Guard against silently widening the policy: hosts need a licence record."""
        assert SHIPPED_REMOTE_IMAGE_ALLOWLIST == frozenset()

    def test_default_blocks_source_image_and_queues_a_brief(
        self, image_briefs_stub, target_dir
    ):
        strict = ArticleImageHandler(
            image_briefs=image_briefs_stub, remote_image_hosts=frozenset()
        )
        download = MagicMock()

        result = self._resolve(
            strict, target_dir, "https://www.wired.com/photo.jpg", download
        )

        assert result.resolved is False
        assert result.queued_brief is True
        assert result.image_url is None
        assert "licen" in (result.message or "")
        download.assert_not_called()
        saved = image_briefs_stub.build_brief.call_args
        assert saved is not None
        assert saved.kwargs.get("reason") == "third_party_image_blocked"
        image_briefs_stub.save_brief.assert_called_once()

    def test_allowlisted_host_and_its_subdomains_are_downloaded(
        self, image_briefs_stub, target_dir
    ):
        allowing = ArticleImageHandler(
            image_briefs=image_briefs_stub,
            remote_image_hosts=frozenset({"images.nasa.gov"}),
        )
        download = MagicMock(return_value="~/assets/images/nasa.jpg")

        for url in (
            "https://images.nasa.gov/a.jpg",
            "https://IMAGES.nasa.gov/a.jpg",
            "https://cdn.images.nasa.gov/a.jpg",
        ):
            download.reset_mock()
            result = self._resolve(allowing, target_dir, url, download)
            assert result.resolved is True, url
            download.assert_called_once()

    @pytest.mark.parametrize(
        "url",
        [
            "https://evilimages.nasa.gov.example.net/a.jpg",
            "https://notimages.nasa.gov/a.jpg",
            "https://nasa.gov/a.jpg",
            "https://example.com/images.nasa.gov/a.jpg",
        ],
    )
    def test_look_alike_hosts_do_not_match(self, image_briefs_stub, target_dir, url):
        allowing = ArticleImageHandler(
            image_briefs=image_briefs_stub,
            remote_image_hosts=frozenset({"images.nasa.gov"}),
        )
        download = MagicMock()

        result = self._resolve(allowing, target_dir, url, download)

        assert result.resolved is False
        download.assert_not_called()

    def test_staged_editorial_image_still_wins_over_the_block(
        self, image_briefs_stub, target_dir
    ):
        strict = ArticleImageHandler(
            image_briefs=image_briefs_stub, remote_image_hosts=frozenset()
        )
        brief = MagicMock()
        brief.status = "editorial_image_ready"
        brief.draft_alt_text = "Ilustración original del hallazgo"
        image_briefs_stub.find_for_article.return_value = brief

        result = self._resolve(strict, target_dir, "https://www.wired.com/photo.jpg")

        assert result.resolved is True
        assert result.image_url == "~/assets/images/staged.jpg"

    def test_local_image_path_is_not_affected(self, image_briefs_stub, target_dir):
        strict = ArticleImageHandler(
            image_briefs=image_briefs_stub, remote_image_hosts=frozenset()
        )

        result = self._resolve(
            strict, target_dir, "~/assets/images/own-illustration.webp"
        )

        assert result.resolved is True
        assert result.image_url == "~/assets/images/own-illustration.webp"


class TestSlugWriteGuard:
    """Plan 142: the asset writer refuses traversal-shaped slugs.

    The identity resolver's DB branch can return a preferred slug verbatim
    (LAW-B5 keeps that semantics), so the writer owns the allowlist and the
    containment check.
    """

    @pytest.mark.parametrize(
        "bad_slug",
        [
            "../evil",
            "/tmp/evil",
            "a/b",
            "a\\b",
            ".hidden",
            "-leading",
            "",
        ],
    )
    def test_download_rejects_unsafe_slugs_and_writes_nothing(
        self, handler, target_dir, bad_slug
    ):
        response = _make_mock_http_response()

        with _patch_http_client(response):
            result = handler.download(
                url="https://example.com/photo.jpg",
                slug=bad_slug,
                target_dir=target_dir,
            )

        assert result is None
        assets_dir = target_dir / "src/assets/images"
        assert not assets_dir.exists() or not any(assets_dir.iterdir())

    def test_download_containment_check_blocks_when_allowlist_is_bypassed(
        self, handler, target_dir, monkeypatch
    ):
        """Defense-in-depth: even if a slug cleared the regex (simulated
        here), the resolved path must stay inside assets_dir."""
        monkeypatch.setattr(image_handler_module, "_SAFE_SLUG_RE", re.compile(r".*"))
        response = _make_mock_http_response()

        with _patch_http_client(response):
            result = handler.download(
                url="https://example.com/photo.jpg",
                slug="../evil",
                target_dir=target_dir,
            )

        assert result is None
        assets_dir = target_dir / "src/assets/images"
        assert not (target_dir / "src" / "evil.jpg").exists()
        assert not (target_dir / "src" / "assets" / "evil.jpg").exists()
        assert not assets_dir.exists() or not any(assets_dir.iterdir())

    def test_resolve_falls_back_to_title_slug_when_preferred_is_unsafe(
        self, handler, target_dir
    ):
        download = MagicMock(return_value="~/assets/images/safe.jpg")

        result = handler.resolve(
            article={
                "id": "42",
                "title": "Test Article",
                "url": "https://example.com/article",
                "summary": "Summary",
                "image_url": "https://example.com/photo.jpg",
                "published_date": datetime(2024, 1, 25),
            },
            article_id="42",
            canonical_date="2024-01-25",
            preferred_slug="../evil",
            target_dir=target_dir,
            download_fn=download,
        )

        assert result.resolved is True
        used_slug = download.call_args.args[1]
        assert used_slug == "2024-01-25-test-article"
        assert image_handler_module._SAFE_SLUG_RE.match(used_slug)

    def test_resolve_sanitizes_slug_when_title_and_id_are_unusable(
        self, handler, target_dir
    ):
        download = MagicMock(return_value="~/assets/images/safe.jpg")

        result = handler.resolve(
            article={
                "id": "..%2Fevil",
                "title": "",
                "url": "https://example.com/article",
                "summary": "Summary",
                "image_url": "https://example.com/photo.jpg",
                "published_date": datetime(2024, 1, 25),
            },
            article_id="..%2Fevil",
            canonical_date="2024-01-25",
            preferred_slug=None,
            target_dir=target_dir,
            download_fn=download,
        )

        assert result.resolved is True
        used_slug = download.call_args.args[1]
        assert image_handler_module._SAFE_SLUG_RE.match(used_slug)
        assert "/" not in used_slug and ".." not in used_slug
