"""
Module role: Pure file-I/O helpers for published-post maintenance — hero-image
placeholder allowlist pruning and frontmatter parsing.

Owns:
- prune_hero_placeholder_allowlist_for_post: drop a stale allowlist entry
  once a post no longer uses the default hero placeholder
- remove_hero_placeholder_allowlist_entry + allowlist read/write helpers
- extract_frontmatter_block / parse_frontmatter_text / parse_frontmatter_file
- get_post_image_source

Does NOT own:
- Published-content snapshots, git clones, PR/ Pages health
  (see apps.refinery.published_content — the legacy Streamlit edge, which
  re-exports these helpers until the panel is retired)
- Manifest read/write for the target repo (see target_repo_writer.py)

Relocated verbatim from apps.refinery.published_content (plan 095) so the
workflow layer (target_repo_writer.py) no longer imports the legacy UI
package. No Streamlit/UI-state/DB dependency: safe for workflow use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

HERO_PLACEHOLDER_ALLOWLIST_SUBPATH = Path("data/hero-image-placeholder-allowlist.json")
DEFAULT_HERO_IMAGE = "~/assets/images/default.png"


def extract_frontmatter_block(text: str) -> str | None:
    if not text.startswith("---"):
        return None

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[1:idx])
    return None


def parse_frontmatter_text(text: str) -> dict[str, Any]:
    frontmatter_block = extract_frontmatter_block(text)
    if not frontmatter_block:
        return {}

    parsed = yaml.safe_load(frontmatter_block)
    return parsed if isinstance(parsed, dict) else {}


def parse_frontmatter_file(file_path: Path) -> dict[str, Any]:
    return parse_frontmatter_text(file_path.read_text(encoding="utf-8"))


def get_post_image_source(frontmatter: dict[str, Any]) -> str | None:
    image = frontmatter.get("image")
    if isinstance(image, str):
        value = image.strip()
        return value or None
    if isinstance(image, dict):
        src = image.get("src")
        if isinstance(src, str):
            value = src.strip()
            return value or None
    return None


def hero_placeholder_allowlist_path(repo_root: Path) -> Path:
    return repo_root / HERO_PLACEHOLDER_ALLOWLIST_SUBPATH


def _normalize_allowlist_entries(entries: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for rel_path, reason in sorted(entries.items()):
        if isinstance(reason, str):
            normalized[rel_path] = reason
    return normalized


def _write_placeholder_allowlist(allowlist_path: Path, entries: dict[str, Any]) -> None:
    payload = {"allowedPlaceholders": _normalize_allowlist_entries(entries)}
    allowlist_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def remove_hero_placeholder_allowlist_entry(repo_root: Path, rel_path: str) -> bool:
    allowlist_path = hero_placeholder_allowlist_path(repo_root)
    if not allowlist_path.exists():
        return False

    payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
    entries = payload.get("allowedPlaceholders")
    if not isinstance(entries, dict):
        return False

    if rel_path not in entries:
        return False

    updated_entries = dict(entries)
    del updated_entries[rel_path]
    _write_placeholder_allowlist(allowlist_path, updated_entries)
    return True


def prune_hero_placeholder_allowlist_for_post(repo_root: Path, post_file: Path) -> bool:
    resolved_repo_root = repo_root.resolve()

    try:
        rel_path = post_file.resolve().relative_to(resolved_repo_root).as_posix()
    except ValueError:
        return False

    if not post_file.exists():
        return remove_hero_placeholder_allowlist_entry(resolved_repo_root, rel_path)

    frontmatter = parse_frontmatter_file(post_file)
    image_src = get_post_image_source(frontmatter)
    if image_src == DEFAULT_HERO_IMAGE:
        return False

    return remove_hero_placeholder_allowlist_entry(resolved_repo_root, rel_path)
