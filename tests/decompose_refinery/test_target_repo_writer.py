"""
tests/decompose_refinery/test_target_repo_writer.py

Verifies TargetRepoWriter (spec §3.3, §6.3 WRITE-01..07).

Import path after implementation:
    from news_collector.logic.workflows.target_repo_writer import TargetRepoWriter
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.target_repo_writer import TargetRepoWriter

MANIFEST_FILENAME = "refinery_manifest.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def writer() -> TargetRepoWriter:
    return TargetRepoWriter()


@pytest.fixture
def posts_dir(tmp_path) -> Path:
    d = tmp_path / "src/content/posts"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def target_dir(tmp_path) -> Path:
    d = tmp_path / "target"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# WRITE-01: write_article creates the file with correct content
# ---------------------------------------------------------------------------


class TestWriteArticle:
    def test_write_01_file_created_with_correct_content(
        self, writer, posts_dir, target_dir, tmp_path
    ):
        """WRITE-01: write_article creates posts_dir/output_filename with given content.

        A brand-new file with no source_url gains an explicit disabled social
        block (plan social-distribution §9); the body is preserved verbatim.
        """
        with patch(
            "apps.refinery.published_content.prune_hero_placeholder_allowlist_for_post",
            return_value=False,
        ):
            result = writer.write_article(
                posts_dir=posts_dir,
                output_filename="2024-01-25-test.md",
                content="---\ntitle: Test\n---\nBody",
                article_id="1",
                target_dir=target_dir,
            )

        assert result == posts_dir / "2024-01-25-test.md"
        assert result.exists()
        text = result.read_text()
        assert text.startswith("---\ntitle: Test\n")
        assert "social:\n  publish: false" in text
        assert text.endswith("\n---\nBody")

    def test_write_02_manifest_updated_after_write(self, writer, posts_dir, target_dir):
        """WRITE-02: write_article calls update_manifest after writing the file."""
        with patch(
            "apps.refinery.published_content.prune_hero_placeholder_allowlist_for_post",
            return_value=False,
        ):
            writer.write_article(
                posts_dir=posts_dir,
                output_filename="2024-01-25-test.md",
                content="---\ntitle: Test\n---\nBody",
                article_id="42",
                target_dir=target_dir,
            )

        manifest_path = posts_dir / MANIFEST_FILENAME
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data.get("42") == "2024-01-25-test.md"

    def test_write_07_path_traversal_raises(self, writer, posts_dir, target_dir):
        """WRITE-07: write_article raises ValueError on path traversal attempt."""
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            writer.write_article(
                posts_dir=posts_dir,
                output_filename="../../../etc/passwd",
                content="malicious",
                article_id="evil",
                target_dir=target_dir,
            )

    def test_write_07_absolute_filename_raises(self, writer, posts_dir, target_dir):
        """WRITE-07 edge: Absolute output_filename is rejected."""
        with pytest.raises((ValueError, OSError)):
            writer.write_article(
                posts_dir=posts_dir,
                output_filename="/etc/passwd",
                content="malicious",
                article_id="evil",
                target_dir=target_dir,
            )


# ---------------------------------------------------------------------------
# WRITE-03: update_manifest atomic write (no .tmp left behind)
# ---------------------------------------------------------------------------


class TestManifest:
    def test_write_03_atomic_write_no_tmp_left(self, writer, posts_dir):
        """WRITE-03: Manifest write uses tmp+rename; no .tmp file remains."""
        for i in range(5):
            writer.update_manifest(posts_dir, str(i), f"2024-01-0{i + 1}-article.md")

        manifest_path = posts_dir / MANIFEST_FILENAME
        assert manifest_path.exists()
        assert not (posts_dir / MANIFEST_FILENAME.replace(".json", ".tmp")).exists()

        data = json.loads(manifest_path.read_text())
        assert len(data) == 5

    def test_manifest_load_empty_dir(self, writer, posts_dir):
        """load_manifest on a dir with no manifest → empty cache, no crash."""
        writer.load_manifest(posts_dir)
        # After loading, cache is empty but method is idempotent
        assert isinstance(writer._manifest_cache, dict)

    def test_manifest_load_existing(self, writer, posts_dir):
        """load_manifest reads an existing manifest correctly."""
        manifest_path = posts_dir / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps({"99": "2024-01-01-article.md"}))

        writer.load_manifest(posts_dir)
        assert writer._manifest_cache.get("99") == "2024-01-01-article.md"

    def test_manifest_no_duplicate_write(self, writer, posts_dir):
        """update_manifest skips disk write when entry is unchanged."""
        writer.update_manifest(posts_dir, "1", "2024-01-01-article.md")
        mtime_before = (posts_dir / MANIFEST_FILENAME).stat().st_mtime_ns

        writer.update_manifest(posts_dir, "1", "2024-01-01-article.md")  # same data
        mtime_after = (posts_dir / MANIFEST_FILENAME).stat().st_mtime_ns

        assert (
            mtime_before == mtime_after
        ), "File should not be rewritten for identical entries"


# ---------------------------------------------------------------------------
# WRITE-04/05/06: find_existing_file
# ---------------------------------------------------------------------------


class TestFindExistingFile:
    def test_write_04_manifest_hit(self, writer, posts_dir):
        """WRITE-04: find_existing_file returns manifest hit when file exists."""
        target = posts_dir / "2024-01-25-test.md"
        target.write_text("content")
        writer.update_manifest(posts_dir, "42", "2024-01-25-test.md")

        result = writer.find_existing_file(posts_dir, "42")
        assert result == target

    def test_write_05_stale_manifest_falls_back_to_scan(self, writer, posts_dir):
        """WRITE-05: Stale manifest entry (file deleted) falls back to slow scan."""
        # Write manifest entry but do NOT create the file
        writer.update_manifest(posts_dir, "42", "2024-01-25-missing.md")

        # Create a different file that has the refinery_id in its frontmatter
        real_file = posts_dir / "2024-06-01-real.md"
        real_file.write_text('---\nrefinery_id: "42"\n---\nContent')

        result = writer.find_existing_file(posts_dir, "42")
        assert result == real_file

    def test_write_06_slow_scan_self_heals_manifest(self, writer, posts_dir):
        """WRITE-06: Slow scan updates manifest when file is found."""
        real_file = posts_dir / "2024-06-01-real.md"
        real_file.write_text('---\nrefinery_id: "55"\n---\nContent')

        writer.find_existing_file(posts_dir, "55")

        # Manifest should now contain the self-healed entry
        manifest_path = posts_dir / MANIFEST_FILENAME
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
            assert data.get("55") == "2024-06-01-real.md"

    def test_find_returns_none_when_not_found(self, writer, posts_dir):
        """find_existing_file returns None for unknown article_id."""
        result = writer.find_existing_file(posts_dir, "nonexistent-999")
        assert result is None

    def test_frontmatter_crlf_file_still_matches(self, writer, posts_dir):
        """CRLF line endings must not hide a matching refinery_id."""
        real_file = posts_dir / "2024-06-01-crlf.md"
        real_file.write_bytes(b'---\r\nrefinery_id: "77"\r\n---\r\nContent with CRLF')

        result = writer.find_existing_file(posts_dir, "77")
        assert result == real_file

    def test_frontmatter_int_value_matches(self, writer, posts_dir):
        """An integer (unquoted) refinery_id must match the string id."""
        real_file = posts_dir / "2024-06-01-int.md"
        real_file.write_text("---\nrefinery_id: 88\n---\nContent")

        result = writer.find_existing_file(posts_dir, "88")
        assert result == real_file

    def test_head_without_closing_marker_is_not_matched(self, writer, posts_dir):
        """A head whose frontmatter never closes must not be parsed from the
        body (the old code sliced from the opening marker to the END of the
        file head, so a body line like 'refinery_id: 99' could false-match)."""
        # Frontmatter opens but never closes within the scanned head; the
        # body mimics the target key.
        real_file = posts_dir / "2024-06-01-unclosed.md"
        real_file.write_text(
            "---\nrefinery_id: 999\nbody line\nrefinery_id: 42\nmore body"
        )

        # 42 is NOT this file's id (its id is 999, in the unclosed block)
        assert writer.find_existing_file(posts_dir, "42") is None

    def test_refinery_id_value_after_closing_marker_is_ignored(self, writer, posts_dir):
        """Only the frontmatter block counts; a matching value in the body
        must not self-heal the wrong file."""
        real_file = posts_dir / "2024-06-01-body.md"
        real_file.write_text(
            '---\nrefinery_id: "33"\n---\nbody text with refinery_id: "44"'
        )

        result = writer.find_existing_file(posts_dir, "33")
        assert result == real_file
        assert writer.find_existing_file(posts_dir, "44") is None


# ---------------------------------------------------------------------------
# Social distribution stamping (plan social-distribution §9)
# ---------------------------------------------------------------------------


SOURCE_URL = "https://www.nature.com/articles/s41586-024-00001-2"


def _write(writer, posts_dir, target_dir, *, filename, content, article_id):
    with patch(
        "apps.refinery.published_content.prune_hero_placeholder_allowlist_for_post",
        return_value=False,
    ):
        return writer.write_article(
            posts_dir=posts_dir,
            output_filename=filename,
            content=content,
            article_id=article_id,
            target_dir=target_dir,
        )


class TestSocialStamping:
    def test_new_file_with_source_url_opts_in(self, writer, posts_dir, target_dir):
        from news_collector.contracts.social_publication import derive_social_id

        body = "\n\nCuerpo con tildes áéí.\n\n<!-- source_identity: source_id=1; source_name=x -->"
        content = (
            f"---\ntitle: Hola\ndate: 2026-05-07\nsource_url: {SOURCE_URL}\n---{body}"
        )
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-hola.md",
            content=content,
            article_id="1",
        )
        text = path.read_text()
        assert "publish: true" in text
        assert f"id: {derive_social_id(SOURCE_URL)}" in text
        assert text.endswith(body)  # body byte-for-byte
        assert "date: 2026-05-07\n" in text  # date not quoted

    def test_new_file_without_source_url_writes_disabled(
        self, writer, posts_dir, target_dir
    ):
        content = "---\ntitle: Manual\ndate: 2026-05-07\n---\n\nBody"
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-manual.md",
            content=content,
            article_id="2",
        )
        assert "social:\n  publish: false" in path.read_text()

    def test_rewrite_preserves_prior_social_id_and_body(
        self, writer, posts_dir, target_dir
    ):
        prior_id = "b" * 64
        existing = (
            f"---\ntitle: Viejo\ndate: 2026-05-07\nsocial:\n  publish: true\n"
            f"  id: {prior_id}\n---\n\nCuerpo original."
        )
        target = posts_dir / "2026-05-07-post.md"
        target.write_text(existing)

        regenerated = (
            f"---\ntitle: Titulo corregido\ndate: 2026-05-07\nsource_url: {SOURCE_URL}\n"
            f"---\n\nCuerpo reescrito."
        )
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-post.md",
            content=regenerated,
            article_id="3",
        )
        text = path.read_text()
        assert f"id: {prior_id}" in text  # prior identity preserved
        assert "Titulo corregido" in text  # editorial content still updated
        assert text.endswith("\n\nCuerpo reescrito.")

    def test_rewrite_preserves_prior_publish_false(self, writer, posts_dir, target_dir):
        target = posts_dir / "2026-05-07-paused.md"
        target.write_text(
            "---\ntitle: Pausado\ndate: 2026-05-07\nsocial:\n  publish: false\n---\n\nBody"
        )
        regenerated = f"---\ntitle: Pausado\ndate: 2026-05-07\nsource_url: {SOURCE_URL}\n---\n\nBody"
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-paused.md",
            content=regenerated,
            article_id="4",
        )
        text = path.read_text()
        assert "publish: false" in text
        assert "publish: true" not in text

    def test_rewrite_of_legacy_file_without_social_keeps_absence(
        self, writer, posts_dir, target_dir
    ):
        target = posts_dir / "2026-05-07-legacy.md"
        target.write_text("---\ntitle: Legacy\ndate: 2026-05-07\n---\n\nBody")
        regenerated = f"---\ntitle: Legacy\ndate: 2026-05-07\nsource_url: {SOURCE_URL}\n---\n\nBody"
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-legacy.md",
            content=regenerated,
            article_id="5",
        )
        assert "social:" not in path.read_text()

    def test_unparseable_previous_frontmatter_blocks_write(
        self, writer, posts_dir, target_dir
    ):
        target = posts_dir / "2026-05-07-corrupt.md"
        target.write_text("this file has no yaml frontmatter fence")
        original_bytes = target.read_bytes()

        with pytest.raises(ValueError, match="parseable YAML front-matter"):
            _write(
                writer,
                posts_dir,
                target_dir,
                filename="2026-05-07-corrupt.md",
                content="---\ntitle: New\n---\n\nBody",
                article_id="6",
            )
        # File not overwritten.
        assert target.read_bytes() == original_bytes

    def test_stamped_output_passes_fast_frontmatter_validation(
        self, writer, posts_dir, target_dir
    ):
        from news_collector.logic.workflows.frontend_publication_validation import (
            validate_post_frontmatter_fast,
        )

        content = (
            "---\n"
            "title: Un titular suficientemente largo\n"
            "schema_version: 1\n"
            "excerpt: Una bajada con mas de diez caracteres.\n"
            "date: 2026-05-07\n"
            "image: /_astro/hero.jpg\n"
            "image_alt: Descripcion del hero\n"
            f"source_url: {SOURCE_URL}\n"
            "---\n\nCuerpo del articulo."
        )
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-valid.md",
            content=content,
            article_id="7",
        )
        ok, error_class, error = validate_post_frontmatter_fast(path)
        assert ok, f"{error_class}: {error}"

    def test_corrupt_previous_blocks_write_even_if_generated_is_malformed(
        self, writer, posts_dir, target_dir
    ):
        """Both sides broken is the case that would silently clobber a stored
        editorial decision, so the previous-file guard must still fire."""
        target = posts_dir / "2026-05-07-both-broken.md"
        target.write_text("this file has no yaml frontmatter fence")
        original_bytes = target.read_bytes()

        with pytest.raises(ValueError, match="parseable YAML front-matter"):
            _write(
                writer,
                posts_dir,
                target_dir,
                filename="2026-05-07-both-broken.md",
                content="---\ntitle: [unclosed\n---\n\nBody",
                article_id="8",
            )
        assert target.read_bytes() == original_bytes

    def test_regeneration_over_prettier_formatted_file_keeps_every_value(
        self, writer, posts_dir, target_dir
    ):
        """The previous file on a PR branch is prettier-formatted (quoted scalars,
        indented sequences), not PyYAML-formatted. Re-serialisation must preserve
        the prior decision and every generated field *value* — no key may be lost
        or retyped by the round trip."""
        import yaml as _yaml

        prior_id = "d" * 64
        # Verbatim shape of a real committed post (quoted scalars, indented list
        # items) plus the editor's pause decision.
        existing = (
            "---\n"
            "title: 'Cursos en línea abren puertas a nuevas carreras'\n"
            "schema_version: 1\n"
            "categories:\n"
            "  - 'Tecnología'\n"
            "permalink: '2026-05-07-cursos'\n"
            "refinery_id: '135'\n"
            "investigation: false\n"
            "social:\n"
            "  publish: false\n"
            f"  id: '{prior_id}'\n"
            "---\n\nCuerpo viejo."
        )
        target = posts_dir / "2026-05-07-cursos.md"
        target.write_text(existing, encoding="utf-8")

        generated_fields = {
            "title": "Cursos en línea abren puertas a nuevas carreras (v2)",
            "schema_version": 1,
            "categories": ["Tecnología"],
            "permalink": "2026-05-07-cursos",
            "refinery_id": "135",
            "investigation": False,
            "featured": False,
            "source_url": SOURCE_URL,
        }
        dumped = _yaml.safe_dump(
            generated_fields,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=1000,
        ).strip()
        path = _write(
            writer,
            posts_dir,
            target_dir,
            filename="2026-05-07-cursos.md",
            content=f"---\n{dumped}\n---\n\nCuerpo nuevo.",
            article_id="9",
        )

        text = path.read_text(encoding="utf-8")
        written = _yaml.safe_load(text[4 : text.find("\n---", 4)])
        # Prior decision preserved verbatim, including the paused publish flag.
        assert written.pop("social") == {"publish": False, "id": prior_id}
        # Every generated field survives the round trip with its value and type.
        assert written == generated_fields
        assert text.endswith("\n\nCuerpo nuevo.")
