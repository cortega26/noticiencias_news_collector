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
