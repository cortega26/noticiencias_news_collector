"""Workflow helpers for editorial image briefs and staged uploads."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from news_collector.contracts import IMAGE_PROMPT_VERSION, ImageBriefModel
from news_collector.contracts.image_brief import (
    IMAGE_ORIGIN_VALUES,
    ImageGenerationMetadata,
)
from news_collector.utils.slug import slugify

PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "editorial"
    / "prompts"
    / "editorial_image_prompt_v1.md"
)
DEFAULT_TONE = "curiosity, credibility, relevance, scientific wonder, seriousness"

# NC-BE-087 S1 GUARD: slug allowlist. Slugs are produced by derive_slug →
# `{date}-{slugified}` so they may only contain ASCII alphanumerics plus
# `-`/`_` and must not start with a separator (no `.`, `/`, or empty).
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# NC-BE-087 S2: upload/storage-scoped image type allowlist (extensions only;
# genuine-type enforcement comes from _verify_image_magic below).
_ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif"}
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_DIMENSION = 16384


@dataclass(frozen=True)
class _AssetInspection:
    sha256: str
    width: int
    height: int


def _inspect_image(content: bytes, extension: str) -> _AssetInspection:
    """Decode bounded raster bytes rather than trusting a file signature."""
    from PIL import Image, UnidentifiedImageError

    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image upload too large")
    _verify_image_magic(content, extension)
    expected_format = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".gif": "GIF",
        ".webp": "WEBP",
        ".avif": "AVIF",
    }.get(extension)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                if (
                    width * height > MAX_IMAGE_PIXELS
                    or max(width, height) > MAX_IMAGE_DIMENSION
                    or min(width, height) <= 0
                ):
                    raise ValueError("Image dimensions exceed supported limits")
                if image.format != expected_format:
                    raise ValueError("Decoded image type does not match extension")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except (
        OSError,
        UnidentifiedImageError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Invalid or corrupt image upload") from exc
    return _AssetInspection(hashlib.sha256(content).hexdigest(), width, height)


def _atomic_write(path: Path, content: bytes) -> None:
    """Readers see either the previous file or the complete durable replacement."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _validate_slug(slug: str) -> str:
    """Reject traversal-shaped or otherwise unsafe slugs.

    Raises ValueError naming the offending slug; applied at brief_path()
    (the choke point for load/save/list) and before staging uploads.
    """
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(f"Invalid image-brief slug: {slug!r}")
    return slug


def _verify_image_magic(content: bytes, extension: str) -> None:
    """Verify uploaded bytes match the claimed image type by magic signature.

    Local byte check only (stdlib imghdr was removed in Python 3.13 — no new
    dependency). Raises ValueError on mismatch or empty content.
    """
    if not content:
        raise ValueError("Empty image upload")
    if extension == ".png":
        valid = content[:8] == b"\x89PNG\r\n\x1a\n"
    elif extension in (".jpg", ".jpeg"):
        valid = content[:3] == b"\xff\xd8\xff"
    elif extension == ".gif":
        valid = content[:6] in (b"GIF87a", b"GIF89a")
    elif extension == ".webp":
        valid = content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    elif extension == ".avif":
        valid = content[4:8] == b"ftyp" and content[8:12] in (b"avif", b"avis")
    else:  # pragma: no cover - extension allowlist guards this branch
        valid = False
    if not valid:
        raise ValueError(f"Uploaded content does not match {extension} image signature")


def _ensure_min_text(value: str, *, fallback: str, min_length: int) -> str:
    """Guarantee contract-safe text for brief fields fed from sparse article data."""
    candidate = re.sub(r"\s+", " ", (value or "").strip())
    if len(candidate) >= min_length:
        return candidate

    normalized_fallback = re.sub(r"\s+", " ", fallback.strip())
    if len(normalized_fallback) >= min_length:
        return normalized_fallback

    if len(candidate) >= len(normalized_fallback):
        base = candidate or normalized_fallback
    else:
        base = normalized_fallback or candidate

    padded = base.strip() or "editorial reference"
    while len(padded) < min_length:
        padded = f"{padded} {base}".strip()
    return padded[: max(min_length, len(base))].strip()


