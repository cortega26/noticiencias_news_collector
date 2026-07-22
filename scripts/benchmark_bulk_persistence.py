#!/usr/bin/env python
"""Benchmark for plan 037: set-based bulk article persistence.

Runs a deterministic synthetic batch (default 100 articles, including
in-batch exact URL/content duplicates and near-duplicates) through the
real `ArticleRepository.save_articles_bulk()` against a real sqlite
database, counting SELECT statements via `before_cursor_execute`.

Pre-refactor baseline measured 561 SELECTs for a 100-article batch with
no in-batch duplicates (~5-6 per article: one URL-exists query, one
content-hash query, and up to 3 near-dup prefix queries each). Steps 2-4
replace that with a small, roughly batch-size-independent number of
chunked queries.

Usage:
    python scripts/benchmark_bulk_persistence.py --articles 100 --max-selects 10
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from sqlalchemy import event  # noqa: E402

from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.storage.models import Base  # noqa: E402


def _payload(
    url: str, title: str, summary: str, content: str, published_date: datetime
) -> Dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "summary": summary,
        "content": content,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "science",
        "published_date": published_date,
        "word_count": 100,
        "reading_time_minutes": 5,
    }


def _generate_batch(count: int) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    articles = []
    for i in range(count):
        # Every 10th article is a near-duplicate of the previous one
        # (same normalized text basis via a repeated summary keyword),
        # and every 15th shares an exact-duplicate URL with an earlier one
        # — exercising both the exact-dup and near-dup batched paths.
        if count >= 10 and i % 10 == 1:
            title = f"Benchmark Duplicate Cluster Title {i // 10}"
            summary = "Shared near duplicate summary text for clustering test."
        else:
            title = f"Benchmark Article Title Number {i}"
            summary = f"Unique summary body for article number {i}, padded out."

        url = f"https://example.com/bench-{i}"
        if count >= 15 and i % 15 == 1 and i >= 15:
            url = f"https://example.com/bench-{i - 15}"  # exact URL duplicate

        articles.append(
            _payload(
                url,
                title,
                summary,
                content=f"Unique content body for article {i}. " * 20,
                published_date=now,
            )
        )
    return articles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=int, default=100)
    parser.add_argument("--max-selects", type=int, default=10)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = DatabaseManager(
            {"type": "sqlite", "path": Path(tmpdir) / "benchmark_bulk.db"}
        )
        assert manager.engine is not None
        Base.metadata.create_all(manager.engine)
        manager.initialize_sources(
            {
                "src1": {
                    "url": "http://a.com",
                    "name": "Source A",
                    "credibility_score": 1.0,
                    "category": "general",
                }
            }
        )

        select_count = 0

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            nonlocal select_count
            if statement.strip().upper().startswith("SELECT"):
                select_count += 1

        event.listen(manager.engine, "before_cursor_execute", _before_cursor_execute)

        articles = _generate_batch(args.articles)
        start = time.perf_counter()
        saved = manager.save_articles_bulk(articles)
        elapsed = time.perf_counter() - start

        event.remove(manager.engine, "before_cursor_execute", _before_cursor_execute)
        manager.close()

    print(f"Articles submitted:   {args.articles}")
    print(f"Articles saved:       {saved}")
    print(f"SELECT statements:    {select_count}")
    print(f"Duration (sec):       {elapsed:.4f}")

    if select_count > args.max_selects:
        print(
            f"\nFAIL: SELECT count ({select_count}) exceeds bound "
            f"(--max-selects {args.max_selects})"
        )
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
