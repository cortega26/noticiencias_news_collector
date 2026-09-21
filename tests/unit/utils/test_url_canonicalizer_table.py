"""Characterization table for ``canonicalize_url`` (mutation-driven).

The canonical URL is the identity used to dedupe articles; if any rule below silently changes,
the same story is ingested twice (or two stories merge). Each row was reviewed by hand against
the module's documented rules. Mutation testing showed 91 surviving mutants before this table.
"""

from __future__ import annotations

import pytest

from news_collector.utils import url_canonicalizer as uc

CASES = [
    ("", ""),
    ("   ", ""),
    ("https://Example.COM/a//b///c", "https://example.com/a/b/c"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com/a/./b/../c", "https://example.com/a/c"),
    ("https://example.com/a/b/", "https://example.com/a/b/"),
    ("https://example.com/a%20b/%7Euser", "https://example.com/a%20b/~user"),
    ("https://example.com/a/amp", "https://example.com/a/"),
    ("https://example.com/a/amp/", "https://example.com/a/"),
    ("https://example.com/a.amp", "https://example.com/a/"),
    ("https://example.com/a/amp/amp", "https://example.com/a/"),
    ("https://example.com/amp/a", "https://example.com/amp/a"),
    ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ("https://example.com/p?B=2&A=1", "https://example.com/p?a=1&b=2"),
    ("https://example.com/p?utm_source=x&id=5", "https://example.com/p?id=5"),
    ("https://example.com/p?icid=1&id=5", "https://example.com/p?id=5"),
    ("https://example.com/p?fbclid=z&ref=q&id=5", "https://example.com/p?id=5"),
    ("https://example.com/p?amp=1&id=5", "https://example.com/p?id=5"),
    ("https://example.com/p?amp=true", "https://example.com/p"),
    ("https://example.com/p?id=1&id=1&id=2", "https://example.com/p?id=1&id=2"),
    ("https://example.com/p?a=&b=2", "https://example.com/p?b=2"),
    ("https://example.com/p?q=a+b%26c", "https://example.com/p?q=a%20b%26c"),
    ("https://example.com/p?k=v%20w", "https://example.com/p?k=v%20w"),
    ("https://example.com/p?=x&id=1", "https://example.com/p?id=1"),
    ("https://example.com/p?id=5#frag", "https://example.com/p?id=5"),
    ("http://www.example.com/x", "https://example.com/x"),
    ("https://m.example.com/x", "https://example.com/x"),
    ("https://mobile.example.com/x", "https://example.com/x"),
    ("https://amp.example.com/x", "https://example.com/x"),
    ("https://www.com/x", "https://www.com/x"),
    ("https://www.m.example.com/x", "https://example.com/x"),
    ("https://www.example.com:8080/x", "https://example.com:8080/x"),
    ("http://example.com:80/x", "https://example.com/x"),
    ("https://example.com:443/x", "https://example.com/x"),
    ("https://example.com:8443/x", "https://example.com:8443/x"),
    ("http://example.com:81/x", "https://example.com:81/x"),
    ("example.com", "https://example.com/"),
    ("example.com/foo", "https://example.com/foo"),
    ("example.com/foo?b=1&a=2", "https://example.com/foo?a=2&b=1"),
    ("example.com:80/foo", "https://example.com/foo"),
    ("example.com:8080", "https://example.com:8080/"),
    ("example.com:8080/x", "https://example.com:8080/x"),
    ("localhost:3000/x", "https://localhost:3000/x"),
    ("localhost:3000", "https://localhost:3000/"),
    ("EXAMPLE.com:443/Path", "https://example.com/Path"),
    ("mailto:a@b.com", "mailto:a@b.com"),
    ("javascript:alert(1)", "javascript:alert(1)"),
    ("tel:+123", "tel:+123"),
    ("data:text/plain,hi", "data:text/plain,hi"),
    ("ftp://example.com/x", "ftp://example.com/x"),
    ("//example.com/x", "https://example.com/x"),
    ("/relative/path", "/relative/path"),
    ("https://", "https://"),
    ("HTTPS://EXAMPLE.COM/Path?X=1", "https://example.com/Path?x=1"),
    ("https://example.com/p?q=%E2%9C%93", "https://example.com/p?q=%E2%9C%93"),
    ("https://example.com/%E2%9C%93", "https://example.com/%E2%9C%93"),
    ("https://example.com/a b", "https://example.com/a%20b"),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_canonical_form(raw, expected):
    assert uc._canonicalize_url_impl(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_canonical_form_is_idempotent(raw, expected):
    assert uc._canonicalize_url_impl(expected) == expected


def test_clean_host_only_strips_prefixes_that_leave_a_real_domain():
    assert uc._clean_host("WWW.Example.com") == "example.com"
    assert uc._clean_host("www.com") == "www.com"  # remainder without a dot: keep
    assert uc._clean_host("www.m.example.com") == "example.com"  # stacked prefixes
    assert uc._clean_host("mobile.") == "mobile."  # empty remainder
    assert uc._clean_host("news.example.com") == "news.example.com"


def test_normalize_path_edges():
    assert uc._normalize_path("") == "/"
    assert uc._normalize_path("/.") == "/"
    assert uc._normalize_path(".") == "/"
    assert uc._normalize_path("/a//b") == "/a/b"
    assert uc._normalize_path("/a/b/") == "/a/b/"
    assert uc._normalize_path("/a b") == "/a%20b"
    assert uc._normalize_path("/a:b@c") == "/a:b@c"  # SAFE_PATH_CHARS survive quoting


def test_filter_query_params_rules_in_order():
    pairs = [
        ("Zed", "1"),
        ("", "x"),  # blank key
        ("UTM_Medium", "m"),  # tracking prefix, case-insensitive
        ("icid", "3"),
        ("fbclid", "f"),  # tracking param
        ("amp", "true"),
        ("keep", ""),  # blank value
        ("dup", "1"),
        ("dup", "1"),  # exact duplicate pair
        ("dup", "2"),  # same key, other value survives
    ]
    assert list(uc._filter_query_params(pairs)) == [
        ("zed", "1"),
        ("dup", "1"),
        ("dup", "2"),
    ]


def test_canonicalization_cache_configuration_and_clearing():
    original = uc._CACHE_SIZE
    try:
        uc.configure_canonicalization_cache(0)
        assert uc.canonicalize_url is uc._canonicalize_url_impl  # cache disabled
        uc.configure_canonicalization_cache(-3)
        assert uc.canonicalize_url is uc._canonicalize_url_impl

        uc.configure_canonicalization_cache(2)
        assert uc._CACHE_SIZE == 2
        assert uc.canonicalize_url.cache_info().maxsize == 2
        uc.canonicalize_url("https://a.test/x")
        uc.canonicalize_url("https://a.test/x")
        assert uc.canonicalize_url.cache_info().hits == 1

        same = uc.canonicalize_url
        uc.configure_canonicalization_cache(2)  # same size: keeps the warm cache
        assert uc.canonicalize_url is same

        uc.clear_canonicalization_cache()
        assert uc.canonicalize_url.cache_info().currsize == 0

        uc.configure_canonicalization_cache(
            1
        )  # size 1 is still a cache (size <= 0 disables)
        assert uc.canonicalize_url.cache_info().maxsize == 1
        uc.configure_canonicalization_cache(0)
        uc.clear_canonicalization_cache()  # no cache_clear on the plain function: must not raise
    finally:
        uc.configure_canonicalization_cache(original)
