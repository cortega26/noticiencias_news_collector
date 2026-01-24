"""
Observability module for NewsCollectorSystem.
Centralizes logging, metrics emission, and tracing logic.
"""

from typing import Any, Dict


def create_session_logger(logger_factory: Any, session_id: str) -> Any:
    """Creates a module-specific logger for the session."""
    return logger_factory.create_module_logger(f"session.{session_id}")


def trace_cycle_start(
    logger: Any, trace_id: str, session_id: str, dry_run: bool, sources_filter: Any
) -> None:
    """Logs collection_cycle.start event."""
    logger.info(
        {
            "event": "collection_cycle.start",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": 0.0,
            "details": {
                "dry_run": dry_run,
                "source_filter": sources_filter or "all",
            },
        }
    )


def trace_sources_selected(
    logger: Any, trace_id: str, session_id: str, count: int
) -> None:
    """Logs collection_cycle.sources.selected event."""
    logger.info(
        {
            "event": "collection_cycle.sources.selected",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": 0.0,
            "details": {"count": count},
        }
    )


def record_collection_outcomes(
    logger_factory: Any,
    metrics: Any,
    collection_results: Dict[str, Any],
    session_id: str,
    trace_id: str,
) -> None:
    """
    Logs per-source results and emits ingest/error metrics.
    Replaces: NewsCollectorSystem._record_collection_observability
    """
    source_details = collection_results.get("source_details") or {}
    if not source_details:
        return

    collector_logger = logger_factory.create_module_logger("collectors")

    for source_id, result in source_details.items():
        latency = float(result.get("processing_time") or 0.0)
        payload = {
            "event": (
                "collector.source.completed"
                if result.get("success", False)
                else "collector.source.failed"
            ),
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": source_id,
            "latency": latency,
            "details": {
                "articles_found": result.get("articles_found", 0),
                "articles_saved": result.get("articles_saved", 0),
                "error_message": result.get("error_message"),
            },
        }

        if result.get("success", False):
            collector_logger.info(payload)
            if metrics:
                metrics.record_ingest(
                    source_id=source_id,
                    article_count=result.get("articles_saved", 0),
                    latency=latency,
                    trace_id=trace_id,
                    session_id=session_id,
                )
        else:
            collector_logger.warning(payload)
            if metrics:
                metrics.record_error(
                    source_id=source_id,
                    error=result.get("error_message", "unknown"),
                    trace_id=trace_id,
                    session_id=session_id,
                )


def trace_validation_completed(
    logger: Any, trace_id: str, session_id: str, validated: int, rejected: int
) -> None:
    """Logs collection_cycle.validation.completed event."""
    logger.info(
        {
            "event": "collection_cycle.validation.completed",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": 0.0,
            "details": {
                "validated": validated,
                "rejected": rejected,
            },
        }
    )


def trace_scoring_completed(
    logger: Any, trace_id: str, session_id: str, stats: Dict[str, Any]
) -> None:
    """Logs collection_cycle.scoring.completed event."""
    logger.info(
        {
            "event": "collection_cycle.scoring.completed",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": 0.0,
            "details": stats,
        }
    )


def trace_cycle_completed(
    logger: Any, trace_id: str, session_id: str, latency: float, summary: Dict[str, Any]
) -> None:
    """Logs collection_cycle.completed event."""
    logger.info(
        {
            "event": "collection_cycle.completed",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": latency,
            "details": summary,
        }
    )


def trace_cycle_error(
    logger: Any, trace_id: str, session_id: str, latency: float, error: str
) -> None:
    """Logs collection_cycle.error event."""
    logger.error(
        {
            "event": "collection_cycle.error",
            "trace_id": trace_id,
            "session_id": session_id,
            "source_id": "system",
            "latency": latency,
            "details": {"error": error},
        }
    )


def log_user_summary(logger_factory: Any, collection_results: Dict[str, Any]) -> None:
    """Logs the high-level human readable summary (saved articles count)."""
    source_details = collection_results.get("source_details", {})
    total_sources = len(source_details)
    sources_with_data = sum(
        1 for res in source_details.values() if res.get("articles_saved", 0) > 0
    )

    # We use create_module_logger directly if we don't have a specific system_logger instance passed,
    # or just assume logger_factory IS the system logger if passed?
    # In pipeline.py it uses system.system_logger.
    # Let's assume logger_factory is the main logger interface which can create module loggers.
    # But system_logger is a specific instance.
    # Let's look at pipeline.py usage: "if system.system_logger: system.system_logger.info(...)"
    # We should probably pass the system_logger directly if available, or simpler:
    # Use logger_factory to create/get "system" logger.

    # "system" logger creation: logger.create_module_logger("system")
    system_logger = logger_factory.create_module_logger("system")
    system_logger.info(
        f"📊 Reporte de Recolección: {sources_with_data}/{total_sources} fuentes produjeron información con éxito (artículos guardados)."
    )
