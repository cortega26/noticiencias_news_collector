"""Unit tests for the final publication artifact stage (plan 060 Phase 7c-4).

Exercises `run_publication_artifact_stage` without an `EditorAgent`: hooks are
recording/identity callbacks, so the tests pin the frontmatter envelope, the
publication gates and their typed failure codes.
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml

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
        "summary_points": ["Punto uno", "Punto dos"],
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
        "image_origin": None,
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
    assert result.frontmatter["summary_points"] == ["Punto uno", "Punto dos"]
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


def test_image_free_draft_is_not_a_publication_artifact() -> None:
    content = "## Cuerpo\n\n**TL;DR Visual** un plano del laboratorio\n\n**Sección**\n\ntexto final."
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_publication_artifact_stage(
            _input(final_content=content, image_url=None), _hooks()
        )
    assert excinfo.value.error_code == "image_required"
    with_image = run_publication_artifact_stage(_input(final_content=content), _hooks())
    assert "TL;DR Visual" in with_image.markdown


def test_upstream_enrichment_overrides_win() -> None:
    data = _input(
        raw_text={"id": "article-1", "why_it_matters": ["Override editorial"]}
    )

    result = run_publication_artifact_stage(data, _hooks())

    assert result.frontmatter["why_it_matters"] == ["Override editorial"]


def test_ai_generated_alt_gets_the_visible_caption_prefix() -> None:
    """Plan 169: the frontend renders image_alt as the <figcaption>."""
    result = run_publication_artifact_stage(
        _input(image_origin="ai_generated"), _hooks()
    )

    assert result.frontmatter["image_alt"] == (
        "Ilustración generada con IA: Descripción"
    )
    # Disclosure lives in the caption only — never repeated in the prose.
    assert "Ilustración generada con IA" not in result.markdown.split("---", 2)[2]


def test_ai_generated_alt_prefix_is_idempotent() -> None:
    result = run_publication_artifact_stage(
        _input(
            image_alt="Ilustración generada con IA: Descripción",
            image_origin="ai_generated",
        ),
        _hooks(),
    )

    assert result.frontmatter["image_alt"] == (
        "Ilustración generada con IA: Descripción"
    )
    assert result.markdown.count("Ilustración generada con IA:") == 1


def test_ai_generated_alt_prefix_detection_is_case_insensitive() -> None:
    result = run_publication_artifact_stage(
        _input(
            image_alt="ilustración generada con IA: Descripción",
            image_origin="ai_generated",
        ),
        _hooks(),
    )

    assert (
        result.frontmatter["image_alt"].casefold().count("ilustración generada con ia:")
        == 1
    )


@pytest.mark.parametrize("origin", ["licensed", "original", "unknown", None])
def test_non_ai_origins_leave_the_alt_untouched(origin: str | None) -> None:
    result = run_publication_artifact_stage(_input(image_origin=origin), _hooks())

    assert result.frontmatter["image_alt"] == "Descripción"
    assert "Ilustración generada con IA" not in result.markdown


def test_ai_alt_with_colons_serializes_as_valid_quoted_yaml() -> None:
    """Regression for #312: an unquoted ``: `` breaks the frontmatter."""
    result = run_publication_artifact_stage(
        _input(image_origin="ai_generated"), _hooks()
    )

    frontmatter_block = result.markdown.split("---", 2)[1]
    parsed = yaml.safe_load(frontmatter_block)

    assert parsed["image_alt"] == "Ilustración generada con IA: Descripción"
    assert "image_alt: 'Ilustración generada con IA: Descripción'" in result.markdown


