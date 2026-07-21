"""ScoringCoordinator — orchestrates the scoring phase of the pipeline.

Extracted from NewsCollectorSystem._execute_scoring to give the scoring
phase its own class with explicit dependencies.

Plan 036: processes bounded pages instead of loading the entire
pending+rescore backlog into memory, and bounds fallback concurrency
instead of scheduling one coroutine per article.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, cast

from news_collector.config import ALL_SOURCES
from news_collector.config.settings import get_runtime_config
from news_collector.storage.article_repository import ArticleCursor, ArticlePage


@dataclass
class _PageResult:
    """Outcome of scoring+persisting one page (plan 036)."""

    persisted: bool
    scored: int = 0
    new: int = 0
    rescored: int = 0
    included: int = 0
    excluded: int = 0
    failed: int = 0
    total_score: float = 0.0


@dataclass
class _CycleState:
    """Shared, mutable accumulators for one scoring cycle's page walk."""

    scoring_stats: Dict[str, Any]
    total_score: float = 0.0
    seen_ids: Set[int] = field(default_factory=set)
    pages_processed: int = 0
    items_fetched: int = 0
    stop_reason: str = "exhausted"
    failed_cursor: Optional[ArticleCursor] = None
    stop_all: bool = False
    failed_count: int = 0


class ScoringCoordinator:
    """Owns the batch/sequential scoring dispatch loop.

    Dependencies (all injected):
        db_manager       – persistence layer (get_pending_articles_page,
                            get_completed_articles_for_rescoring_page,
                            update_articles_score_bulk)
        scorer           – scoring engine (score_batch_async, score_article_async)
        logger           – logging facade (create_module_logger)
        config_override  – optional override dict (scoring_workers, rescore_days_back)
    """

    def __init__(
        self,
        db_manager: Any,
        scorer: Any,
        logger: Any,
        config_override: Dict[str, Any] | None = None,
    ) -> None:
        self.db_manager = db_manager
        self.scorer = scorer
        self.logger = logger
        self.config_override = config_override or {}
        self._inflight = 0
        self._max_inflight_observed = 0
        self._inflight_lock = asyncio.Lock()

    async def execute(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Run the scoring phase, one bounded page at a time."""
        if dry_run:
            return self._simulate_scoring(collection_results)

        cycle_start = time.perf_counter()
        self._max_inflight_observed = 0

        scoring_config = get_runtime_config().scoring_config
        page_size = scoring_config.get("page_size", 200)
        max_fallback_concurrency = self.config_override.get(
            "scoring_workers"
        ) or scoring_config.get("workers", 4)
        cycle_item_budget = scoring_config.get("cycle_item_budget")
        rescore_days = self.config_override.get(
            "rescore_days_back"
        ) or scoring_config.get("rescore_days_back", 14)

        module_logger = self.logger.create_module_logger("scoring")

        if hasattr(self.scorer, "reset_cycle_metrics"):
            self.scorer.reset_cycle_metrics()

        state = _CycleState(
            scoring_stats={
                "articles_scored": 0,
                "articles_included": 0,
                "articles_excluded": 0,
                "average_score": 0.0,
                "new_articles_scored": 0,
                "completed_articles_rescored": 0,
            }
        )

        sources = (
            (
                True,
                lambda cursor: self.db_manager.get_pending_articles_page(
                    limit=page_size, status="validated", cursor=cursor
                ),
            ),
            (
                False,
                lambda cursor: self.db_manager.get_completed_articles_for_rescoring_page(
                    limit=page_size, days_back=rescore_days, cursor=cursor
                ),
            ),
        )

        for is_pending, fetch_page in sources:
            if state.stop_all:
                break
            await self._run_source(
                state,
                is_pending,
                fetch_page,
                cycle_item_budget,
                max_fallback_concurrency,
                module_logger,
            )

        return self._build_result(state, module_logger, time.perf_counter() - cycle_start)

    async def _run_source(
        self,
        state: _CycleState,
        is_pending: bool,
        fetch_page: Any,
        cycle_item_budget: Optional[int],
        max_fallback_concurrency: int,
        module_logger: Any,
    ) -> None:
        """Page through one source until exhausted, budget-stopped, or a
        persistence failure — mutating `state` in place."""
        cursor: Optional[ArticleCursor] = None
        while True:
            if (
                cycle_item_budget is not None
                and state.items_fetched >= cycle_item_budget
            ):
                state.stop_reason = "budget_reached"
                state.stop_all = True
                return

            page: ArticlePage = fetch_page(cursor)
            if not page.items:
                return

            state.items_fetched += len(page.items)
            fresh_articles = [a for a in page.items if a.id not in state.seen_ids]
            state.seen_ids.update(a.id for a in fresh_articles)

            if fresh_articles:
                page_result = await self._process_page(
                    fresh_articles, is_pending, max_fallback_concurrency, module_logger
                )
                if not page_result.persisted:
                    state.stop_reason = "persistence_failed"
                    state.failed_cursor = cursor
                    state.stop_all = True
                    return

                self._accumulate(state, page_result)

            state.pages_processed += 1
            cursor = page.next_cursor
            if cursor is None:
                return

    @staticmethod
    def _accumulate(state: _CycleState, page_result: _PageResult) -> None:
        stats = state.scoring_stats
        stats["articles_scored"] += page_result.scored
        stats["new_articles_scored"] += page_result.new
        stats["completed_articles_rescored"] += page_result.rescored
        stats["articles_included"] += page_result.included
        stats["articles_excluded"] += page_result.excluded
        state.total_score += page_result.total_score
        state.failed_count += page_result.failed

    def _build_result(
        self, state: _CycleState, module_logger: Any, duration_sec: float
    ) -> Dict[str, Any]:
        stats = state.scoring_stats
        if stats["articles_scored"] > 0:
            stats["average_score"] = state.total_score / stats["articles_scored"]

        module_logger.info(
            f"Scoring complete. Total: {stats['articles_scored']} articles "
            f"({stats['new_articles_scored']} new, "
            f"{stats['completed_articles_rescored']} rescored) "
            f"across {state.pages_processed} page(s). "
            f"Stop reason: {state.stop_reason}."
        )

        telemetry: Dict[str, Any] = {
            "duration_sec": round(duration_sec, 4),
            "pages_processed": state.pages_processed,
            "max_fallback_inflight_observed": self._max_inflight_observed,
            "committed": stats["articles_scored"],
            "failed": state.failed_count,
            "stop_reason": state.stop_reason,
        }
        if hasattr(self.scorer, "get_cycle_telemetry"):
            telemetry.update(self.scorer.get_cycle_telemetry())

        result: Dict[str, Any] = {
            "success": state.stop_reason != "persistence_failed",
            "statistics": stats,
            "processed_articles": stats["articles_scored"],
            "stop_reason": state.stop_reason,
            "pages_processed": state.pages_processed,
            "telemetry": telemetry,
        }
        if state.failed_cursor is not None:
            result["failed_cursor"] = {
                "collected_date": state.failed_cursor.collected_date,
                "id": state.failed_cursor.id,
            }
        return result

    async def _process_page(
        self,
        articles: List[Any],
        is_pending: bool,
        max_fallback_concurrency: int,
        module_logger: Any,
    ) -> _PageResult:
        """Score and persist one page. Never partially counts a page whose
        bulk persist failed — `persisted=False` means the caller must treat
        the whole page as not committed."""
        payloads = self._adapt_payloads(articles)
        results = await self._score_payloads(
            payloads, max_fallback_concurrency, module_logger
        )

        bulk_score_updates: List[tuple] = []
        new_count = 0
        rescored_count = 0
        included = 0
        excluded = 0
        failed = 0
        total_score = 0.0

        for article, score_result in zip(articles, results, strict=False):
            if isinstance(score_result, Exception):
                module_logger.error(
                    f"Error scoring artículo {article.id}: {score_result}"
                )
                failed += 1
                continue

            bulk_score_updates.append((article.id, score_result))
            total_score += score_result["final_score"]

            if is_pending:
                new_count += 1
            else:
                rescored_count += 1

            if score_result["should_include"]:
                included += 1
            else:
                excluded += 1

        if not bulk_score_updates:
            return _PageResult(persisted=True, failed=failed)

        persisted = self.db_manager.update_articles_score_bulk(bulk_score_updates)
        if not persisted:
            module_logger.error("Failed to perform bulk score updates.")
            return _PageResult(persisted=False)

        return _PageResult(
            persisted=True,
            scored=len(bulk_score_updates),
            new=new_count,
            rescored=rescored_count,
            included=included,
            excluded=excluded,
            failed=failed,
            total_score=total_score,
        )

    def _adapt_payloads(self, articles: List[Any]) -> List[Dict[str, Any]]:
        from news_collector.contracts.adapters import adapt_to_scoring_input

        payloads: List[Dict[str, Any]] = []
        for article in articles:
            source_config = ALL_SOURCES.get(article.source_id)
            scoring_model = adapt_to_scoring_input(article, source_config)
            payloads.append(scoring_model.model_dump())
        return payloads

    async def _score_payloads(
        self,
        payloads: List[Dict[str, Any]],
        max_fallback_concurrency: int,
        module_logger: Any,
    ) -> List[Any]:
        """Score one page's payloads: batch if available, else a
        semaphore-bounded per-article fallback (never unbounded gather).
        """
        if not payloads:
            return []

        use_batch = hasattr(self.scorer, "score_batch_async")

        if use_batch:
            try:
                return cast(
                    List[Any], await self.scorer.score_batch_async(payloads)
                )
            except Exception as batch_error:
                module_logger.error(
                    f"Batch scoring failed ({len(payloads)} items): {batch_error}"
                )

                if not hasattr(self.scorer, "score_article_async"):
                    module_logger.error(
                        "Safe fallback failed: 'score_article_async' "
                        "not found on scorer."
                    )
                    raise

                module_logger.info("Attempting sequential fallback.")

        return await self._bounded_sequential_score(payloads, max_fallback_concurrency)

    async def _bounded_sequential_score(
        self, payloads: List[Dict[str, Any]], max_concurrency: int
    ) -> List[Any]:
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def _score_one(payload: Dict[str, Any]) -> Any:
            async with semaphore:
                async with self._inflight_lock:
                    self._inflight += 1
                    self._max_inflight_observed = max(
                        self._max_inflight_observed, self._inflight
                    )
                try:
                    return await self.scorer.score_article_async(payload)
                finally:
                    async with self._inflight_lock:
                        self._inflight -= 1

        tasks = [_score_one(p) for p in payloads]
        return cast(
            List[Any], await asyncio.gather(*tasks, return_exceptions=True)
        )

    def _simulate_scoring(self, collection_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate scoring for dry-run mode (preserved from original)."""
        articles_found = collection_results.get("collection_summary", {}).get(
            "articles_found", 0
        )

        included = articles_found // 2
        simulated_scoring = {
            "success": True,
            "statistics": {
                "articles_scored": articles_found,
                "articles_included": included,
                "articles_excluded": articles_found - included,
                "average_score": 0.0,
            },
        }

        return simulated_scoring
