"""Grounding rules (advisory). The 2315 fixture reproduces the defects that
shipped in the bioRxiv alginate article (see docs/editorial_grounding_check.md)."""

from news_collector.editorial.grounding import (
    ERROR,
    WARN,
    check_grounding,
    extract_claim_segments,
    normalize_text_hygiene,
)

SOURCE = (
    "Pluripotent stem cell-derived islets (SC-islets) are a promising source of "
    "insulin-producing tissue for type 1 diabetes. We encapsulated SC-islets in "
    "high concentration alginate beads made by emulsion and cultured them for 25 "
    "days. Cell recovery was 91 ± 3 % versus 60 ± 10 % for unencapsulated "
    "SC-islets. Transplanted SC-islets kept secreting human C-peptide up to day "
    "98 post-transplant. This is a preprint that has not been peer reviewed. "
) * 4  # long enough to pass MIN_SOURCE_CHARS


def _post(**fields):
    front = "\n".join(f"{k}: {v}" for k, v in fields.pop("meta", {}).items())
    body = fields.pop("body", "Texto neutro sin cifras.")
    return f"---\n{front}\n---\n\n{body}\n"


def kinds(report, severity=None):
    return {f.kind for f in report.findings if severity in (None, f.severity)}


def test_clean_article_has_no_findings():
    md = _post(
        meta={"title": "Microesferas de alginato protegen islotes"},
        body="La recuperación celular fue del 91 ± 3 %, frente al 60 ± 10 %, tras 25 días.",
    )
    assert check_grounding(md, SOURCE).findings == []


def test_2315_defects_are_detected():
    md = _post(
        meta={
            "excerpt": "Se producen miles de células por lote",
            "why_it_matters": "Afecta a millones de personas en América Latina",
        },
        body=(
            "Los resultados en roedores inmunodeficientes muestran menos fibrosis. "
            "Requiere manufactura GMP. Además, cada bead‑ de alginato…"
        ),
    )
    r = check_grounding(md, SOURCE)
    assert "vague_quantifier" in kinds(r, ERROR)
    assert {"scope_claim", "hygiene"} <= kinds(r, WARN)
    labels = " ".join(f.detail for f in r.findings)
    for expected in ("miles", "millones", "roedores", "fibrosis", "GMP", "bead"):
        assert expected in labels
    assert "U+202F" in labels and "U+2011" in labels


def test_number_missing_from_source_is_an_error_and_taints_fact_check():
    md = (
        "---\nfact_check:\n"
        "  - label: La recuperación fue del 95 %.\n    status: confirmed\n---\nCuerpo."
    )
    r = check_grounding(md, SOURCE)
    assert any(f.kind == "number" and "95" in f.detail for f in r.errors)
    assert "fact_check" in kinds(r, WARN)


def test_number_formats_and_number_words_are_grounded():
    src = SOURCE + " There were 1,500 patients and twenty participants over 4.5 years."
    md = _post(body="Participaron 1.500 pacientes y 20 personas durante 4,5 años.")
    assert check_grounding(md, src).findings == []


def test_space_grouped_thousands_match_source_digits():
    src = SOURCE + " The model has 30000 parameters."
    md = _post(body="Tiene 30 000 parámetros.")
    assert "number" not in kinds(check_grounding(md, src), ERROR)


def test_figure_followed_by_millones_is_not_a_vague_quantifier():
    md = _post(body="Unos 2,2 millones y treinta mil millones de casos.")
    r = check_grounding(md, SOURCE + " 2.2 30000")
    assert "vague_quantifier" not in kinds(r)


def test_vague_quantifier_allowed_when_source_has_equivalent():
    md = _post(body="Miles de participantes.")
    assert "vague_quantifier" not in kinds(
        check_grounding(md, SOURCE + " thousands of")
    )


def test_latam_framing_allowed_in_why_it_matters_only():
    ok = _post(meta={"why_it_matters": "Relevante en América Latina"})
    bad = _post(body="Relevante en América Latina")
    assert "scope_claim" not in kinds(check_grounding(ok, SOURCE))
    assert "scope_claim" in kinds(check_grounding(bad, SOURCE))
    assert "scope_claim" not in kinds(
        check_grounding(bad, SOURCE, allow_terms=["América Latina / Latinoamérica"])
    )


def test_overclaim_lexicon_is_a_warning():
    r = check_grounding(
        _post(body="Un avance revolucionario y sin precedentes."), SOURCE
    )
    assert kinds(r) == {"overclaim"} and not r.errors


def test_short_or_missing_source_is_skipped_not_alarmed():
    r = check_grounding(_post(body="Cifra 999."), "corto")
    assert r.findings == [] and r.skipped_reason == "source_too_short"
    assert check_grounding("x", "").skipped_reason == "source_too_short"


def test_hygiene_repair_is_deterministic():
    text = "a‑b c d e​f"
    assert normalize_text_hygiene(text) == "a-b c d ef"


def test_invalid_frontmatter_falls_back_to_body_only():
    segs = extract_claim_segments("---\n: : bad: [\n---\nCuerpo con 12.")
    assert segs == [("body", "Cuerpo con 12.")]


def test_stage_details_is_compact_and_errors_first():
    md = _post(
        meta={"title": "T"},
        body="Cifra 999. Avance revolucionario.",
    )
    d = check_grounding(md, SOURCE).stage_details(top=1)
    assert d["errors"] >= 1 and d["findings"][0]["severity"] == ERROR
    assert d["by_kind"]["overclaim"] == 1


def test_glossary_and_sources_are_not_checked():
    md = (
        "---\nglossary:\n  - term: x\n    definition: 5000 millones\n"
        "sources:\n  - title: t\n    date: '2026-09-12'\n---\nCuerpo."
    )
    assert check_grounding(md, SOURCE).findings == []


def test_grouped_thousands_do_not_ground_a_decimal_reading():
    src = SOURCE + " There were 1,500 patients."
    md = _post(body="Participaron 1,5 pacientes.")
    assert any(f.kind == "number" for f in check_grounding(md, src).errors)
    assert "number" not in kinds(check_grounding(_post(body="Hubo 1.500."), src))


def test_overclaim_translated_from_the_source_is_not_flagged():
    md = _post(body="Un resultado sin precedentes.")
    assert "overclaim" not in kinds(
        check_grounding(md, SOURCE + " an unprecedented result")
    )
    assert "overclaim" in kinds(check_grounding(md, SOURCE))
