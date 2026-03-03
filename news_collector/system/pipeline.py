"""
Module role: Encapsulates the execution orchestration logic of the full news collection cycle.

Inputs:
- Initialized NewsCollectorSystem instance.
- Optional lists of source filters, dry_run flags, and trace IDs.

Outputs:
- Dictionary containing final session reports, performance metrics, and summary.
- Traces and metrics emitted to the observability system.

Side effects:
- Writes session logs and performance metrics.
- Orchestrates external system calls (collection, validation, scoring) via system methods.
- Generates global session identifiers.

Invariants:
- LAW-3: System Layer Is Orchestration Only. Must not embed business rules or data parsing.
- Must execute stages in correct order: collection -> validation -> scoring -> selection -> report.
- System must be fully initialized before pipeline execution starts.

Failure modes:
- Raises RuntimeError if system is not initialized prior to execution.
- Propagates collection/scoring/validation exceptions but logs them with context and trace IDs first.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from news_collector.system import observability


async def run_cycle_orchestration(
    system: Any,
    sources_filter: Optional[List[str]] = None,
    dry_run: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ejecuta un ciclo completo de recolección de noticias.
    """
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado. Ejecutar initialize() primero.")

    trace_id = trace_id or str(uuid.uuid4())

    session_id = (
        f"{system.system_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    system.current_session = session_id

    # Observability: Session Logger
    session_logger = observability.create_session_logger(system.logger, session_id)
    cycle_start = time.perf_counter()

    # Trace: Start
    observability.trace_cycle_start(
        session_logger, trace_id, session_id, dry_run, sources_filter
    )

    try:
        # Access internal methods of system - temporary coupling is allowed for extraction
        sources_to_process = system._get_sources_to_process(sources_filter)

        # Trace: Sources Selected
        observability.trace_sources_selected(
            session_logger, trace_id, session_id, len(sources_to_process)
        )

        collection_results = await system._execute_collection(
            sources_to_process,
            dry_run,
            session_id=session_id,
            trace_id=trace_id,
        )

        # Observability: Outcomes (Metrics + Logs)
        observability.record_collection_outcomes(
            system.logger, system.metrics, collection_results, session_id, trace_id
        )

        validation_results = system._execute_validation(collection_results, dry_run)

        # Trace: Validation
        observability.trace_validation_completed(
            session_logger,
            trace_id,
            session_id,
            validation_results.get("validated_count", 0),
            validation_results.get("rejected_count", 0),
        )

        scoring_results = await system._execute_scoring(collection_results, dry_run)

        # Trace: Scoring
        observability.trace_scoring_completed(
            session_logger, trace_id, session_id, scoring_results.get("statistics", {})
        )

        final_selection = system._execute_final_selection(
            scoring_results, collection_results
        )
        final_report = system._generate_session_report(
            collection_results, scoring_results, final_selection, session_id
        )

        system.logger.log_performance_metrics(
            final_report["performance_metrics"], "CICLO COMPLETO"
        )

        # Log informativo solicitado por usuario
        observability.log_user_summary(system.logger, collection_results)

        # Trace: Cycle Completed
        observability.trace_cycle_completed(
            session_logger,
            trace_id,
            session_id,
            time.perf_counter() - cycle_start,
            final_report["summary"],
        )

        return cast(Dict[str, Any], final_report)

    except Exception as e:
        latency = time.perf_counter() - cycle_start
        observability.trace_cycle_error(
            session_logger, trace_id, session_id, latency, str(e)
        )

        system.logger.log_error_with_context(
            e,
            {
                "session_id": session_id,
                "system_id": system.system_id,
                "trace_id": trace_id,
            },
        )
        raise
