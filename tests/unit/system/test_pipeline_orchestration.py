from __future__ import annotations

import asyncio
from typing import Any

import pytest

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
        assert dry_run is True
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
    event_names = {
        payload["event"]
        for _, payload in system.logger.events
        if isinstance(payload, dict)
    }
    assert "collection_cycle.start" in event_names
    assert "collection_cycle.completed" in event_names
    assert ("perf", "CICLO COMPLETO") in system.logger.events


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
