from __future__ import annotations

import string
from urllib.parse import parse_qsl, urlparse

from hypothesis import given, settings
from hypothesis import strategies as st

from src.utils.text_cleaner import clean_html, normalize_text
from src.utils.url_canonicalizer import canonicalize_url


TEXT_STRATEGY = st.text(alphabet=st.characters(blacklist_categories=("Cs",)))


@given(TEXT_STRATEGY)
@settings(max_examples=150)
def test_normalize_text_strips_controls_and_is_idempotent(raw: str) -> None:
    normalized = normalize_text(raw)
    assert normalize_text(normalized) == normalized
    assert normalized == normalized.strip()
    for forbidden in ("\n", "\r", "\x00"):
        assert forbidden not in normalized


@given(
    st.lists(
        st.text(
            alphabet=string.ascii_letters + string.digits,
            min_size=1,
            max_size=10,
        ),
        min_size=1,
        max_size=6,
    ),
    st.sampled_from([" ", "\n", "\t", "\r", "  \n"]),
)
@settings(max_examples=75)
def test_normalize_text_collapses_whitespace(parts: list[str], spacer: str) -> None:
    raw = spacer.join(parts)
    normalized = normalize_text(raw)
    assert "  " not in normalized
    assert "\n" not in normalized
    assert normalized.split(" ") == normalize_text(" ".join(parts)).split(" ")


@st.composite
def html_fragments(draw) -> str:
    words = draw(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5))
    boilerplate = draw(st.sampled_from([
        "Read More",
        "Continue Reading",
        "The post Foo appeared first on Bar",
    ]))
    script_body = draw(st.text(min_size=0, max_size=20))
    wrapper = draw(st.sampled_from(["div", "span", "article", "section"]))
    body = " ".join(words)
    return (
        f"<html><head><script>{script_body}</script><style>.x{{color:red}}</style></head>"
        f"<body><{wrapper}>{body}</{wrapper}><p>{boilerplate}</p></body></html>"
    )


@given(html_fragments())
@settings(max_examples=60)
def test_clean_html_removes_boilerplate_and_scripts(payload: str) -> None:
    cleaned = clean_html(payload)
    assert "script" not in cleaned.lower()
    assert "style" not in cleaned.lower()
    assert "read more" not in cleaned.lower()
    assert cleaned == normalize_text(cleaned)


_TRACKING_KEYS = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref",
    "amp",
    "spm",
]


@st.composite
def messy_urls(draw) -> str:
    scheme = draw(st.sampled_from(["http", "https", "HTTP", "", "HtTp"]))
    prefix = draw(st.sampled_from(["", "www.", "m.", "mobile.", "amp."]))
    domain = draw(
        st.text(
            alphabet=st.sampled_from(list(string.ascii_lowercase)),
            min_size=3,
            max_size=12,
        )
    )
    suffix = draw(st.sampled_from(["com", "org", "net"]))
    host = f"{prefix}{domain}.{suffix}"
    port = draw(st.sampled_from(["", ":80", ":443", ":8080"]))
    segment_chars = string.ascii_letters + string.digits + "-_"
    segments = draw(
        st.lists(
            st.text(alphabet=segment_chars, min_size=0, max_size=8),
            min_size=0,
            max_size=4,
        )
    )
    path = "/" + "/".join(filter(None, segments)) if segments else "/"
    if draw(st.booleans()):
        path += draw(st.sampled_from(["", "/", "/amp", "/amp/", "/AMP"]))
    query_pairs = draw(
        st.lists(
            st.tuples(
                st.one_of(
                    st.sampled_from(_TRACKING_KEYS),
                    st.text(alphabet=segment_chars, min_size=1, max_size=6),
                    st.just(""),
                ),
                st.text(alphabet=segment_chars, min_size=0, max_size=6),
            ),
            max_size=5,
        )
    )
    query_parts = [
        f"{key}={value}" if value else key for key, value in query_pairs
    ]
    if draw(st.booleans()):
        query_parts.append("amp")
    base = f"{host}{port}{path}"
    if scheme:
        url = f"{scheme}://{base}"
    else:
        url = base
    if query_parts:
        url += "?" + "&".join(query_parts)
    if draw(st.booleans()):
        url += draw(st.sampled_from(["", "#fragment", "#Section"]))
    prefix_ws = draw(st.sampled_from(["", " ", "\n", "\t"]))
    suffix_ws = draw(st.sampled_from(["", " ", "\n"]))
    return f"{prefix_ws}{url}{suffix_ws}"


@given(messy_urls())
@settings(max_examples=120)
def test_canonicalize_url_is_idempotent_and_https(raw: str) -> None:
    canonical = canonicalize_url(raw)
    assert canonicalize_url(canonical) == canonical
    parsed = urlparse(canonical)
    if parsed.netloc:
        assert parsed.scheme == "https"
        assert not parsed.netloc.startswith(("www.", "m.", "mobile.", "amp."))
    assert " " not in canonical
    pairs = parse_qsl(parsed.query, keep_blank_values=False)
    assert pairs == sorted(pairs, key=lambda item: (item[0], item[1]))
    for key, _ in pairs:
        assert not key.startswith("utm_")
        assert key not in {"fbclid", "gclid", "amp", "spm", "ref", ""}


@given(messy_urls())
@settings(max_examples=120)
def test_canonicalize_url_drops_tracking_equivalents(raw: str) -> None:
    canonical = canonicalize_url(raw)
    parsed = urlparse(canonical)
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        assert key not in _TRACKING_KEYS
        assert value != ""
    assert canonical == canonicalize_url(canonical.strip())
