"""Workflow helpers for editorial image briefs and staged uploads."""

from __future__ import annotations

import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from news_collector.contracts import IMAGE_PROMPT_VERSION, ImageBriefModel

PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "editorial"
    / "prompts"
    / "editorial_image_prompt_v1.md"
)
DEFAULT_TONE = "curiosity, credibility, relevance, scientific wonder, seriousness"


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
    return padded[:max(min_length, len(base))].strip()


def slugify_text(value: str, fallback: str) -> str:
    """Deterministically sanitize titles into filesystem-safe slugs."""
    normalized = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode("utf-8")
    )
    normalized = re.sub(r"[^a-zA-Z0-9\-_]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
    return normalized or fallback


class ImageBriefStore:
    """Persist and resolve editorial image briefs for the refinery workflow."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.briefs_dir = self.data_dir / "image-briefs"
        self.uploads_dir = self.data_dir / "image-uploads"
        self.briefs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    def brief_path(self, slug: str) -> Path:
        return self.briefs_dir / f"{slug}.json"

    def list_briefs(self) -> list[ImageBriefModel]:
        briefs: list[ImageBriefModel] = []
        for brief_file in sorted(self.briefs_dir.glob("*.json")):
            brief = self.load_brief(brief_file.stem)
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
            brief = self.load_brief(slug)
            if brief is not None:
                return brief

        for brief in self.list_briefs():
            if brief.article_id == article_id:
                return brief
        return None

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
            (existing.subject_scene if existing else "")
            or self._derive_subject_scene(title=title, summary=summary, domain=scientific_domain)
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
            (existing.draft_alt_text if existing else "")
            or f"Imagen editorial de {title}"
        )
        draft_alt_text = _ensure_min_text(
            draft_alt_text,
            fallback=f"Imagen editorial de {title or slug}",
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
        status: Literal["editorial_image_ready", "needs_editorial_image"] = (
            "editorial_image_ready"
            if uploaded_asset_path
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
            source_url=str(article.get("url") or article.get("source_url") or "").strip()
            or None,
            draft_alt_text=draft_alt_text,
            prompt_version=IMAGE_PROMPT_VERSION,
            generated_prompt=prompt,
            uploaded_asset_path=uploaded_asset_path,
            updated_at=datetime.now(timezone.utc),
        )

    def save_brief(self, brief: ImageBriefModel) -> Path:
        path = self.brief_path(brief.slug)
        path.write_text(
            brief.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

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
    ) -> ImageBriefModel:
        safe_ext = Path(filename).suffix.lower() or ".png"
        staged_path = self.uploads_dir / f"{brief.slug}{safe_ext}"
        staged_path.write_bytes(content)

        updated = brief.model_copy(
            update={
                "status": "editorial_image_ready",
                "uploaded_asset_path": str(staged_path),
                "draft_alt_text": draft_alt_text.strip(),
                "topic": topic.strip(),
                "news_angle": news_angle.strip(),
                "scientific_domain": scientific_domain.strip(),
                "subject_scene": subject_scene.strip(),
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
        self.save_brief(updated)
        return updated

    def materialize_uploaded_asset(
        self,
        *,
        brief: ImageBriefModel,
        target_assets_dir: Path,
    ) -> str | None:
        if not brief.uploaded_asset_path:
            return None

        source_path = Path(brief.uploaded_asset_path)
        if not source_path.exists():
            return None

        target_assets_dir.mkdir(parents=True, exist_ok=True)
        extension = source_path.suffix.lower() or ".png"
        destination = target_assets_dir / f"{brief.slug}{extension}"
        shutil.copy2(source_path, destination)
        return f"~/assets/images/{destination.name}"

    @staticmethod
    def _derive_subject_scene(*, title: str, summary: str, domain: str) -> str:
        sentence = summary.split(".")[0].strip()
        sentence = re.sub(r"\s+", " ", sentence)
        if sentence:
            return sentence
        return f"Editorial scene representing {title} within {domain}"
