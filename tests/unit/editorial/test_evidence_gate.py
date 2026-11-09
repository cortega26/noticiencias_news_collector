"""Plan 212: the evidence gate blocks drafts that invent checkable specifics."""

from __future__ import annotations

from news_collector.editorial.evidence_gate import (
    DEFAULT_THRESHOLD,
    GATE_ERROR_CODE,
    SHORT_SOURCE_CHARS,
    EvidenceGateDecision,
    evaluate_evidence_gate,
)

_SENTENCES = (
    "Researchers analysed hair and nail samples from eight frozen mummies "
    "recovered near volcanic peaks and detected cocaine in every individual. "
    "Harmine, an alkaloid linked to ayahuasca, appeared in one of them. "
    "Four of the bodies also tested positive for alcohol, probably from maize "
    "beer, and the authors say the ritual was not a single standard practice. "
)


def _source(extra: str = "") -> str:
    base = _SENTENCES * 6 + extra
    assert len(base) > SHORT_SOURCE_CHARS
    return base


def _article(body: str, summary: str = "") -> str:
    points = f"summary_points:\n  - {summary}\n" if summary else ""
    return f"---\ntitle: Prueba\n{points}---\n\n{body}\n"


def test_fabricated_acronyms_block_the_draft():
    body = (
        "No se detectó DMT en ninguna momia. El análisis usó LC-MS/MS y la harmina "
        "actúa como inhibidor de la IMAO en el cerebro."
    )
    decision = evaluate_evidence_gate(_article(body), _source())
    assert decision.blocked
    values = {u.value for u in decision.unsupported}
    assert {"DMT", "LC-MS/MS", "IMAO"} <= values
    assert decision.by_kind() == {"acronym": 3}
    assert GATE_ERROR_CODE in "editorial_unsupported_specifics"
    assert "DMT" in decision.message()


def test_invented_figures_block_the_draft():
    body = "El muestreo cubrió 50 localidades y 200 000 ejemplares en 12 meses."
    decision = evaluate_evidence_gate(_article(body), _source())
    assert decision.blocked
    assert decision.by_kind().get("number", 0) >= 2


def test_faithful_draft_passes():
    body = (
        "Cuatro de los ocho cuerpos dieron positivo en alcohol, probablemente por "
        "chicha, y la harmina apareció en uno de ellos."
    )
    decision = evaluate_evidence_gate(_article(body), _source())
    assert not decision.blocked
    assert decision.unsupported == ()


def test_single_unsupported_specific_stays_below_the_threshold():
    decision = evaluate_evidence_gate(
        _article("El equipo menciona el CNIC en su afiliación."), _source()
    )
    assert len(decision.unsupported) == 1
    assert decision.threshold == DEFAULT_THRESHOLD
    assert not decision.blocked


def test_repeated_specific_counts_once():
    body = "El DMT. Otra vez el DMT. Y de nuevo DMT, siempre DMT."
    decision = evaluate_evidence_gate(_article(body), _source())
    assert len(decision.unsupported) == 1
    assert not decision.blocked


def test_short_source_fails_closed_on_a_single_specific():
    decision = evaluate_evidence_gate(
        _article("La muestra tenía 95 individuos."), "Texto breve de la fuente."
    )
    assert decision.short_source
    assert decision.threshold == 1
    assert decision.blocked


def test_short_source_without_specifics_passes():
    decision = evaluate_evidence_gate(
        _article("Un hallazgo sin cifras ni siglas."), "Texto breve."
    )
    assert decision.short_source
    assert not decision.blocked


def test_empty_source_is_treated_as_short():
    decision = evaluate_evidence_gate(_article("Hubo 70 casos."), "")
    assert decision.short_source and decision.blocked


def test_spanish_acronym_is_grounded_by_its_english_source_form():
    source = _source("The DNA sample and the MAOI effect were measured. ")
    body = "El ADN de la muestra y el efecto de la IMAO se midieron."
    decision = evaluate_evidence_gate(_article(body), source)
    assert [u for u in decision.unsupported if u.kind == "acronym"] == []


def test_acronym_defined_in_the_article_is_not_a_fresh_claim():
    body = (
        "La técnica de reemplazo mitocondrial (TRM) se usó en la clínica. "
        "Después la TRM se aplicó en otros centros, y la fecundación in vitro "
        "(FIV) se repitió."
    )
    decision = evaluate_evidence_gate(
        _article(body, summary="La TRM y la FIV se compararon."), _source()
    )
    assert decision.unsupported == ()


def test_acronym_defined_after_an_unrelated_phrase_is_still_flagged():
    body = "La harmina del estudio (DMT) apareció en un cuerpo."
    decision = evaluate_evidence_gate(_article(body), _source())
    assert [u.value for u in decision.unsupported] == ["DMT"]


def test_roman_numerals_and_boilerplate_acronyms_are_ignored():
    body = (
        "Entre los siglos XIII y XVI, en EE. UU. y en la UE. "
        "La ilustración fue generada con IA."
    )
    decision = evaluate_evidence_gate(_article(body), _source())
    assert [u.value for u in decision.unsupported if u.kind == "acronym"] == ["UE"]


def test_invented_doi_is_flagged_and_a_sourced_doi_is_not():
    source = _source("The paper is doi 10.1073/pnas.2614248123 in PNAS. ")
    body = "El trabajo (doi 10.1073/pnas.9999999) difiere del 10.1073/pnas.2614248123."
    decision = evaluate_evidence_gate(_article(body), source)
    assert [u.value for u in decision.unsupported if u.kind == "doi"] == [
        "10.1073/pnas.9999999"
    ]


def test_vague_quantifier_without_source_counts_toward_the_gate():
    source = _source()
    body = "Participaron cientos de investigadores y miles de muestras."
    decision = evaluate_evidence_gate(_article(body), source)
    assert decision.blocked
    assert decision.by_kind().get("vague_quantifier", 0) >= 2


def test_stage_details_are_bounded_and_serializable():
    body = " ".join(f"El código ZZ{n}X apareció." for n in range(20))
    decision = evaluate_evidence_gate(_article(body), _source())
    details = decision.stage_details(top=5)
    assert details["blocked"] is True
    assert details["unsupported_count"] == 20
    assert len(details["unsupported"]) == 5
    assert set(details["unsupported"][0]) == {"kind", "value", "field"}
    assert "+12 more" in decision.message()


def test_odd_markdown_never_raises():
    for text in ("", "---\n---\n", "sin frontmatter ni cifras", "```code 99```"):
        decision = evaluate_evidence_gate(text, _source())
        assert isinstance(decision, EvidenceGateDecision)
        assert decision.blocked is False
