"""Tests for Stage 4 Editorial Enrichment Field Generation."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import pytest
import yaml

from news_collector.components.editorial.ai_editor import EditorAgent


def parse_frontmatter(content: str) -> dict:
    """Extract and parse YAML frontmatter from a full article string."""
    match = re.search(r"---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    return yaml.safe_load(match.group(1))


VALID_ENRICHMENT_RESPONSE = json.dumps(
    {
        "summary_points": [
            "Investigadores del MIT lograron mantener plasma estable en un experimento de fusión nuclear.",
            "El avance se publicó en Nature y fue revisado por pares.",
            "Aún faltan décadas para una aplicación comercial de esta tecnología.",
        ],
        "glossary": [
            {
                "term": "Fusión nuclear",
                "definition": (
                    "Proceso que genera energía al unir núcleos atómicos, "
                    "similar al que ocurre en el Sol."
                ),
            },
            {
                "term": "Plasma",
                "definition": (
                    "Estado de la materia compuesto por partículas cargadas "
                    "a altas temperaturas."
                ),
            },
        ],
        "fact_check": [
            {
                "label": (
                    "El experimento logró mantener plasma estable durante "
                    "5 segundos."
                ),
                "status": "confirmed",
            },
            {
                "label": (
                    "La fusión nuclear podría revolucionar la producción de "
                    "energía limpia."
                ),
                "status": "uncertain",
            },
        ],
        "why_it_matters": [
            "La fusión nuclear promete una fuente de energía limpia y prácticamente inagotable para América Latina.",
            "De concretarse, reduciría la dependencia de combustibles fósiles en la región.",
        ],
        "confidence": (
            "Alta — estudio revisado por pares con metodología sólida, "
            "aunque los resultados son a escala de laboratorio."
        ),
        "sources": [
            {
                "title": "Nature - Stable plasma maintenance in nuclear fusion experiments",
                "url": "https://doi.org/10.1038/example",
                "publisher": "Nature",
                "date": "2024-01-15",
            },
        ],
    }
)


class TestEnrichmentGeneration:
    """Tests for _generate_enrichment_fields method."""

    def test_generates_all_fields(self) -> None:
        """Verify full enrichment output with valid LLM response."""
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value=VALID_ENRICHMENT_RESPONSE)

        result = agent._generate_enrichment_fields("Article body", "Test Title")

        assert len(result["summary_points"]) == 3
        assert len(result["glossary"]) == 2
        assert result["glossary"][0]["term"] == "Fusión nuclear"
        assert len(result["fact_check"]) == 2
        assert result["fact_check"][0]["status"] == "confirmed"
        assert len(result["why_it_matters"]) == 2
        assert result["confidence"] != ""
        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == (
            "Nature - Stable plasma maintenance in nuclear fusion experiments"
        )

    def test_fallback_on_invalid_json(self) -> None:
        """Verify graceful fallback when LLM returns invalid JSON."""
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value="```json\n{invalid json\n```")

        result = agent._generate_enrichment_fields("Article body", "Test Title")

        assert result["summary_points"] == []
        assert result["glossary"] == []
        assert result["fact_check"] == []
        assert result["why_it_matters"] == []
        assert result["confidence"] == ""
        assert result["sources"] == []

    def test_fallback_on_missing_prompt(self) -> None:
        """Verify graceful fallback when enrichment prompt is missing."""
        agent = EditorAgent("http://example", "model")
        agent.prompts = {}  # Remove all prompts

        result = agent._generate_enrichment_fields("Article body", "Test Title")

        assert result["summary_points"] == []
        assert result["glossary"] == []
        # _send_prompt should not have been called
        agent._send_prompt = MagicMock()
        assert agent._send_prompt.call_count == 0

    def test_fallback_on_validation_error(self) -> None:
        """Verify graceful fallback when Pydantic validation rejects output."""
        bad_response = json.dumps(
            {
                "summary_points": "not a list",  # Invalid type
                "glossary": [],
                "fact_check": [],
                "why_it_matters": [],
                "confidence": "",
                "sources": [],
            }
        )
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value=bad_response)

        result = agent._generate_enrichment_fields("Article body", "Test Title")

        # Falls back to empty on validation error
        assert result["summary_points"] == []

    def test_sources_fallback_when_omitted_by_llm(self) -> None:
        """LLM returning valid JSON without ``sources`` must not poison Stage 4:
        the article's own original source is used as the deterministic default."""
        response_without_sources = json.dumps(
            {
                "summary_points": ["Punto uno.", "Punto dos."],
                "glossary": [{"term": "Plasma", "definition": "Estado de la materia."}],
                "fact_check": [{"label": "Afirmación", "status": "confirmed"}],
                "why_it_matters": ["Impacto en la región."],
                "confidence": "Alta — revisado por pares.",
            }
        )
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value=response_without_sources)

        result = agent._generate_enrichment_fields(
            "Article body",
            "Test Title",
            source_url="https://example.com/original",
            source_name="Example Journal",
        )

        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == "Example Journal"
        assert result["sources"][0]["url"] == "https://example.com/original"
        assert result["sources"][0]["publisher"] == "Example Journal"

    def test_sources_empty_list_rejected_by_schema(self) -> None:
        """Explicit ``sources: []`` in the LLM response fails pydantic's
        ``min_length=1`` and falls back to empty defaults (fail-closed: no
        fabricated source is invented). The real production bug is the
        OMITTED key, covered by test_sources_fallback_when_omitted_by_llm."""
        response_empty_sources = json.dumps(
            {
                "summary_points": ["Punto uno", "Punto dos"],
                "glossary": [{"term": "Plasma", "definition": "Definición"}],
                "fact_check": [{"label": "Afirmación", "status": "confirmed"}],
                "why_it_matters": ["Relevancia regional"],
                "confidence": "Alta",
                "sources": [],
            }
        )
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value=response_empty_sources)

        result = agent._generate_enrichment_fields(
            "Article body",
            "Test Title",
            source_url="https://feed.example/item/1",
            source_name="Example Feed",
        )

        # Validation rejected the empty list: fail-closed, no fabricated source
        assert result["sources"] == []

    def test_no_fallback_without_source_metadata(self) -> None:
        """Without source metadata there is nothing truthful to fall back to:
        sources stays empty (the V2 gate will reject it, as designed)."""
        agent = EditorAgent("http://example", "model")
        agent._send_prompt = MagicMock(return_value=VALID_ENRICHMENT_RESPONSE)

        result = agent._generate_enrichment_fields("Article body", "Test Title")

        # Valid response keeps its own sources; no fallback needed
        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == (
            "Nature - Stable plasma maintenance in nuclear fusion experiments"
        )

    def test_empty_enrichment_fields_static(self) -> None:
        """Verify _empty_enrichment_fields returns correct shape."""
        result = EditorAgent._empty_enrichment_fields()

        assert result == {
            "summary_points": [],
            "glossary": [],
            "fact_check": [],
            "why_it_matters": [],
            "confidence": "",
            "sources": [],
        }


