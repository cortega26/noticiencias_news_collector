"""Unit tests for EditorAgent content rules."""

from __future__ import annotations

import sys
from pathlib import Path


from news_collector.components.editorial.ai_editor import EditorAgent  # noqa: E402


def test_process_article_strips_tldr_without_image_and_adds_source() -> None:
    agent = EditorAgent("http://example", "model")
    sample_output = (
        "---\n"
        "title: Demo\n"
        "author: AI\n"
        "date: 2026-01-01\n"
        "---\n\n"
        "**TL;DR Visual**\n"
        "- ⚡ Punto uno\n\n"
        "**El Impacto (Lead)**\n"
        "Texto base.\n"
    )
    agent._send_prompt = lambda prompt, system=None: sample_output  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido",
            "image_url": None,
            "url": "https://example.com/source",
        }
    )

    assert "TL;DR Visual" not in result
    assert "⚡" not in result
    assert 'source_url: "https://example.com/source"' in result
    assert "Fuente original: [https://example.com/source]" in result


def test_process_article_keeps_sections_with_image() -> None:
    agent = EditorAgent("http://example", "model")
    sample_output = (
        "---\n"
        "title: Demo\n"
        "author: AI\n"
        "date: 2026-01-01\n"
        "---\n\n"
        "**TL;DR Visual**\n"
        "- Punto uno\n\n"
        "**El Impacto (Lead)**\n"
        "Texto base.\n"
    )
    agent._send_prompt = lambda prompt, *args, **kwargs: sample_output  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido",
            "image_url": "https://example.com/image.jpg",
            "url": "https://example.com/source",
        }
    )

    assert "TL;DR Visual" in result
    assert 'source_url: "https://example.com/source"' in result
    assert "Fuente original: [https://example.com/source]" in result
