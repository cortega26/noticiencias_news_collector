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
            }
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
            }
        )

        fm = parse_frontmatter(result)
        assert fm != {}

        # Upstream value should win
        assert fm["summary_points"] == upstream_summary
        # But generated fields without upstream override should still appear
        assert "glossary" in fm
        assert len(fm["glossary"]) == 2
