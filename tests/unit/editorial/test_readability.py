"""Unit tests for news_collector.editorial.readability (plan 065).

Syllable expectations follow standard Spanish syllabification
(RAE: guion/truhan monosílabos, triptongos uruguay/buey, hiatos con tilde
en débil como país/río, fuerte+fuerte como teatro/héroe).
"""

import pytest

from news_collector.editorial.readability import (
    analyze_body_readability,
    check_english_spillover,
    check_headline,
    count_syllables_es,
    count_words_es,
    fernandez_huerta_ifh,
    readability_grade,
    readability_suitability,
    split_sentences_es,
    szigriszt_ifsz,
)


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("casa", 2),
        ("mesa", 2),
        ("sol", 1),
        ("árbol", 2),
        ("lápiz", 2),
        ("examen", 3),
        ("que", 1),
        ("los", 1),
        ("hola", 2),
        ("ciencia", 2),
        ("cuidado", 3),
        ("fiesta", 2),
        ("puerta", 2),
        ("causa", 2),
        ("aula", 2),
        ("Europa", 3),
        ("aire", 2),
        ("país", 2),
        ("río", 2),
        ("dúo", 2),
        ("oír", 2),
        ("caía", 3),
        ("teatro", 3),
        ("héroe", 3),
        ("aéreo", 4),
        ("poeta", 3),
        ("leer", 2),
        ("alcohol", 3),
        ("ahínco", 3),
        ("Uruguay", 3),
        ("miau", 1),
        ("buey", 1),
        ("ley", 1),
        ("hoy", 1),
        ("y", 1),
        ("yugo", 2),
        ("proyecto", 3),
        ("pingüino", 3),
        ("vergüenza", 3),
        ("cigüeña", 3),
        ("guion", 1),
        ("murciélago", 4),
        ("diálogo", 3),
        ("diéresis", 3),
        ("adiós", 2),
        ("camión", 2),
        ("avión", 2),
        ("canción", 2),
        ("ciénaga", 3),
        ("truhan", 1),
        ("huésped", 2),
        ("química", 3),
        ("queso", 2),
        ("quien", 1),
        ("guerra", 2),
        ("guitarra", 3),
        ("siguiente", 3),
        ("antiguo", 3),
        ("constitución", 4),
        ("Chile", 2),
        ("estrés", 2),
        ("2026", 1),
        ("", 0),
    ],
)
def test_count_syllables_es(word, expected):
    assert count_syllables_es(word) == expected


def test_split_sentences_es_guards_abbreviations_and_decimals():
    text = "El Dr. García midió 3.5 mg. Llegó el Sr. Pérez."
    sentences = split_sentences_es(text)
    assert sentences == ["El Dr. García midió 3.5 mg", "Llegó el Sr. Pérez"]


def test_split_sentences_es_eeuu():
    assert split_sentences_es("Fue en EE. UU. ayer. Volvió.") == [
        "Fue en EEUU ayer",
        "Volvió",
    ]


def test_formulas_on_toy_sentence():
    # El(1) sol(1) sale(2) por(1) el(1) este(2) = 8 syllables, 6 words.
    assert szigriszt_ifsz(8, 6, 1) == pytest.approx(117.77, abs=0.01)
    assert fernandez_huerta_ifh(8, 6, 1) == pytest.approx(120.72, abs=0.01)


def test_formulas_guard_empty_input():
    assert szigriszt_ifsz(0, 0, 0) is None
    assert fernandez_huerta_ifh(10, 5, 0) is None
    assert readability_grade(None) == "sin contenido"
    assert readability_suitability(None) is None


def test_readability_grades_and_suitability():
    assert readability_grade(95) == "muy fácil"
    assert readability_grade(62.5) == "normal"
    assert readability_grade(10) == "muy difícil"
    assert readability_suitability(75) == 1.0
    assert readability_suitability(45) == 0.5
    assert readability_suitability(15) == 0.0
    assert readability_suitability(200) == 1.0


def test_analyze_body_readability_reference_paragraph():
    body = (
        "La fotosíntesis convierte la luz solar en energía química. "
        "Las plantas usan este proceso cada día."
    )
    report = analyze_body_readability(body)
    assert report.words == 16
    assert report.sentences == 2
    assert report.syllables == 35
    assert report.avg_syllables_per_word == pytest.approx(2.188, abs=0.001)
    assert report.avg_words_per_sentence == pytest.approx(8.0)
    assert report.ifsz == pytest.approx(62.56, abs=0.05)
    assert report.ifh == pytest.approx(67.43, abs=0.05)
    assert report.grade == "normal"
    assert report.suitability == pytest.approx(0.793, abs=0.005)


