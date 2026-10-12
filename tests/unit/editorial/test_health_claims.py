"""Unit tests for the health guarantee-language check (spec L4).

Must fire on guarantee phrasing inside health scope, stay silent outside
health scope, exempt quoted speech, and never raise on degenerate input.
"""

from __future__ import annotations

from news_collector.editorial.health_claims import find_guarantee_language


def _codes(body: str, **scope) -> set[str]:
    return {finding.code for finding in find_guarantee_language(body, **scope)}


def test_garantiza_fires_in_health_scope():
    assert "garantiza" in _codes(
        "Un CAC de cero garantiza que no habrá eventos cardiovasculares.",
        category="salud",
    )


def test_cero_riesgo_and_cura_fires():
    codes = _codes(
        "El tratamiento tiene cero riesgo y ofrece una cura definitiva.",
        category="salud",
    )
    assert {"cero_riesgo", "cura_definitiva"} <= codes


def test_silent_outside_health_scope():
    assert (
        find_guarantee_language(
            "El nuevo chip garantiza un 20 % más de rendimiento.",
            category="tecnologia",
        )
        == []
    )


def test_keyword_text_triggers_scope():
    assert "garantiza" in _codes(
        "La vacuna garantiza protección total.", category="ciencia"
    )


def test_quoted_speech_is_exempt():
    assert (
        find_guarantee_language(
            'El médico dijo: "Esto garantiza su recuperación". '
            "El estudio observó mejoras en el tratamiento de pacientes.",
            category="salud",
        )
        == []
    )


def test_degenerate_input_is_safe():
    assert find_guarantee_language(None, category="salud") == []
    assert find_guarantee_language("", category="salud") == []
    assert find_guarantee_language("garantiza todo", category=None) == []


def test_finding_shape():
    (finding,) = find_guarantee_language(
        "El fármaco garantiza la recuperación.", category="salud"
    )
    assert finding.severity == "warn"
    assert finding.count == 1
    assert finding.snippets
