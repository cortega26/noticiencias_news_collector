"""
Module role: Resolves canonical publication identity for an article — slug, date, and
filename — before any I/O is performed.

Owns:
- Priority 1: DB canonical slug (immutable identity lock)
- Priority 2: FS scan via TargetRepoWriter manifest (legacy recovery + self-heal)
- Priority 3: Creation mode — derive from published_date / collected_date / datetime.now()
- Collision avoidance (Priority 3 only)
- extract_slug — pure static helper

Does NOT own:
- DB write lifecycle beyond explicit backfill/register calls
- File writes
- Policy decisions
- Image logic
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from news_collector.utils.logger import get_logger
from news_collector.utils.slug import slugify

if TYPE_CHECKING:
    pass

logger = get_logger().create_module_logger("PublicationIdentityResolver")


@dataclass
class PublicationIdentity:
    final_slug: str  # e.g. "2024-01-25-my-article"
    canonical_date: str  # e.g. "2024-01-25"
    output_filename: str  # e.g. "2024-01-25-my-article.md"
    is_new: bool  # True = creation mode; False = recovered from DB or FS


class PublicationIdentityResolver:
    """
    Resolves the canonical publication identity for an article.

    Instantiate once per RefineryEngine and call resolve() for each article.
    The manifest parameter should be a TargetRepoWriter instance (or any object
    with a find_existing_file(posts_dir, article_id) -> Path | None method).
    """

    def __init__(self, db: Any, manifest: Any) -> None:
        self._db = db
        self._manifest = manifest

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve(
        self,
        article_id: str,
        article: Dict[str, Any],
        posts_dir: Path,
    ) -> PublicationIdentity:
        """
        Determine the canonical slug, date, and filename for an article.

        Priority 1: DB canonical slug (immutable identity).
        Priority 2: FS scan via manifest (legacy recovery + self-heal backfill).
        Priority 3: Creation mode — source date, collected date, then now().

        Collision avoidance runs only in Priority 3 (slug is already stable in P1/P2).
        """
        # Priority 1 — DB (only if slug is well-formed with a date prefix)
        db_slug = self._get_db_slug(article_id)
        canonical_date = self._date_from_slug(db_slug) if db_slug else None
        if db_slug and canonical_date:
            logger.info("🔒 Identity: Locked to DB canonical slug: {}", db_slug)
            return PublicationIdentity(
                final_slug=db_slug,
                canonical_date=canonical_date,
                output_filename=f"{db_slug}.md",
                is_new=False,
            )

        # Priority 2 — FS scan
        existing_file = self._manifest.find_existing_file(posts_dir, article_id)
        if existing_file:
            logger.info("♻️ Idempotency: Found existing file {}", existing_file.name)
            fn = existing_file.name
            slug = fn.replace(".md", "")
            canonical_date = self._date_from_slug(slug)
            if canonical_date is None:
                raise ValueError(
                    f"Recovered post file '{fn}' for article {article_id} has no "
                    "parseable date prefix; refusing to invent a non-deterministic date."
                )
            # Self-heal: write slug into DB
            self.backfill_slug(article_id, slug)
            return PublicationIdentity(
                final_slug=slug,
                canonical_date=canonical_date,
                output_filename=fn,
                is_new=False,
            )

        # Priority 3 — Creation mode (also handles malformed DB slug)
        canonical_date = self._derive_date(article)
        logger.info("Processing with intended date: {}", canonical_date)
        # Derive a provisional slug from the article title so resolve() always
        # returns a complete identity.  The engine calls finalize_slug() after
        # AI editing to replace this with the translated-title slug.
        title = article.get("title", "")
        title_content = f"title: {title}" if title else ""
        slug_part = (
            self.extract_slug(title_content, article_id)
            if title_content
            else f"article-{article_id}"
        )

        final_slug = f"{canonical_date}-{slug_part}"
        output_filename = f"{final_slug}.md"

        # Collision avoidance
        target = posts_dir / output_filename
        iteration = 1
        while target.exists():
            final_slug = f"{canonical_date}-{slug_part}-{iteration}"
            output_filename = f"{final_slug}.md"
            target = posts_dir / output_filename
            iteration += 1

        return PublicationIdentity(
            final_slug=final_slug,
            canonical_date=canonical_date,
            output_filename=output_filename,
            is_new=True,
        )

    def finalize_slug(
        self,
        identity: PublicationIdentity,
        refined_content: str,
        article_id: str,
        posts_dir: Path,
        extract_slug_fn=None,
    ) -> PublicationIdentity:
        """
        Complete a creation-mode identity after AI editing.

        Derives the slug from refined_content, applies collision avoidance,
        and returns a new PublicationIdentity with all fields populated.

        extract_slug_fn: optional callable(content, article_id) -> str to override
        the default static extract_slug (used so test monkeypatches are respected).

        Only valid to call when identity.is_new is True.
        """
        assert identity.is_new, "finalize_slug only valid for creation-mode identities"

        canonical_date = identity.canonical_date
        _slug_fn = extract_slug_fn if extract_slug_fn is not None else self.extract_slug
        slug_part = _slug_fn(refined_content, article_id)

        final_slug = f"{canonical_date}-{slug_part}"
        output_filename = f"{final_slug}.md"

        # Collision avoidance
        target_file_path = posts_dir / output_filename
        iteration = 1
        while target_file_path.exists():
            final_slug = f"{canonical_date}-{slug_part}-{iteration}"
            output_filename = f"{final_slug}.md"
            target_file_path = posts_dir / output_filename
            iteration += 1

        return PublicationIdentity(
            final_slug=final_slug,
            canonical_date=canonical_date,
            output_filename=output_filename,
            is_new=True,
        )

    def backfill_slug(self, article_id: str, slug: str) -> None:
        """Write slug to DB (called when identity comes from FS scan)."""
        if hasattr(self._db, "set_canonical_slug"):
            try:
                self._db.set_canonical_slug(article_id, slug)
                logger.info("💾 Backfilled canonical slug to DB: {}", slug)
            except Exception as e:
                logger.error("Failed to backfill canonical slug: {}", e)

    def register_slug(self, article_id: str, slug: str) -> bool:
        """
        Write a new slug to DB (called after policy approval, B-02 / F-0018).
        Returns True if the slug was newly inserted, False if it already existed.
        """
        if not hasattr(self._db, "set_canonical_slug"):
            return False
        try:
            result = self._db.set_canonical_slug(article_id, slug)
            if result:
                logger.info("🔒 Identity Created: {}", slug)
            else:
                logger.info(
                    "🔒 Canonical slug already exists for article {}: {}",
                    article_id,
                    slug,
                )
            return bool(result)
        except Exception as e:
            logger.error("Failed to persist canonical slug: {}", e)
            return False

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_slug(content: str, fallback_id: str) -> str:
        """
        Extract slug from frontmatter 'slug:' or 'title:' field.

        Applies NFKD normalisation, ASCII encode, special-char sanitise, and dedash.
        This is a pure function — no I/O.
        """
        slug = None

        if "slug:" in content:
            match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
            if match:
                slug = match.group(1).strip()

        if not slug and "title:" in content:
            title_match = re.search(r'title:\s*"?([^"\n]+)"?', content)
            if title_match:
                slug = title_match.group(1).strip()

        if not slug:
            slug = f"article-{fallback_id}"

        # NC-BE-015 S0 GUARD: strict sanitise
        slug = slugify(slug, fallback=f"article-{fallback_id}")

        return slug

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_db_slug(self, article_id: str) -> str | None:
        if not hasattr(self._db, "get_canonical_slug"):
            return None
        return self._db.get_canonical_slug(article_id) or None

    @staticmethod
    def _date_from_slug(slug: str) -> str | None:
        match = re.match(r"^(\d{4}-\d{2}-\d{2})-", slug)
        return match.group(1) if match else None

    @staticmethod
    def _derive_date(article: Dict[str, Any]) -> str:
        """Derive canonical date from article payload (Priority 3).

        Always returns the current publication date (the date when we publish the article).
        """
        # Always return the current date in YYYY-MM-DD format
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