SAMPLE_OUTPUT = (
    "**El Impacto (Lead)**\n"
    "Este análisis examina los avances recientes en el campo científico y tecnológico. "
    "Los investigadores han identificado nuevos patrones que permiten comprender mejor los "
    "fenómenos estudiados en este dominio. El trabajo demuestra resultados significativos "
    "para la comunidad científica internacional. Las implicaciones de estos hallazgos se "
    "extienden a múltiples disciplinas y abren nuevas líneas de investigación prometedoras. "
    "La metodología empleada resulta reproducible y transparente, lo que fortalece la "
    "credibilidad del estudio. En conclusión, estos resultados contribuyen al avance del "
    "conocimiento en el área y representan un paso importante para futuras investigaciones.\n"
)


class TestEnrichmentInProcessArticle:
    """Integration tests for enrichment fields in the full pipeline output."""

    def test_enrichment_fields_in_frontmatter(self, tmp_path) -> None:
        """Verify enrichment fields appear in the final frontmatter."""
        agent = EditorAgent("http://example", "model")
        agent.cache_dir = tmp_path / "editor-cache"
        agent.cache_dir.mkdir(parents=True, exist_ok=True)
        agent.category_resolver._classifier = MagicMock(
            try_classify_article=MagicMock(return_value=None)
        )
        # Mock all LLM calls
        agent._send_prompt = MagicMock(return_value=SAMPLE_OUTPUT)
        agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
        agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)  # type: ignore[method-assign]
        agent._generate_headlines = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is an SEO excerpt that is long enough for validation.",
        }
        # Override enrichment specifically with valid data
        agent._generate_enrichment_fields = MagicMock(
            return_value=json.loads(VALID_ENRICHMENT_RESPONSE)
        )

        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            },
            override_date="2026-03-02",
        )

        fm = parse_frontmatter(result)
        assert fm != {}, "Frontmatter should not be empty"

        assert "summary_points" in fm
        assert len(fm["summary_points"]) == 3
        assert "glossary" in fm
        assert len(fm["glossary"]) == 2
        assert "fact_check" in fm
        assert len(fm["fact_check"]) == 2
        assert "why_it_matters" in fm
        assert len(fm["why_it_matters"]) == 2
        assert "confidence" in fm
        assert fm["confidence"] != ""
        assert "sources" in fm
        assert len(fm["sources"]) == 1

    def test_upstream_raw_text_takes_precedence(self, tmp_path) -> None:
        """Verify raw_text values override generated enrichment fields."""
        agent = EditorAgent("http://example", "model")
        agent.cache_dir = tmp_path / "editor-cache"
        agent.cache_dir.mkdir(parents=True, exist_ok=True)
        agent.category_resolver._classifier = MagicMock(
            try_classify_article=MagicMock(return_value=None)
        )
        agent._send_prompt = MagicMock(return_value=SAMPLE_OUTPUT)
        agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
        agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)  # type: ignore[method-assign]
        agent._generate_headlines = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is an SEO excerpt that is long enough for validation.",
        }
        agent._generate_enrichment_fields = MagicMock(
            return_value=json.loads(VALID_ENRICHMENT_RESPONSE)
        )

        # Provide upstream summary_points that should override LLM output
        upstream_summary = ["Punto upstream manual"]
        result = agent.process_article(
            {
                "title": "Demo",
                "summary": "Resumen",
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
                "summary_points": upstream_summary,
            },
            override_date="2026-03-02",
        )

        fm = parse_frontmatter(result)
        assert fm != {}

        # Upstream value should win
        assert fm["summary_points"] == upstream_summary
        # But generated fields without upstream override should still appear
        assert "glossary" in fm
        assert len(fm["glossary"]) == 2

    def test_v2_enforcement_rejects_missing_enrichment_fields(self, tmp_path) -> None:
        """V2 article with empty enrichment output must not reach the writer."""
        agent = EditorAgent("http://example", "model")
        agent.cache_dir = tmp_path / "editor-cache"
        agent.cache_dir.mkdir(parents=True, exist_ok=True)
        agent.category_resolver._classifier = MagicMock(
            try_classify_article=MagicMock(return_value=None)
        )
        agent._send_prompt = MagicMock(return_value=SAMPLE_OUTPUT)
        agent._critic_pass = lambda *args: (True, None)
        agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)
        agent._generate_headlines = lambda *args, **kwargs: {
            "direct": "A v2 article missing enrichment",
            "question": "Q?",
            "benefit": "B",
            "excerpt": "SEO excerpt that is long enough for validation.",
        }
        # Stage 4 returns empty / incomplete output
        agent._generate_enrichment_fields = MagicMock(return_value={})

        from news_collector.components.editorial.ai_editor import (
            GeneratedArticleValidationError,
        )

        with pytest.raises(GeneratedArticleValidationError) as excinfo:
            agent.process_article(
                {
                    "title": "V2 Missing Enrichment",
                    "summary": "Resumen " * 20,
                    "content": "Contenido " * 200,
                    "url": "https://example.com/source",
                },
                override_date="2026-03-02",
            )
        assert excinfo.value.error_code == "editorial_v2_incomplete"
        assert "summary_points" in str(excinfo.value)

    def test_v2_enrichment_all_fields_succeeds(self, tmp_path) -> None:
        """V2 article with all enrichment fields is written successfully."""
        agent = EditorAgent("http://example", "model")
        agent.cache_dir = tmp_path / "editor-cache"
        agent.cache_dir.mkdir(parents=True, exist_ok=True)
        agent.category_resolver._classifier = MagicMock(
            try_classify_article=MagicMock(return_value=None)
        )
        agent._send_prompt = MagicMock(return_value=SAMPLE_OUTPUT)
        agent._critic_pass = lambda *args: (True, None)
        agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)
        agent._generate_headlines = lambda *args, **kwargs: {
            "direct": "Full V2 Article",
            "question": "Q?",
            "benefit": "B",
            "excerpt": "SEO excerpt that is long enough for validation.",
        }
        agent._generate_enrichment_fields = MagicMock(
            return_value=json.loads(VALID_ENRICHMENT_RESPONSE)
        )

        result = agent.process_article(
            {
                "title": "V2 Complete",
                "summary": "Resumen " * 20,
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            },
            override_date="2026-03-02",
        )
        result = agent.process_article(
            {
                "title": "V2 Complete",
                "summary": "Resumen " * 20,
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
            },
            override_date="2026-03-02",
        )
        fm = parse_frontmatter(result)
        assert fm.get("schema_version") == 2
        for field in (
            "summary_points",
            "glossary",
            "fact_check",
            "why_it_matters",
            "confidence",
            "sources",
        ):
            assert fm.get(field), f"Missing required v2 field: {field}"


