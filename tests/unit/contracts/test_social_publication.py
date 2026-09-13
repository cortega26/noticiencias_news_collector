"""Tests for the social-distribution adapter (plan social-distribution §8/§9).

Covers deterministic identity derivation, previous-decision preservation, the
LLM-ignored rule, and the full-document stamping helper.
"""

from __future__ import annotations

import hashlib
import unicodedata

import pytest
import yaml

from news_collector.contracts.social_publication import (
    SOCIAL_ID_HASH_PREFIX,
    SOCIAL_ID_RE,
    apply_social_decision,
    derive_social_id,
    stamp_social_frontmatter,
)

SOURCE = "https://www.nature.com/articles/s41586-024-00001-2"


# --------------------------------------------------------------------------- #
# derive_social_id
# --------------------------------------------------------------------------- #


def test_derive_id_matches_independent_vector():
    expected = hashlib.sha256(
        (SOCIAL_ID_HASH_PREFIX + SOURCE).encode("utf-8")
    ).hexdigest()
    assert derive_social_id(SOURCE) == expected
    assert SOCIAL_ID_RE.match(derive_social_id(SOURCE))


def test_derive_id_is_stable_across_retries():
    assert derive_social_id(SOURCE) == derive_social_id(SOURCE)


def test_derive_id_trims_and_nfc_normalizes():
    nfd = unicodedata.normalize("NFD", "https://example.com/café")
    nfc = unicodedata.normalize("NFC", "https://example.com/café")
    assert nfd != nfc  # sanity: the two encodings really differ
    assert derive_social_id(nfd) == derive_social_id(nfc)
    assert derive_social_id(f"  {SOURCE}  ") == derive_social_id(SOURCE)


def test_derive_id_does_not_depend_on_title_or_date():
    # The adapter never feeds title/date into the hash; only source_url does.
    a = apply_social_decision(
        generated_frontmatter={
            "title": "Título A",
            "date": "2026-01-01",
            "source_url": SOURCE,
        },
        previous_frontmatter=None,
    )
    b = apply_social_decision(
        generated_frontmatter={
            "title": "Otro título",
            "date": "2027-09-09",
            "source_url": SOURCE,
        },
        previous_frontmatter=None,
    )
    assert (
        a["social"] == b["social"] == {"publish": True, "id": derive_social_id(SOURCE)}
    )


# --------------------------------------------------------------------------- #
# apply_social_decision
# --------------------------------------------------------------------------- #


def test_new_file_with_source_opts_in():
    result = apply_social_decision(
        generated_frontmatter={"title": "t", "source_url": SOURCE},
        previous_frontmatter=None,
    )
    assert result["social"] == {"publish": True, "id": derive_social_id(SOURCE)}


@pytest.mark.parametrize(
    "bad", [None, "", "   ", "not a url", "ftp://x", "https://a b"]
)
def test_new_file_without_usable_source_stays_disabled(bad):
    fm = {"title": "t"}
    if bad is not None:
        fm["source_url"] = bad
    result = apply_social_decision(generated_frontmatter=fm, previous_frontmatter=None)
    assert result["social"] == {"publish": False}


def test_previous_publish_false_is_preserved():
    result = apply_social_decision(
        generated_frontmatter={"title": "t", "source_url": SOURCE},
        previous_frontmatter={"title": "t", "social": {"publish": False}},
    )
    assert result["social"] == {"publish": False}


def test_previous_publish_true_id_is_preserved_verbatim():
    prior = {"publish": True, "id": "b" * 64}
    result = apply_social_decision(
        generated_frontmatter={"title": "new title", "source_url": SOURCE},
        previous_frontmatter={"social": prior},
    )
    assert result["social"] == prior
    assert result["social"] is not prior  # deep-copied, not aliased


def test_previous_without_social_keeps_absence_no_backfill():
    result = apply_social_decision(
        generated_frontmatter={"title": "t", "source_url": SOURCE},
        previous_frontmatter={"title": "t", "excerpt": "x"},
    )
    assert "social" not in result


def test_llm_produced_social_is_discarded_on_new_file():
    result = apply_social_decision(
        generated_frontmatter={
            "title": "t",
            "source_url": SOURCE,
            "social": {"publish": True, "id": "d" * 64},
        },
        previous_frontmatter=None,
    )
    # Re-derived from source_url, not taken from the LLM block.
    assert result["social"] == {"publish": True, "id": derive_social_id(SOURCE)}


def test_llm_produced_social_is_discarded_when_previous_has_none():
    result = apply_social_decision(
        generated_frontmatter={
            "title": "t",
            "social": {"publish": True, "id": "e" * 64},
        },
        previous_frontmatter={"title": "t"},
    )
    assert "social" not in result


