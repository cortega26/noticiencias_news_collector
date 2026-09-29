"""Unit tests for the final publication artifact stage (plan 060 Phase 7c-4).

Exercises `run_publication_artifact_stage` without an `EditorAgent`: hooks are
recording/identity callbacks, so the tests pin the frontmatter envelope, the
publication gates and their typed failure codes.
"""

from __future__ import annotations

from datetime import date

import pytest

from news_collector.components.editorial.editorial_publication_artifact import (
    GeneratedArticleValidationError,
    PublicationArtifactHooks,
    PublicationArtifactInput,
    run_publication_artifact_stage,
)

_REQUIRED_ENRICHMENT_FIELDS = (
    "summary_points",
    "glossary",
    "fact_check",
    "why_it_matters",
    "confidence",
    "sources",
)

# Verbatim Codex P1 case from plan 083: a present-tense capability claim.
_CODEX_WHY_IT_MATTERS = (
    "Al aprovechar sensores CGM cada vez más accesibles, GlucoFM permite una "
    "detección temprana y un manejo personalizado de la glucosa, lo que podría "
    "disminuir complicaciones asociadas a la diabetes en la población."
)


def _enrichment() -> dict:
    return {
        "summary_points": ["Punto uno"],
        "glossary": [{"term": "Término", "definition": "Definición"}],
        "fact_check": [{"label": "Afirmación", "status": "confirmed"}],
        "why_it_matters": ["Relevancia regional"],
        "confidence": "Alta — metodología sólida.",
        "sources": [
            {"title": "Fuente", "url": "https://example.com/fuente", "publisher": "Ed"}
        ],
    }


def _normalize_identity(payload: dict) -> dict:
    return payload


def _upsert_identity(
    markdown: str, source_id: str | None, source_name: str | None
) -> str:
    return (
        f"{markdown}\n\n<!-- source_identity: source_id={source_id}; "
        f"source_name={source_name} -->"
    )


def _strip_identity(text: str) -> str:
    return text


def _hooks(
    normalize_frontmatter=_normalize_identity,
    upsert_source_identity=_upsert_identity,
    strip_emojis=_strip_identity,
) -> PublicationArtifactHooks:
    return PublicationArtifactHooks(
        normalize_frontmatter=normalize_frontmatter,
        upsert_source_identity=upsert_source_identity,
        strip_emojis=strip_emojis,
    )


def _input(**overrides) -> PublicationArtifactInput:
    values: dict = {
        "final_content": "## Cuerpo\n\nTexto del artículo.",
        "headlines": {
            "direct": "Título directo",
            "excerpt": "Resumen del artículo listo para SEO.",
            "tags": ["ciencia"],
        },
        "enrichment_fields": _enrichment(),
        "verified_fact_check": [{"label": "Afirmación", "status": "confirmed"}],
        "raw_text": {"id": "article-1"},
        "override_date": "2026-09-26",
        "article_id": "article-1",
        "title": "Título original",
        "final_category": "ciencia",
        "raw_category": "ciencia",
        "metadata_category": None,
        "image_url": "https://example.com/hero.jpg",
        "image_alt": "Descripción",
        "source_id": "source-1",
        "source_name": "Fuente",
        "source_url": "https://example.com/article",
        "required_enrichment_fields": _REQUIRED_ENRICHMENT_FIELDS,
    }
    values.update(overrides)
    return PublicationArtifactInput(**values)


def test_happy_path_builds_frontmatter_and_markdown() -> None:
    result = run_publication_artifact_stage(_input(), _hooks())

    assert result.frontmatter["title"] == "Título directo"
    assert result.frontmatter["schema_version"] == 2
    assert result.frontmatter["date"] == date(2026, 9, 26)
    assert result.frontmatter["categories"] == ["ciencia"]
    assert result.frontmatter["tags"]
    assert result.frontmatter["summary_points"] == ["Punto uno"]
    assert result.frontmatter["requires_uncertainty_note"] is False

    assert result.markdown.startswith("---\n")
    assert "## Cuerpo" in result.markdown
    assert "source_id=source-1" in result.markdown


def test_missing_override_date_refuses_runtime_clock() -> None:
    with pytest.raises(ValueError, match="process_article requires override_date"):
        run_publication_artifact_stage(_input(override_date=None), _hooks())


def test_markdown_goes_through_strip_emojis_hook() -> None:
    result = run_publication_artifact_stage(
        _input(), _hooks(strip_emojis=lambda text: "X" + text)
    )

    assert result.markdown.startswith("X---")


def test_frontmatter_goes_through_normalize_hook() -> None:
    result = run_publication_artifact_stage(
        _input(),
        _hooks(normalize_frontmatter=lambda payload: {**payload, "hooked": True}),
    )

    assert result.frontmatter["hooked"] is True
    assert "hooked: true" in result.markdown


def test_v2_incomplete_blocks_publication() -> None:
    broken = _enrichment()
    broken.pop("sources")

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_publication_artifact_stage(_input(enrichment_fields=broken), _hooks())

    assert excinfo.value.error_code == "editorial_v2_incomplete"


def test_disputed_fact_check_blocks_even_with_upstream_override() -> None:
    data = _input(
        verified_fact_check=[{"label": "Afirmación disputada", "status": "disputed"}],
        raw_text={
            "id": "article-1",
            "fact_check": [{"label": "x", "status": "confirmed"}],
        },
    )

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_publication_artifact_stage(data, _hooks())

    assert excinfo.value.error_code == "editorial_fact_check_disputed"


def test_health_scope_overclaim_blocks_publication() -> None:
    data = _input(
        headlines={
            "direct": "Título",
            "excerpt": "Resumen",
            "tags": [],
            "requires_uncertainty_note": True,
            "uncertainty_note": "El resultado aún es preliminar.",
        },
        enrichment_fields={
            **_enrichment(),
            "why_it_matters": [_CODEX_WHY_IT_MATTERS],
        },
        final_category="Salud",
        raw_category="salud",
    )

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_publication_artifact_stage(data, _hooks())

    assert excinfo.value.error_code == "editorial_capability_overclaim"


def test_tldr_visual_is_stripped_only_without_image() -> None:
    content = (
        "## Cuerpo\n\n**TL;DR Visual** un plano del laboratorio\n\n"
        "**Sección**\n\ntexto final."
    )

    without_image = run_publication_artifact_stage(
        _input(final_content=content, image_url=None), _hooks()
    )
    with_image = run_publication_artifact_stage(_input(final_content=content), _hooks())

    assert "TL;DR Visual" not in without_image.markdown
    assert "TL;DR Visual" in with_image.markdown


def test_upstream_enrichment_overrides_win() -> None:
    data = _input(
        raw_text={"id": "article-1", "why_it_matters": ["Override editorial"]}
    )

    result = run_publication_artifact_stage(data, _hooks())

    assert result.frontmatter["why_it_matters"] == ["Override editorial"]
