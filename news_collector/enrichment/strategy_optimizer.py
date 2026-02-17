
from typing import Dict, Any, List, Optional
import logging
from news_collector.observability.enrichment_metrics_store import enrichment_metrics

logger = logging.getLogger(__name__)

class StrategyOptimizer:
    """
    Analyzes enrichment metrics to recommend optimal strategies per source.
    """
    
    def __init__(self):
        # Integrity: Optimizer must read from PRODUCTIONDB by default to ensure
        # recommendations are based on real evidence.
        from news_collector.observability.enrichment_metrics_store import enrichment_metrics, production_metrics_view
        from news_collector.infrastructure.run_context import run_context
        
        ctx = run_context.get_context()
        if ctx["environment"] == "test":
             # Allow testing the optimizer logic itself with test data
             self.metrics_store = enrichment_metrics
        else:
             # Force Production Read
             self.metrics_store = production_metrics_view

    def analyze_source(self, source_id: str) -> Dict[str, Any]:
        """
        Computes performance metrics for a source.
        """
        metrics = self.metrics_store.get_metrics(source_id)
        if not metrics:
            return {
                "source_id": source_id,
                "status": "insufficient_data",
                "recommended_strategy": "auto" # Stick to current
            }
            
        total_attempts = metrics.get("total_enrichment_attempted", 0)
        
        # Integrity: Minimum attempts required before recommending changes
        if total_attempts < 5:
             return {
                "source_id": source_id,
                "status": "insufficient_data",
                "reason": f"below_min_attempts_5 (actual: {total_attempts})",
                "recommended_strategy": "auto"
            }

        total_publishable = metrics.get("total_publishable", 0)
        
        if total_attempts == 0:
             return {"source_id": source_id, "status": "no_attempts"}

        yield_rate = (total_publishable / total_attempts) * 100.0
        
        # Strategy specific success rates - Handle NULL (None) from DB
        http_attempts = metrics.get("http_attempts") or 0
        http_success = metrics.get("http_success") or 0
        http_rate = (http_success / http_attempts * 100.0) if http_attempts > 0 else 0.0
        
        headless_attempts = metrics.get("headless_attempts") or 0
        headless_success = metrics.get("headless_success") or 0
        headless_rate = (headless_success / headless_attempts * 100.0) if headless_attempts > 0 else 0.0

        proxy_attempts = metrics.get("proxy_attempts") or 0
        proxy_success = metrics.get("proxy_success") or 0
        proxy_rate = (proxy_success / proxy_attempts * 100.0) if proxy_attempts > 0 else 0.0
        
        # Check for Auto-Lock Opportunities (Phase 36)
        # Criteria: Headless Yield >= 70% AND HTTP Yield <= 10% AND Attempts >= 5
        if total_attempts >= 5:
            if headless_rate >= 70.0 and http_rate <= 10.0:
                 from news_collector.enrichment.strategy_lock_manager import strategy_lock_manager
                 try:
                     strategy_lock_manager.suggest_lock(
                         source_id, 
                         "headless_fallback", 
                         f"Auto-Lock: Headless Yield {headless_rate:.1f}% vs HTTP {http_rate:.1f}% (>5 attempts)"
                     )
                     logger.info(f"🔒 Auto-Lock suggested for {source_id}: headless_fallback")
                 except Exception as e:
                     logger.error(f"Failed to suggest auto-lock for {source_id}: {e}")

        # Recommendations Logic
        recommendation = "http" # Default baseline
        reason = "baseline_efficient"
        
        # 1. If HTTP is working well (> 80% success), stick with it.
        if http_rate > 80.0:
            recommendation = "http"
            reason = f"high_http_yield_{http_rate:.1f}%"
            
        # 2. If HTTP is poor but Headless works well
        elif headless_rate > 50.0 and headless_rate > http_rate:
             recommendation = "headless_fallback"
             reason = f"headless_yield_{headless_rate:.1f}%_better_than_http_{http_rate:.1f}%"
             
        # 3. If Proxy is the only thing working
        elif proxy_rate > 50.0 and proxy_rate > http_rate and proxy_rate > headless_rate:
             recommendation = "proxy_auto" # Suggest enabling proxy mode
             reason = f"proxy_yield_{proxy_rate:.1f}%_highest"
             
        # 4. If nothing works well
        elif yield_rate < 10.0 and total_attempts > 10:
             recommendation = "review_source"
             reason = "very_low_yield"

        return {
            "source_id": source_id,
            "total_attempts": total_attempts,
            "yield_rate": yield_rate,
            "http_rate": http_rate,
            "headless_rate": headless_rate,
            "proxy_rate": proxy_rate,
            "avg_time": metrics.get("avg_enrichment_time", 0.0),
            "recommended_strategy": recommendation,
            "reason": reason
        }

    def generate_report(self) -> str:
        """Generates a markdown report of all sources."""
        all_metrics = self.metrics_store.get_all_metrics()
        report = []
        report.append("# Adaptive Enrichment Optimization Report\n")
        report.append("| Source | Attempts | Yield % | HTTP % | Headless % | Proxy % | Avg Time (s) | Recommendation | Reason |")
        report.append("|---|---|---|---|---|---|---|---|---|")
        
        for source_id in sorted(all_metrics.keys()):
            analysis = self.analyze_source(source_id)
            if "yield_rate" in analysis:
                row = (
                    f"| {source_id} "
                    f"| {analysis['total_attempts']} "
                    f"| {analysis['yield_rate']:.1f}% "
                    f"| {analysis['http_rate']:.1f}% "
                    f"| {analysis['headless_rate']:.1f}% "
                    f"| {analysis['proxy_rate']:.1f}% "
                    f"| {analysis['avg_time']:.2f} "
                    f"| **{analysis['recommended_strategy']}** "
                    f"| {analysis['reason']} |"
                )
                report.append(row)
                
        return "\n".join(report)

    def get_strategy_hint(self, source_id: str) -> Optional[str]:
        """
        Returns a strategy hint if the optimizer is confident.
        """
        analysis = self.analyze_source(source_id)
        recommendation = analysis.get("recommended_strategy")
        
        if recommendation in ["auto", "review_source"]:
            return None
            
        return recommendation

strategy_optimizer = StrategyOptimizer()
