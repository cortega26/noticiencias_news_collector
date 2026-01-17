
from typing import Any, Dict, List, Optional
import asyncio
from news_collector.collectors.base_collector import BaseCollector, create_collector
from news_collector.config.settings import COLLECTION_CONFIG

class CollectorDispatcher:
    """
    Despachador que enruta las solicitudes de recolección al colector adecuado
    según el tipo de fuente (RSS, HTML, etc.).
    """

    def __init__(self, logger_factory=None):
        self.collectors: Dict[str, BaseCollector] = {}
        self.logger_factory = logger_factory
        
        # Initialize collectors dynamically or lazily?
        # For now, initialize known ones.
        # We check async_enabled to decide between RSSCollector and AsyncRSSCollector
        rss_type = "async_rss" if COLLECTION_CONFIG.get("async_enabled", False) else "rss"
        
        try:
            self.collectors["rss"] = create_collector(rss_type)
        except Exception as e:
            print(f"Error initializing RSS collector: {e}")

        try:
            self.collectors["html"] = create_collector("html")
        except Exception as e:
            print(f"Error initializing HTML collector: {e}")

        if self.logger_factory:
            for c in self.collectors.values():
                 if hasattr(c, "set_logger_factory"):
                     c.set_logger_factory(self.logger_factory)

    def set_logger_factory(self, logger_factory):
        self.logger_factory = logger_factory
        for c in self.collectors.values():
             if hasattr(c, "set_logger_factory"):
                 c.set_logger_factory(logger_factory)

    def collect_from_multiple_sources(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous collection dispatch."""
        # Simple implementation: delegate to async version using asyncio.run
        # similar to HtmlCollector, to ensure we use the best path.
        # But if the caller is async (system.py checks), we should provide async method.
        # Here we provide sync wrapper.
        return asyncio.run(
            self.collect_from_multiple_sources_async(
                sources_config, session_id=session_id, trace_id=trace_id
            )
        )

    async def collect_from_multiple_sources_async(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        
        # Group sources by type
        grouped_sources: Dict[str, Dict[str, Any]] = {}
        for source_id, config in sources_config.items():
            ctype = config.get("collector_type", "rss").lower()
            if ctype not in self.collectors:
                # Fallback to RSS if not specified? Or error?
                # Default to rss for backward compatibility
                ctype = "rss"
            
            if ctype not in grouped_sources:
                 grouped_sources[ctype] = {}
            grouped_sources[ctype][source_id] = config

        # Dispatch async
        tasks = []
        for ctype, sources in grouped_sources.items():
            collector = self.collectors.get(ctype)
            if collector:
                 # Check if collector supports async batch
                 if hasattr(collector, "collect_from_multiple_sources_async"):
                     tasks.append(
                         collector.collect_from_multiple_sources_async(
                             sources, session_id=session_id, trace_id=trace_id
                         )
                     )
                 else:
                     # Wrap sync in thread
                     tasks.append(
                        asyncio.to_thread(
                            collector.collect_from_multiple_sources,
                            sources,
                            session_id=session_id,
                            trace_id=trace_id
                        )
                     )
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Merge results
        final_results = {
            "source_details": {},
            "collection_summary": {
                "sources_processed": 0,
                "articles_found": 0,
                "articles_saved": 0,
                "errors_encountered": 0,
            }
        }
        
        for res in results_list:
            if isinstance(res, Exception):
                # Log error
                continue
            if not isinstance(res, dict): continue
            
            # Merge source details
            if "source_details" in res:
                final_results["source_details"].update(res["source_details"])
            
            # Merge summary stats
            if "collection_summary" in res:
                summ = res["collection_summary"]
                final_summary = final_results["collection_summary"]
                final_summary["sources_processed"] += summ.get("sources_processed", 0)
                final_summary["articles_found"] += summ.get("articles_found", 0)
                final_summary["articles_saved"] += summ.get("articles_saved", 0)
                final_summary["errors_encountered"] += summ.get("errors_encountered", 0)

        # Recalculate rates
        s_proc = final_results["collection_summary"]["sources_processed"]
        if s_proc > 0:
            success_count = sum(1 for r in final_results["source_details"].values() if r.get("success"))
            final_results["collection_summary"]["success_rate_percent"] = round((success_count / s_proc) * 100, 2)
        
        return final_results

    def is_healthy(self) -> bool:
        return all(c.is_healthy() for c in self.collectors.values())

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        for name, c in self.collectors.items():
            stats[name] = c.get_stats()
        return stats
