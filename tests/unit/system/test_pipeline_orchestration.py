from __future__ import annotations

import asyncio
from typing import Any

import pytest

from news_collector.contracts.admin import AdminRunProgress
from news_collector.system.pipeline import run_cycle_orchestration


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def create_module_logger(self, name: str) -> "_FakeLogger":
        return self

    def info(self, payload: Any) -> None:
        self.events.append(("info", payload))

    def warning(self, payload: Any) -> None:
        self.events.append(("warning", payload))

    def error(self, payload: Any) -> None:
        self.events.append(("error", payload))

    def log_performance_metrics(self, metrics: Any, label: str) -> None:
        self.events.append(("perf", label))

    def log_error_with_context(self, exc: Exception, context: Any) -> None:
        self.events.append(("errctx", str(exc)))


class _FakeMetrics:
    def record_ingest(self, **kwargs: Any) -> None:
        pass

    def record_error(self, **kwargs: Any) -> None:
        pass


class _FakeSystem:
    def __init__(
        self,
        *,
        is_initialized: bool = True,
        fail_collection: bool = False,
    ) -> None:
        self.is_initialized = is_initialized
        self.fail_collection = fail_collection
        self.system_id = "fake-sys"
        self.current_session: str | None = None
        self.logger = _FakeLogger()
        self.metrics = _FakeMetrics()
        self.last_selection_dry_run: bool | None = None

    def _get_sources_to_process(self, sources_filter: Any) -> dict[str, dict[str, Any]]:
        return {"source": {}}

    async def _execute_collection(
        self,
        sources: Any,
        dry_run: bool,
        *,
        session_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if self.fail_collection:
            raise ValueError("simulated collection failure")
        return {
            "collection_summary": {"articles_found": 1},
            "source_details": {
                "source": {
                    "success": True,
                    "articles_found": 1,
                    "articles_saved": 1,
                    "processing_time": 0.1,
                }
            },
        }

    def _execute_validation(
        self, collection_results: Any, dry_run: bool
    ) -> dict[str, Any]:
        return {"validated_count": 1, "rejected_count": 0}

    async def _execute_scoring(
        self, collection_results: Any, dry_run: bool
    ) -> dict[str, Any]:
        return {"statistics": {"articles_scored": 1}}

    def _execute_final_selection(
        self,
        scoring_results: Any,
        collection_results: Any = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self.last_selection_dry_run = dry_run
        return {
            "success": True,
            "selected_count": 1,
            "articles": [{"title": "Selected"}],
            "selection_criteria": {"mode": "dry_run_simulation"},
        }

    def _generate_session_report(
        self,
        collection_results: Any,
        scoring_results: Any,
        selection_results: Any,
        session_id: str,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "performance_metrics": {"cycle_latency_ms": 1.0},
            "summary": {"sources_processed": 1},
            "selection_results": selection_results,
        }


def test_run_cycle_orchestration_happy_path() -> None:
    system = _FakeSystem()

    report = asyncio.run(run_cycle_orchestration(system, dry_run=True))

    assert report["summary"]["sources_processed"] == 1
    assert system.current_session is not None
    assert system.last_selection_dry_run is True
    event_names = {
        payload["event"]
        for _, payload in system.logger.events
        if isinstance(payload, dict)
    }
    assert "collection_cycle.start" in event_names
    assert "collection_cycle.completed" in event_names
    assert ("perf", "CICLO COMPLETO") in system.logger.events


def test_run_cycle_orchestration_reports_backend_steps_and_contains_listener_errors() -> (
    None
):
    system = _FakeSystem()
    progress: list[AdminRunProgress] = []
    failed_once = False

    def listener(update: AdminRunProgress) -> None:
        nonlocal failed_once
        progress.append(update)
        if not failed_once:
            failed_once = True
            raise RuntimeError("progress store unavailable")

    report = asyncio.run(
        run_cycle_orchestration(system, dry_run=True, progress_callback=listener)
    )

    assert report["summary"]["sources_processed"] == 1
    assert [
        (
            item.phase_key,
            item.phase_index,
            item.phase_count,
            item.step_key,
            item.step_status,
        )
        for item in progress
    ] == [
        ("collection", 1, 5, "source_collection", "running"),
        ("collection", 1, 5, "source_collection", "completed"),
        ("validation", 2, 5, "validation", "running"),
        ("validation", 2, 5, "validation", "completed"),
        ("scoring", 3, 5, "scoring", "running"),
        ("scoring", 3, 5, "scoring", "completed"),
        ("selection", 4, 5, "final_selection", "running"),
        ("selection", 4, 5, "final_selection", "completed"),
        ("selection", 4, 5, "session_report", "running"),
        ("selection", 4, 5, "session_report", "completed"),
    ]


@pytest.mark.parametrize(
    ("stage", "phase_key", "step_key"),
    [
        ("validation", "validation", "validation"),
        ("scoring", "scoring", "scoring"),
        ("selection", "selection", "final_selection"),
        ("report", "selection", "session_report"),
    ],
)
def test_run_cycle_orchestration_marks_failed_backend_step(
    stage: str, phase_key: str, step_key: str
) -> None:
    system = _FakeSystem()
    progress: list[AdminRunProgress] = []
    failure = ValueError(f"simulated {stage} failure")

    def fail_stage(*args: Any, **kwargs: Any) -> None:
        raise failure

    if stage == "scoring":

        async def fail_scoring(*args: Any, **kwargs: Any) -> None:
            raise failure

        system._execute_scoring = fail_scoring  # type: ignore[method-assign]
    elif stage == "validation":
        system._execute_validation = fail_stage  # type: ignore[method-assign]
    elif stage == "selection":
        system._execute_final_selection = fail_stage  # type: ignore[method-assign]
    else:
        system._generate_session_report = fail_stage  # type: ignore[method-assign]

    with pytest.raises(ValueError, match=f"simulated {stage} failure"):
        asyncio.run(
            run_cycle_orchestration(
                system, dry_run=True, progress_callback=progress.append
            )
        )

    failed_updates = [item for item in progress if item.step_status == "failed"]
    assert [(item.phase_key, item.step_key) for item in failed_updates] == [
        (phase_key, step_key)
    ]


def test_run_cycle_orchestration_requires_initialized_system() -> None:
    system = _FakeSystem(is_initialized=False)

    with pytest.raises(RuntimeError, match="no inicializado"):
        asyncio.run(run_cycle_orchestration(system))


def test_run_cycle_orchestration_propagates_collection_failure() -> None:
    system = _FakeSystem(fail_collection=True)

    with pytest.raises(ValueError, match="simulated collection failure"):
        asyncio.run(run_cycle_orchestration(system, trace_id="t1"))

    event_names = {
        payload["event"]
        for _, payload in system.logger.events
        if isinstance(payload, dict)
    }
    assert "collection_cycle.error" in event_names
    assert ("errctx", "simulated collection failure") in system.logger.events
