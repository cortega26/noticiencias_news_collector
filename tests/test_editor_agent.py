"""Unit tests for EditorAgent content rules."""

from __future__ import annotations

import re

import yaml
from news_collector.components.editorial.ai_editor import EditorAgent  # noqa: E402


def parse_frontmatter(content: str) -> dict:
    match = re.search(r"---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    return yaml.safe_load(match.group(1))


def test_process_article_strips_tldr_without_image_and_adds_source() -> None:
    agent = EditorAgent("http://example", "model")
    sample_output = (
        "**TL;DR Visual**\n"
        "- ⚡ Punto uno\n\n"
        "**El Impacto (Lead)**\n"
        "Texto base.\n"
    )
    agent._send_prompt = lambda prompt, system=None, **kwargs: sample_output  # type: ignore[method-assign]
    agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
    agent._generate_headlines = lambda *args: {
        "direct": "Direct Headline",
        "question": "Question Headline?",
        "benefit": "Benefit Headline",
        "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
    }  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "image_url": None,
            "url": "https://example.com/source",
        }
    )

    assert "TL;DR Visual" not in result
    assert "⚡" not in result

    fm = parse_frontmatter(result)
    fm = parse_frontmatter(result)
    assert (
        fm.get("source_url") == "https://example.com/source"
    ), f"Keys: {fm.keys()} \nYAML: {result[:300]}"

    # Check footer logic generally
    assert "https://example.com/source" in result and "Fuente" in result


def test_process_article_keeps_sections_with_image() -> None:
    agent = EditorAgent("http://example", "model")
    sample_output = (
        "**TL;DR Visual**\n" "- Punto uno\n\n" "**El Impacto (Lead)**\n" "Texto base.\n"
    )
    agent._send_prompt = lambda prompt, *args, **kwargs: sample_output  # type: ignore[method-assign]
    agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
    agent._generate_headlines = lambda *args: {
        "direct": "Direct Headline",
        "question": "Question Headline?",
        "benefit": "Benefit Headline",
        "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
    }  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "image_url": "https://example.com/image.jpg",
            "url": "https://example.com/source",
        }
    )

    assert "TL;DR Visual" in result

    fm = parse_frontmatter(result)
    assert fm.get("source_url") == "https://example.com/source"

    assert "https://example.com/source" in result and "Fuente" in result


def test_frontmatter_date_is_emitted_as_unquoted_yaml_date(tmp_path) -> None:
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)
    sample_output = "**El Impacto (Lead)**\nTexto base.\n"
    agent._send_prompt = lambda prompt, *args, **kwargs: sample_output  # type: ignore[method-assign]
    agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
    agent._generate_headlines = lambda *args: {
        "direct": "Direct Headline",
        "question": "Question Headline?",
        "benefit": "Benefit Headline",
        "excerpt": "This excerpt is long enough for metadata validation.",
    }  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "id": "1087",
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "image_url": "https://example.com/image.jpg",
            "url": "https://example.com/source",
        },
        override_date="2026-03-02",
    )

    assert "\ndate: 2026-03-02\n" in result
    assert "date: '2026-03-02'" not in result
    assert 'date: "2026-03-02"' not in result


def test_frontmatter_datetime_remains_datetime_token(tmp_path) -> None:
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)
    sample_output = "**El Impacto (Lead)**\nTexto base.\n"
    agent._send_prompt = lambda prompt, *args, **kwargs: sample_output  # type: ignore[method-assign]
    agent._critic_pass = lambda *args: (True, None)  # type: ignore[method-assign]
    agent._generate_headlines = lambda *args: {
        "direct": "Direct Headline",
        "question": "Question Headline?",
        "benefit": "Benefit Headline",
        "excerpt": "This excerpt is long enough for metadata validation.",
    }  # type: ignore[method-assign]

    result = agent.process_article(
        {
            "id": "1087",
            "title": "Demo",
            "summary": "Resumen",
            "content": "Contenido " * 200,
            "image_url": "https://example.com/image.jpg",
            "url": "https://example.com/source",
        },
        override_date="2026-03-02T15:30:00+00:00",
    )

    assert "date: '2026-03-02T15:30:00+00:00'" not in result
    assert 'date: "2026-03-02T15:30:00+00:00"' not in result
    assert re.search(r"\ndate: 2026-03-02\s+15:30:00\+00:00\n", result)
