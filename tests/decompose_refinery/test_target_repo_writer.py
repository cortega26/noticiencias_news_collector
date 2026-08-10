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
        """WRITE-01: write_article creates posts_dir/output_filename with given content."""
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
        assert result.read_text() == "---\ntitle: Test\n---\nBody"

    def test_write_02_manifest_updated_after_write(self, writer, posts_dir, target_dir):
        """WRITE-02: write_article calls update_manifest after writing the file."""
        with patch(
            "apps.refinery.published_content.prune_hero_placeholder_allowlist_for_post",
            return_value=False,
        ):
            writer.write_article(
                posts_dir=posts_dir,
                output_filename="2024-01-25-test.md",
                content="---\n---\nBody",
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
