#!/usr/bin/env python3
"""Backtest the editorial grounding rules over already-published posts.

Usage:
    python scripts/grounding_backtest.py [--posts DIR] [--db PATH] [--show N] [--json]

Read-only. For every post with a ``refinery_id`` whose source text exists in the
local DB, runs ``check_grounding`` and reports findings per rule and per article.
Use it to calibrate rules before making any of them blocking: a rule is only
worth blocking on if its ``error`` findings are (almost) never false positives.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.editorial.grounding import check_grounding  # noqa: E402

_DEFAULT_POSTS = Path(__file__).resolve().parents[2] / "noticiencias/src/content/posts"
_DEFAULT_DB = Path(__file__).resolve().parents[1] / "data/news_v3.db"
_REFINERY_ID_RE = re.compile(r"^refinery_id:\s*['\"]?(\d+)", re.MULTILINE)


_SOURCE_URL_RE = re.compile(r"^source_url:\s*['\"]?(\S+?)['\"]?\s*$", re.MULTILINE)


def _url_key(url: str) -> str:
    """Scheme/query/trailing-slash-insensitive identity of a URL."""
    return re.sub(r"^https?://(www\.)?", "", url.split("?")[0].split("#")[0]).rstrip(
        "/"
    )


def source_text(conn: sqlite3.Connection, article_id: int, post_url: str = "") -> str:
    """Source of a post, or "" when the row is missing or is a *different*
    article: ``refinery_id`` values from before the DB was rebuilt no longer
    point at the same rows, so the stored URL must match the post's."""
    row = conn.execute(
        "select title, summary, content, url from articles where id = ?",
        (article_id,),
    ).fetchone()
    if row and post_url and _url_key(row[3] or "") != _url_key(post_url):
        return ""
    row = row[:3] if row else None
    title, summary, content = row or (None, None, None)
    parts = [p for p in (title, content) if p]
    if summary and (not content or summary not in content):
        parts.append(summary)  # the summary is redundant when the content has it
    return "\n".join(parts)


def run(posts_dir: Path, db_path: Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    results = []
    for path in sorted(posts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = _REFINERY_ID_RE.search(text)
        if not match:
            continue
        url_match = _SOURCE_URL_RE.search(text)
        source = source_text(
            conn, int(match.group(1)), url_match.group(1) if url_match else ""
        )
        if not source.strip():
            continue
        report = check_grounding(text, source)
        if report.skipped_reason:
            continue
        results.append({"post": path.name, "report": report})
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--posts", type=Path, default=_DEFAULT_POSTS)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--show", type=int, default=0, help="print N findings per kind")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    results = run(args.posts, args.db)
    kinds: Counter[str] = Counter()
    err_articles = 0
    for r in results:
        rep = r["report"]
        kinds.update((f"{f.kind}/{f.severity}" for f in rep.findings))
        err_articles += bool(rep.errors)
    if args.as_json:
        print(
            json.dumps(
                [{"post": r["post"], **r["report"].stage_details(99)} for r in results],
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    print(f"{len(results)} posts with source text; {err_articles} with >=1 error")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind:<28}{n:>4}  ({n / max(len(results), 1):.1f}/post)")
    if args.show:
        shown: Counter[str] = Counter()
        for r in results:
            for f in r["report"].findings:
                key = f"{f.kind}/{f.severity}"
                if shown[key] < args.show:
                    shown[key] += 1
                    print(
                        f"\n[{key}] {r['post']} · {f.field}\n  {f.snippet}\n  → {f.detail}"
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
