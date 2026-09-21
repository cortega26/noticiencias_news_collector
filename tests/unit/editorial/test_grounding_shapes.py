"""Exact-shape tests for editorial.grounding (mutation-driven).

The PR-body section, the persisted stage details and the finding payloads are consumed by
other code (PR orchestrator, publish-status API, reviewers): key names and windows are contract.
"""

from __future__ import annotations

from news_collector.editorial import grounding as g

LONG = "Cell recovery was 91 percent after 25 days of culture. " * 40


def _md(front="", body="Texto."):
    return f"---\n{front}\n---\n\n{body}\n"


def test_finding_as_dict_has_exactly_the_documented_keys():
    f = g.GroundingFinding("number", g.ERROR, "body", "snip", "detail")
    assert f.as_dict() == {
        "kind": "number",
        "severity": "error",
        "field": "body",
        "snippet": "snip",
        "detail": "detail",
    }
    assert g.GroundingFinding("k", g.WARN, "f", "s").as_dict()["detail"] == ""


def test_report_counters_and_stage_details_shape():
    report = g.check_grounding(_md(body="Cifra 999 y avance revolucionario."), LONG)
    d = report.stage_details(top=1)
    assert set(d) == {
        "errors",
        "warnings",
        "by_kind",
        "source_chars",
        "skipped_reason",
        "findings",
    }
    assert d["errors"] == 1 and d["warnings"] == 1
    assert d["by_kind"] == {"number": 1, "overclaim": 1}
    assert d["source_chars"] == len(LONG) and d["skipped_reason"] == ""
    assert [f["kind"] for f in d["findings"]] == ["number"]  # errors first, top=1
    assert set(d["findings"][0]) == {"kind", "severity", "field", "snippet", "detail"}
    assert report.by_kind() == {"number": 1, "overclaim": 1}  # counts, not overwritten


def test_by_kind_counts_repeats():
    report = g.check_grounding(_md(body="Cifras 111, 222 y 333."), LONG)
    assert report.by_kind() == {"number": 3}


def test_skipped_report_carries_reason_and_zero_counts():
    d = g.check_grounding(_md(), "corto").stage_details()
    assert d["skipped_reason"] == "source_too_short" and d["errors"] == 0
    assert d["source_chars"] == len("corto") and d["findings"] == []


def test_snippet_window_is_centered_and_collapses_whitespace():
    text = "a" * 100 + "  \n TARGET \n " + "b" * 100
    snip = g._snippet(text, 100)
    assert "TARGET" in snip and "\n" not in snip and "  " not in snip
    assert g._snippet("short text", 0) == "short text"
    assert g._snippet("x" * 200, 0) == "x" * 70  # no left padding at the start
    assert len(g._snippet("x" * 300, 150)) <= 105


def test_number_forms_distinguish_grouping_from_decimals():
    assert g._number_forms("1,500") == {"1,500", "1500"}
    assert g._number_forms("1.500") == {"1.500", "1500"}
    assert g._number_forms("2,50") == {"2,50", "2.5"}
    assert g._number_forms("4.0") == {"4"}
    assert g._number_forms("100") == {"100"}  # no '.', trailing zeros untouched
    assert g._number_forms("3.10") == {"3.1"}


def test_number_forms_examples_in_context():
    src = g._source_number_set("There were 4.0 mg and 2.50 units and 100 cases")
    assert {"4", "2.5", "100"} <= src
    assert (
        "1" not in src and "10" not in src
    )  # trailing-zero strip must not eat integers


def test_frontmatter_split_edges():
    meta, body = g._split_frontmatter("sin frontmatter")
    assert meta == {} and body == "sin frontmatter"
    assert g._split_frontmatter("") == ({}, "")
    assert g._split_frontmatter(None) == ({}, "")  # type: ignore[arg-type]
    meta, body = g._split_frontmatter("---\ntitle: T\n---\nCuerpo")
    assert meta == {"title": "T"} and body == "Cuerpo"
    meta, body = g._split_frontmatter("---\n: : [bad\n---\nCuerpo")
    assert meta == {} and body == "Cuerpo"  # invalid YAML -> empty meta, body kept
    meta, _ = g._split_frontmatter("---\n- just\n- a list\n---\nx")
    assert meta == {}  # non-mapping frontmatter


def test_field_texts_shapes():
    assert g._field_texts("s") == ["s"]
    assert g._field_texts({"a": "x", "b": 3, "c": "y"}) == ["x", "y"]
    assert g._field_texts(["a", {"label": "L"}, {"text": "T"}, {"other": 1}, 5]) == [
        "a",
        "L",
        "T",
    ]
    assert g._field_texts(None) == [] and g._field_texts(7) == []


def test_extract_claim_segments_order_and_code_fences():
    md = _md(
        "title: T\nsummary_points:\n  - p1\nglossary:\n  - term: x\n    definition: d\n",
        "Antes\n```\ncode 999\n```\nDespués",
    )
    segs = g.extract_claim_segments(md)
    assert segs[0] == ("title", "T") and segs[1] == ("summary_points", "p1")
    assert segs[-1][0] == "body" and "code 999" not in segs[-1][1]
    assert "Antes" in segs[-1][1] and "Después" in segs[-1][1]
    assert not any(f == "glossary" for f, _ in segs)


def test_hygiene_findings_are_fully_described():
    findings = g._check_hygiene("body", "5 % y‑x y bead.")
    by = {f.detail.split(" (")[0]: f for f in findings}
    assert all(
        f.kind == "hygiene" and f.severity == g.WARN and f.field == "body"
        for f in findings
    )
    assert "carácter especial: espacio fino no separable" in " ".join(by)
    assert any("anglicismo sin traducir «bead»" in f.detail for f in findings)
    assert all(f.snippet for f in findings)
    # first occurrence is reported, with its count
    twice = g._check_hygiene("f", "a b c")
    assert len(twice) == 1 and twice[0].detail.endswith("(2×)")
    assert twice[0].snippet.startswith("a")  # window starts at the FIRST occurrence


def test_hero_alt_finding_payload_and_edges():
    boiler = "Ilustración editorial relacionada con algo"
    (f,) = g._check_hero_alt({"image_alt": f"  {boiler}  "})
    assert (f.kind, f.severity, f.field) == ("hero_alt", g.WARN, "image_alt")
    assert f.snippet == boiler and "alt genérico" in f.detail
    long_alt = "Ilustración editorial relacionada con " + "x" * 100
    assert len(g._check_hero_alt({"image_alt": long_alt})[0].snippet) == 70
    assert g._check_hero_alt({}) == []  # missing alt: silent
    assert g._check_hero_alt({"image_alt": "Fotografía de un rollo"}) == []
    assert g._check_hero_alt("not a mapping") == []  # type: ignore[arg-type]


def test_replica_scope_finding_payload():
    meta = {
        "requires_uncertainty_note": True,
        "uncertainty_note": "Resultados con réplicas modernas hechas en laboratorio; no probado en el original.",
        "summary_points": ["Lograron recuperar palabras legibles de los rollos."],
    }
    findings = g._check_replica_scope(meta)
    assert findings, "expected a replica-scope warning"
    f = findings[0]
    assert (f.kind, f.severity) == ("replica_scope", g.WARN)
    assert f.field.startswith("summary_points") and f.snippet and len(f.snippet) <= 70
    assert "réplicas" in f.detail
    assert g._check_replica_scope("nope") == []  # type: ignore[arg-type]


def test_code_span_neutralizes_backticks_and_whitespace():
    assert g._code_span("a`b\n  c ") == "`a'b c`"
