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
    find_capability_overclaims,
    find_unvalidated_capability_claims,
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


# --- Capability-overclaim detector (plan 083) ---------------------------

# Verbatim Codex P1 case on PR #153.
_CODEX_WHY_IT_MATTERS = (
    "Al aprovechar sensores CGM cada vez más accesibles, GlucoFM permite una "
    "detección temprana y un manejo personalizado de la glucosa, lo que podría "
    "disminuir complicaciones asociadas a la diabetes en la población."
)


def test_find_flags_codex_present_tense_claim():
    found = find_capability_overclaims(_CODEX_WHY_IT_MATTERS)
    assert found == [_CODEX_WHY_IT_MATTERS]


def test_find_flags_second_clause_verb_a_rewriter_would_mangle():
    text = (
        "El modelo permite detectar la diabetes e identifica la resistencia "
        "a la insulina."
    )
    assert find_capability_overclaims(text) == [text]


@pytest.mark.parametrize(
    "text",
    [
        # Hedged: the natural Spanish construction puts an infinitive after
        # the modal, so no bare finite capability verb remains.
        "El modelo podría permitir una detección temprana de la diabetes.",
        "El sistema puede detectar el riesgo de diabetes.",
        # No clinical context — an architectural statement.
        "El modelo permite reutilizar las representaciones aprendidas.",
        # Past tense — a reported result, not a live capability.
        "GlucoFM detectó el riesgo de diabetes en cuatro cohortes.",
        # No capability verb.
        "GlucoFM es un modelo fundacional para el monitoreo de glucosa.",
        "",
        "   ",
    ],
)
def test_find_ignores_safe_text(text):
    assert find_capability_overclaims(text) == []


def test_find_non_string_is_safe():
    assert find_capability_overclaims(None) == []
    assert find_capability_overclaims(123) == []


def test_claims_no_counterweight_is_noop():
    fields = {"why_it_matters": [_CODEX_WHY_IT_MATTERS]}
    assert (
        find_unvalidated_capability_claims(
            fields, requires_uncertainty_note=False, uncertainty_note=None
        )
        == []
    )


def test_claims_flags_why_it_matters_under_flag():
    fields = {
        "why_it_matters": [
            "Una predicción más fiable del riesgo de diabetes puede reducir la "
            "carga de diagnóstico.",
            _CODEX_WHY_IT_MATTERS,
        ]
    }
    found = find_unvalidated_capability_claims(
        fields, requires_uncertainty_note=True, uncertainty_note=None
    )
    assert found == [f"why_it_matters[1]: {_CODEX_WHY_IT_MATTERS}"]


def test_claims_flags_benefit_headline_when_note_present():
    fields = {
        "headlines_variants": {
            "question": "¿Puede la IA leer tu glucosa?",
            "benefit": "El modelo que detecta la diabetes desde tu sensor de glucosa.",
        }
    }
    found = find_unvalidated_capability_claims(
        fields,
        requires_uncertainty_note=False,
        uncertainty_note="Aún no validado en estudios clínicos.",
    )
    assert found == [
        "headlines_variants.benefit: El modelo que detecta la diabetes desde "
        "tu sensor de glucosa."
    ]


def test_claims_returns_empty_when_nothing_matches():
    fields = {"why_it_matters": ["GlucoFM separa la señal en dos corrientes."]}
    assert (
        find_unvalidated_capability_claims(
            fields, requires_uncertainty_note=True, uncertainty_note=None
        )
        == []
    )