def test_preparation_without_media_preserves_editorial_work_and_identity() -> None:
    from news_collector.components.editorial.editorial_publication_artifact import (
        prepare_editorial_draft,
    )

    draft = prepare_editorial_draft(
        _input(image_url=None, image_alt=None),
        _hooks(),
        critic_verdict={"approved": True, "average": 87},
        grounding_notes="Verified against source text.",
    )

    assert draft.frontmatter["title"] == "Título directo"
    assert "image" not in draft.frontmatter
    assert "image_alt" not in draft.frontmatter
    assert draft.article_id == "article-1"
    assert draft.source_id == "source-1"
    assert draft.critic_verdict == {"approved": True, "average": 87}
    assert draft.grounding_notes == "Verified against source text."
    assert "source_id=source-1" in draft.preview_markdown


def test_image_free_preparation_rejects_disputed_fact_check() -> None:
    from news_collector.components.editorial.editorial_publication_artifact import (
        prepare_editorial_draft,
    )

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        prepare_editorial_draft(
            _input(
                image_url=None,
                verified_fact_check=[{"label": "Dato falso", "status": "disputed"}],
            ),
            _hooks(),
        )
    assert excinfo.value.error_code == "editorial_fact_check_disputed"


def test_preparation_rejects_invalid_editorial_schema_without_placeholder_media() -> (
    None
):
    from news_collector.components.editorial.editorial_publication_artifact import (
        prepare_editorial_draft,
    )

    with pytest.raises(ValueError, match="summary_points must have 2-5"):
        prepare_editorial_draft(
            _input(
                image_url=None,
                enrichment_fields={**_enrichment(), "summary_points": ["Solo uno"]},
            ),
            _hooks(),
        )


def test_saved_draft_assembles_with_ai_disclosure_once_without_editorial_work() -> None:
    from news_collector.components.editorial.editorial_publication_artifact import (
        assemble_editorial_draft,
        prepare_editorial_draft,
    )
    from news_collector.contracts.editorial_draft import EditorialDraft
    from news_collector.contracts.frontend_schema import AstroPost

    draft = prepare_editorial_draft(_input(image_url=None), _hooks())
    replayed = EditorialDraft.model_validate_json(draft.model_dump_json())
    artifact = assemble_editorial_draft(
        replayed,
        image_url="/images/generated-roots.webp",
        image_alt="Raíces e hifas en el suelo",
        image_origin="ai_generated",
        hooks=_hooks(),
    )

    parsed = yaml.safe_load(artifact.markdown.split("---", 2)[1])
    post = AstroPost.model_validate(parsed)
    assert post.image == "/images/generated-roots.webp"
    assert post.image_alt == "Ilustración generada con IA: Raíces e hifas en el suelo"
    assert artifact.markdown.count("Ilustración generada con IA:") == 1
    assert artifact.markdown.count("source_id=source-1") == 1
    assert "image" not in replayed.frontmatter


def test_assembly_rejects_missing_image_but_preserves_saved_draft() -> None:
    from news_collector.components.editorial.editorial_publication_artifact import (
        assemble_editorial_draft,
        prepare_editorial_draft,
    )

    draft = prepare_editorial_draft(_input(image_url=None), _hooks())
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        assemble_editorial_draft(
            draft,
            image_url="",
            image_alt="Raíces",
            image_origin="ai_generated",
            hooks=_hooks(),
        )
    assert excinfo.value.error_code == "image_required"
    assert draft.frontmatter["title"] == "Título directo"


def test_assembly_validates_metadata_after_emoji_stripping() -> None:
    from news_collector.components.editorial.editorial_publication_artifact import (
        assemble_editorial_draft,
        prepare_editorial_draft,
    )

    draft = prepare_editorial_draft(
        _input(
            headlines={
                "direct": "🌱🌱🌱🌱🌱",
                "excerpt": "Descripción suficientemente larga",
            }
        ),
        _hooks(),
    )
    with pytest.raises(ValueError, match="Content Contract Violation"):
        assemble_editorial_draft(
            draft,
            image_url="/images/roots.webp",
            image_alt="Raíces e hifas",
            image_origin="ai_generated",
            hooks=_hooks(strip_emojis=lambda text: text.replace("🌱", "")),
        )
