"""Mark published articles in the collector database based on site posts."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from news_collector.storage.database import DatabaseManager

SOURCE_KEYS = ("source_url", "source", "original_url")


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    return cleaned.strip()


def _extract_frontmatter_value(frontmatter: str, key: str) -> Optional[str]:
    match = re.search(rf"^{re.escape(key)}\s*:\s*(.+)$", frontmatter, re.MULTILINE)
    if not match:
        return None
    return _clean_value(match.group(1))


def _extract_source_url(text: str) -> Optional[str]:
    frontmatter, body = _split_frontmatter(text)
    for key in SOURCE_KEYS:
        value = _extract_frontmatter_value(frontmatter, key)
        if value:
            return value

    match = re.search(
        r"Fuente original:\s*(?:\[(https?://[^\]\s]+)\]|(https?://\S+))",
        body,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1) or match.group(2)
    return None


def _extract_permalink(text: str) -> Optional[str]:
    frontmatter, _ = _split_frontmatter(text)
    value = _extract_frontmatter_value(frontmatter, "permalink")
    return value


def _build_published_url(site_url: Optional[str], text: str) -> Optional[str]:
    if not site_url:
        return None
    permalink = _extract_permalink(text)
    if not permalink:
        return None
    return site_url.rstrip("/") + "/" + permalink.lstrip("/")


def _iter_posts(posts_dir: Optional[Path], posts: Iterable[Path]) -> list[Path]:
    result = list(posts)
    if posts_dir:
        result.extend(sorted(posts_dir.rglob("*.md")))
    seen = set()
    unique = []
    for path in result:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark published articles based on site posts."
    )
    parser.add_argument(
        "--posts-dir",
        type=Path,
        help="Directory containing published posts (e.g. noticiencias/_posts).",
    )
    parser.add_argument(
        "--post",
        type=Path,
        action="append",
        default=[],
        help="Individual post file to process.",
    )
    parser.add_argument(
        "--site-url",
        type=str,
        default=None,
        help="Optional site base URL for published_url (e.g. https://noticiencias.com).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without writing to the database.",
    )
    args = parser.parse_args()

    post_paths = _iter_posts(args.posts_dir, args.post)
    if not post_paths:
        raise SystemExit("No posts provided.")

    db_manager = DatabaseManager()
    updated = 0
    skipped = 0

    for path in post_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"⚠️  No se pudo leer {path}: {exc}")
            skipped += 1
            continue

        source_url = _extract_source_url(text)
        if not source_url:
            print(f"⚠️  Sin fuente original en {path}")
            skipped += 1
            continue

        published_url = _build_published_url(args.site_url, text)
        if args.dry_run:
            print(f"DRY RUN: marcar {source_url} como publicado ({path})")
            updated += 1
            continue

        if db_manager.mark_article_published(
            source_url,
            published_url=published_url,
            published_at=datetime.now(timezone.utc),
        ):
            updated += 1
        else:
            skipped += 1

    print(f"✅ Publicaciones actualizadas: {updated}")
    if skipped:
        print(f"⚠️  Publicaciones omitidas: {skipped}")

    if not args.dry_run and post_paths and updated == 0 and skipped > 0:
        print("❌ No se marcó ninguna publicación pese a encontrar posts.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
