"""Unit tests for spec-editorial-quality-lifts L5/L6.

L5: headline-critic exhaustion emits a structured, countable event while
still publishing the last headlines (behavior unchanged).
L6: enrichment retries exactly once on total failure before accepting empty
defaults (prompt-missing stays single-path, zero calls).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from news_collector.components.editorial import ai_editor as ai_editor_module
from news_collector.components.editorial.ai_editor import EditorAgent


def _agent() -> EditorAgent:
    agent = object.__new__(EditorAgent)
    agent.prompts = {
        "headline": {"system": "h"},
        "headline_critic": {"system": "hc"},
        "enrichment": {"system": "en"},
    }
    agent.enrichment_model = "m"
    agent.provider = MagicMock()
    agent.provider._extract_json = MagicMock(side_effect=json.loads)
    return agent


_VALID_ENRICHMENT = json.dumps(
    {
        "summary_points": ["Punto resumido uno", "Punto resumido dos"],
        "glossary": [{"term": "Término", "definition": "Definición"}],
        "fact_check": [{"label": "Afirmación", "status": "confirmed"}],
        "why_it_matters": ["Relevancia"],
        "confidence": "Alta.",
        "sources": [{"title": "Fuente", "url": "https://example.com/f"}],
    }
)


class TestHeadlineExhaustionEvent:
    def test_exhaustion_holds_rejected_headlines(self, monkeypatch) -> None:
        agent = _agent()
        headlines = {"direct": "Titular final"}
        agent._generate_headlines = MagicMock(return_value=dict(headlines))
        agent._headline_critic_pass = MagicMock(return_value=(False, "muy largo"))
        events: list = []
        monkeypatch.setattr(
            ai_editor_module.logger,
            "warning",
            lambda *a, **k: events.append(a[0] if a else None),
        )

        import pytest

        from news_collector.components.editorial.ai_editor import (
            GeneratedArticleValidationError,
        )

        with pytest.raises(GeneratedArticleValidationError) as held:
            agent._generate_headlines_with_critic("cuerpo")
        assert held.value.error_code == "E_HEADLINE_EVIDENCE"
        assert agent._headline_critic_pass.call_count == 3

    def test_approval_short_circuits_without_event(self, monkeypatch) -> None:
        agent = _agent()
        agent._generate_headlines = MagicMock(return_value={"direct": "T"})
        agent._headline_critic_pass = MagicMock(return_value=(True, None))
        events: list = []
        monkeypatch.setattr(
            ai_editor_module.logger,
            "warning",
            lambda *a, **k: events.append(a[0] if a else None),
        )

        assert agent._generate_headlines_with_critic("cuerpo") == {"direct": "T"}
        assert not [e for e in events if isinstance(e, dict)]


class TestEnrichmentSingleRetry:
    def test_transient_failure_recovers_with_one_retry(self) -> None:
        agent = _agent()
        agent._send_prompt = MagicMock(
            side_effect=[RuntimeError("boom"), _VALID_ENRICHMENT]
        )

        result = agent._generate_enrichment_fields("cuerpo", "Título")

        assert result["summary_points"] == ["Punto resumido uno", "Punto resumido dos"]
        assert agent._send_prompt.call_count == 2

    def test_persistent_failure_returns_empty_after_two_calls(self) -> None:
        agent = _agent()
        agent._send_prompt = MagicMock(return_value="not json at all {{{")

        result = agent._generate_enrichment_fields("cuerpo", "Título")

        assert result["summary_points"] == []
        assert result["sources"] == []
        assert agent._send_prompt.call_count == 2

    def test_missing_prompt_makes_zero_calls(self) -> None:
        agent = _agent()
        agent.prompts = {}
        agent._send_prompt = MagicMock()

        result = agent._generate_enrichment_fields("cuerpo", "Título")

        assert result["summary_points"] == []
        assert agent._send_prompt.call_count == 0
