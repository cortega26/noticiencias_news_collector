from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from loguru import logger

from news_collector.editorial.categories import (
    ContentSignalMatch,
    detect_content_category,
    match_content_signals,
)
from news_collector.editorial.category_resolver import EditorialCategoryResolver

NEANDERTHAL_TITLE = "Un neandertal sobrevivió a una herida de lanza hace 100.000 años"
NEANDERTHAL_SUMMARY = (
    "El hallazgo en un yacimiento de Irak reescribe la prehistoria: "
    "los restos óseos muestran una lesión infligida por otro humano."
)
OPENAI_TITLE = "OpenAI lanza un nuevo modelo de lenguaje"
OPENAI_SUMMARY = "La plataforma de software promete mejoras en IA empresarial."
FOSSIL_TITLE = "Fossil fuels still dominate the grid"
FOSSIL_SUMMARY = (
    "Los combustibles fósiles siguen siendo la principal fuente de energía."
)


@pytest.fixture
def loguru_records() -> Iterator[list[str]]:
    """Capture loguru messages, since caplog only observes stdlib logging."""
    records: list[str] = []

    def _sink(message) -> None:
        records.append(message.record["message"])

    sink_id = logger.add(_sink)
    try:
        yield records
    finally:
        logger.remove(sink_id)


def test_detect_content_category_matches_two_signal_groups() -> None:
    assert (
        detect_content_category(
            title=NEANDERTHAL_TITLE,
            summary=NEANDERTHAL_SUMMARY,
        )
        == "ARQUEOLOGÍA"
    )


def test_detect_content_category_folds_case_and_accents() -> None:
    assert (
        detect_content_category(
            title="NEANDERTAL",
            summary="Hallazgo en un YACIMIENTO del Paleolítico.",
        )
        == "ARQUEOLOGÍA"
    )


def test_detect_content_category_ignores_fossil_fuels() -> None:
    assert detect_content_category(title=FOSSIL_TITLE, summary=FOSSIL_SUMMARY) is None


def test_detect_content_category_ignores_single_strong_group() -> None:
    assert (
        detect_content_category(
            title="Un neandertal protagoniza un videojuego de estrategia",
            summary="La aventura se ambienta en un mundo de fantasía.",
            content="Contenido sobre lanzamiento y plataformas.",
        )
        is None
    )


def test_match_content_signals_reports_groups_and_terms() -> None:
    match = match_content_signals(
        title=NEANDERTHAL_TITLE,
        summary=NEANDERTHAL_SUMMARY,
    )

    assert isinstance(match, ContentSignalMatch)
    assert match.category == "ARQUEOLOGÍA"
    assert set(match.groups) == {"strong", "supporting"}
    assert "neandertal" in match.signals
    assert "yacimiento" in match.signals


@pytest.mark.parametrize(
    (
        "raw_category",
        "metadata_category",
        "title",
        "summary",
        "expected_category",
        "expected_method",
    ),
    [
        (
            "technology",
            None,
            NEANDERTHAL_TITLE,
            NEANDERTHAL_SUMMARY,
            "Arqueología",
            "content_override",
        ),
        (
            "tech",
            None,
            NEANDERTHAL_TITLE,
            NEANDERTHAL_SUMMARY,
            "Arqueología",
            "content_override",
        ),
        (
            None,
            "technology",
            NEANDERTHAL_TITLE,
            NEANDERTHAL_SUMMARY,
            "Arqueología",
            "content_override",
        ),
        (
            "technology",
            None,
            OPENAI_TITLE,
            OPENAI_SUMMARY,
            "Tecnología",
            "direct_map",
        ),
        (
            "technology",
            None,
            FOSSIL_TITLE,
            FOSSIL_SUMMARY,
            "Tecnología",
            "direct_map",
        ),
        (
            "software",
            None,
            NEANDERTHAL_TITLE,
            NEANDERTHAL_SUMMARY,
            "Tecnología",
            "direct_map",
        ),
        (
            "archaeology",
            None,
            NEANDERTHAL_TITLE,
            NEANDERTHAL_SUMMARY,
            "Arqueología",
            "direct_map",
        ),
    ],
    ids=[
        "technology-source-archaeology-content",
        "tech-source-archaeology-content",
        "metadata-technology-archaeology-content",
        "technology-source-tech-content",
        "technology-source-fossil-fuels",
        "specific-source-category-untouched",
        "archaeology-source-unchanged",
    ],
)
def test_resolver_category_matrix(
    raw_category: str | None,
    metadata_category: str | None,
    title: str,
    summary: str,
    expected_category: str,
    expected_method: str,
) -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="matrix-article",
        title=title,
        summary=summary,
        raw_category=raw_category,
        metadata_category=metadata_category,
    )

    assert resolution.public_category == expected_category
    assert resolution.resolution_method == expected_method
    classifier.try_classify_article.assert_not_called()


def test_generic_source_keeps_classifier_fallback() -> None:
    classifier = MagicMock()
    classifier.try_classify_article.return_value = "ARQUEOLOGÍA"
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="generic-archaeology",
        title=NEANDERTHAL_TITLE,
        summary=NEANDERTHAL_SUMMARY,
        raw_category="science",
        metadata_category=None,
    )

    assert resolution.public_category == "Arqueología"
    assert resolution.resolution_method == "classifier"
    classifier.try_classify_article.assert_called_once()


