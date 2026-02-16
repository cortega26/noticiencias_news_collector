"""Enrichment Strategy Router orchestration logic."""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from news_collector.enrichment.http_enricher import HttpEnricher
from news_collector.enrichment.headless_enricher import HeadlessEnricher
from news_collector.enrichment.scholarly import ScholarlyMetadataEnricher

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

    def route_enrichment(
        self, 
        source_id: str, 
        source_config: Dict[str, Any], 
        candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes enrichment based on source configuration.
        
        Returns:
             dict: {
                 "success": bool,
                 "content": str | None,
                 "error": str | None,
                 "metadata": dict | None,
                 "strategy_used": str,
                 "reason": str | None
             }
        """
        strategy = source_config.get("enrichment_strategy", "http")
        url = candidate.get("url")
        
        if not url:
            return {"success": False, "reason": "missing_url", "strategy_used": "none"}

        # 1. Scholarly Strategy
        if strategy == "scholarly":
            result = self.scholarly.enrich_url(url)
            if result["success"]:
                 return {
                     "success": True,
                     "content": result["content"],
                     "raw_content": None,
                     "metadata": result.get("metadata"),
                     "strategy_used": "scholarly"
                 }
            else:
                 return {
                     "success": False,
                     "reason": result.get("reason", "scholarly_failed"),
                     "strategy_used": "scholarly"
                 }

        # 2. HTTP Strategy
        if strategy == "http":
            return self._execute_http(url)

        # 3. Headless Fallback Strategy
        if strategy == "headless_fallback":
            # First attempt HTTP
            http_result = self._execute_http(url)
            if http_result["success"]:
                return http_result
            
            # If HTTP failed (or content too short), try Headless
            # Only if explicitly enabled and configured
            if not source_config.get("headless_enabled"):
                 self.logger.info(
                     {
                         "event": "enrichment.headless.skipped",
                         "details": {
                             "source_id": source_id,
                             "url": url,
                             "reason": "headless_disabled_config"
                         }
                     }
                 )
                 return {
                     "success": False, 
                     "reason": "headless_disabled_config", 
                     "strategy_used": "headless_fallback"
                 }
            
            self.logger.info(
                {
                    "event": "enrichment.headless.eligible",
                    "details": {
                        "source_id": source_id,
                        "url": url,
                        "http_length": len(http_result.get("content", "") or "")
                    }
                }
            )
            
            # Attempt Headless
            self.logger.info(
                {
                    "event": "enrichment.headless.attempt",  # Renamed from attempted to match requirement
                    "details": {
                        "source_id": source_id,
                        "url": url
                    }
                }
            )

            headless_res = self.headless.enrich(url, source_config)
            
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
                             "duration": headless_res.get("duration")
                         }
                     }
                 )

                 if length >= 500:
                      return {
                          "success": True, 
                          "content": content,
                          "raw_content": headless_res.get("raw_content"),
                          "strategy_used": "headless"
                      }
                 else:
                      self.logger.warning(
                          {
                              "event": "quality.stage_b.rejected_short",
                              "details": {
                                  "source_id": source_id,
                                  "url": url,
                                  "length": length,
                                  "strategy": "headless"
                              }
                          }
                      )
                      return {
                          "success": False, 
                          "reason": "content_too_short_headless", 
                          "strategy_used": "headless"
                      }
            else:
                 # Check if failure was due to budget
                 error_reason = headless_res.get("error", "headless_failed")
                 
                 if error_reason == "headless_budget_exhausted":
                     self.logger.info(
                         {
                             "event": "enrichment.headless.budget_exhausted", # Renamed from skipped to match requirement
                             "details": {
                                 "source_id": source_id,
                                 "url": url,
                                 "reason": "budget_exhausted"
                             }
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
                                 "duration": headless_res.get("duration")
                             }
                         }
                     )
                 
                 return {
                     "success": False, 
                     "reason": error_reason, 
                     "strategy_used": "headless"
                 }

        # 4. Discovery Only
        if strategy == "discovery_only":
             return {
                 "success": False, 
                 "reason": "discovery_only_source", 
                 "strategy_used": "discovery_only"
             }

        # Default / Fallback
        return {
            "success": False, 
            "reason": f"unknown_strategy_{strategy}", 
            "strategy_used": "unknown"
        }

    def _execute_http(self, url: str) -> Dict[str, Any]:
        """Helper to run HTTP enrichment and validate length."""
        res = self.http.enrich(url)
        if res["success"]:
             content = res["content"]
             length = len(content)
             self.logger.info(
                 {
                     "event": "enrichment.http.result",
                     "details": {
                         "url": url,
                         "length": length
                     }
                 }
             )
             if length >= 500:
                  return {
                      "success": True, 
                      "content": content,
                      "raw_content": res.get("raw_content"),
                      "strategy_used": "http"
                  }
             else:
                  return {
                      "success": False, 
                      "reason": "content_too_short_http", 
                      "strategy_used": "http"
                  }
        else:
             return {
                 "success": False, 
                 "reason": res.get("error", "http_failed"), 
                 "strategy_used": "http"
             }
