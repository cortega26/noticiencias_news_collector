"""Tests for Plan 060 / Phase 2c: real fact-check verification (Stage 4.5).

Covers `EditorAgent._verify_fact_check_claims` / `_send_fact_check_prompt`
directly, the new Stage 4.5 call site in `process_article` (both the
cache-hit and cache-miss branches must run verification), and the new
"editorial_fact_check_disputed" fail-closed gate.

See plans/060/phase-2c-real-fact-check/spec.md for the full design and
plans/060/phase-2c-real-fact-check/todo.md Step 5 for the specific test
obligations this file exists to satisfy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    GeneratedArticleValidationError,
)

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
    "fact_check": [
        {"label": "Primera afirmación verificable", "status": "confirmed"},
        {"label": "Segunda afirmación verificable", "status": "needs_review"},
    ],
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

_ENGLISH_SOURCE_CONTENT = (
    "Scientists at a university engineering lab announced on Tuesday that a new "
    "battery prototype retained 92 percent of its original capacity after 5,000 "
    "charge cycles, a result the team called a major step toward longer-lasting "
    "electric vehicle batteries. The prototype has so far only been tested under "
    "laboratory conditions and has not yet been installed or evaluated in a "
    "full-size vehicle. The researchers said commercial availability, if the "
    "approach proves viable at scale, remains several years away."
)


def _pipeline_agent(tmp_path: Path) -> EditorAgent:
    """Build an EditorAgent with every stage stubbed except the new Phase 2c
    fact-check verification, so process_article-level tests exercise the
    real _verify_fact_check_claims loop/overwrite/gate logic."""
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)
    agent.category_resolver._classifier = MagicMock(
        try_classify_article=MagicMock(return_value=None)
    )
    agent._send_prompt = lambda *a, **k: _LONG_BODY
    agent._critic_pass = lambda *a: (True, None, True)
    agent._critic_editorial_pass = lambda *a, **k: (True, None, True)
    agent._generate_enrichment_fields = lambda *a, **k: json.loads(
        json.dumps(_VALID_ENRICHMENT_FIELDS)
    )
    agent._generate_headlines = lambda *a, **k: {
        "direct": "Direct Headline",
        "question": "Question Headline?",
        "benefit": "Benefit Headline",
        "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
        "tags": ["ciencia"],
    }
    return agent


def _base_article(**overrides) -> dict:
    article = {
        "id": "fc-1",
        "title": "Demo",
        "summary": "Resumen",
        "content": _ENGLISH_SOURCE_CONTENT,
        "url": "https://example.com/source",
    }
    article.update(overrides)
    return article


# ---------------------------------------------------------------------------
# Unit tests for _verify_fact_check_claims / _send_fact_check_prompt
# ---------------------------------------------------------------------------


class TestVerifyFactCheckClaimsUnit:
    def test_confirmed_uncertain_disputed_paths(self) -> None:
        """The verifier's returned status is what ends up on each claim,
        regardless of Stage 4's own self-assessed value."""
        agent = EditorAgent("http://example", "model")
        responses = iter(
            [
                {"status": "confirmed"},
                {"status": "uncertain"},
                {"status": "disputed"},
            ]
        )
        agent._send_fact_check_prompt = MagicMock(
            side_effect=lambda *a, **k: next(responses)
        )

        claims = [
            {"label": "Claim A", "status": "needs_review"},
            {"label": "Claim B", "status": "needs_review"},
            {"label": "Claim C", "status": "needs_review"},
        ]
        result = agent._verify_fact_check_claims(
            claims, "Some source content.", "Title", "full_text"
        )

        assert [c["status"] for c in result] == ["confirmed", "uncertain", "disputed"]
        assert [c["label"] for c in result] == ["Claim A", "Claim B", "Claim C"]

    def test_unrecognized_verifier_status_falls_back_to_uncertain(self) -> None:
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock(
            return_value={"status": "exaggerated"}
        )
        result = agent._verify_fact_check_claims(
            [{"label": "Claim", "status": "confirmed"}],
            "Some source content.",
            "Title",
            "full_text",
        )
        assert result == [{"label": "Claim", "status": "uncertain"}]

    def test_summary_mode_label_reaches_prompt_context(self) -> None:
        """content_mode == summary_only/summary_fallback must add an honest
        'this is a summary, not the full article' marker to the prompt
        context sent to the verifier."""
        agent = EditorAgent("http://example", "model")
        captured: dict[str, str] = {}

        def _capture(prompt: str, system: str) -> dict:
            captured["prompt"] = prompt
            return {"status": "confirmed"}

        agent._send_fact_check_prompt = _capture

        agent._verify_fact_check_claims(
            [{"label": "Algo", "status": "needs_review"}],
            "Source text here.",
            "Title",
            "summary_only",
        )
        assert "RESUMEN" in captured["prompt"]

        agent._verify_fact_check_claims(
            [{"label": "Algo", "status": "needs_review"}],
            "Source text here.",
            "Title",
            "full_text",
        )
        assert "RESUMEN" not in captured["prompt"]

        agent._verify_fact_check_claims(
            [{"label": "Algo", "status": "needs_review"}],
            "Source text here.",
            "Title",
            "summary_fallback",
        )
        assert "RESUMEN" in captured["prompt"]

    def test_infrastructure_error_falls_back_to_uncertain_never_crashes(self) -> None:
        """An Ollama call error for a claim must degrade that claim to
        'uncertain' — never 'disputed', never a silent pass-through of the
        old self-assessed value, and never a raised exception."""
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock(side_effect=ConnectionError("boom"))
        result = agent._verify_fact_check_claims(
            [{"label": "Claim", "status": "disputed"}],
            "Source text.",
            "Title",
            "full_text",
        )
        assert result == [{"label": "Claim", "status": "uncertain"}]

    def test_empty_source_content_marks_all_uncertain_without_guessing(self) -> None:
        """STOP condition #2: an empty/null source despite content_mode
        claiming otherwise must be treated as verification-unavailable (all
        claims uncertain) — never guessed, and no LLM call is made at all."""
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock()

        result = agent._verify_fact_check_claims(
            [
                {"label": "Claim 1", "status": "confirmed"},
                {"label": "Claim 2", "status": "disputed"},
            ],
            "   ",
            "Title",
            "full_text",
        )

        assert result == [
            {"label": "Claim 1", "status": "uncertain"},
            {"label": "Claim 2", "status": "uncertain"},
        ]
        agent._send_fact_check_prompt.assert_not_called()

    def test_no_claims_returns_empty_without_calling_llm(self) -> None:
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock()
        assert (
            agent._verify_fact_check_claims([], "Source.", "Title", "full_text") == []
        )
        agent._send_fact_check_prompt.assert_not_called()

    def test_missing_prompt_config_fails_open_to_uncertain(self) -> None:
        """If the fact_check_verification prompt is missing/misconfigured,
        every claim degrades to 'uncertain' rather than crashing or silently
        publishing an unverified status."""
        agent = EditorAgent("http://example", "model")
        agent.prompts = {**agent.prompts, "fact_check_verification": {}}
        agent._send_fact_check_prompt = MagicMock()

        result = agent._verify_fact_check_claims(
            [{"label": "Claim", "status": "confirmed"}],
            "Source text.",
            "Title",
            "full_text",
        )
        assert result == [{"label": "Claim", "status": "uncertain"}]
        agent._send_fact_check_prompt.assert_not_called()

    def test_overwrite_all_rule_discards_stage4_self_assessment(self) -> None:
        """A claim Stage 4 self-assessed as 'disputed' that the independent
        verifier re-checks as 'confirmed' must end up 'confirmed' — the old
        six-value self-assessment never survives verification, not even
        partially."""
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "confirmed"})

        result = agent._verify_fact_check_claims(
            [{"label": "Claim", "status": "disputed"}],
            "Source content that actually supports the claim.",
            "Title",
            "full_text",
        )
        assert result == [{"label": "Claim", "status": "confirmed"}]

    def test_malformed_claims_are_skipped_not_crashed_on(self) -> None:
        agent = EditorAgent("http://example", "model")
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "confirmed"})
        result = agent._verify_fact_check_claims(
            [
                "not-a-dict",
                {"label": "", "status": "confirmed"},
                {"label": "Real claim", "status": "x"},
            ],
            "Source text.",
            "Title",
            "full_text",
        )
        # The bare string is dropped; the empty-label dict becomes 'uncertain'
        # without a network call; the real claim is verified for real.
        assert result == [
            {"label": "", "status": "uncertain"},
            {"label": "Real claim", "status": "confirmed"},
        ]

    def test_cross_lingual_prompt_carries_english_source_and_spanish_claim(
        self,
    ) -> None:
        """Deterministic (no live network) proof that a real English source
        excerpt and a real Spanish claim are both threaded into the same
        verification prompt, alongside the cross-lingual instruction — the
        production input is always cross-lingual (Spanish claims drafted
        from a typically-English source), so this must not be a
        same-language synthetic pair."""
        agent = EditorAgent("http://example", "model")
        captured: dict[str, str] = {}

        def _capture(prompt: str, system: str) -> dict:
            captured["prompt"] = prompt
            captured["system"] = system
            return {"status": "confirmed"}

        agent._send_fact_check_prompt = _capture

        spanish_claim = (
            "El prototipo de batería retuvo el 92% de su capacidad tras 5.000 "
            "ciclos de carga."
        )
        agent._verify_fact_check_claims(
            [{"label": spanish_claim, "status": "needs_review"}],
            _ENGLISH_SOURCE_CONTENT,
            "Nuevo prototipo de batería",
            "full_text",
        )

        assert spanish_claim in captured["prompt"]
        assert "battery prototype retained 92 percent" in captured["prompt"]
        # The system prompt (config/prompts.yaml: fact_check_verification)
        # must carry the explicit cross-lingual instruction.
        assert "idioma" in captured["system"].lower()


