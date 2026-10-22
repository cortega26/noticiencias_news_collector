"""Plan 155: derive the Stage-4 critic average from its seven scores.

The model's own ``average`` is model arithmetic, not a gate input. The
canary's first real local run (issue #366) failed with ``parse_error``
because the model's mean did not match its scores; these tests pin that a
drifting, absent, or unusable model average can no longer disable the critic.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    _parse_editorial_critic_result,
)

_SCORES = {
    "hook_score": 9,
    "clarity_score": 8,
    "structure_score": 8,
    "rigor_score": 8,
    "voice_score": 9,
    "shareability_score": 8,
    "closing_score": 9,
}
_DERIVED_AVERAGE = 8.43  # 59 / 7, rounded to two decimals


def _verdict(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "approved": True,
        "material_claims_supported": True,
        "average": 8.5,
        "feedback": "",
        "recoverable": True,
        **_SCORES,
    }
    payload.update(overrides)
    return payload


def _bare_agent() -> EditorAgent:
    agent = object.__new__(EditorAgent)
    agent.model = "m"
    agent.translator_model = "m"
    agent.editor_model = "m"
    agent.headlines_model = "m"
    agent.enrichment_model = "m"
    agent.critic_threshold = 70
    agent.prompts = {"editor_critic": {"system": "ec"}}
    agent.provider = MagicMock()
    agent.provider._extract_json = MagicMock(return_value={})
    agent.category_resolver = MagicMock()
    agent.last_critic_verdict = None
    return agent


class TestAverageIsDerived:
    def test_drifting_model_average_parses_with_derived_value(self):
        """Canary shape: complete verdict, model average off by > 0.11."""
        approved, recoverable, feedback, average, scores = (
            _parse_editorial_critic_result(_verdict(average=2.0))
        )

        assert approved is True
        assert recoverable is True
        assert feedback == ""
        assert average == _DERIVED_AVERAGE
        assert scores == _SCORES

    def test_missing_model_average_parses(self):
        payload = _verdict()
        payload.pop("average")

        assert _parse_editorial_critic_result(payload)[3] == _DERIVED_AVERAGE

    def test_unusable_model_average_is_ignored(self):
        assert (
            _parse_editorial_critic_result(_verdict(average="8.5"))[3]
            == _DERIVED_AVERAGE
        )


class TestScoresRemainValidated:
    def test_missing_score_still_rejected(self):
        payload = _verdict()
        payload.pop("clarity_score")

        with pytest.raises(ValueError, match="missing"):
            _parse_editorial_critic_result(payload)

    @pytest.mark.parametrize("bad_score", [11, -1, 7.5, "8", True])
    def test_invalid_score_still_rejected(self, bad_score):
        with pytest.raises(ValueError, match="integers from 0 to 10"):
            _parse_editorial_critic_result(_verdict(clarity_score=bad_score))


class TestApprovalRuleUnchanged:
    def test_approval_contradicting_derived_thresholds_is_rejected(self):
        with pytest.raises(ValueError, match="contradicts the stated thresholds"):
            _parse_editorial_critic_result(_verdict(approved=False))

    def test_approval_with_low_rigor_is_rejected(self):
        with pytest.raises(ValueError, match="contradicts the stated thresholds"):
            _parse_editorial_critic_result(_verdict(rigor_score=5))

    def test_close_paraphrase_cannot_be_approved(self):
        assert (
            _parse_editorial_critic_result(
                _verdict(value_add_assessment="close_paraphrase")
            )[0]
            is False
        )


class TestAgentStoresDerivedVerdict:
    def test_canary_shape_stores_verdict_instead_of_failing_open(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value=json.dumps(_verdict(average=2.0)))

        verdict = agent._critic_editorial_pass("real body " * 20)

        assert verdict.is_valid is True
        assert verdict.checkpointable is True
        assert agent.last_critic_verdict is not None
        assert agent.last_critic_verdict["approved"] is True
        assert agent.last_critic_verdict["average"] == _DERIVED_AVERAGE
        assert agent.last_critic_verdict["scores"] == _SCORES
