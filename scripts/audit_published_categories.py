"""Dry-run audit for published frontend categories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news_collector.editorial.category_resolver import EditorialCategoryResolver


def _extract_frontmatter_and_body(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text

    end_idx = text.find("\n---\n", 4)
    if end_idx == -1:
        return {}, text

    frontmatter = yaml.safe_load(text[4:end_idx]) or {}
    body = text[end_idx + 5 :].strip()
    return frontmatter, body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report likely published-category mismatches without editing files."
    )
    parser.add_argument(
        "--posts-dir",
        default="../noticiencias/src/content/posts",
        help="Path to the frontend posts directory.",
    )
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir).resolve()
    resolver = EditorialCategoryResolver()
    mismatches: list[tuple[str, str, str, str]] = []
    scanned = 0

    for post_path in sorted(posts_dir.glob("*.md")):
        frontmatter, body = _extract_frontmatter_and_body(
            post_path.read_text(encoding="utf-8")
        )
        if not isinstance(frontmatter, dict):
            continue

        if not frontmatter.get("refinery_id"):
            continue

        categories = frontmatter.get("categories") or []
        if not isinstance(categories, list) or not categories:
            continue

        current_category = str(categories[0]).strip()
        scanned += 1

        resolution = resolver.resolve_category(
            article_id=str(frontmatter.get("refinery_id")),
            title=str(frontmatter.get("title", "")),
            summary=str(frontmatter.get("excerpt", "")),
            content=body,
            raw_category=current_category,
            metadata_category=None,
        )

        if resolution.public_category != current_category:
            mismatches.append(
                (
                    post_path.name,
                    current_category,
                    resolution.public_category,
                    resolution.resolution_method,
                )
            )

    print(f"Scanned {scanned} refinery-managed posts in {posts_dir}")
    if not mismatches:
        print("No category mismatches detected.")
        return 0

    print(f"Detected {len(mismatches)} likely category mismatches:")
    for filename, current_category, suggested_category, method in mismatches:
        print(
            f"- {filename}: current={current_category} suggested={suggested_category} via {method}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