# ---------------------------------------------------------------------------
# Real, live-Ollama proof of cross-lingual verification (opt-in only — this
# repo's convention for tests that hit real network/local infra, matching
# tests/integration/test_scrapling_e2e.py's SCRAPLING_E2E gate). Run
# manually with NOTICIENCIAS_FACT_CHECK_LIVE=true when a local Ollama
# instance with the configured fact_check_model is available.
# ---------------------------------------------------------------------------

_FACT_CHECK_LIVE = os.getenv("NOTICIENCIAS_FACT_CHECK_LIVE", "").lower() == "true"


@pytest.mark.skipif(
    not _FACT_CHECK_LIVE,
    reason="Set NOTICIENCIAS_FACT_CHECK_LIVE=true to run against a real local Ollama instance",
)
@pytest.mark.timeout(180)
def test_live_cross_lingual_verification_against_real_ollama() -> None:
    """Real (non-mocked) proof that the dedicated fact-check model can
    correctly verify a Spanish claim against an English source: confirms a
    claim the source supports, and disputes one the source explicitly
    contradicts. This is the one test in this file that actually exercises
    qwen3-next (or whatever fact_check_model resolves to) end-to-end."""
    agent = EditorAgent(
        "http://localhost:11434/api/generate", "qwen3-next:80b-a3b-instruct-q4_K_M"
    )

    supported_claim = (
        "El prototipo de batería retuvo el 92% de su capacidad tras 5.000 "
        "ciclos de carga."
    )
    contradicted_claim = (
        "El prototipo ya fue instalado y evaluado con éxito en un vehículo "
        "eléctrico completo."
    )

    result = agent._verify_fact_check_claims(
        [
            {"label": supported_claim, "status": "needs_review"},
            {"label": contradicted_claim, "status": "needs_review"},
        ],
        _ENGLISH_SOURCE_CONTENT,
        "Nuevo prototipo de batería",
        "full_text",
    )

    statuses = {item["label"]: item["status"] for item in result}
    assert statuses[supported_claim] == "confirmed"
    assert statuses[contradicted_claim] == "disputed"