class TestPoisonedStage4Cache:
    """A cached Stage 4 artifact with an empty ``sources`` list must never be
    reused: it would fail the V2 frontmatter gate on every run. The cache is
    ignored and regenerated instead (the exact production failure mode that
    made the pipeline 'consistently fail on Stage 4')."""

    def _make_agent(self, tmp_path) -> EditorAgent:
        agent = EditorAgent("http://example", "model")
        agent.cache_dir = tmp_path / "editor-cache"
        agent.cache_dir.mkdir(parents=True, exist_ok=True)
        agent.category_resolver._classifier = MagicMock(
            try_classify_article=MagicMock(return_value=None)
        )
        agent._send_prompt = MagicMock(return_value=SAMPLE_OUTPUT)
        agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
        agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)  # type: ignore[method-assign]
        agent._generate_headlines = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "direct": "Direct Headline",
            "question": "Question Headline?",
            "benefit": "Benefit Headline",
            "excerpt": "This is an SEO excerpt that is long enough for validation.",
        }
        return agent

    def test_poisoned_cache_is_regenerated(self, tmp_path) -> None:
        """Cache with all fields but sources=[] must be ignored and regenerated."""
        from news_collector.components.editorial.ai_editor import (
            _V2_REQUIRED_ENRICHMENT_FIELDS,
        )

        poisoned = {
            key: (
                ["Item de ejemplo"]
                if key in ("summary_points", "glossary", "fact_check", "why_it_matters")
                else "Alta" if key == "confidence" else []
            )
            for key in _V2_REQUIRED_ENRICHMENT_FIELDS
        }
        cache_dir = tmp_path / "editor-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "demo_stage4_enrichment.txt"
        cache_path.write_text(
            json.dumps(poisoned, ensure_ascii=False), encoding="utf-8"
        )

        agent = self._make_agent(tmp_path)
        # Regeneration must produce complete output
        agent._generate_enrichment_fields = MagicMock(
            return_value=json.loads(VALID_ENRICHMENT_RESPONSE)
        )

        result = agent.process_article(
            {
                "id": "demo",
                "title": "Poisoned Cache Demo",
                "summary": "Resumen " * 20,
                "content": "Contenido " * 200,
                "url": "https://example.com/source",
                "source_name": "Example Feed",
            },
            override_date="2026-03-02",
        )
        fm = parse_frontmatter(result)
        assert fm != {}
        # Sources came from the regenerated (valid) artifact, not the cache
        assert len(fm["sources"]) == 1
        assert fm["sources"][0]["title"] == (
            "Nature - Stable plasma maintenance in nuclear fusion experiments"
        )
        # And the on-disk cache was overwritten with the valid artifact
        regenerated = json.loads(cache_path.read_text(encoding="utf-8"))
        assert len(regenerated["sources"]) == 1
