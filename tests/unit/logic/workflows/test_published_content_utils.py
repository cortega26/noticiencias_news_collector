"""Unit tests for news_collector.logic.workflows.published_content_utils.

Backfill for the branches the 90% changed-file coverage gate requires
(plan 106 touched this module's docstring): frontmatter edge cases,
dict-shaped image sources, non-string allowlist reasons, and malformed
or key-missing allowlist payloads.
"""

from __future__ import annotations

import json
from pathlib import Path

from news_collector.logic.workflows.published_content_utils import (
    _normalize_allowlist_entries,
    extract_frontmatter_block,
    get_post_image_source,
    remove_hero_placeholder_allowlist_entry,
)


def test_extract_frontmatter_block_without_closing_fence_returns_none() -> None:
    assert extract_frontmatter_block("---\ntitle: orphan\n") is None


def test_extract_frontmatter_block_with_non_fence_first_line_returns_none() -> None:
    assert extract_frontmatter_block("---foo\ntitle: x\n---\n") is None


def test_get_post_image_source_from_dict_src() -> None:
    assert get_post_image_source({"image": {"src": "  pic.jpg "}}) == "pic.jpg"


def test_get_post_image_source_from_dict_with_non_string_src_returns_none() -> None:
    assert get_post_image_source({"image": {"src": 42}}) is None


def test_normalize_allowlist_entries_drops_non_string_reasons() -> None:
    assert _normalize_allowlist_entries({"a.md": 123, "b.md": "ok"}) == {"b.md": "ok"}


def _write_allowlist(repo_root: Path, payload: object) -> None:
    target = repo_root / "data" / "hero-image-placeholder-allowlist.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def test_remove_entry_with_non_dict_payload_returns_false(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, {"allowedPlaceholders": ["not-a-dict"]})
    assert remove_hero_placeholder_allowlist_entry(tmp_path, "a.md") is False


def test_remove_entry_with_missing_key_returns_false(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, {"allowedPlaceholders": {"other.md": "reason"}})
    assert remove_hero_placeholder_allowlist_entry(tmp_path, "a.md") is False
