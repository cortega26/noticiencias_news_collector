from __future__ import annotations

import pytest

from news_collector.components.editorial.ai_editor import (
    GeneratedArticleValidationError,
    validate_generated_article_markdown,
)


def test_validate_generated_article_markdown_rejects_placeholder_stub() -> None:
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        validate_generated_article_markdown(
            """
## Fuga del Código Fuente Completo de Claude Code CLI

El contenido fuente proporcionado para este artículo es ilegible y corrupto, impidiendo la elaboración de un texto que cumpla con los estándares de rigor científico.
"""
        )

    assert excinfo.value.error_code == "editorial_placeholder_blocked"


def test_validate_generated_article_markdown_accepts_real_article_body() -> None:
    validate_generated_article_markdown(
        """
## Un error de empaquetado expone el interior de Claude Code

Anthropic publicó una versión del paquete de Claude Code para npm que incluía un archivo source map. Ese archivo permitió reconstruir casi todo el código TypeScript de la herramienta, algo especialmente sensible porque Claude Code se ha vuelto una de las interfaces más visibles para programar con modelos de IA en la terminal.

La filtración no expuso datos de clientes ni credenciales, según la propia empresa, pero sí abrió una ventana inusual a la arquitectura interna del producto. Investigadores y desarrolladores empezaron a revisar de inmediato módulos relacionados con memoria, verificación de contexto y herramientas conectadas al flujo de trabajo del agente.

El episodio muestra un riesgo operativo clásico en software moderno: un error de empaquetado puede convertir metadatos útiles para depurar en una fuga masiva de propiedad intelectual. También deja a potenciales atacantes con más pistas para estudiar la superficie de seguridad del producto y buscar puntos débiles en sus guardrails.
"""
    )