# ---------------------------------------------------------------------------
# process_article integration: Stage 4.5 call site, cache-hit proof, and the
# new fail-closed gate.
# ---------------------------------------------------------------------------


class TestProcessArticleFactCheckIntegration:
    def test_gate_blocks_on_disputed_verified_claim(self, tmp_path: Path) -> None:
        agent = _pipeline_agent(tmp_path)
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "disputed"})

        with pytest.raises(GeneratedArticleValidationError) as excinfo:
            agent.process_article(_base_article(), override_date="2026-03-02")

        assert excinfo.value.error_code == "editorial_fact_check_disputed"
        for claim in _VALID_ENRICHMENT_FIELDS["fact_check"]:
            assert claim["label"] in str(excinfo.value)

    def test_gate_does_not_block_on_all_confirmed_or_uncertain(
        self, tmp_path: Path
    ) -> None:
        agent = _pipeline_agent(tmp_path)
        responses = iter([{"status": "confirmed"}, {"status": "uncertain"}])
        agent._send_fact_check_prompt = MagicMock(
            side_effect=lambda *a, **k: next(responses)
        )

        result = agent.process_article(
            _base_article(id="fc-2"), override_date="2026-03-02"
        )

        assert "Direct Headline" in result

    def test_stage4_self_assessed_disputed_never_verified_does_not_block(
        self, tmp_path: Path
    ) -> None:
        """Proves the overwrite-all rule end-to-end: Stage 4 drafted one
        claim self-assessed as 'disputed' (old six-value vocabulary), but
        the independent verifier re-checks it as 'confirmed' — publication
        must NOT be blocked, because only a verifier-returned 'disputed'
        can trigger the gate."""
        agent = _pipeline_agent(tmp_path)
        agent._generate_enrichment_fields = lambda *a, **k: {
            **json.loads(json.dumps(_VALID_ENRICHMENT_FIELDS)),
            "fact_check": [
                {
                    "label": "Afirmación self-assessed como disputed",
                    "status": "disputed",
                }
            ],
        }
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "confirmed"})

        result = agent.process_article(
            _base_article(id="fc-3"), override_date="2026-03-02"
        )

        assert "Direct Headline" in result

    def test_stage4_cache_hit_still_runs_verification_and_can_block(
        self, tmp_path: Path
    ) -> None:
        """Proves the cache-poisoning fix (spec.md Design §2): a
        stage4_enrichment cache file seeded with an old-style self-assessed
        fact_check status must NOT let that status survive to the gate —
        verification must run unconditionally on the cache-hit path too,
        and a verifier-returned 'disputed' must still block."""
        agent = _pipeline_agent(tmp_path)
        article_id = "fc-cache-hit"

        cache_path = agent.cache_dir / f"{article_id}_stage4_enrichment.txt"
        cached_enrichment = {
            **_VALID_ENRICHMENT_FIELDS,
            "fact_check": [
                {"label": "Afirmación cacheada con status viejo", "status": "confirmed"}
            ],
        }
        cache_path.write_text(json.dumps(cached_enrichment), encoding="utf-8")

        # If Stage 4 were called for real on a cache hit, this would fail
        # the test with a clear signal — the cache-hit branch must reuse
        # `cached_enrichment` and never call _generate_enrichment_fields.
        agent._generate_enrichment_fields = MagicMock(
            side_effect=AssertionError("Stage 4 must not run again on a cache hit")
        )
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "disputed"})

        with pytest.raises(GeneratedArticleValidationError) as excinfo:
            agent.process_article(
                _base_article(id=article_id), override_date="2026-03-02"
            )

        assert excinfo.value.error_code == "editorial_fact_check_disputed"
        assert "Afirmación cacheada con status viejo" in str(excinfo.value)
        agent._generate_enrichment_fields.assert_not_called()
        agent._send_fact_check_prompt.assert_called_once()

    def test_stage4_cache_hit_with_confirmed_verdict_publishes_normally(
        self, tmp_path: Path
    ) -> None:
        """Control case for the cache-hit test above: when the verifier
        re-checks the cached claim as 'confirmed', a cache-hit article
        publishes normally (verification ran, but did not block)."""
        agent = _pipeline_agent(tmp_path)
        article_id = "fc-cache-hit-ok"

        cache_path = agent.cache_dir / f"{article_id}_stage4_enrichment.txt"
        cached_enrichment = {
            **_VALID_ENRICHMENT_FIELDS,
            "fact_check": [{"label": "Afirmación cacheada", "status": "confirmed"}],
        }
        cache_path.write_text(json.dumps(cached_enrichment), encoding="utf-8")

        agent._generate_enrichment_fields = MagicMock(
            side_effect=AssertionError("Stage 4 must not run again on a cache hit")
        )
        agent._send_fact_check_prompt = MagicMock(return_value={"status": "confirmed"})

        result = agent.process_article(
            _base_article(id=article_id), override_date="2026-03-02"
        )

        assert "Direct Headline" in result
        fm_marker = "fact_check"
        assert fm_marker in result
        agent._generate_enrichment_fields.assert_not_called()
        agent._send_fact_check_prompt.assert_called_once()

    def test_summary_only_content_mode_reaches_verification(
        self, tmp_path: Path
    ) -> None:
        agent = _pipeline_agent(tmp_path)
        captured: dict[str, str] = {}

        def _capture(prompt: str, system: str) -> dict:
            captured["prompt"] = prompt
            return {"status": "confirmed"}

        agent._send_fact_check_prompt = _capture

        agent.process_article(
            _base_article(id="fc-summary", content_mode="summary_only"),
            override_date="2026-03-02",
        )

        assert "RESUMEN" in captured["prompt"]
