"""Plan 103 regression tests: editorial critic fails open on keyless verdicts.

Covers the 2026-09-16 article-1181 incident: a non-JSON critic reply fell
back to ``{}`` and was read as a 0-score quality REJECT. A keyless verdict
is an infra/parse failure and must fail open; headline generation must not
burn LLM calls on blank input.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    _extract_publishable_body,
)


def _bare_agent() -> EditorAgent:
    agent = object.__new__(EditorAgent)
    agent.model = "m"
    agent.translator_model = "m"
    agent.editor_model = "m"
    agent.headlines_model = "m"
    agent.enrichment_model = "m"
    agent.critic_threshold = 70
    agent.prompts = {
        "translator": {"system": "t"},
        "editor": {"system": "e", "user_template": "x"},
        "headline": {"system": "h"},
        "editor_critic": {"system": "ec"},
        "headline_critic": {"system": "hc"},
        "enrichment": {"system": "en"},
    }
    agent.provider = MagicMock()
    agent.provider._extract_json = MagicMock(return_value={})
    agent.category_resolver = MagicMock()
    agent.last_critic_verdict = None
    return agent


def _full_agent(tmp_path: Path) -> EditorAgent:
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)
    agent.category_resolver._classifier = MagicMock(
        try_classify_article=MagicMock(return_value=None)
    )
    return agent


_LONG_BODY = (
    "**El Impacto (Lead)**\n"
    "Este análisis examina los avances recientes en el campo científico y tecnológico. "
    "Los investigadores han identificado nuevos patrones que permiten comprender mejor "
    "los fenómenos estudiados en este dominio. El trabajo demuestra resultados "
    "significativos para la comunidad científica internacional. Las implicaciones de "
    "estos hallazgos se extienden a múltiples disciplinas y abren nuevas líneas de "
    "investigación prometedoras. La metodología empleada resulta reproducible y "
    "transparente, lo que fortalece la credibilidad del estudio. En conclusión, estos "
    "resultados contribuyen al avance del conocimiento en el área y representan un "
    "paso importante para futuras investigaciones.\n"
)

_VALID_ENRICHMENT_FIELDS: dict[str, object] = {
    "summary_points": ["Punto resumido"],
    "glossary": [{"term": "Término", "definition": "Definición"}],
    "fact_check": [{"label": "Afirmación", "status": "confirmed"}],
    "why_it_matters": ["Relevancia regional"],
    "confidence": "Alta — metodología sólida.",
    "sources": [
        {
            "title": "Fuente",
            "url": "https://example.com/fuente",
            "publisher": "Editorial",
        }
    ],
}

# 1181-shape prose: no braces, hence no extractable verdict keys.
_KEYLESS_PROSE = (
    "El artículo presenta un análisis sólido sobre los corales de Galápagos "
    "con buena estructura y cierre. Recomiendo su publicación con ajustes "
    "menores de estilo en la apertura para reforzar el gancho inicial."
)


class TestKeylessCriticVerdictFailsOpen:
    def test_prose_without_keys_fails_open(self):
        """Keyless critic prose approves instead of scoring a 0/10 REJECT."""
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value=_KEYLESS_PROSE)
        assert agent._critic_editorial_pass("real body") == (True, None, True)
        assert agent.last_critic_verdict is None

    def test_empty_dict_verdict_fails_open(self):
        """A bare {} verdict (generic-extractor fallback) also fails open."""
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value="plain prose, no braces")
        assert agent._critic_editorial_pass("real body") == (True, None, True)

    def test_genuine_rejection_still_rejects(self):
        """A real approved=false verdict with scores still returns REJECT."""
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value=json.dumps(
                {
                    "approved": False,
                    "average": 4.0,
                    "hook_score": 3,
                    "clarity_score": 5,
                    "structure_score": 5,
                    "rigor_score": 6,
                    "voice_score": 5,
                    "shareability_score": 4,
                    "closing_score": 4,
                    "feedback": "La apertura es genérica; reescribir el gancho.",
                    "recoverable": True,
                }
            )
        )
        is_valid, feedback, recoverable = agent._critic_editorial_pass("real body")
        assert is_valid is False
        assert feedback == "La apertura es genérica; reescribir el gancho."
        assert recoverable is True


class TestBlankHeadlineInputShortCircuits:
    @pytest.mark.parametrize(
        "blank_input",
        ["", "   \n\t  ", "---\ntitle: x\n---\n"],
    )
    def test_blank_input_returns_empty_without_llm_calls(self, blank_input):
        assert _extract_publishable_body(blank_input or "") == ""
        agent = _bare_agent()
        agent._send_prompt = MagicMock()
        assert agent._generate_headlines(blank_input) == {}
        agent._send_prompt.assert_not_called()


class TestIncident1181Replay:
    def test_keyless_verdict_never_sends_article_to_repair(self, tmp_path):
        """1181 replay: critic-passed content + keyless editorial-critic
        prose must not trigger the editorial repair loop."""
        agent = _full_agent(tmp_path)
        # Every LLM seam returns fixed content; the critic call therefore
        # receives prose with no verdict keys (the 1181 shape).
        agent._send_prompt = lambda prompt, *a, **k: _LONG_BODY
        agent._critic_pass = lambda *a: (True, None, True)
        agent._generate_enrichment_fields = lambda *a, **k: dict(
            _VALID_ENRICHMENT_FIELDS
        )
        agent._send_fact_check_prompt = lambda *a, **k: {"status": "confirmed"}
        agent._generate_headlines = lambda *a, **k: {
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
            "tags": ["espacio"],
        }
        agent._repair_editorial = MagicMock(return_value=_LONG_BODY)
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            },
            override_date="2026-03-02",
        )
        agent._repair_editorial.assert_not_called()
        assert "Direct Headline" in result
