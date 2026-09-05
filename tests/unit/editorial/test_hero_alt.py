"""Unit tests for news_collector.editorial.hero_alt (plan 079).

Codex P2 root fix: the pre-edit fallback stamped the ENGLISH original
title into the alt text. Good brief alts pass through untouched; only
empty/boilerplate alts are recomputed once the Spanish title exists.
"""

import pytest

from news_collector.editorial.hero_alt import is_boilerplate_alt, resolve_hero_alt_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ilustración editorial relacionada con X", True),
        ("ilustración editorial relacionada con X", True),
        ("  Ilustración editorial relacionada con X  ", True),
        ("Imagen de un laboratorio", True),
        ("", True),
        ("   ", True),
        (None, True),
        (123, True),
        ("Micrografía de neuronas bajo microscopio", False),
        ("Ilustración del eclipse sobre el desierto", False),
    ],
)
def test_is_boilerplate_alt(text, expected):
    assert is_boilerplate_alt(text) is expected


def test_resolve_keeps_good_alt():
    good = "Micrografía de neuronas bajo microscopio"
    assert resolve_hero_alt_text(good, "Titular español") == good


def test_resolve_replaces_english_boilerplate_with_spanish_title():
    result = resolve_hero_alt_text(
        "Ilustración editorial relacionada con Lightning strikes kill",
        "¿Qué efectos tiene un rayo sin rasguños visibles?",
    )
    assert result == (
        "Ilustración editorial relacionada con "
        "¿Qué efectos tiene un rayo sin rasguños visibles?"
    )
    assert "Lightning" not in result


def test_resolve_empty_alt_uses_spanish_title():
    assert resolve_hero_alt_text("", "Titular español") == (
        "Ilustración editorial relacionada con Titular español"
    )
    assert resolve_hero_alt_text(None, "Titular español") == (
        "Ilustración editorial relacionada con Titular español"
    )


def test_resolve_without_title_keeps_current():
    assert resolve_hero_alt_text("", "") is None
    assert resolve_hero_alt_text(None, None) is None
    boilerplate = "Ilustración editorial relacionada con X"
    assert resolve_hero_alt_text(boilerplate, "") == boilerplate


def test_resolve_list_input_takes_first():
    assert resolve_hero_alt_text(["Alt buena", "otra"], "Título") == "Alt buena"
    assert resolve_hero_alt_text([], "Título") == (
        "Ilustración editorial relacionada con Título"
    )


def test_resolve_imagen_de_prefix_is_replaced():
    result = resolve_hero_alt_text("Imagen de un laboratorio", "Titular")
    assert result == "Ilustración editorial relacionada con Titular"