def test_inputs_are_not_mutated():
    generated = {
        "title": "t",
        "source_url": SOURCE,
        "social": {"publish": True, "id": "f" * 64},
    }
    previous = {"social": {"publish": False}}
    apply_social_decision(
        generated_frontmatter=generated, previous_frontmatter=previous
    )
    assert generated["social"] == {"publish": True, "id": "f" * 64}
    assert previous["social"] == {"publish": False}


# --------------------------------------------------------------------------- #
# stamp_social_frontmatter
# --------------------------------------------------------------------------- #

_BODY = "\n\nCuerpo con tildes áéí y symbols &<>.\n\n<!-- source_identity: source_id=1; source_name=x -->"


def _doc(frontmatter: str, body: str = _BODY) -> str:
    return f"---\n{frontmatter}\n---{body}"


def test_stamp_new_file_appends_social_and_preserves_body():
    generated = _doc(f"title: Hola\ndate: 2026-05-07\nsource_url: {SOURCE}")
    out = stamp_social_frontmatter(generated, None)
    assert out.endswith(_BODY)  # body byte-for-byte
    assert "date: 2026-05-07\n" in out  # date stays an unquoted YAML token
    assert f"id: {derive_social_id(SOURCE)}" in out
    assert "publish: true" in out


def test_stamp_new_file_without_source_writes_publish_false():
    out = stamp_social_frontmatter(_doc("title: Hola\ndate: 2026-05-07"), None)
    assert "social:\n  publish: false" in out
    assert out.endswith(_BODY)


def test_stamp_is_byte_identical_when_nothing_changes():
    # Previous file without social + generated without social -> no rewrite.
    generated = _doc("title: Hola")
    previous = _doc("title: Hola", body="\n\nOld body")
    assert stamp_social_frontmatter(generated, previous) == generated


def test_stamp_preserves_previous_social_and_body():
    prior_id = "c" * 64
    generated = _doc(f"title: Nuevo título\nsource_url: {SOURCE}")
    previous = _doc(f"title: Viejo\nsocial:\n  publish: true\n  id: {prior_id}")
    out = stamp_social_frontmatter(generated, previous)
    assert f"id: {prior_id}" in out
    assert "Nuevo título" in out
    assert out.endswith(_BODY)


def test_stamp_unparseable_previous_frontmatter_raises():
    with pytest.raises(ValueError, match="parseable YAML front-matter"):
        stamp_social_frontmatter(_doc("title: Hola"), "no fence here at all")


def test_stamp_returns_generated_unchanged_when_it_has_no_fence():
    assert stamp_social_frontmatter("just a body, no frontmatter", None) == (
        "just a body, no frontmatter"
    )


def test_stamped_output_has_no_quoted_date_only_frontmatter():
    from news_collector.logic.workflows.refinery_engine import (
        QUOTED_DATE_ONLY_FRONTMATTER_RE,
    )

    out = stamp_social_frontmatter(
        _doc(f"title: Hola\ndate: 2026-05-07\nsource_url: {SOURCE}"), None
    )
    fm_block = out[4 : out.find("\n---", 4)]
    assert QUOTED_DATE_ONLY_FRONTMATTER_RE.search(fm_block) is None


def _editor_v2_document() -> str:
    """A full schema_version:2 document serialised exactly as
    ``ai_editor`` does (``yaml.safe_dump`` with the same kwargs) — nested
    lists of dicts, long strings, native date. This is the real shape the
    stamping path re-serialises on every brand-new article.
    """
    import datetime

    import yaml

    model = {
        "title": "Un titular con acentos áéí y un 38% incluido",
        "schema_version": 2,
        "date": datetime.date(2026, 5, 7),
        "author": "Noticiencias AI",
        "categories": ["Salud"],
        "tags": ["cáncer", "prevención", "salud pública"],
        "excerpt": "Una bajada con más de diez caracteres que menciona el 38% y algo más.",
        "image": "~/assets/images/2026-05-07-article-657.jpg",
        "image_alt": "Descripción del hero con tildes",
        "source_url": SOURCE,
        "headlines_variants": {
            "question": "¿Cuánto se reduce?",
            "benefit": "Se abre camino.",
        },
        "summary_points": [
            "Un primer punto suficientemente largo para forzar el ancho.",
            "Un segundo punto con guion y — em dash — y comillas «así».",
        ],
        "glossary": [
            {
                "term": "cáncer prevenible",
                "definition": "Casos evitables modificando factores.",
            },
        ],
        "fact_check": [
            {"label": "El 38% de los casos son evitables.", "status": "confirmed"},
        ],
        "why_it_matters": ["Importa porque afecta la política sanitaria regional."],
        "confidence": "alta",
        "sources": [
            {
                "title": "These two habits are linked to cancer",
                "url": "https://scientificamerican.com/article/these-two-habits/",
                "publisher": "Scientific American",
                "date": "2026-02-05",
            }
        ],
        "requires_uncertainty_note": False,
    }
    dumped = yaml.safe_dump(
        model,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,
    ).strip()
    return f"---\n{dumped}\n---\n\nCuerpo del artículo.\n\n<!-- source_identity: source_id=657; source_name=SciAm -->"


