"""Coverage-focused unit tests for news_collector.components.editorial.ai_editor.

Targets the extraction/critic/headline/repair branches and process_article
defensive paths that the behavioral suites do not reach.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date as _dt
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    GeneratedArticleValidationError,
    HeadlinesSchema,
    _collect_heading_structure_issues,
    _extract_publishable_body,
    _reason_indicates_missing_text,
    _sample_for_critic,
    _strip_llm_epilogue,
    _strip_llm_preamble,
    validate_generated_article_markdown,
)


def _json_parser():
    def _parse(text):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return {}

    parse = MagicMock(wraps=_parse)
    return parse


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


class TestModuleHelpers:
    def test_sample_for_critic_long_content(self):
        long_content = "a" * 6000
        sample = _sample_for_critic(long_content, max_chars=2000)
        assert "[...]" in sample
        assert len(sample) < 6000

    def test_sample_for_critic_short_content(self):
        assert _sample_for_critic("short", max_chars=2000) == "short"

    def test_strip_llm_preamble(self):
        text = "\nAquí tienes el artículo:\n\nContent body\n"
        assert _strip_llm_preamble(text) == "Content body\n"

    def test_strip_llm_preamble_removes_all(self):
        with patch(
            "news_collector.components.editorial.ai_editor.logger"
        ) as mock_logger:
            result = _strip_llm_preamble("Aquí tienes el artículo:\n")
        mock_logger.warning.assert_called()
        assert result == "Aquí tienes el artículo:\n"

    def test_strip_llm_epilogue(self):
        text = "Content body\n\n¿Te gustaría que modifique algo?\n"
        result = _strip_llm_epilogue(text)
        assert "¿Te gustaría" not in result
        assert "Content body" in result

    def test_collect_heading_issues_empty_body(self):
        assert _collect_heading_structure_issues("") == []

    def test_collect_heading_issues_h1(self):
        issues = _collect_heading_structure_issues("# Big H1\n\nbody text\n")
        assert any("H1" in i for i in issues)

    def test_validate_markdown_empty_body(self):
        with pytest.raises(GeneratedArticleValidationError):
            validate_generated_article_markdown("---\ntitle: x\n---\n")

    def test_validate_markdown_too_thin(self):
        with pytest.raises(GeneratedArticleValidationError) as exc:
            validate_generated_article_markdown("short body")
        assert "too thin" in str(exc.value)

    def test_reason_indicates_missing_text_empty(self):
        assert _reason_indicates_missing_text(None) is False
        assert _reason_indicates_missing_text("") is False
        assert _reason_indicates_missing_text("no text provided") is True

    def test_extract_publishable_body_removes_scaffolding(self):
        body = _extract_publishable_body(
            "---\ntitle: x\n---\n\nReal body\n\n"
            "Fuente original: [link](https://x.com)\n"
        )
        assert "Real body" in body
        assert "Fuente original" not in body


class TestAgentHelpers:
    def test_inject_frontmatter_field_no_frontmatter(self):
        agent = _bare_agent()
        result = agent._inject_frontmatter_field("body\n", "key", "value")
        assert result.startswith("---")

    def test_inject_frontmatter_field_existing_key(self):
        agent = _bare_agent()
        text = "---\ntitle: old\nkey: exists\n---\n\nbody\n"
        result = agent._inject_frontmatter_field(text, "key", "value")
        assert result == text

    def test_inject_frontmatter_field_inserts(self):
        agent = _bare_agent()
        text = "---\ntitle: old\n---\n\nbody\n"
        result = agent._inject_frontmatter_field(text, "key", "value")
        assert 'key: "value"' in result
        assert "title: old" in result

    def test_extract_markdown_content_fenced_markdown(self):
        agent = _bare_agent()
        result = agent._extract_markdown_content("```markdown\nBody here\n```")
        assert result.strip() == "Body here"

    def test_extract_markdown_content_fenced_generic(self):
        agent = _bare_agent()
        result = agent._extract_markdown_content("```\nBody here\n```")
        assert result.strip() == "Body here"

    def test_upsert_source_identity_comment_empty_cleaned(self):
        agent = _bare_agent()
        result = agent._upsert_source_identity_comment("", "s1", "S One")
        assert result.startswith("<!-- source_identity")

    def test_normalize_frontmatter_for_yaml(self):
        agent = _bare_agent()

        class Custom:
            def __str__(self):
                return "custom-str"

        result = agent._normalize_frontmatter_for_yaml(
            {"a": Custom(), "b": None, "c": [1, "x"], "d": {"k": 2}}
        )
        assert result["a"] == "custom-str"
        # None values are dropped, not emitted as YAML `null`: the frontend
        # schema declares optional fields as z.string().optional() which
        # accepts absence but rejects null (sources[].date regression,
        # plan 021/048 found 2026-08-11).
        assert "b" not in result
        assert result["c"] == [1, "x"]
        assert result["d"] == {"k": 2}

    def test_normalize_frontmatter_drops_none_in_source_items(self):
        """Regression: sources[].date: null failed the frontend schema
        (expected string, received null). None must serialize as absent."""
        agent = _bare_agent()
        payload = {
            "title": "T",
            "date": _dt(2026, 8, 11),
            "sources": [
                {"title": "S", "url": "https://x.io", "publisher": None, "date": None},
                {"title": "S2", "url": "https://y.io", "date": "2026-01-01"},
            ],
            "glossary": [{"term": "t", "definition": "d", "alt": None}],
        }
        result = agent._normalize_frontmatter_for_yaml(payload)
        assert "publisher" not in result["sources"][0]
        assert "date" not in result["sources"][0]
        assert result["sources"][1]["date"] == "2026-01-01"
        assert "alt" not in result["glossary"][0]
        assert result["date"] == _dt(2026, 8, 11)

    def test_send_prompt_success(self):
        agent = _bare_agent()
        agent.provider.generate_sync = MagicMock(
            return_value=iter(["chunk1", " chunk2"])
        )
        result = agent._send_prompt("prompt", system="sys", model="mm")
        assert result == "chunk1 chunk2"

    def test_send_prompt_error(self):
        agent = _bare_agent()
        agent.provider.generate_sync = MagicMock(
            side_effect=RuntimeError("provider down")
        )
        with pytest.raises(RuntimeError):
            agent._send_prompt("prompt")

    def test_load_technical_glossary_missing(self):
        agent = _bare_agent()
        with patch.object(Path, "exists", return_value=False):
            assert agent._load_technical_glossary() == {}

    def test_load_technical_glossary_exception(self):
        agent = _bare_agent()
        with patch(
            "news_collector.components.editorial.ai_editor.json.loads",
            side_effect=RuntimeError("bad json"),
        ):
            assert agent._load_technical_glossary() == {}

    def test_format_technical_glossary_empty(self):
        agent = _bare_agent()
        assert agent._format_technical_glossary_for_prompt({}) == ""

    def test_format_technical_glossary_full(self):
        agent = _bare_agent()
        result = agent._format_technical_glossary_for_prompt(
            {
                "brands_and_proper_nouns": ["Gemini"],
                "acronyms": {"LLM": "large model"},
                "technical_terms": {"*benchmark*": "prueba"},
            }
        )
        assert "Gemini" in result
        assert "LLM" in result

    def test_load_scientific_entities_missing(self):
        agent = _bare_agent()
        with patch("news_collector.components.editorial.ai_editor.Path") as mock_path:
            parent = MagicMock()
            parent.__truediv__.return_value.exists.return_value = False
            mock_path.return_value.resolve.return_value.parents[3] = parent
            assert agent._load_scientific_entities() == ""

    def test_format_editor_context_block_none(self):
        agent = _bare_agent()
        result = agent._format_editor_context_block(None)
        assert "<<DATOS_NO_CONFIABLES>>" in result
        assert "Sin metadata adicional" in result

    def test_format_editor_context_block_empty_lines(self):
        agent = _bare_agent()
        result = agent._format_editor_context_block({"title": ""})
        assert "Sin metadata adicional" in result

    def test_format_editor_context_block_truncates(self):
        agent = _bare_agent()
        result = agent._format_editor_context_block({"summary": "s" * 500})
        assert "…" in result

    def test_adapt_editorial_fallback_prompt(self):
        agent = _bare_agent()
        agent.prompts = {"editor": {"system": "e"}}
        agent._send_prompt = MagicMock(return_value="out")
        result = agent._adapt_editorial("translated", {"title": "T"})
        assert result == "out"
        sent = agent._send_prompt.call_args.args[0]
        assert "Vas a redactar el artículo" in sent

    def test_extract_json_raises_when_no_result(self):
        agent = _bare_agent()
        agent.provider._extract_json = MagicMock(return_value={})
        with pytest.raises(ValueError):
            agent._extract_json('{"key": "value"}')

    def test_extract_json_returns_result(self):
        agent = _bare_agent()
        agent.provider._extract_json = MagicMock(return_value={"score": 80})
        assert agent._extract_json("whatever") == {"score": 80}

    def test_repair_editorial_mentions_terms(self):
        agent = _bare_agent()
        agent.prompts = {"editor": {"system": "e"}}
        agent._send_prompt = MagicMock(return_value="fixed")
        agent._load_technical_glossary = MagicMock(
            return_value={
                "brands_and_proper_nouns": ["Gemini"],
                "acronyms": {"LLM": "large"},
                "technical_terms": {"*quantum*": "cuántico"},
            }
        )
        result = agent._repair_editorial(
            "base", "revisa Gemini y LLM y *quantum*", {"title": "T"}
        )
        assert result == "fixed"
        sent = agent._send_prompt.call_args.args[0]
        assert "ATENCIÓN" in sent


class TestCriticPasses:
    def test_critic_pass_kill_switch(self):
        agent = _bare_agent()
        with patch.dict(os.environ, {"ENABLE_TRANSLATION_GUARD": "false"}):
            assert agent._critic_pass("any") == (True, None, True)

    def test_critic_pass_exception_fails_closed(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(side_effect=RuntimeError("boom"))
        is_valid, reason, recoverable = agent._critic_pass("content")
        assert is_valid is False
        assert "Critic Exception" in reason
        assert recoverable is True

    def test_critic_pass_rejects_low_score(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value='{"score": 10, "reason": "bad", "recoverable": true}'
        )
        is_valid, reason, recoverable = agent._critic_pass("content")
        assert is_valid is False
        assert reason == "bad"

    def test_critic_pass_accepts(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value='{"score": 95, "reason": "ok", "recoverable": false}'
        )
        is_valid, reason, recoverable = agent._critic_pass("content")
        assert is_valid is True
        assert reason is None

    def test_extract_critic_json_nested_fallback(self):
        agent = _bare_agent()
        result = agent._extract_critic_json(
            '{"wrapper": {"inner": 1}, "score": 85, "reason": "r"}'
        )
        assert result["score"] == 85

    def test_extract_critic_json_generic_fallback(self):
        agent = _bare_agent()
        agent.provider._extract_json = MagicMock(
            return_value={"score": 90, "reason": "fallback"}
        )
        result = agent._extract_critic_json("no json here")
        assert result["score"] == 90

    def test_editorial_critic_kill_switch(self):
        agent = _bare_agent()
        with patch.dict(os.environ, {"ENABLE_EDITORIAL_CRITIC": "false"}):
            assert agent._critic_editorial_pass("content") == (True, None, True)

    def test_editorial_critic_missing_prompt(self):
        agent = _bare_agent()
        agent.prompts = {}
        assert agent._critic_editorial_pass("content") == (True, None, True)

    def test_editorial_critic_empty_body(self):
        agent = _bare_agent()
        assert agent._critic_editorial_pass("---\ntitle: x\n---\n") == (
            True,
            None,
            True,
        )

    def test_editorial_critic_infra_error_fails_open(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(side_effect=RuntimeError("down"))
        assert agent._critic_editorial_pass("real body") == (True, None, True)

    def test_editorial_critic_unparseable_scores_fails_open(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value='{"approved": "yes", "average": "not-a-float"}'
        )
        assert agent._critic_editorial_pass("real body") == (True, None, True)

    def test_editorial_critic_approved(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value=json.dumps(
                {
                    "approved": True,
                    "average": 8.0,
                    "hook_score": 8,
                    "clarity_score": 8,
                    "structure_score": 8,
                    "rigor_score": 8,
                    "voice_score": 8,
                    "shareability_score": 8,
                    "closing_score": 8,
                    "feedback": "",
                    "recoverable": True,
                }
            )
        )
        assert agent._critic_editorial_pass("real body") == (True, None, True)

    def test_editorial_critic_rejected_no_feedback(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value='{"approved": false, "recoverable": true, "average": 4.0}'
        )
        is_valid, feedback, recoverable = agent._critic_editorial_pass("real body")
        assert is_valid is False
        assert feedback
        assert recoverable is True

    def test_extract_editorial_critic_json_fallback(self):
        agent = _bare_agent()
        agent.provider._extract_json = MagicMock(return_value={"approved": True})
        result = agent._extract_editorial_critic_json("plain text")
        assert result == {"approved": True}

    def test_extract_editorial_critic_json_nested(self):
        agent = _bare_agent()
        result = agent._extract_editorial_critic_json(
            '{"meta": {"a": 1}, "approved": false, "average": 5.0}'
        )
        assert result["approved"] is False

    def test_headline_critic_kill_switch(self):
        agent = _bare_agent()
        with patch.dict(os.environ, {"ENABLE_HEADLINE_CRITIC": "false"}):
            assert agent._headline_critic_pass("body", {}) == (True, None)

    def test_headline_critic_empty_body(self):
        agent = _bare_agent()
        assert agent._headline_critic_pass("", {}) == (True, None)

    def test_headline_critic_infra_error_fails_open(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(side_effect=RuntimeError("down"))
        assert agent._headline_critic_pass("real body", {}) == (True, None)

    def test_headline_critic_unparseable_fails_open(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value="not json with { brace")
        assert agent._headline_critic_pass("real body", {}) == (True, None)

    def test_headline_critic_approved(self):
        agent = _bare_agent()
        agent.provider._extract_json = _json_parser()
        agent._send_prompt = MagicMock(
            return_value='{"approved": true, "fidelity_pass": true, "sensationalism_pass": true}'
        )
        assert agent._headline_critic_pass("real body", {}) == (True, None)

    def test_headline_critic_rejected(self):
        agent = _bare_agent()
        agent.provider._extract_json = _json_parser()
        agent._send_prompt = MagicMock(
            return_value='{"approved": false, "regenerate_instruction": "try other pattern"}'
        )
        approved, instruction = agent._headline_critic_pass("real body", {})
        assert approved is False
        assert instruction == "try other pattern"

    def test_generate_headlines_with_critic_exhausts_retries(self):
        agent = _bare_agent()
        agent._generate_headlines = MagicMock(return_value={"direct": "H"})
        agent._headline_critic_pass = MagicMock(
            side_effect=[(False, "regen now"), (False, "again"), (False, "last")]
        )
        result = agent._generate_headlines_with_critic("body")
        assert result == {"direct": "H"}

    def test_generate_headlines_with_critic_honors_configured_retries(self):
        """text_processing.max_headline_retries=0 disables the retry loop:
        one generate + one critic, no regeneration (2026-08-12: a failing
        article burned ~9 min across 3 attempts before publishing the
        rejected headlines anyway)."""
        agent = _bare_agent()
        agent.max_headline_retries = 0
        agent._generate_headlines = MagicMock(return_value={"direct": "H"})
        agent._headline_critic_pass = MagicMock(return_value=(False, "regen now"))
        result = agent._generate_headlines_with_critic("body")
        assert result == {"direct": "H"}
        assert agent._generate_headlines.call_count == 1
        assert agent._headline_critic_pass.call_count == 1


class TestHeadlineGeneration:
    def _headlines_agent(self):
        agent = _bare_agent()
        agent.provider._extract_json = _json_parser()
        agent._send_prompt = MagicMock(
            return_value=json.dumps(
                {
                    "direct": "Direct Headline",
                    "question": "Question?",
                    "benefit": "Benefit",
                    "excerpt": "Excerpt long enough for SEO purposes here.",
                    "tags": ["espacio", "fisica"],
                    "pattern_used": "question",
                    "requires_uncertainty_note": False,
                    "uncertainty_note": "",
                }
            )
        )
        return agent

    def test_generate_headlines_success(self):
        agent = self._headlines_agent()
        result = agent._generate_headlines("content")
        assert result["direct"] == "Direct Headline"
        assert HeadlinesSchema.model_validate(result)

    def test_generate_headlines_with_regenerate_instruction(self):
        agent = self._headlines_agent()
        result = agent._generate_headlines(
            "content", regenerate_instruction="try curiosity_gap"
        )
        sent = agent._send_prompt.call_args.args[0]
        assert "curiosity_gap" in sent
        assert result["direct"] == "Direct Headline"

    def test_generate_headlines_kill_switch_skips_schema(self):
        agent = self._headlines_agent()
        agent._send_prompt = MagicMock(return_value='{"direct": "only-direct"}')
        with patch.dict(os.environ, {"ENABLE_TRANSLATION_GUARD": "false"}):
            result = agent._generate_headlines("content")
        assert result == {"direct": "only-direct"}

    def test_generate_headlines_schema_failure(self):
        agent = self._headlines_agent()
        agent._send_prompt = MagicMock(return_value='{"unexpected": true}')
        with pytest.raises(ValueError) as exc:
            agent._generate_headlines("content")
        assert "Schema Validation Failed" in str(exc.value)

    def test_generate_headlines_generic_failure(self):
        agent = self._headlines_agent()
        agent._extract_json = MagicMock(side_effect=RuntimeError("no json"))
        with pytest.raises(ValueError) as exc:
            agent._generate_headlines("content")
        assert "Failed to generate headlines" in str(exc.value)


class TestRepairOutput:
    def test_repair_output_fallback_headlines(self):
        agent = _bare_agent()
        content = _LONG_BODY
        headlines = {}
        repaired, out = agent._repair_output(content, headlines, len(content))
        assert out["direct"] == "Noticia Científica"
        assert "¿Qué plantea este estudio" in out["question"]
        assert "Importancia del hallazgo" in out["benefit"]

    def test_repair_output_trims_long_content(self):
        agent = _bare_agent()
        long_content = (
            "## Introducción\n\n" + ("Palabra repetida para relleno. " * 200) + "\n\n"
            "## Cierre\n\n" + ("Palabra repetida para relleno. " * 200) + "\n"
        )
        repaired, _ = agent._repair_output(
            long_content, {"direct": "D", "question": "Q", "benefit": "B"}, 50
        )
        assert len(repaired) < len(long_content)


class TestGenerateMethods:
    def test_generate_social_content(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value="### Twitter\npost")
        result = agent.generate_social_content("article", "https://x.com")
        assert result == "### Twitter\npost"
        sent = agent._send_prompt.call_args.args[0]
        assert "Twitter" in sent

    def test_analyze_visuals_success(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(
            return_value='{"visual_category": "SPACE", "visual_keywords": ["star"], "visual_prompt": "p"}'
        )
        agent.provider._extract_json = MagicMock(
            return_value={"visual_category": "SPACE"}
        )
        result = agent.analyze_visuals("article")
        assert result["visual_category"] == "SPACE"

    def test_analyze_visuals_failure_fallback(self):
        agent = _bare_agent()
        agent._send_prompt = MagicMock(return_value="garbage { bad")
        agent.provider._extract_json = MagicMock(return_value={})
        result = agent.analyze_visuals("article")
        assert result["visual_category"] == "OTHER"


class TestProcessArticlePaths:
    def _pipeline_agent(self, tmp_path: Path) -> EditorAgent:
        agent = _full_agent(tmp_path)
        agent._send_prompt = lambda prompt, *a, **k: _LONG_BODY
        agent._critic_pass = lambda *a: (True, None, True)
        agent._critic_editorial_pass = lambda *a, **k: (True, None, True)
        agent._generate_enrichment_fields = lambda *a, **k: dict(
            _VALID_ENRICHMENT_FIELDS
        )
        agent._generate_headlines = lambda *a, **k: {
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
            "tags": ["espacio"],
        }
        return agent

    def test_content_falls_back_to_summary(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Contenido " * 200,
                "content": "",
                "url": "https://example.com/source",
            }
        )
        assert "Direct Headline" in result

    def test_string_input_uses_hash_id(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        result = agent.process_article("Contenido " * 200)
        assert "Direct Headline" in result

    def test_content_too_short_raises(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        with pytest.raises(ValueError, match="Content too short"):
            agent.process_article(
                {
                    "title": "Demo",
                    "summary": "x",
                    "content": "tiny",
                    "url": "https://example.com/source",
                }
            )

    def test_cached_stage2_not_critic_ready_re_adapts(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        article = {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "url": "https://example.com/source",
        }
        agent.process_article(article)
        cache_s2 = agent.cache_dir / "unknown_stage2_editorial.txt"
        cache_s2.write_text("---\ntitle: x\n---\n", encoding="utf-8")
        result = agent.process_article(article)
        assert "Direct Headline" in result

    def test_critic_checkpoint_write_failure(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        original = agent.cache_dir
        real_write_text = Path.write_text

        def fake_get_cache_path(article_id, stage):
            return original / f"{article_id}_{stage}.txt"

        agent._get_cache_path = fake_get_cache_path
        with patch.object(Path, "write_text", autospec=True) as mock_write:

            def side_effect(self_path, *args, **kwargs):
                if "stage2_5_critic_ok" in str(self_path):
                    raise OSError("disk full")
                return real_write_text(self_path, *args, **kwargs)

            mock_write.side_effect = side_effect
            result = agent.process_article(
                {
                    "title": "Demo",
                    "summary": "Resumen",
                    "content": "Contenido " * 200,
                    "url": "https://example.com/source",
                }
            )
        assert "Direct Headline" in result

    def test_critic_irrecoverable_raises(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        agent._critic_pass = lambda *a: (False, "off topic", False)
        with pytest.raises(ValueError, match="permanently discarded"):
            agent.process_article(
                {
                    "title": "Demo",
                    "summary": "Resumen",
                    "content": "Contenido " * 200,
                    "url": "https://example.com/source",
                }
            )

    def test_critic_rejected_exhausted_retries(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        agent._critic_pass = lambda *a: (False, "bad translation", True)
        with pytest.raises(ValueError, match="Translation Guardrail"):
            agent.process_article(
                {
                    "title": "Demo",
                    "summary": "Resumen",
                    "content": "Contenido " * 200,
                    "url": "https://example.com/source",
                }
            )

    def test_editorial_critic_cache_skips_gate(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        article = {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "url": "https://example.com/source",
        }
        agent.process_article(article)
        cache = agent.cache_dir / "unknown" / "stage2_6_editorial_critic_ok"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("ok", encoding="utf-8")
        calls = []
        agent._critic_editorial_pass = lambda *a, **k: calls.append(1) or (
            True,
            None,
            True,
        )
        result = agent.process_article(article)
        assert calls == []
        assert "Direct Headline" in result

    def test_editorial_critic_irrecoverable_publishes(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        agent._critic_editorial_pass = lambda *a, **k: (False, "unfixable", False)
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            }
        )
        assert "Direct Headline" in result

    def test_enrichment_cache_invalid_regenerates(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        article = {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "url": "https://example.com/source",
        }
        agent.process_article(article)
        cache = agent.cache_dir / "unknown_stage4_enrichment.txt"
        cache.write_text("{not json", encoding="utf-8")
        result = agent.process_article(article)
        assert "Direct Headline" in result

    def test_headline_list_title_and_excerpt(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        agent._generate_headlines = lambda *a, **k: {
            "direct": ["List Direct"],
            "excerpt": ["List Excerpt"],
            "tags": ["espacio"],
            "requires_uncertainty_note": False,
        }
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            }
        )
        assert "List Direct" in result
        assert "List Excerpt" in result

    def test_uncertainty_note_emitted_when_required(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        agent._generate_headlines = lambda *a, **k: {
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
            "tags": ["espacio"],
            "requires_uncertainty_note": True,
            "uncertainty_note": "El resultado aún es preliminar.",
        }
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            }
        )
        assert "El resultado aún es preliminar" in result

    def test_override_date_invalid_format(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            },
            override_date="2026-13-99",
        )
        assert "Direct Headline" in result

    def test_image_alt_and_passthrough_fields(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
                "image_url": "https://example.com/i.jpg",
                "image_alt": "Una imagen",
                "featured": True,
                "featured_rank": 1,
                "investigation": False,
                "uncertainty_note": "nota",
            }
        )
        assert "Una imagen" in result
        assert "featured: true" in result

    def test_tag_normalization_failure_falls_back(self, tmp_path):
        agent = self._pipeline_agent(tmp_path)
        with patch(
            "news_collector.taxonomy.normalizer.TagNormalizer",
            side_effect=RuntimeError("normalizer down"),
        ):
            result = agent.process_article(
                {
                    "title": "Demo",
                    "summary": "Resumen",
                    "content": "Contenido " * 200,
                    "url": "https://example.com/source",
                }
            )
        assert "Direct Headline" in result

    def test_send_prompt_stream_dots(self, tmp_path):
        agent = _bare_agent()
        chunks = [f"c{i}" for i in range(45)]
        agent.provider.generate_sync = MagicMock(return_value=iter(chunks))
        result = agent._send_prompt("p", system="s", model="m")
        assert result == "".join(chunks)


class TestConstructorFallbacks:
    def test_init_fallback_config(self):
        with (
            patch(
                "news_collector.components.editorial.ai_editor.load_config",
                side_effect=RuntimeError("config broken"),
            ),
            patch(
                "news_collector.components.editorial.ai_editor.get_provider",
                return_value=MagicMock(),
            ),
            patch(
                "news_collector.components.editorial.ai_editor.resolve_ollama_model_map",
                return_value={
                    "default": MagicMock(model_id="m"),
                    "translator": MagicMock(model_id="m"),
                    "editor": MagicMock(model_id="m"),
                    "headlines": MagicMock(model_id="m"),
                    "enrichment": MagicMock(model_id="m"),
                },
            ),
        ):
            agent = EditorAgent("http://example", "model")
        assert agent.min_content_length == 750

    def test_init_none_config_threshold(self):
        with (
            patch(
                "news_collector.components.editorial.ai_editor.load_config",
                return_value=None,
            ),
            patch(
                "news_collector.components.editorial.ai_editor.get_provider",
                return_value=MagicMock(),
            ),
            patch(
                "news_collector.components.editorial.ai_editor.resolve_ollama_model_map",
                return_value={
                    "default": MagicMock(model_id="m"),
                    "translator": MagicMock(model_id="m"),
                    "editor": MagicMock(model_id="m"),
                    "headlines": MagicMock(model_id="m"),
                    "enrichment": MagicMock(model_id="m"),
                },
            ),
        ):
            agent = EditorAgent("http://example", "model", config=None)
        assert agent.critic_threshold == 70