def slugify_text(value: str, fallback: str) -> str:
    """Deterministically sanitize titles into filesystem-safe slugs."""
    return slugify(value, fallback=fallback)


class ImageBriefStore:
    """Persist and resolve editorial image briefs for the refinery workflow.

    `read_only=True` skips directory creation so request-time validation
    (e.g. the publish pre-dispatch image gate) can look briefs up without
    any filesystem side effect. `load_brief`/`list_briefs` already only read.
    """

    def __init__(self, data_dir: Path, *, read_only: bool = False):
        self.data_dir = Path(data_dir)
        self.briefs_dir = self.data_dir / "image-briefs"
        self.uploads_dir = self.data_dir / "image-uploads"
        if not read_only:
            self.briefs_dir.mkdir(parents=True, exist_ok=True)
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    def brief_path(self, slug: str) -> Path:
        _validate_slug(slug)
        candidate = self.briefs_dir / f"{slug}.json"
        # NC-BE-087 S1 GUARD (defense-in-depth): containment check on the
        # resolved path, mirroring target_repo_writer.py NC-BE-015.
        try:
            candidate.resolve().relative_to(self.briefs_dir.resolve())
        except ValueError as err:
            raise ValueError(
                f"Path traversal detected for image-brief slug: {slug!r}"
            ) from err
        return candidate

    def list_briefs(self) -> list[ImageBriefModel]:
        briefs: list[ImageBriefModel] = []
        for brief_file in sorted(self.briefs_dir.glob("*.json")):
            try:
                brief = self.load_brief(brief_file.stem)
            except ValueError:
                # Stray file whose stem is not a valid slug — skip rather
                # than breaking the whole queue listing.
                continue
            if brief is not None:
                briefs.append(brief)
        briefs.sort(key=lambda item: item.updated_at, reverse=True)
        return briefs

    def load_brief(self, slug: str) -> ImageBriefModel | None:
        path = self.brief_path(slug)
        if not path.exists():
            return None
        return ImageBriefModel.model_validate_json(path.read_text(encoding="utf-8"))

    def find_for_article(
        self, article_id: str, slug_candidates: list[str] | tuple[str, ...]
    ) -> ImageBriefModel | None:
        for slug in slug_candidates:
            if not slug:
                continue
            try:
                brief = self.load_brief(slug)
            except ValueError:
                # Invalid candidate slug can never match a stored brief.
                continue
            if brief is not None and brief.article_id == article_id:
                return brief

        for brief in self.list_briefs():
            if brief.article_id == article_id:
                return brief
        return None

    def ready_for_article(self, article_id: str) -> bool:
        """Read-only reconciler probe: rights, sidecar and actual bytes agree."""
        return self.brief_ready(self.find_for_article(str(article_id), []))

    def brief_ready(self, brief: ImageBriefModel | None) -> bool:
        return self._read_verified_asset(brief) is not None

    def _read_verified_asset(self, brief: ImageBriefModel | None) -> bytes | None:
        if (
            brief is None
            or brief.status not in {"editorial_image_ready", "resolved"}
            or brief.image_origin not in {"original", "licensed", "ai_generated"}
            or not brief.uploaded_asset_path
        ):
            return None
        path = Path(brief.uploaded_asset_path)
        try:
            path.resolve().relative_to(self.uploads_dir.resolve())
            if path.stat().st_size > MAX_IMAGE_BYTES:
                return None
            content = path.read_bytes()
            actual = _inspect_image(content, path.suffix.lower())
        except (OSError, ValueError):
            return None
        if (
            (brief.asset_sha256 and actual.sha256 != brief.asset_sha256)
            or (brief.asset_width and actual.width != brief.asset_width)
            or (brief.asset_height and actual.height != brief.asset_height)
        ):
            return None
        generation = brief.generation_metadata
        if generation and (
            generation.sha256 != actual.sha256
            or generation.width != actual.width
            or generation.height != actual.height
        ):
            return None
        return content

    def derive_slug(
        self,
        *,
        article_id: str,
        canonical_date: str,
        title: str,
        preferred_slug: str | None = None,
    ) -> str:
        if preferred_slug:
            return preferred_slug
        base_slug = slugify_text(title, fallback=f"article-{article_id}")
        return f"{canonical_date}-{base_slug}"

    def build_brief(
        self,
        *,
        article: dict[str, Any],
        slug: str,
        reason: str,
        existing: ImageBriefModel | None = None,
    ) -> ImageBriefModel:
        title = str(article.get("title") or "").strip()
        summary = str(article.get("summary") or "").strip()
        category = str(article.get("category") or "").strip()
        metadata = article.get("article_metadata") or {}
        enrichment = metadata.get("enrichment") if isinstance(metadata, dict) else {}

        topics = enrichment.get("topics") if isinstance(enrichment, dict) else None
        scientific_domain = (
            (existing.scientific_domain if existing else "")
            or category
            or (topics[0] if isinstance(topics, list) and topics else "")
            or "science and technology"
        )
        scientific_domain = _ensure_min_text(
            scientific_domain,
            fallback="science and technology",
            min_length=2,
        )
        subject_scene = (
            existing.subject_scene if existing else ""
        ) or self._derive_subject_scene(
            title=title, summary=summary, domain=scientific_domain
        )
        topic = _ensure_min_text(
            (existing.topic if existing else "") or title,
            fallback=f"Editorial image for {title or slug}",
            min_length=5,
        )
        news_angle = _ensure_min_text(
            (existing.news_angle if existing else "") or summary,
            fallback=f"Editorial context for {title or slug}",
            min_length=10,
        )
        subject_scene = _ensure_min_text(
            subject_scene,
            fallback=f"Editorial scene representing {title or slug} within {scientific_domain}",
            min_length=5,
        )
        draft_alt_text = (
            existing.draft_alt_text if existing else ""
        ) or f"Imagen de {title}"
        draft_alt_text = _ensure_min_text(
            draft_alt_text,
            fallback=f"Imagen de {title or slug}",
            min_length=5,
        )
        tone = _ensure_min_text(
            (existing.tone if existing else "") or DEFAULT_TONE,
            fallback=DEFAULT_TONE,
            min_length=5,
        )

        prompt = self.prompt_template.format(
            topic=topic,
            news_angle=news_angle,
            subject_scene=subject_scene,
            scientific_domain=scientific_domain,
            tone=tone,
        )
        uploaded_asset_path = existing.uploaded_asset_path if existing else None
        image_origin = existing.image_origin if existing else "unknown"
        status: Literal["editorial_image_ready", "needs_editorial_image"] = (
            "editorial_image_ready"
            if self.brief_ready(existing)
            else "needs_editorial_image"
        )

        return ImageBriefModel(
            slug=slug,
            article_id=str(article.get("id", "")).strip() or slug,
            status=status,
            reason=reason,  # type: ignore[arg-type]
            topic=topic,
            news_angle=news_angle,
            scientific_domain=scientific_domain,
            subject_scene=subject_scene,
            tone=tone,
            source_url=str(
                article.get("url") or article.get("source_url") or ""
            ).strip()
            or None,
            draft_alt_text=draft_alt_text,
            prompt_version=IMAGE_PROMPT_VERSION,
            generated_prompt=prompt,
            uploaded_asset_path=uploaded_asset_path,
            image_origin=image_origin,
            generation_metadata=existing.generation_metadata if existing else None,
            asset_sha256=existing.asset_sha256 if existing else None,
            asset_width=existing.asset_width if existing else None,
            asset_height=existing.asset_height if existing else None,
            updated_at=datetime.now(timezone.utc),
        )

    def save_brief(self, brief: ImageBriefModel) -> Path:
        path = self.brief_path(brief.slug)
        _atomic_write(path, brief.model_dump_json(indent=2).encode("utf-8"))
        return path

    def update_brief(self, brief: ImageBriefModel) -> ImageBriefModel:
        """Reassess readiness after an authenticated editor updates brief details."""
        updated = ImageBriefModel.model_validate(brief.model_dump())
        if updated.uploaded_asset_path:
            candidate = updated.model_copy(update={"status": "editorial_image_ready"})
            ready_status = (
                "resolved" if updated.status == "resolved" else "editorial_image_ready"
            )
            updated = updated.model_copy(
                update={
                    "status": (
                        ready_status
                        if self.brief_ready(candidate)
                        else "needs_editorial_image"
                    )
                }
            )
        self.save_brief(updated)
        return updated

    def stage_upload(
        self,
        *,
        brief: ImageBriefModel,
        filename: str,
        content: bytes,
        draft_alt_text: str,
        topic: str,
        news_angle: str,
        scientific_domain: str,
        subject_scene: str,
        image_origin: str | None = None,
        generation_metadata: ImageGenerationMetadata | None = None,
    ) -> ImageBriefModel:
        _validate_slug(brief.slug)
        if image_origin is not None and image_origin not in IMAGE_ORIGIN_VALUES:
            raise ValueError(f"Invalid image origin: {image_origin!r}")
        raw_ext = Path(filename).suffix.lower()
        if raw_ext not in _ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"Disallowed image upload extension: {raw_ext!r}")
        # Normalize .jpeg -> .jpg like the downloaders do.
        safe_ext = ".jpg" if raw_ext == ".jpeg" else raw_ext
        actual = _inspect_image(content, safe_ext)
        if generation_metadata is not None and (
            generation_metadata.sha256 != actual.sha256
            or generation_metadata.width != actual.width
            or generation_metadata.height != actual.height
        ):
            raise ValueError("Generation metadata does not match actual image")
        # Immutable per-content assets ensure a failed sidecar commit or a racing
        # upload never changes bytes already referenced by a ready sidecar.
        staged_path = self.uploads_dir / f"{brief.slug}-{actual.sha256}{safe_ext}"
        # NC-BE-087 S1 GUARD (defense-in-depth): containment check on the
        # resolved staged path, mirroring target_repo_writer.py NC-BE-015.
        try:
            staged_path.resolve().relative_to(self.uploads_dir.resolve())
        except ValueError as err:
            raise ValueError(
                f"Path traversal detected for image-brief slug: {brief.slug!r}"
            ) from err
        origin = image_origin
        if origin is None:
            same_asset = brief.asset_sha256 == actual.sha256
            origin = brief.image_origin if same_asset else "unknown"
        generation = generation_metadata
        if generation is None and brief.asset_sha256 == actual.sha256:
            generation = brief.generation_metadata
        updated = ImageBriefModel.model_validate(
            {
                **brief.model_dump(),
                "status": (
                    "editorial_image_ready"
                    if origin != "unknown"
                    else "needs_editorial_image"
                ),
                "uploaded_asset_path": str(staged_path),
                "draft_alt_text": draft_alt_text.strip(),
                "topic": topic.strip(),
                "news_angle": news_angle.strip(),
                "scientific_domain": scientific_domain.strip(),
                "subject_scene": subject_scene.strip(),
                "image_origin": origin,
                "generation_metadata": generation,
                "asset_sha256": actual.sha256,
                "asset_width": actual.width,
                "asset_height": actual.height,
                "generated_prompt": self.prompt_template.format(
                    topic=topic.strip(),
                    news_angle=news_angle.strip(),
                    subject_scene=subject_scene.strip(),
                    scientific_domain=scientific_domain.strip(),
                    tone=brief.tone,
                ),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        _atomic_write(staged_path, content)
        self.save_brief(updated)
        return updated

    def materialize_uploaded_asset(
        self,
        *,
        brief: ImageBriefModel,
        target_assets_dir: Path,
    ) -> str | None:
        content = self._read_verified_asset(brief)
        if content is None or brief.uploaded_asset_path is None:
            return None

        target_assets_dir.mkdir(parents=True, exist_ok=True)
        extension = Path(brief.uploaded_asset_path).suffix.lower()
        destination = target_assets_dir / f"{brief.slug}{extension}"
        destination.resolve().relative_to(target_assets_dir.resolve())
        _atomic_write(destination, content)
        return f"~/assets/images/{destination.name}"

    @staticmethod
    def _derive_subject_scene(*, title: str, summary: str, domain: str) -> str:
        sentence = summary.split(".")[0].strip()
        sentence = re.sub(r"\s+", " ", sentence)
        if sentence:
            return sentence
        return f"Editorial scene representing {title} within {domain}"
