"""ScoringCoordinator — orchestrates the scoring phase of the pipeline.

Extracted from NewsCollectorSystem._execute_scoring to give the scoring
phase its own class with explicit dependencies.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from news_collector.config import ALL_SOURCES, SCORING_CONFIG


class ScoringCoordinator:
    """Owns the batch/sequential scoring dispatch loop.

    Dependencies (all injected):
        db_manager       – persistence layer (get_pending_articles, update_articles_score_bulk)
        scorer           – scoring engine (score_batch_async, score_article_async)
        logger           – logging facade (create_module_logger)
        config_override  – optional override dict (scoring_workers)
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

    async def execute(  # noqa: C901
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Run the scoring phase — same logic as the extracted method."""
        if dry_run:
            return self._simulate_scoring(collection_results)

        pending_articles = self.db_manager.get_pending_articles(status="validated")
        rescore_days = self.config_override.get(
            "rescore_days_back"
        ) or SCORING_CONFIG.get("rescore_days_back", 14)
        completed_articles = self.db_manager.get_completed_articles_for_rescoring(
            days_back=rescore_days
        )

        self.logger.create_module_logger("scoring").info(
            f"Retrieved {len(pending_articles)} pending articles and {len(completed_articles)} "
            f"completed but unpublished articles for rescoring (lookback: {rescore_days} days)."
        )

        all_articles = []
        all_articles.extend(pending_articles)
        all_articles.extend(completed_articles)

        scoring_stats: Dict[str, Any] = {
            "articles_scored": 0,
            "articles_included": 0,
            "articles_excluded": 0,
            "average_score": 0.0,
            "new_articles_scored": 0,
            "completed_articles_rescored": 0,
        }

        total_score = 0.0

        # Preserve original expression evaluation — result is intentionally unused
        self.config_override.get("scoring_workers") or SCORING_CONFIG.get("workers", 4)

        if hasattr(self.scorer, "reset_cycle_metrics"):
            self.scorer.reset_cycle_metrics()

        from news_collector.contracts.adapters import adapt_to_scoring_input

        payloads: List[Dict[str, Any]] = []
        for article in all_articles:
            source_config = ALL_SOURCES.get(article.source_id)
            scoring_model = adapt_to_scoring_input(article, source_config)
            payloads.append(scoring_model.model_dump())

        results: List[Any] = []
        if payloads:
            use_batch = hasattr(self.scorer, "score_batch_async")

            if use_batch:
                try:
                    results = await self.scorer.score_batch_async(payloads)
                except Exception as batch_error:
                    self.logger.create_module_logger("scoring").error(
                        f"Batch scoring failed ({len(payloads)} items): {batch_error}"
                    )

                    if not hasattr(self.scorer, "score_article_async"):
                        self.logger.create_module_logger("scoring").error(
                            "Safe fallback failed: 'score_article_async' "
                            "not found on scorer."
                        )
                        raise batch_error

                    self.logger.create_module_logger("scoring").info(
                        "Attempting sequential fallback."
                    )
                    use_batch = False
                    results = []

            if not use_batch:
                tasks = [self.scorer.score_article_async(p) for p in payloads]
                results = await asyncio.gather(*tasks, return_exceptions=True)

        if results:
            bulk_score_updates: List[tuple] = []
            new_scored_count = 0
            completed_rescored_count = 0

            pending_ids = {art.id for art in pending_articles}
            completed_ids = {art.id for art in completed_articles}

            for article, score_result in zip(all_articles, results, strict=False):
                if isinstance(score_result, Exception):
                    self.logger.create_module_logger("scoring").error(
                        f"Error scoring artículo {article.id}: " f"{str(score_result)}"
                    )
                    continue

                bulk_score_updates.append((article.id, score_result))

                scoring_stats["articles_scored"] += 1
                total_score += score_result["final_score"]

                if article.id in pending_ids:
                    new_scored_count += 1
                elif article.id in completed_ids:
                    completed_rescored_count += 1

                if score_result["should_include"]:
                    scoring_stats["articles_included"] += 1
                else:
                    scoring_stats["articles_excluded"] += 1

            scoring_stats["new_articles_scored"] = new_scored_count
            scoring_stats["completed_articles_rescored"] = completed_rescored_count

            self.logger.create_module_logger("scoring").info(
                f"Scoring complete. Total: {scoring_stats['articles_scored']} articles "
                f"({new_scored_count} new, {completed_rescored_count} rescored)."
            )

            if bulk_score_updates:
                success = self.db_manager.update_articles_score_bulk(bulk_score_updates)
                if not success:
                    self.logger.create_module_logger("scoring").error(
                        "Failed to perform bulk score updates."
                    )

        if scoring_stats["articles_scored"] > 0:
            scoring_stats["average_score"] = (
                total_score / scoring_stats["articles_scored"]
            )

        return {
            "success": True,
            "statistics": scoring_stats,
            "processed_articles": scoring_stats["articles_scored"],
        }

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
