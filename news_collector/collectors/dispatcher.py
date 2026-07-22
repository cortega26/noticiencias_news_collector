"""
Module role: Routes collection requests to the appropriate collector implementation based on source configurations.

Inputs:
- Dictionaries of source configurations (mapping source IDs to settings).
- Logger factories and health tracking dependencies injected during initialization.

Outputs:
- Aggregated dictionaries containing `source_details` and a `collection_summary` with overall article counts, errors, and success rates.

Side effects:
- Instantiates child collectors (RSS, HTML, Headless).
- Invokes network calls by delegating execution to the underlying collectors.

Invariants:
- Fallbacks gracefully to the 'rss' collector type if an unrecognized collector type is specified.
- Synthesizes and merges batch collection metrics from all underlying collectors into a single summary.

Failure modes:
- Collector initialization errors are caught and logged, omitting the failing collector from the registered mapping.
- Individual collection task failures or exceptions are swallowed at the dispatcher level and excluded from the merged results to allow partial successes.
"""

import asyncio
from typing import Any, Dict, Optional

from news_collector.collectors.base_collector import BaseCollector, create_collector
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class CollectorDispatcher:
    """
    Despachador que enruta las solicitudes de recolección al colector adecuado
    según el tipo de fuente (RSS, HTML, etc.).
    """

    # Every collector_type string create_collector() recognizes (base_collector.py).
    # Used to distinguish "known type whose collector failed to initialize"
    # (must be attributed as collector_unavailable) from "genuinely unknown
    # type string" (kept as a silent fallback to rss — see plan 040's STOP
    # condition). Conflating the two was a real bug found by review: a
    # missing `headless`/`reddit` collector used to reroute to rss instead
    # of being flagged.
    _KNOWN_COLLECTOR_TYPES = frozenset(
        {"rss", "html", "async_rss", "headless", "reddit"}
    )

    def __init__(self, logger_factory=None, health_tracker=None):  # noqa: C901
        self.collectors: Dict[str, BaseCollector] = {}
        self.logger_factory = logger_factory
        self.health_tracker = health_tracker
        logger.debug(
            "Dispatcher init health_tracker={} id={}",
            health_tracker,
            id(health_tracker) if health_tracker else "None",
        )

        # Initialize collectors dynamically or lazily?
        # For now, initialize known ones.
        # We check async_enabled to decide between RSSCollector and AsyncRSSCollector
        rss_type = "rss"

        try:
            self.collectors["rss"] = create_collector(rss_type)
        except Exception as e:
            logger.opt(exception=True).error(
                "Failed to initialize RSS collector: {}", e
            )

        try:
            self.collectors["html"] = create_collector("html")
        except Exception as e:
            logger.opt(exception=True).error(
                "Failed to initialize HTML collector: {}", e
            )

        try:
            self.collectors["headless"] = create_collector("headless")
        except Exception as e:
            logger.warning(
                "Failed to initialize Headless collector (check playwright install): {}",
                e,
            )

        try:
            self.collectors["reddit"] = create_collector("reddit")
        except Exception as e:
            logger.opt(exception=True).error(
                "Failed to initialize Reddit collector: {}", e
            )

        if self.logger_factory:
            for c in self.collectors.values():
                if hasattr(c, "set_logger_factory"):
                    c.set_logger_factory(self.logger_factory)

        if self.health_tracker:
            for name, c in self.collectors.items():
                if hasattr(c, "health_tracker"):
                    c.health_tracker = self.health_tracker
                    logger.debug("Dispatcher set tracker on {} ({})", name, type(c))
                else:
                    logger.debug(
                        "Collector {} ({}) has no health_tracker attr", name, type(c)
                    )

    def set_logger_factory(self, logger_factory):
        self.logger_factory = logger_factory
        for c in self.collectors.values():
            if hasattr(c, "set_logger_factory"):
                c.set_logger_factory(logger_factory)

    def set_health_tracker(self, health_tracker):
        self.health_tracker = health_tracker
        for c in self.collectors.values():
            if hasattr(c, "health_tracker"):
                c.health_tracker = health_tracker

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

    def _attribute_dispatch_failure(
        self,
        final_results: Dict[str, Any],
        *,
        source_ids: list,
        collector_type: str,
        reason: str,
        error_class: str,
        error_message: str,
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> None:
        """Record one source_details entry + health-tracker call per
        affected source for a dispatcher-level failure (a whole-group
        exception, an unavailable collector, or a malformed result).
        Never raises: a telemetry failure must not take down the
        collection result (plan 040 Step 4)."""
        details = {"error_class": error_class, "error_message": error_message}
        for sid in source_ids:
            final_results["source_details"][sid] = {
                "success": False,
                "reason": reason,
                "collector_type": collector_type,
                **details,
            }
            if self.health_tracker:
                try:
                    self.health_tracker.record_attempt(sid)
                    self.health_tracker.record_failure(sid, "unknown", reason, details)
                except Exception as tracker_exc:  # noqa: BLE001
                    logger.opt(exception=tracker_exc).warning(
                        "health_tracker call failed for source={} reason={}: {}",
                        sid,
                        reason,
                        tracker_exc,
                    )

    async def collect_from_multiple_sources_async(  # noqa: C901
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        sources_requested = len(sources_config)

        # Group sources by type. A genuinely unrecognized `collector_type`
        # string falls back to "rss" (deliberate, kept behavior — see plan
        # 040's STOP condition: not externally promised elsewhere, but not
        # asked to be changed either; locked in by
        # test_dispatcher_unknown_collector_type_falls_back_to_rss).
        # A *known* type whose collector failed to initialize (e.g.
        # `headless` without playwright) must NOT take that same silent
        # fallback — it needs to reach the collector_unavailable branch
        # below instead, so it stays grouped under its own type name.
        grouped_sources: Dict[str, Dict[str, Any]] = {}
        source_assigned_type: Dict[str, str] = {}
        for source_id, config in sources_config.items():
            ctype = config.get("collector_type", "rss").lower()
            if (
                ctype not in self.collectors
                and ctype not in self._KNOWN_COLLECTOR_TYPES
            ):
                ctype = "rss"

            if ctype not in grouped_sources:
                grouped_sources[ctype] = {}
            grouped_sources[ctype][source_id] = config
            source_assigned_type[source_id] = ctype

        final_results: Dict[str, Any] = {
            "source_details": {},
            "collection_summary": {
                "sources_requested": sources_requested,
                "sources_processed": 0,
                "sources_succeeded": 0,
                "sources_failed": 0,
                "articles_found": 0,
                "articles_saved": 0,
                "errors_encountered": 0,
            },
        }

        # Dispatch async with metadata for failure attribution
        tasks: list[asyncio.Task] = []
        task_metadata: dict[int, dict[str, Any]] = {}
        for ctype, sources in grouped_sources.items():
            collector = self.collectors.get(ctype)
            source_ids = list(sources.keys())
            if not collector:
                logger.error(
                    "Collector unavailable: type={}, sources={}, session={}, trace={}",
                    ctype,
                    source_ids,
                    session_id,
                    trace_id,
                )
                self._attribute_dispatch_failure(
                    final_results,
                    source_ids=source_ids,
                    collector_type=ctype,
                    reason="collector_unavailable",
                    error_class="CollectorUnavailable",
                    error_message=f"No collector registered for type '{ctype}'",
                    session_id=session_id,
                    trace_id=trace_id,
                )
                continue
            meta = {"collector_type": ctype, "source_ids": source_ids}
            if hasattr(collector, "collect_from_multiple_sources_async"):
                coro = collector.collect_from_multiple_sources_async(
                    sources, session_id=session_id, trace_id=trace_id
                )
            else:
                coro = asyncio.to_thread(
                    collector.collect_from_multiple_sources,
                    sources,
                    session_id=session_id,
                    trace_id=trace_id,
                )
            task_metadata[len(tasks)] = meta
            tasks.append(coro)  # type: ignore[arg-type]

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, res in enumerate(results_list):
            meta = task_metadata.get(idx, {})
            result_ctype: str = str(meta.get("collector_type", "unknown"))
            result_source_ids: list = list(meta.get("source_ids", []))

            if isinstance(res, Exception):
                logger.opt(exception=res).error(
                    "Collector task failed: type={}, sources={}, session={}, trace={}, error={}",
                    result_ctype,
                    result_source_ids,
                    session_id,
                    trace_id,
                    res,
                )
                final_results["collection_summary"]["errors_encountered"] += len(
                    result_source_ids
                )
                self._attribute_dispatch_failure(
                    final_results,
                    source_ids=result_source_ids,
                    collector_type=result_ctype,
                    reason="dispatcher_task_exception",
                    error_class=type(res).__name__,
                    error_message=str(res),
                    session_id=session_id,
                    trace_id=trace_id,
                )
                continue
            if not isinstance(res, dict):
                logger.error(
                    "Collector returned malformed result: type={}, sources={}, "
                    "session={}, trace={}, result_type={}",
                    result_ctype,
                    result_source_ids,
                    session_id,
                    trace_id,
                    type(res).__name__,
                )
                final_results["collection_summary"]["errors_encountered"] += len(
                    result_source_ids
                )
                self._attribute_dispatch_failure(
                    final_results,
                    source_ids=result_source_ids,
                    collector_type=result_ctype,
                    reason="malformed_result",
                    error_class=type(res).__name__,
                    error_message="Collector returned a non-dict result",
                    session_id=session_id,
                    trace_id=trace_id,
                )
                continue

            # Merge source details. Only accept entries for sources actually
            # requested — a child collector reporting a foreign/extra sid
            # must not inflate sources_succeeded/failed beyond
            # sources_requested (review finding: the mirror direction of
            # the under-reporting gap below).
            if "source_details" in res:
                for sid, detail in res["source_details"].items():
                    if sid in sources_config:
                        final_results["source_details"][sid] = detail
                    else:
                        logger.warning(
                            "Collector reported source_details for an "
                            "unrequested source: type={}, source_id={}, "
                            "session={}, trace={}",
                            result_ctype,
                            sid,
                            session_id,
                            trace_id,
                        )

            # Merge summary stats (errors_encountered here reflects a
            # successful group's own reported sub-source error count,
            # distinct from dispatch-level failures above)
            if "collection_summary" in res:
                summ = res["collection_summary"]
                final_summary = final_results["collection_summary"]
                final_summary["articles_found"] += summ.get("articles_found", 0)
                final_summary["articles_saved"] += summ.get("articles_saved", 0)
                final_summary["errors_encountered"] += summ.get("errors_encountered", 0)

        # Reconcile against the requested set: a child collector's own
        # result can be a valid dict whose source_details sub-map still
        # omits one of the sources assigned to it (a bug inside that
        # collector, not a dispatch-level exception/malformed-result).
        # Without this, that source would silently vanish — counted
        # nowhere — breaking the succeeded+failed==requested invariant
        # (review finding). Backfill it as an attributed failure instead.
        missing_ids = [
            sid for sid in sources_config if sid not in final_results["source_details"]
        ]
        if missing_ids:
            by_type: Dict[str, list] = {}
            for sid in missing_ids:
                by_type.setdefault(source_assigned_type.get(sid, "unknown"), []).append(
                    sid
                )
            for ctype, sids in by_type.items():
                logger.error(
                    "Collector omitted requested sources from its own "
                    "result: type={}, sources={}, session={}, trace={}",
                    ctype,
                    sids,
                    session_id,
                    trace_id,
                )
                self._attribute_dispatch_failure(
                    final_results,
                    source_ids=sids,
                    collector_type=ctype,
                    reason="child_source_missing",
                    error_class="MissingSourceDetail",
                    error_message="Collector result omitted this source",
                    session_id=session_id,
                    trace_id=trace_id,
                )

        # Derive succeeded/failed from the final merged source_details in
        # one pass, so `succeeded + failed == requested` is structural
        # rather than accumulated per-branch (plan 040 Step 3).
        succeeded = sum(
            1 for r in final_results["source_details"].values() if r.get("success")
        )
        failed = len(final_results["source_details"]) - succeeded
        final_summary = final_results["collection_summary"]
        final_summary["sources_succeeded"] = succeeded
        final_summary["sources_failed"] = failed
        final_summary["sources_processed"] = sources_requested
        final_summary["success_rate_percent"] = (
            round((succeeded / sources_requested) * 100, 2)
            if sources_requested > 0
            else 0.0
        )

        return final_results

    def is_healthy(self) -> bool:
        return all(c.is_healthy() for c in self.collectors.values())

    async def close(self):
        """Close all initialized collectors."""
        for c in self.collectors.values():
            if hasattr(c, "close"):
                if asyncio.iscoroutinefunction(c.close):
                    await c.close()
                else:
                    c.close()

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        for name, c in self.collectors.items():
            stats[name] = c.get_stats()
        return stats