def test_first_party_editorial_source_is_not_overridden() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="first-party-tech-label",
        title=NEANDERTHAL_TITLE,
        summary=NEANDERTHAL_SUMMARY,
        raw_category="technology",
        metadata_category=None,
        source_url="https://noticiencias.com/categorias/tecnologia",
        source_name="Noticiencias",
        source_id="noticiencias",
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_content_override_logs_signals_without_article_content(
    loguru_records: list[str],
) -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="3724",
        title=NEANDERTHAL_TITLE,
        summary=NEANDERTHAL_SUMMARY,
        raw_category="technology",
        metadata_category=None,
    )

    assert resolution.public_category == "Arqueología"
    messages = "\n".join(loguru_records)
    assert "Category content override for article 3724" in messages
    assert "neandertal" in messages
    assert "yacimiento" in messages
    assert NEANDERTHAL_TITLE not in messages


def test_top_level_technology_maps_without_metadata() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="tech-1",
        title="Nueva alianza de software e IA",
        summary="La plataforma mejora redes empresariales.",
        content="Contenido sobre software y despliegue digital.",
        raw_category="technology",
        metadata_category=None,
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_top_level_health_maps_without_metadata() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="health-1",
        title="Nueva guía clínica",
        summary="La evidencia mejora prevención y riesgo en pacientes.",
        content="Contenido médico.",
        raw_category="health",
        metadata_category=None,
    )

    assert resolution.public_category == "Salud"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_top_level_astronomy_maps_without_metadata() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="space-1",
        title="Nuevo mapa de galaxias",
        summary="El observatorio refina la expansión cósmica.",
        content="Contenido astronómico.",
        raw_category="astronomy",
        metadata_category=None,
    )

    assert resolution.public_category == "Astronomía"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_generic_science_promotes_to_health_via_classifier() -> None:
    classifier = MagicMock()
    classifier.try_classify_article.return_value = "SALUD"
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="generic-health",
        title="Ejercicio y salud ósea",
        summary="Nuevo estudio sobre prevención y bienestar humano.",
        content="Pacientes, prevención y riesgo clínico.",
        raw_category="science",
        metadata_category=None,
    )

    assert resolution.public_category == "Salud"
    assert resolution.resolution_method == "classifier"
    classifier.try_classify_article.assert_called_once()


def test_generic_science_promotes_to_technology_via_classifier() -> None:
    classifier = MagicMock()
    classifier.try_classify_article.return_value = "TECNOLOGÍA"
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="generic-tech",
        title="Nueva infraestructura digital",
        summary="La plataforma acelera software e IA empresarial.",
        content="Contenido sobre despliegue técnico y herramientas.",
        raw_category="science",
        metadata_category=None,
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "classifier"
    classifier.try_classify_article.assert_called_once()


def test_metadata_category_remains_supported_for_legacy_payloads() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="legacy-metadata",
        title="Moltbot",
        summary="Asistente de IA personal.",
        content="Contenido tecnológico.",
        raw_category=None,
        metadata_category="technology",
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_generic_source_prefers_specific_metadata_category() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="generic-source-tech",
        title="Nueva capa de seguridad para internet satelital",
        summary="La cobertura describe una plataforma y su impacto operativo.",
        content="Contenido sobre software, redes y despliegue técnico.",
        raw_category="multidisciplinary",
        metadata_category="technology",
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "direct_map"
    assert resolution.selected_raw_category == "technology"
    classifier.try_classify_article.assert_not_called()


def test_non_first_party_article_cannot_resolve_to_editorial() -> None:
    classifier = MagicMock()
    classifier.try_classify_article.return_value = "TECNOLOGÍA"
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="translated-analysis",
        title="Meta cambia las reglas",
        summary="Análisis de plataformas digitales.",
        content="Contenido sobre plataformas y diseño digital.",
        raw_category="analysis",
        metadata_category=None,
        source_url="https://theconversation.com/example-story",
        source_name="The Conversation",
        source_id="the_conversation",
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "classifier"
    classifier.try_classify_article.assert_called_once()


def test_first_party_article_can_resolve_to_editorial() -> None:
    classifier = MagicMock()
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="noti-editorial",
        title="Nuestra visión",
        summary="Explicamos nuestra línea editorial.",
        content="Meta-discusión sobre el proyecto.",
        raw_category="editorial",
        metadata_category=None,
        source_url="https://noticiencias.com/categorias/editorial",
        source_name="Noticiencias",
        source_id="noticiencias",
    )

    assert resolution.public_category == "Editorial"
    assert resolution.resolution_method == "direct_map"
    classifier.try_classify_article.assert_not_called()


def test_classifier_failure_falls_back_deterministically() -> None:
    classifier = MagicMock()
    classifier.try_classify_article.return_value = None
    resolver = EditorialCategoryResolver(classifier=classifier)

    resolution = resolver.resolve_category(
        article_id="classifier-failure",
        title="Hallazgo amplio",
        summary="Resumen breve.",
        content="Contenido general.",
        raw_category="general",
        metadata_category="technology",
    )

    assert resolution.public_category == "Tecnología"
    assert resolution.resolution_method == "direct_map"
