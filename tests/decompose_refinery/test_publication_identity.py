"""
tests/decompose_refinery/test_publication_identity.py

Verifies PublicationIdentityResolver and PublicationIdentity (spec §3.1, §6.3 IDENT-01..08).

Import path after implementation:
    from news_collector.logic.workflows.publication_identity import (
        PublicationIdentity,
        PublicationIdentityResolver,
    )
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.publication_identity import (
    PublicationIdentity,
    PublicationIdentityResolver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_stub():
    """Minimal stand-in for TargetRepoWriter that supports find_existing_file."""
    m = MagicMock()
    m.find_existing_file.return_value = None
    return m


def _make_resolver(db=None, manifest=None) -> PublicationIdentityResolver:
    if db is None:
        db = MagicMock()
        db.get_canonical_slug.return_value = None
        db.set_canonical_slug.return_value = True
    manifest = manifest or _make_manifest_stub()
    return PublicationIdentityResolver(db=db, manifest=manifest)


# ---------------------------------------------------------------------------
# IDENT-01: DB canonical slug present → locked identity returned, no FS scan
# ---------------------------------------------------------------------------


class TestIdentityFromDB:
    def test_ident_01_db_slug_used(self, tmp_path):
        """IDENT-01: DB slug present → is_new=False, slug from DB, no manifest scan."""
        db = MagicMock()
        db.get_canonical_slug.return_value = "2024-01-25-my-article"
        manifest = _make_manifest_stub()

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)
        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        identity = resolver.resolve(
            article_id="99",
            article={"published_date": datetime(2026, 1, 1)},
            posts_dir=posts_dir,
        )

        assert identity.final_slug == "2024-01-25-my-article"
        assert identity.canonical_date == "2024-01-25"
        assert identity.output_filename == "2024-01-25-my-article.md"
        assert identity.is_new is False
        # Manifest scan must NOT be called when DB has the slug
        manifest.find_existing_file.assert_not_called()

    def test_ident_01_malformed_db_slug_falls_through(self, tmp_path):
        """IDENT-01 edge: DB slug without date prefix falls through to creation mode."""
        db = MagicMock()
        db.get_canonical_slug.return_value = "no-date-prefix"  # malformed
        manifest = _make_manifest_stub()

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)
        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        identity = resolver.resolve(
            article_id="99",
            article={"published_date": datetime(2024, 3, 15)},
            posts_dir=posts_dir,
        )

        # Should produce a valid identity regardless
        assert re.match(r"^\d{4}-\d{2}-\d{2}-", identity.final_slug)
        assert identity.canonical_date  # non-empty


# ---------------------------------------------------------------------------
# IDENT-02: DB empty, file exists in FS → recovered, manifest self-healed
# ---------------------------------------------------------------------------


class TestIdentityFromFilesystem:
    def test_p2_recovery_dateless_filename_is_deterministic(self, tmp_path):
        """P2 recovery rejects a filename that cannot yield a stable date."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None

        existing_file = tmp_path / "some-article-without-date.md"
        existing_file.write_text("---\n---\nContent")
        manifest = MagicMock()
        manifest.find_existing_file.return_value = existing_file

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)

        with pytest.raises(ValueError, match="no parseable date prefix"):
            resolver.resolve(article_id="77", article={}, posts_dir=tmp_path)

        db.set_canonical_slug.assert_not_called()

    def test_p2_recovery_dated_filename_uses_slug_date(self, tmp_path):
        """P2 recovery keeps deriving canonical dates from valid filenames."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None

        existing_file = tmp_path / "2026-01-15-some-slug.md"
        existing_file.write_text("---\n---\nContent")
        manifest = MagicMock()
        manifest.find_existing_file.return_value = existing_file

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)
        identity = resolver.resolve(article_id="77", article={}, posts_dir=tmp_path)

        assert identity.canonical_date == "2026-01-15"
        assert identity.is_new is False

    def test_ident_02_existing_file_recovered(self, tmp_path):
        """IDENT-02: No DB slug, but file found on FS → is_new=False, manifest self-healed."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)
        existing_file = posts_dir / "2025-06-01-old-slug.md"
        existing_file.write_text('---\nrefinery_id: "77"\n---\nOld content')

        # Manifest stub reports the existing file
        manifest = MagicMock()
        manifest.find_existing_file.return_value = existing_file

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)
        identity = resolver.resolve(
            article_id="77",
            article={},
            posts_dir=posts_dir,
        )

        assert identity.final_slug == "2025-06-01-old-slug"
        assert identity.canonical_date == "2025-06-01"
        assert identity.output_filename == "2025-06-01-old-slug.md"
        assert identity.is_new is False

    def test_ident_02_manifest_self_heal_called(self, tmp_path):
        """IDENT-02: backfill_slug is called when identity comes from FS."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None
        db.set_canonical_slug.return_value = True

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)
        existing_file = posts_dir / "2025-06-01-old-slug.md"
        existing_file.write_text("---\n---\nContent")

        manifest = MagicMock()
        manifest.find_existing_file.return_value = existing_file

        resolver = PublicationIdentityResolver(db=db, manifest=manifest)
        resolver.resolve(article_id="77", article={}, posts_dir=posts_dir)

        # backfill should have been called
        db.set_canonical_slug.assert_called_once_with("77", "2025-06-01-old-slug")


# ---------------------------------------------------------------------------
# IDENT-03: Creation mode — date from published_date
# ---------------------------------------------------------------------------


class TestIdentityCreationMode:
    def test_ident_03_ignores_published_date_uses_today(self, tmp_path):
        """IDENT-03: New article, published_date present → ignores it, uses today."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        manifest = _make_manifest_stub()
        resolver = PublicationIdentityResolver(db=db, manifest=manifest)

        identity = resolver.resolve(
            article_id="1",
            article={"published_date": datetime(2025, 12, 25)},
            posts_dir=posts_dir,
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert identity.canonical_date == today
        assert identity.is_new is True
        assert identity.final_slug.startswith(f"{today}-")

    def test_ident_04_ignores_collected_date_uses_today(self, tmp_path):
        """IDENT-04: No published_date, collected_date present → ignores it, uses today."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None
        manifest = _make_manifest_stub()
        resolver = PublicationIdentityResolver(db=db, manifest=manifest)

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        identity = resolver.resolve(
            article_id="2",
            article={"collected_date": datetime(2025, 11, 10)},
            posts_dir=posts_dir,
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert identity.canonical_date == today
        assert identity.is_new is True
        assert identity.final_slug.startswith(f"{today}-")

    def test_ident_05_date_fallback_to_today(self, tmp_path):
        """IDENT-05: No dates → falls back to today."""
        import re

        db = MagicMock()
        db.get_canonical_slug.return_value = None
        manifest = _make_manifest_stub()
        resolver = PublicationIdentityResolver(db=db, manifest=manifest)

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        identity = resolver.resolve(
            article_id="3",
            article={},
            posts_dir=posts_dir,
        )

        # Date must be valid YYYY-MM-DD
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", identity.canonical_date)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert identity.canonical_date == today

    def test_ident_06_collision_avoidance(self, tmp_path):
        """IDENT-06: When target file already exists, suffix counter is appended."""
        db = MagicMock()
        db.get_canonical_slug.return_value = None
        manifest = _make_manifest_stub()
        resolver = PublicationIdentityResolver(db=db, manifest=manifest)

        posts_dir = tmp_path / "src/content/posts"
        posts_dir.mkdir(parents=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        expected_colliding_name = f"{today}-test-article-title.md"
        # Pre-create the file that would be the first choice
        (posts_dir / expected_colliding_name).write_text("existing")

        identity = resolver.resolve(
            article_id="10",
            article={
                "published_date": datetime(2024, 1, 1),
                "title": "Test Article Title",
            },
            posts_dir=posts_dir,
        )

        # The resolver must NOT use the colliding filename
        assert identity.output_filename != expected_colliding_name
        # But must still start with today's date
        assert identity.final_slug.startswith(f"{today}-")
        # And must not overwrite the existing file
        assert not (posts_dir / expected_colliding_name).read_text().startswith("---")


# ---------------------------------------------------------------------------
# IDENT-07 / IDENT-08: extract_slug — pure function, path traversal + Unicode
# ---------------------------------------------------------------------------


class TestExtractSlug:
    """extract_slug is a pure static method — no I/O required."""

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("slug: ../../../etc/passwd", "etc-passwd"),
            ("slug: ..\\\\..\\\\secret", "secret"),
            ("slug: %2e%2e/forbidden", "2e-2e-forbidden"),
            ("slug: a/../../b", "a-b"),
            ("slug: ¡weird-çhars!", "weird-chars"),
            ("slug: \x00null-byte", "null-byte"),
            ("slug: ---repeated---dashes---", "repeated-dashes"),
        ],
    )
    def test_ident_07_path_traversal_and_sanitization(self, content, expected):
        """IDENT-07: Path traversal and special chars are sanitized."""
        result = PublicationIdentityResolver.extract_slug(content, "fallback")
        assert result == expected

    def test_ident_07_empty_slug_uses_fallback(self):
        """IDENT-07 edge: Slug that reduces to empty → article-{fallback}."""
        result = PublicationIdentityResolver.extract_slug(
            "slug: !@#$%^&*()", "fallback"
        )
        assert result == "article-fallback"

    def test_ident_08_unicode_normalization(self):
        """IDENT-08: Unicode slug is NFKD-normalized and ASCII-encoded."""
        result = PublicationIdentityResolver.extract_slug("slug: café résumé", "x")
        # After NFKD + ASCII encode: 'cafe-resume'
        assert result == "cafe-resume"

    def test_ident_08_title_fallback_when_no_slug_field(self):
        """IDENT-08: If no 'slug:' field, title: is used."""
        result = PublicationIdentityResolver.extract_slug(
            "title: My Great Article", "fallback"
        )
        assert "my-great-article" in result


# ---------------------------------------------------------------------------
# backfill_slug / register_slug
# ---------------------------------------------------------------------------


class TestSlugPersistence:
    def test_backfill_slug_calls_db(self):
        db = MagicMock()
        db.set_canonical_slug.return_value = True
        resolver = _make_resolver(db=db)
        resolver.backfill_slug("77", "2025-06-01-old-slug")
        db.set_canonical_slug.assert_called_once_with("77", "2025-06-01-old-slug")

    def test_register_slug_returns_bool(self):
        db = MagicMock()
        db.set_canonical_slug.return_value = True
        resolver = _make_resolver(db=db)
        result = resolver.register_slug("42", "2025-01-01-new-slug")
        assert result is True

    def test_register_slug_returns_false_when_already_exists(self):
        db = MagicMock()
        db.set_canonical_slug.return_value = False
        resolver = _make_resolver(db=db)
        result = resolver.register_slug("42", "2025-01-01-new-slug")
        assert result is False


# ---------------------------------------------------------------------------
# IDENT-09: finalize_slug — completes creation-mode identity post-AI-edit
# ---------------------------------------------------------------------------


class TestFinalizeSlug:
    def test_ident_09_basic_slug_derived_from_content(self, tmp_path):
        """IDENT-09: finalize_slug sets final_slug and output_filename from content."""
        resolver = _make_resolver()
        identity = PublicationIdentity(
            final_slug=None,
            canonical_date="2025-06-01",
            output_filename=None,
            is_new=True,
        )
        content = "slug: my-great-story\ntitle: My Great Story\nbody text"

        result = resolver.finalize_slug(
            identity=identity,
            refined_content=content,
            article_id="99",
            posts_dir=tmp_path,
        )

        assert result.final_slug == "2025-06-01-my-great-story"
        assert result.output_filename == "2025-06-01-my-great-story.md"
        assert result.is_new is True
        assert result.canonical_date == "2025-06-01"

    def test_ident_09_collision_avoidance(self, tmp_path):
        """IDENT-09: When target file already exists, suffix counter is appended."""
        # Pre-create the would-be output file to trigger collision avoidance.
        (tmp_path / "2025-06-01-my-great-story.md").write_text("existing")

        resolver = _make_resolver()
        identity = PublicationIdentity(
            final_slug=None,
            canonical_date="2025-06-01",
            output_filename=None,
            is_new=True,
        )
        content = "slug: my-great-story\ntitle: My Great Story"

        result = resolver.finalize_slug(
            identity=identity,
            refined_content=content,
            article_id="99",
            posts_dir=tmp_path,
        )

        assert result.final_slug == "2025-06-01-my-great-story-1"
        assert result.output_filename == "2025-06-01-my-great-story-1.md"

    def test_ident_09_extract_slug_fn_override(self, tmp_path):
        """IDENT-09: extract_slug_fn kwarg overrides default static method."""
        resolver = _make_resolver()
        identity = PublicationIdentity(
            final_slug=None,
            canonical_date="2025-03-15",
            output_filename=None,
            is_new=True,
        )

        result = resolver.finalize_slug(
            identity=identity,
            refined_content="irrelevant content",
            article_id="7",
            posts_dir=tmp_path,
            extract_slug_fn=lambda _content, _id: "custom-slug",
        )

        assert result.final_slug == "2025-03-15-custom-slug"
        assert result.output_filename == "2025-03-15-custom-slug.md"

    def test_ident_09_guard_raises_on_non_new_identity(self, tmp_path):
        """IDENT-09: Calling finalize_slug on a locked (is_new=False) identity raises."""
        resolver = _make_resolver()
        locked_identity = PublicationIdentity(
            final_slug="2025-06-01-existing",
            canonical_date="2025-06-01",
            output_filename="2025-06-01-existing.md",
            is_new=False,
        )

        with pytest.raises(AssertionError):
            resolver.finalize_slug(
                identity=locked_identity,
                refined_content="slug: anything",
                article_id="5",
                posts_dir=tmp_path,
            )