def test_analyze_body_readability_strips_frontmatter_and_urls():
    markdown = (
        "---\nslug: prueba\ntitle: X\n---\n\n"
        "Las células usan energía. Ver https://ejemplo.com/x.\n\n"
        "```python\nprint('hola mundo cruel')\n```\n"
    )
    report = analyze_body_readability(markdown)
    # slug/prueba/X excluded; code block and URL excluded.
    assert report.words == len(count_words_es("Las células usan energía. Ver ."))
    assert report.sentences == 2


def test_analyze_body_readability_empty():
    report = analyze_body_readability("")
    assert report.words == 0
    assert report.ifsz is None
    assert report.grade == "sin contenido"


def test_check_headline_clean():
    assert check_headline("El cerebro consume menos energía que una bombilla LED") == []


def test_check_headline_empty():
    assert [i.code for i in check_headline("")] == ["empty"]
    assert [i.code for i in check_headline(None)] == ["empty"]
    assert [i.code for i in check_headline([])] == ["empty"]


def test_check_headline_list_payload_judges_first_element():
    assert check_headline(["El cerebro consume menos energía"]) == []
    assert "too-short" in [i.code for i in check_headline(["Hola", "otra cosa"])]


def test_check_headline_too_long_and_short():
    assert "too-long" in [i.code for i in check_headline("Palabra " * 20)]
    assert "too-short" in [i.code for i in check_headline("Hola mundo")]


def test_check_headline_all_caps_but_allows_acronyms():
    issues = check_headline("Un DESCUBRIMIENTO que nadie esperaba ver hoy")
    assert "all-caps" in [i.code for i in issues]
    clean = check_headline("La vacuna contra la COVID muestra eficacia alta")
    assert "all-caps" not in [i.code for i in clean]


def test_check_headline_speculative_adjective_quoted_passes():
    flagged = check_headline("Un descubrimiento revolucionario cambia la física")
    assert "speculative-adjective" in [i.code for i in flagged]
    quoted = check_headline(
        'Los autores lo describen como "revolucionario" y publican datos'
    )
    assert "speculative-adjective" not in [i.code for i in quoted]


def test_check_headline_clickbait_and_period():
    bait = check_headline("No vas a creer lo que descubrieron los físicos")
    assert "clickbait-phrase" in [i.code for i in bait]
    period = check_headline("El hallazgo redefine la edad del universo.")
    assert [i.code for i in period] == ["trailing-period"]
    bang = check_headline("Llegó el eclipse más esperado del siglo!!")
    assert "shouting" in [i.code for i in bang]


def test_check_english_spillover_flags_tendencies_with_context():
    """Plan 079, Codex P2 verbatim case."""
    body = (
        "Los porcentajes deben leerse como indicaciones tendencies "
        "más que como conclusiones definitivas."
    )
    issues = check_english_spillover(body)
    assert [i.code for i in issues] == ["english-spillover"]
    assert "tendencies" in issues[0].message
    assert "indicaciones" in issues[0].message


def test_check_english_spillover_clean_spanish():
    body = (
        "Los rayos causan miles de muertes al año. Los sobrevivientes "
        "suelen presentar lesiones invisibles como dolor crónico."
    )
    assert check_english_spillover(body) == []
    assert check_english_spillover("") == []
    assert check_english_spillover(None) == []


def test_check_english_spillover_skips_quotes_italics_code_urls():
    quoted = 'Los autores hablan de "findings" preliminares en el estudio.'
    assert check_english_spillover(quoted) == []
    italic = "Los *findings* preliminares son importantes aquí."
    assert check_english_spillover(italic) == []
    fenced = "Texto limpio aquí.\n```\nfindings = load()\n```\n"
    assert check_english_spillover(fenced) == []
    linked = "Ver https://example.com/tendencies/report para más datos."
    assert check_english_spillover(linked) == []
    frontmatter = "---\ntitle: tendencies overview\n---\n\nCuerpo limpio total."
    assert check_english_spillover(frontmatter) == []
