from __future__ import annotations

from unittest.mock import MagicMock, patch

from news_collector.components.editorial.ai_editor import EditorAgent


def _valid_markdown_body() -> str:
    return (
        "## El impacto\n\n"
        "Investigadores latinoamericanos presentaron un análisis detallado sobre un nuevo hallazgo científico "
        "con implicancias para salud pública y monitoreo ambiental. El trabajo describe metodología, resultados "
        "y contexto suficiente para sostener una cobertura periodística rigurosa. Además, compara datos previos, "
        "explica limitaciones y detalla por qué el hallazgo importa fuera del laboratorio. La nota cierra con "
        "consecuencias concretas para lectores de América Latina, incluyendo prevención, infraestructura y toma "
        "de decisiones basada en evidencia. Los autores aportan cifras, observaciones verificables y un marco "
        "de interpretación prudente que evita el sensacionalismo y ayuda a comprender el avance con claridad.\n"
    )


def test_critic_no_text_response_is_forced_recoverable(tmp_path) -> None:
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(agent, "_send_prompt") as mock_send:
        mock_send.return_value = (
            '{"score": 0, "reason": "No text provided", "recoverable": false}'
        )

        is_valid, reason, recoverable = agent._critic_pass("")

    assert is_valid is False
    assert reason == "No text provided"
    assert recoverable is True


def test_process_article_recovers_when_editorial_stage_is_empty(tmp_path) -> None:
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)
    agent.min_content_length = 0
    agent.category_resolver._classifier = MagicMock(
        try_classify_article=MagicMock(return_value=None)
    )

    agent._translate_scientific = lambda content: "Texto base traducido"  # type: ignore[method-assign]
    agent._adapt_editorial = lambda *args, **kwargs: ""  # type: ignore[method-assign]
    repair_mock = MagicMock(return_value=_valid_markdown_body())
    agent._repair_editorial = repair_mock  # type: ignore[method-assign]
    # Editorial critic gate is an independent stage; bypass it here so the
    # test stays focused on the technical critic recovery path.
    agent._critic_editorial_pass = lambda *args, **kwargs: (True, None, True)  # type: ignore[method-assign]
    agent._headline_critic_pass = lambda *args, **kwargs: (True, None)  # type: ignore[method-assign]
    agent._generate_enrichment_fields = MagicMock(
        return_value={
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
    )  # type: ignore[method-assign]
    # Stub only the Phase 2c network seam (dedicated Ollama call) so the
    # real _verify_fact_check_claims loop/overwrite/gate logic still runs,
    # without hitting a real Ollama instance in this unit test.
    agent._send_fact_check_prompt = MagicMock(  # type: ignore[method-assign]
        return_value={"status": "confirmed"}
    )
    agent._generate_headlines = lambda *args: {  # type: ignore[method-assign]
        "direct": "Hallazgo con impacto regional",
        "question": "¿Qué cambia con este hallazgo?",
        "benefit": "Lo que importa para América Latina",
        "excerpt": "Resumen suficientemente largo para validar el frontmatter y el SEO.",
        "tags": ["salud pública", "clima"],
    }

    with patch.object(agent, "_critic_pass") as mock_critic:
        mock_critic.return_value = (True, None, True)

        result = agent.process_article(
            {
                "id": "empty-stage-two",
                "title": "Nuevo estudio regional",
                "summary": "Resumen científico",
                "content": "Contenido base " * 100,
                "url": "https://example.com/article",
            },
            override_date="2026-03-02",
        )

    assert "Hallazgo con impacto regional" in result
    assert "No text provided" not in result
    repair_mock.assert_called_once()
    assert mock_critic.call_count == 1
