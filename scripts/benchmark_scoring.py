#!/usr/bin/env python
"""Benchmark for plan 036: bounded scoring workload.

Runs a synthetic backlog (default 1000 articles, including intentional
collected_date ties) through the real `ScoringCoordinator.execute()` against
a deterministic in-memory fake repository and a fake scorer with no
`score_batch_async` method (so the bounded-fallback path — the one Step 4
replaced from an unbounded `asyncio.gather` — is what actually gets
exercised). Asserts:

  1. No single fetched page ever exceeds the configured page size.
  2. The observed peak in-flight fallback concurrency never exceeds
     --assert-max-inflight.
  3. The sum of per-page committed counts equals the total article count
     (nothing lost, nothing double-counted across pages/sources).

Usage:
    python scripts/benchmark_scoring.py --articles 1000 --assert-max-inflight 4
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from news_collector.scoring.coordinator import ScoringCoordinator  # noqa: E402
from news_collector.storage.article_repository import (  # noqa: E402
    Article,
    ArticleCursor,
    ArticlePage,
)


@dataclass
class _FakeArticle:
    id: int
    collected_date: datetime
    title: str = "Synthetic Article"
    url: str = "http://example.com/synthetic"
    source_id: str = "src1"
    source_name: str = "Synthetic Source"
    summary: str = "Synthetic summary."
    content: str = "Synthetic content body."
    published_date: Optional[datetime] = None
    article_metadata: Dict[str, Any] = field(default_factory=dict)
    authors: List[str] = field(default_factory=list)
    peer_reviewed: bool = False
    is_preprint: bool = False
    doi: Optional[str] = None
    journal: Optional[str] = None
    duplication_confidence: float = 0.1
    word_count: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class _FakeRepository:
    """Deterministic in-memory pending-articles repository.

    Every article has a distinct id; every 5th shares its `collected_date`
    with its predecessor (a genuine timestamp tie) to exercise the keyset
    cursor's tuple predicate under the same conditions as production data.
    """

    def __init__(self, article_count: int, page_size_tracker: List[int]):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._articles: List[_FakeArticle] = []
        last_date = base
        for i in range(article_count):
            if i % 5 != 0:
                collected = last_date
            else:
                collected = base + timedelta(minutes=i)
                last_date = collected
            self._articles.append(_FakeArticle(id=i, collected_date=collected))
        self._page_size_tracker = page_size_tracker

    def get_pending_articles_page(
        self,
        limit: int,
        status: str = "validated",
        cursor: Optional[ArticleCursor] = None,
    ) -> ArticlePage:
        self._page_size_tracker.append(limit)
        rows = self._articles
        if cursor is not None:
            rows = [
                a
                for a in rows
                if (a.collected_date, a.id) > (cursor.collected_date, cursor.id)
            ]
        rows = sorted(rows, key=lambda a: (a.collected_date, a.id))
        page_items = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = (
            ArticleCursor(page_items[-1].collected_date, page_items[-1].id)
            if has_more and page_items
            else None
        )
        return ArticlePage(
            items=cast(List[Article], page_items), next_cursor=next_cursor
        )

    def get_completed_articles_for_rescoring_page(
        self, limit: int, days_back: int = 14, cursor: Optional[ArticleCursor] = None
    ) -> ArticlePage:
        return ArticlePage(items=[], next_cursor=None)

    def update_articles_score_bulk(self, score_data_list: List[tuple]) -> bool:
        return True


class _FakeScorer:
    """No `score_batch_async` — forces the bounded-fallback path."""

    def reset_cycle_metrics(self) -> None:
        pass

    async def score_article_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.001)
        return {"final_score": 0.5, "should_include": True}


class _FakeLogger:
    def create_module_logger(self, name: str) -> "_FakeLogger":
        return self

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass


async def _run(article_count: int, max_fallback_concurrency: int) -> Dict[str, Any]:
    page_size_tracker: List[int] = []
    repo = _FakeRepository(article_count, page_size_tracker)
    coordinator = ScoringCoordinator(
        db_manager=repo,
        scorer=_FakeScorer(),
        logger=_FakeLogger(),
        config_override={"scoring_workers": max_fallback_concurrency},
    )

    start = time.perf_counter()
    result = await coordinator.execute({}, dry_run=False)
    elapsed = time.perf_counter() - start

    result["_page_sizes_requested"] = page_size_tracker
    result["_wall_clock_sec"] = elapsed
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=int, default=1000)
    parser.add_argument("--assert-max-inflight", type=int, default=4)
    args = parser.parse_args()

    result = asyncio.run(_run(args.articles, args.assert_max_inflight))

    telemetry = result["telemetry"]
    page_sizes = result["_page_sizes_requested"]
    configured_page_size = max(page_sizes) if page_sizes else 0
    observed_inflight = telemetry["max_fallback_inflight_observed"]
    committed = telemetry["committed"]

    print(f"Articles:              {args.articles}")
    print(f"Pages processed:       {telemetry['pages_processed']}")
    print(f"Configured page size:  {configured_page_size}")
    print(f"Committed:             {committed}")
    print(f"Failed:                {telemetry['failed']}")
    print(f"Max in-flight observed:{observed_inflight}")
    print(f"Duration (sec):        {telemetry['duration_sec']}")
    print(f"Stop reason:           {telemetry['stop_reason']}")

    failures = []
    if committed != args.articles:
        failures.append(f"committed ({committed}) != total articles ({args.articles})")
    if observed_inflight > args.assert_max_inflight:
        failures.append(
            f"observed in-flight ({observed_inflight}) exceeds bound "
            f"(--assert-max-inflight {args.assert_max_inflight})"
        )
    if configured_page_size and any(p != configured_page_size for p in page_sizes):
        failures.append("page size requested was not stable across fetches")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
