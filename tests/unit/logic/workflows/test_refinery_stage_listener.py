"""Live stage listener on RefineryEngine (admin GUI progress)."""

from __future__ import annotations

from news_collector.logic.workflows.refinery_engine import (
    RefineryEngine,
    _PublicationRun,
)


def _bare_engine() -> RefineryEngine:
    engine = RefineryEngine.__new__(RefineryEngine)
    engine._last_publication_stages = None
    engine.stage_listener = None
    return engine


def test_record_stage_notifies_listener() -> None:
    engine = _bare_engine()
    seen: list = []
    engine.stage_listener = lambda aid, name, ok: seen.append((aid, name, ok))

    run = _PublicationRun(engine, "42")
    run.record_stage("image_resolution", True, image_url="x")
    run.record_stage("editor_refinement", False)

    assert seen == [
        ("42", "image_resolution", True),
        ("42", "editor_refinement", False),
    ]
    assert [s.name for s in engine._last_publication_stages] == [
        "image_resolution",
        "editor_refinement",
    ]


def test_listener_failure_does_not_break_stage_recording() -> None:
    engine = _bare_engine()

    def boom(*_a):
        raise RuntimeError("listener down")

    engine.stage_listener = boom
    run = _PublicationRun(engine, "42")
    run.record_stage("policy_gate", True)

    assert [s.name for s in run.stages] == ["policy_gate"]


def test_no_listener_is_a_noop() -> None:
    engine = _bare_engine()
    run = _PublicationRun(engine, "1")
    run.record_stage("policy_gate", True)
    assert len(run.stages) == 1
