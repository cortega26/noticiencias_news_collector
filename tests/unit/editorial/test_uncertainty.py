"""Unit tests for news_collector.editorial.uncertainty (plan 067).

Voice rule §2.4.3: curiosity-gap hook over a preliminary finding ⇒
mandatory visible uncertainty note. Real-world grounding: two published
posts carry requires=true with no note; confidence is free text starting
with Alta/Moderada/Moderada-alta.
"""

import pytest

from news_collector.editorial.uncertainty import (
    GENERIC_UNCERTAINTY_NOTE,
    confidence_suggests_preliminary,
    hook_needs_counterweight,
    resolve_uncertainty_counterweight,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("curiosity_gap", True),
        ("Curiosity Gap", True),
        (" curiosity_gap ", True),
        ("stakes", True),
        ("Stakes", True),
        ("question", False),
        ("counterintuitive", False),
        ("human_emotion", False),
        (None, False),
        ("", False),
        (123, False),
    ],
)
def test_hook_needs_counterweight(pattern, expected):
    assert hook_needs_counterweight(pattern) is expected


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        ("Moderada — estudios preliminares.", True),
        ("Moderada-alta — evidencia parcial.", True),
        ("media — observación única.", True),
        ("Baja: muestra pequeña.", True),
        ("Alta — metodología sólida.", False),
        ("", False),
        (None, False),
        (123, False),
        ("Solidez alta en general.", False),
    ],
)
def test_confidence_suggests_preliminary(confidence, expected):
    assert confidence_suggests_preliminary(confidence) is expected


def test_resolve_keeps_provided_note_with_flag():
    headlines = {
        "requires_uncertainty_note": True,
        "uncertainty_note": "El resultado aún es preliminar.",
    }
    assert resolve_uncertainty_counterweight(headlines, "Alta — sólida.") == (
        True,
        "El resultado aún es preliminar.",
    )


def test_resolve_required_without_note_falls_back_to_generic():
    headlines = {"requires_uncertainty_note": True}
    requires, note = resolve_uncertainty_counterweight(headlines, "Alta — x.")
    assert requires is True
    assert note == GENERIC_UNCERTAINTY_NOTE


def test_resolve_note_without_flag_is_kept():
    headlines = {
        "requires_uncertainty_note": False,
        "uncertainty_note": "Muestra pequeña.",
    }
    assert resolve_uncertainty_counterweight(headlines, "Alta — x.") == (
        False,
        "Muestra pequeña.",
    )


def test_resolve_curiosity_gap_preliminary_forces_flag():
    headlines = {"pattern_used": "curiosity_gap"}
    requires, note = resolve_uncertainty_counterweight(
        headlines, "Moderada — hipótesis sin confirmar."
    )
    assert requires is True
    assert note == GENERIC_UNCERTAINTY_NOTE


def test_resolve_curiosity_gap_confident_needs_nothing():
    headlines = {"pattern_used": "curiosity_gap"}
    assert resolve_uncertainty_counterweight(headlines, "Alta — sólida.") == (
        False,
        None,
    )


def test_resolve_other_pattern_preliminary_needs_nothing():
    headlines = {"pattern_used": "question"}
    assert resolve_uncertainty_counterweight(headlines, "Moderada — hipótesis.") == (
        False,
        None,
    )


def test_resolve_empty_headlines():
    assert resolve_uncertainty_counterweight({}, "Moderada — x.") == (
        False,
        None,
    )
    assert resolve_uncertainty_counterweight(None, "Moderada — x.") == (
        False,
        None,
    )
