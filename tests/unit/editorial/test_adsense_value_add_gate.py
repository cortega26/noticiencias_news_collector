"""Regression tests for source-aware editorial value-add publication control."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    _parse_editorial_critic_result,
)
from news_collector.logic.workflows.refinery_engine import RefineryEngine


def _scores_verdict(**overrides):
    verdict = {
        "hook_score": 8,
        "clarity_score": 8,
        "structure_score": 8,
        "rigor_score": 8,
        "voice_score": 8,
        "shareability_score": 8,
        "closing_score": 8,
        "average": 8.0,
        "approved": True,
        "recoverable": True,
        "feedback": "",
        "value_add_assessment": "substantive",
        "value_add_evidence": "Explica limites que la fuente no desarrolla.",
    }
    verdict.update(overrides)
    return verdict


def test_close_paraphrase_rejects_even_when_seven_scores_pass():
    result = _parse_editorial_critic_result(
        _scores_verdict(
            approved=False,
            value_add_assessment="close_paraphrase",
            feedback="Reorganizar la explicación y contrastar limites.",
        )
    )
    assert result[0] is False
    assert result[2].startswith("Reorganizar")


def test_close_paraphrase_cannot_be_approved():
    assert (
        _parse_editorial_critic_result(
            _scores_verdict(value_add_assessment="close_paraphrase")
        )[0]
        is False
    )


@pytest.mark.parametrize("assessment", ["substantive", "insufficient_source"])
def test_substantive_or_unverifiable_comparison_does_not_block(assessment):
    assert (
        _parse_editorial_critic_result(
            _scores_verdict(value_add_assessment=assessment)
        )[0]
        is True
    )


def test_unknown_value_add_result_is_not_accepted_as_valid_verdict():
    with pytest.raises(ValueError, match="value_add_assessment"):
        _parse_editorial_critic_result(
            _scores_verdict(value_add_assessment="invented_result")
        )


def test_legacy_critic_output_preserves_existing_threshold_validation():
    legacy = _scores_verdict()
    legacy.pop("value_add_assessment")
    assert _parse_editorial_critic_result(legacy)[0] is True


def _engine_with_verdict(verdict):
    engine = object.__new__(RefineryEngine)
    engine.editor = MagicMock()
    engine.policy = SimpleNamespace(critic_threshold=80, mode="standard")
    engine.editor.process_article.return_value = "Contenido editorial"
    engine.editor.last_critic_verdict = verdict
    engine._last_blocked_error = None
    engine._record_advisory_stages = MagicMock(return_value=("Contenido editorial", ""))
    return engine, MagicMock()


def _engine_and_run(value_add_assessment: str, approved: bool):
    return _engine_with_verdict(
        {
            "approved": approved,
            "average": 8.0,
            "value_add_assessment": value_add_assessment,
            "value_add_evidence": "Coincidencia de orden y frases con la muestra fuente.",
        }
    )


def _bare_critic_agent(response: str):
    agent = object.__new__(EditorAgent)
    agent.prompts = {"editor_critic": {"system": "sys"}}
    agent.editor_model = "m"
    agent.last_critic_verdict = None
    agent._send_prompt = MagicMock(return_value=response)
    return agent


def test_refinery_blocks_close_paraphrase_after_repair_exhaustion():
    engine, run = _engine_and_run("close_paraphrase", False)
    assert engine._refine_article({}, "42", "2026-10-12", run) is None
    assert engine._last_blocked_error["error_code"] == "E_EDITORIAL_VALUE_ADD"
    run.record_stage.assert_called_once()
    assert run.record_stage.call_args.args[:2] == ("editor_refinement", False)
    run.persist_attempt.assert_called_once_with(False)
    engine._record_advisory_stages.assert_not_called()


def test_refinery_allows_insufficient_source_without_false_positive():
    engine, run = _engine_and_run("insufficient_source", True)
    assert engine._refine_article({}, "42", "2026-10-12", run) == (
        "Contenido editorial",
        "",
    )
    run.persist_attempt.assert_not_called()
    engine._record_advisory_stages.assert_called_once()


def test_invalid_close_paraphrase_fails_open_and_publishes():
    """Plan 103 fail-open pinned at the engine gate (PR 373 review).

    A `close_paraphrase` verdict missing the seven scores is not a valid
    verdict: `_parse_editorial_critic_result` raises, `_critic_editorial_pass`
    fails open and leaves `last_critic_verdict` as None. The refinery gate must
    publish instead of raising `E_EDITORIAL_VALUE_ADD`.
    """
    payload = json.dumps(
        {
            "approved": False,
            "recoverable": True,
            "feedback": "Sigue de cerca la fuente.",
            "value_add_assessment": "close_paraphrase",
            "value_add_evidence": "Orden y frases coincidentes con la fuente.",
        }
    )
    agent = _bare_critic_agent(payload)
    verdict = agent._critic_editorial_pass("Contenido editorial " * 20)
    assert verdict.is_valid is True
    assert verdict.checkpointable is False
    assert agent.last_critic_verdict["verification_status"] == "unverified"

    # The engine gate must publish for the fail-open verdict the agent just
    # produced, and for a legacy/missing-assessment verdict with no
    # `close_paraphrase` marker.
    for fail_open_verdict in (
        agent.last_critic_verdict,
        {"approved": False, "value_add_evidence": "sin dictamen"},
    ):
        engine, run = _engine_with_verdict(fail_open_verdict)
        assert engine._refine_article({}, "42", "2026-10-12", run) == (
            "Contenido editorial",
            "",
        )
        assert engine._last_blocked_error is None
        run.persist_attempt.assert_not_called()
        engine._record_advisory_stages.assert_called_once()
