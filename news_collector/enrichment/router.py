"""
Module role: Decides and executes the appropriate article enrichment strategy (HTTP, Headless, or Scholarly) for a given source.

Inputs:
- Source IDs and source configuration dictionaries (containing locked or hinted strategies, flags).
- Article candidate dictionaries containing the target URL.

Outputs:
- Enrichment result dictionaries containing success status, extracted content, metadata, and reason codes.
- Strategy utilized in the enrichment process.

Side effects:
- Performs external network calls depending on the selected enrichment strategy.
- Emits enrichment attempts, successes, failures, and cost metrics to the observability store.

Invariants:
- Must honor explicit strategy locks mapped in overriding source configurations.
- Must fallback safely (e.g., to headless fallback if HTTP fails and headless is enabled).
- Must always return a standard dictionary with success boolean and strategy used.

Failure modes:
- Missing URLs immediately return failure without network activity.
- Budget exhaustion for headless strategies returns a specific budget failure code.
- Too short content (<500 chars) is rejected as a failure state ("content_too_short").
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from news_collector.enrichment.headless_enricher import HeadlessEnricher
from news_collector.enrichment.http_enricher import HttpEnricher
from news_collector.enrichment.scholarly import ScholarlyMetadataEnricher
from news_collector.enrichment.strategy_lock_manager import strategy_lock_manager
from news_collector.enrichment.strategy_optimizer import strategy_optimizer
from news_collector.infrastructure.run_context import run_context
from news_collector.observability.enrichment_metrics_store import enrichment_metrics

logger = logging.getLogger(__name__)


class EnrichmentStrategyRouter:
    """
    Decides and executes the appropriate enrichment strategy for a given source and article.
    """

    def __init__(self, logger_factory=None):
        self.logger_factory = logger_factory
        self.logger = (
            logger_factory.create_module_logger("enrichment.router")
            if logger_factory
            else logging.getLogger(__name__)
        )

        self.scholarly = ScholarlyMetadataEnricher()
        self.http = HttpEnricher()
        # HeadlessEnricher also needs logger
        self.headless = HeadlessEnricher(logger_factory=logger_factory)

    def route_enrichment(  # noqa: C901
        self, source_id: str, source_config: Dict[str, Any], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:

        # Record generic attempt (discovery)
        enrichment_metrics.record_attempt(source_id)

        run_context.get_context()

        # 1. Strategy Locking (Highest Priority after Config)
        # Check against source_config hard overrides?
        # Source config is the "truth" passed in. Mutating it affects this run.
        locked_strategy = None
        if source_id:
            lock_info = strategy_lock_manager.get_lock(source_id)
            if lock_info:
                locked_strategy = lock_info.get("strategy")

        # 2. Adaptive Optimizations (Hinting)
        # Only if NOT locked.
        hint = None
        if not locked_strategy:
            enable_adaptive = (
                os.getenv("ENABLE_ADAPTIVE_OPTIMIZER", "true").lower() == "true"
            )
            if source_id and enable_adaptive:
                hint = strategy_optimizer.get_strategy_hint(source_id)

        # Apply Logic
        original_strategy = source_config.get("enrichment_strategy", "http")
        proposed_strategy = locked_strategy or hint

        if proposed_strategy:
            # Safety Checks
            if proposed_strategy == "headless_fallback":
                if source_config.get("headless_enabled"):
                    if original_strategy != "headless_fallback":
                        source_config["enrichment_strategy"] = "headless_fallback"
                        reason = "lock_applied" if locked_strategy else "hint_applied"
                        self.logger.info(
                            {
                                "event": f"strategy.{'lock' if locked_strategy else 'hint'}.applied",
                                "details": {
                                    "source_id": source_id,
                                    "strategy": "headless_fallback",
                                    "original": original_strategy,
                                },
                            }
                        )
                else:
                    reason = "lock_rejected" if locked_strategy else "hint_rejected"
                    self.logger.warning(
                        {
                            "event": f"strategy.{'lock' if locked_strategy else 'hint'}.rejected",
                            "details": {
                                "source_id": source_id,
                                "strategy": "headless_fallback",
                                "reason": "headless_disabled_config",
                            },
                        }
                    )

            elif proposed_strategy == "scholarly":
                if original_strategy != "scholarly":
                    source_config["enrichment_strategy"] = "scholarly"
                    reason = "lock_applied" if locked_strategy else "hint_applied"
                    self.logger.info(
                        {
                            "event": f"strategy.{'lock' if locked_strategy else 'hint'}.applied",
                            "details": {
                                "source_id": source_id,
                                "strategy": "scholarly",
                                "original": original_strategy,
                            },
                        }
                    )

            elif proposed_strategy == "proxy_auto":
                # Proxy auto logic (logging only as it's handled downstream/config)
                self.logger.info(
                    {
                        "event": f"strategy.{'lock' if locked_strategy else 'hint'}.suggestion",
                        "details": {"source_id": source_id, "strategy": "proxy_auto"},
                    }
                )

            elif (
                proposed_strategy == "http"
                and original_strategy != "http"
                and original_strategy != "scholarly"
            ):
                source_config["enrichment_strategy"] = "http"
                reason = "lock_applied" if locked_strategy else "hint_applied"
                self.logger.info(
                    {
                        "event": f"strategy.{'lock' if locked_strategy else 'hint'}.applied",
                        "details": {
                            "source_id": source_id,
                            "strategy": "http",
                            "original": original_strategy,
                        },
                    }
                )

        strategy = source_config.get("enrichment_strategy", "http")
        self.logger.info(
            {
                "event": "enrichment.router.selected",
                "details": {"source_id": source_id, "strategy": strategy},
            }
        )

        url = candidate.get("url")

        if not url:
            enrichment_metrics.record_failure(
                source_id or "unknown", "none", "missing_url"
            )
            return {"success": False, "reason": "missing_url", "strategy_used": "none"}

        # 1. Scholarly Strategy
        if strategy == "scholarly":
            enrichment_metrics.record_attempt(source_id, "scholarly")
            start = time.time()
            result = self.scholarly.enrich_url(url)
            duration = time.time() - start

            if result["success"]:
                enrichment_metrics.record_success(
                    source_id, "scholarly", duration, len(result["content"]), True
                )
                return {
                    "success": True,
                    "content": result["content"],
                    "raw_content": None,
                    "metadata": result.get("metadata"),
                    "strategy_used": "scholarly",
                }
            else:
                reason = result.get("reason", "scholarly_failed")
                enrichment_metrics.record_failure(
                    source_id, "scholarly", reason, duration
                )
                return {
                    "success": False,
                    "reason": reason,
                    "strategy_used": "scholarly",
                }

        # 2. HTTP Strategy
        if strategy == "http":
            enrichment_metrics.record_attempt(source_id, "http")
            return self._execute_http(url, source_id)

        # 3. Headless Fallback Strategy
        if strategy == "headless_fallback":
            # First attempt HTTP
            enrichment_metrics.record_attempt(source_id, "http")
            http_result = self._execute_http(url, source_id)
            print(
                f"DEBUG: Router source={source_id} strategy={strategy} http_success={http_result['success']} len={len(http_result.get('content', '') or '')}",
                flush=True,
            )
            if http_result["success"]:
                return http_result

            # If HTTP failed (or content too short), try Headless
            print(
                f"DEBUG: Router source={source_id} entering headless block. headless_enabled={source_config.get('headless_enabled')}",
                flush=True,
            )
            if not source_config.get("headless_enabled"):
                self.logger.info(
                    {
                        "event": "enrichment.headless.skipped",
                        "details": {
                            "source_id": source_id,
                            "url": url,
                            "reason": "headless_disabled_config",
                        },
                    }
                )
                enrichment_metrics.record_failure(
                    source_id, "headless_fallback", "headless_disabled_config"
                )
                return {
                    "success": False,
                    "reason": "headless_disabled_config",
                    "strategy_used": "headless_fallback",
                }

            # Attempt Headless
            self.logger.info(
                {
                    "event": "enrichment.headless.attempt",
                    "details": {"source_id": source_id, "url": url},
                }
            )
            enrichment_metrics.record_attempt(source_id, "headless")
            headless_res = self.headless.enrich(url, source_config)

            # Record cost (seconds) regardless of success
            duration = headless_res.get("duration", 0.0)
            enrichment_metrics.record_cost(source_id, headless_seconds=duration)

            if headless_res["success"]:
                content = headless_res["content"]
                length = len(content)

                self.logger.info(
                    {
                        "event": "enrichment.headless.success",
                        "details": {
                            "source_id": source_id,
                            "url": url,
                            "length": length,
                            "duration": headless_res.get("duration"),
                        },
                    }
                )

                is_publishable = length >= 500
                enrichment_metrics.record_success(
                    source_id, "headless", duration, length, is_publishable
                )

                if is_publishable:
                    return {
                        "success": True,
                        "content": content,
                        "raw_content": headless_res.get("raw_content"),
                        "strategy_used": "headless",
                    }
                else:
                    self.logger.warning(
                        {
                            "event": "quality.stage_b.rejected_short",
                            "details": {
                                "source_id": source_id,
                                "url": url,
                                "length": length,
                                "strategy": "headless",
                            },
                        }
                    )
                    enrichment_metrics.record_failure(
                        source_id, "headless", "content_too_short_headless", duration
                    )
                    return {
                        "success": False,
                        "reason": "content_too_short_headless",
                        "strategy_used": "headless",
                    }
            else:
                error_reason = headless_res.get("error", "headless_failed")

                if error_reason == "headless_budget_exhausted":
                    self.logger.info(
                        {
                            "event": "enrichment.headless.budget_exhausted",
                            "details": {
                                "source_id": source_id,
                                "url": url,
                                "reason": "budget_exhausted",
                            },
                        }
                    )
                else:
                    self.logger.error(
                        {
                            "event": "enrichment.headless.failed",
                            "details": {
                                "source_id": source_id,
                                "url": url,
                                "reason": error_reason,
                                "duration": headless_res.get("duration"),
                            },
                        }
                    )

                enrichment_metrics.record_failure(
                    source_id,
                    "headless",
                    error_reason,
                    headless_res.get("duration", 0.0),
                )
                return {
                    "success": False,
                    "reason": error_reason,
                    "strategy_used": "headless",
                }

        return {
            "success": False,
            "reason": "unsupported_strategy",
            "strategy_used": "none",
        }

    def _execute_http(self, url: str, source_id: str | None = None) -> Dict[str, Any]:
        """Helper to run HTTP enrichment and validate length."""
        start = time.time()
        res = self.http.enrich(url)
        duration = time.time() - start

        if res["success"]:
            content = res["content"]
            length = len(content)

            self.logger.info(
                {
                    "event": "enrichment.http.result",
                    "details": {"url": url, "length": length},
                }
            )

            is_publishable = length >= 500

            if source_id:
                enrichment_metrics.record_success(
                    source_id, "http", duration, length, is_publishable
                )

            if is_publishable:
                return {
                    "success": True,
                    "content": content,
                    "raw_content": res.get("raw_content"),
                    "strategy_used": "http",
                }
            else:
                if source_id:
                    enrichment_metrics.record_failure(
                        source_id, "http", "content_too_short_http", duration
                    )
                return {
                    "success": False,
                    "reason": "content_too_short_http",
                    "strategy_used": "http",
                }
        else:
            reason = res.get("error", "http_failed")
            if source_id:
                enrichment_metrics.record_failure(source_id, "http", reason, duration)
            return {"success": False, "reason": reason, "strategy_used": "http"}
