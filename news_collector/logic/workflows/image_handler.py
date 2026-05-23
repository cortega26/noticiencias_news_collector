"""
Module role: Resolves the image for an article — downloading remote images,
materializing staged editorial briefs, or queueing a new image brief when
no image is available.

Owns:
- download: fetch a remote image URL and save to the local assets directory
- resolve: orchestrate image resolution (staged brief → HTTP download → queue brief)
- ImageResolution: result dataclass

Does NOT own:
- Canonical identity / slug derivation
- File write for article content
- Git operations
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from news_collector.logic.workflows.image_briefs import ImageBriefStore, slugify_text
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("ArticleImageHandler")

CT_TO_EXT: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


@dataclass
class ImageResolution:
    """Result of ArticleImageHandler.resolve()."""

    resolved: bool
    image_url: str | None = None
    image_alt: str | None = None
    queued_brief: bool = False


class ArticleImageHandler:
    """
    Resolves the hero image for an article.

    Instantiate once per RefineryEngine.
    """

    def __init__(self, image_briefs: ImageBriefStore) -> None:
        self._briefs = image_briefs

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve(
        self,
        *,
        article: Dict[str, Any],
        article_id: str,
        canonical_date: str,
        preferred_slug: str | None,
        target_dir: Path,
        download_fn=None,
    ) -> ImageResolution:
        """
        Orchestrate image resolution for one article.

        Priority:
        1. Staged editorial brief (status=editorial_image_ready / resolved)
        2. HTTP URL → download
        3. Local (non-http) image path → pass through unchanged
        4. Missing / placeholder → queue brief

        download_fn: optional callable(url, slug, target_dir) -> str | None
        override for the download step (used so test monkeypatches are respected).

        Returns an ImageResolution describing the outcome.
        """
        image_slug = self._derive_slug(
            article, article_id, canonical_date, preferred_slug
        )

        # 1. Check editorial brief store
        existing_brief = self._briefs.find_for_article(article_id, [image_slug])
        resolved_brief_image = self._resolve_brief_image(existing_brief, target_dir)
        if resolved_brief_image:
            logger.info(
                "Using staged editorial image for article %s from brief %s",
                article_id,
                existing_brief.slug if existing_brief else "unknown",
            )
            return ImageResolution(
                resolved=True,
                image_url=resolved_brief_image,
                image_alt=(
                    existing_brief.draft_alt_text
                    if existing_brief is not None
                    else None
                ),
                queued_brief=False,
            )

        # 2. HTTP URL → attempt download
        raw_image_url = article.get("image_url")
        if not raw_image_url:
            meta = article.get("article_metadata")
            if isinstance(meta, dict):
                raw_image_url = meta.get("image_url")
        if isinstance(raw_image_url, str):
            raw_image_url = raw_image_url.strip()

        if raw_image_url and raw_image_url.startswith("http"):
            _dl = download_fn if download_fn is not None else self.download
            local_ref = _dl(raw_image_url, image_slug, target_dir)
            if local_ref:
                logger.info("Updated article image to local asset: {}", local_ref)
                alt = article.get("image_alt") or (
                    f"Imagen de {article.get('title', article_id)}"
                )
                return ImageResolution(
                    resolved=True,
                    image_url=local_ref,
                    image_alt=alt,
                    queued_brief=False,
                )
            # Download failed → queue brief
            logger.warning(
                "Failed to download image from {}. Routing article {} to editorial image queue.",
                raw_image_url,
                article_id,
            )
            self._queue_brief(
                article, article_id, image_slug, "image_download_failed", existing_brief
            )
            return ImageResolution(resolved=False, queued_brief=True)

        # 3. Local (non-http) path already set — pass through unchanged
        if (
            raw_image_url
            and not raw_image_url.startswith("http")
            and raw_image_url != "~/assets/images/default.png"
        ):
            alt = article.get("image_alt") or (
                f"Imagen de {article.get('title', article_id)}"
            )
            return ImageResolution(
                resolved=True,
                image_url=raw_image_url,
                image_alt=alt,
                queued_brief=False,
            )

        # 4. No image URL or placeholder → queue brief
        reason = (
            "placeholder_image_debt"
            if raw_image_url == "~/assets/images/default.png"
            else "missing_source_image"
        )
        self._queue_brief(article, article_id, image_slug, reason, existing_brief)
        return ImageResolution(resolved=False, queued_brief=True)

    def download(self, url: str, slug: str, target_dir: Path) -> str | None:
        """
        Download a remote image and save it to the local assets directory.

        Extension is resolved from Content-Type header first, with URL
        heuristic as fallback.

        Returns the Astro-compatible local path (e.g. "~/assets/images/slug.jpg")
        or None if download fails or URL is not HTTP(S).
        """
        from news_collector.infrastructure.requests_client import RobustRequestsClient

        url = str(url).strip()
        if not url or not url.startswith("http"):
            return None

        assets_dir = target_dir / "src/assets/images"
        assets_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading image from {}", url)
        try:
            with RobustRequestsClient() as client:
                response = client.get(url, timeout=15)

            ct = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = CT_TO_EXT.get(ct)
            if not ext:
                url_lower = url.lower().split("?")[0]
                for candidate in (
                    ".png",
                    ".webp",
                    ".avif",
                    ".gif",
                    ".svg",
                    ".jpeg",
                    ".jpg",
                ):
                    if url_lower.endswith(candidate):
                        ext = ".jpg" if candidate == ".jpeg" else candidate
                        break
                else:
                    ext = ".jpg"

            filename = f"{slug}{ext}"
            local_path = assets_dir / filename
            local_path.write_bytes(response.content)
            logger.info(
                "Image saved: {} ({} KB, {})",
                local_path,
                len(response.content) // 1024,
                ct,
            )
            return f"~/assets/images/{filename}"
        except Exception as e:
            logger.error("Failed to download image {}: {}", url, e)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _derive_slug(
        self,
        article: Dict[str, Any],
        article_id: str,
        canonical_date: str,
        preferred_slug: str | None,
    ) -> str:
        if preferred_slug:
            return preferred_slug
        title = str(article.get("title") or "").strip()
        base_slug = slugify_text(title, fallback=f"article-{article_id}")
        return f"{canonical_date}-{base_slug}"

    def _resolve_brief_image(self, brief: Any, target_dir: Path) -> str | None:
        if brief is None:
            return None
        if brief.status not in {"editorial_image_ready", "resolved"}:
            return None
        return self._briefs.materialize_uploaded_asset(
            brief=brief,
            target_assets_dir=target_dir / "src" / "assets" / "images",
        )

    def _queue_brief(
        self,
        article: Dict[str, Any],
        article_id: str,
        slug: str,
        reason: str,
        existing_brief: Any,
    ) -> None:
        brief = self._briefs.build_brief(
            article=article,
            slug=slug,
            reason=reason,
            existing=existing_brief,
        )
        brief_path = self._briefs.save_brief(brief)
        logger.info(
            "Queued editorial image brief for article {} at {}", article_id, brief_path
        )