def test_stamp_v2_editor_document_reserialises_only_the_social_key():
    original = _editor_v2_document()
    out = stamp_social_frontmatter(original, None)

    original_fm = original[4 : original.find("\n---", 4)].splitlines()
    out_fm = out[4 : out.find("\n---", 4)].splitlines()

    social_block = ["social:", "  publish: true", f"  id: {derive_social_id(SOURCE)}"]
    # The social block is appended; every other line is byte-for-byte identical.
    assert out_fm[-3:] == social_block
    assert out_fm[:-3] == original_fm
    assert out.endswith(
        "\n\n<!-- source_identity: source_id=657; source_name=SciAm -->"
    )


def test_stamp_v2_editor_document_passes_fast_frontmatter_validation(tmp_path):
    from news_collector.logic.workflows.frontend_publication_validation import (
        validate_post_frontmatter_fast,
    )

    out = stamp_social_frontmatter(_editor_v2_document(), None)
    path = tmp_path / "2026-05-07-v2.md"
    path.write_text(out, encoding="utf-8")
    ok, error_class, error = validate_post_frontmatter_fast(path)
    assert ok, f"{error_class}: {error}"


# --------------------------------------------------------------------------- #
# Hardening (review pass): source_url validation, regex parity, guard ordering
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://",  # bare scheme, no host
        "https://",
        "http:///path",  # empty authority
        "https://:8080/x",  # port but no host
        "https://@example.com".replace("example.com", ""),  # userinfo only
        "//example.com/x",  # scheme-relative
        "javascript:alert(1)",
        "file:///etc/passwd",
        "data:text/html,x",
    ],
)
def test_new_file_with_unusable_source_url_never_opts_in(url):
    """A prefix check is not validation: `http://` has no host, and hashing it
    would authorise distribution for garbage."""
    result = apply_social_decision(
        generated_frontmatter={"title": "t", "source_url": url},
        previous_frontmatter=None,
    )
    assert result["social"] == {"publish": False}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/a?b=c#d",
        "https://sub.example.co.uk/path",
        "https://example.com:8443/x",
        # Scheme case is not part of validation: `source_url` is already
        # normalised upstream by pydantic HttpUrl, and the identity hashes the
        # stored string verbatim (spec §2).
        "HTTPS://EXAMPLE.COM/x",
    ],
)
def test_new_file_with_host_bearing_http_url_opts_in(url):
    result = apply_social_decision(
        generated_frontmatter={"source_url": url}, previous_frontmatter=None
    )
    assert result["social"] == {"publish": True, "id": derive_social_id(url)}


@pytest.mark.parametrize("bad", ["a" * 64 + "\n", "\n" + "a" * 64, "a" * 64 + " "])
def test_social_id_re_rejects_what_the_schemas_reject(bad):
    """Parity guard: Python `re` lets `$` match before a trailing newline, but
    Pydantic (rust-regex) and Zod (`RegExp.test`) both anchor at end-of-input.
    Downstream consumers of SOCIAL_ID_RE must not be more permissive."""
    assert SOCIAL_ID_RE.match(bad) is None


def test_social_id_re_accepts_a_derived_id():
    assert SOCIAL_ID_RE.match(derive_social_id(SOURCE)) is not None


def test_corrupt_previous_blocks_even_when_generated_is_also_unparseable():
    """The previous-file guard must run before any early return on the generated
    side — the both-broken case is exactly the one that would silently clobber a
    stored editorial decision."""
    corrupt_previous = "no fence here at all"
    for broken_generated in (
        "just a body, no frontmatter",  # no fence
        "---\ntitle: [unclosed\n---\n\nBody",  # fence, malformed YAML
        "---\n- a\n- b\n---\n\nBody",  # fence, YAML list not a mapping
    ):
        with pytest.raises(ValueError, match="parseable YAML front-matter"):
            stamp_social_frontmatter(broken_generated, corrupt_previous)


def test_previous_with_explicit_null_social_drops_the_invalid_key():
    """`social: null` is invalid in both schemas; it is not a stored decision, so
    it is dropped rather than propagated (and never re-enabled)."""
    out = stamp_social_frontmatter(
        _doc(f"title: T\nsource_url: {SOURCE}"),
        _doc("title: T\nsocial: null"),
    )
    assert "social" not in yaml.safe_load(out[4 : out.find("\n---", 4)])
