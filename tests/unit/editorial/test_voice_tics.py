"""Unit tests for the deterministic voice-tic lint (spec L3).

Each banned pattern from the voice contract must fire; quoted speech and
frontmatter must not count (they are not our editorial voice); degenerate
input must be safe.
"""

from __future__ import annotations

from news_collector.editorial.voice_tics import check_voice_tics


def _codes(markdown: str) -> set[str]:
    return {finding.code for finding in check_voice_tics(markdown)}


def test_imagina_opening_fires():
    assert "imagina_opening" in _codes("Imagina que puedes ver el universo entero.")


def test_no_es_x_es_y_fires():
    assert "no_es_X_es_Y" in _codes("No es un planeta, es un laboratorio natural.")


def test_no_solo_sino_fires():
    assert "no_solo_sino" in _codes(
        "No solo mide el brillo sino también la temperatura."
    )


def test_mundo_donde_and_certainty_tics_fire():
    codes = _codes("En un mundo donde todo cambia, esto ocurre sin lugar a dudas.")
    assert {"mundo_donde", "sin_lugar_a_dudas"} <= codes


def test_metadiscourse_tic_fires():
    assert "cabe_destacar" in _codes("Cabe destacar que el estudio es preliminar.")


def test_voseo_fires_and_tuteo_passes():
    assert "voseo" in _codes("Mirá este dato y decí qué pensás.")
    assert _codes("Mira este dato y dime qué piensas.") == set()


def test_clean_prose_passes():
    assert (
        check_voice_tics(
            "El equipo midió el brillo durante tres noches seguidas "
            "y publicó los datos en un repositorio abierto."
        )
        == []
    )


def test_quoted_speech_is_exempt():
    assert (
        check_voice_tics(
            'El director dijo: "Imagina que puedes verlo todo". '
            "El equipo midió el brillo."
        )
        == []
    )


def test_frontmatter_is_exempt():
    assert (
        check_voice_tics(
            "---\ntitle: Imagina un mundo donde todo es posible\n---\n\n"
            "El equipo midió el brillo."
        )
        == []
    )


def test_degenerate_input_is_safe():
    assert check_voice_tics(None) == []
    assert check_voice_tics("") == []
    assert check_voice_tics("---\ntitle: x\n---\n") == []


def test_finding_carries_count_and_snippets():
    (finding,) = [
        f for f in check_voice_tics("No es rojo, es azul.") if f.code == "no_es_X_es_Y"
    ]
    assert finding.count == 1
    assert finding.severity == "warn"
    assert finding.snippets and "rojo" in finding.snippets[0]
