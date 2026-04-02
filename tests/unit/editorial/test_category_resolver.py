from __future__ import annotations

from unittest.mock import MagicMock

from news_collector.editorial.category_resolver import EditorialCategoryResolver


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
    assert resolution.resolution_method == "fallback"
