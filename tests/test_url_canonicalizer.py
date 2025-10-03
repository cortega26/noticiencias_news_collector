import pytest

import src.utils.url_canonicalizer as url_canonicalizer


POSITIVE_CASES = [
    (
        "HTTPS://WWW.Example.com:443/News/Story?utm_source=twitter&b=2&a=1",
        "https://example.com/News/Story?a=1&b=2",
    ),
    (
        "http://m.example.com/article/amp/?gclid=123",
        "https://example.com/article/",
    ),
    (
        "example.com/path/?fbclid=abc&utm_medium=email&id=42",
        "https://example.com/path/?id=42",
    ),
    (
        "https://amp.subdomain.example.com/foo/bar/?amp&c=3&b=2&a=1",
        "https://subdomain.example.com/foo/bar/?a=1&b=2&c=3",
    ),
    (
        "https://example.com//double//slashes/?utm_campaign=test",
        "https://example.com/double/slashes/",
    ),
]


NEGATIVE_CASES = [
    (
        "https://example.com/article?id=1",
        "https://example.com/article?id=1",
    ),
    (
        "https://maps.google.com/?q=coffee",
        "https://maps.google.com/?q=coffee",
    ),
    (
        "https://example.com/path/?ref=section",
        "https://example.com/path/",
    ),
]


@pytest.mark.parametrize("raw, expected", POSITIVE_CASES)
def test_canonicalize_positive(raw: str, expected: str) -> None:
    assert url_canonicalizer.canonicalize_url(raw) == expected


@pytest.mark.parametrize("raw, expected", NEGATIVE_CASES)
def test_canonicalize_negative(raw: str, expected: str) -> None:
    assert url_canonicalizer.canonicalize_url(raw) == expected


def test_canonicalize_cache_configuration() -> None:
    url_canonicalizer.configure_canonicalization_cache(0)
    url_canonicalizer.clear_canonicalization_cache()
    assert not hasattr(url_canonicalizer.canonicalize_url, "cache_info")

    url_canonicalizer.configure_canonicalization_cache(8)
    assert hasattr(url_canonicalizer.canonicalize_url, "cache_info")

    url_canonicalizer.canonicalize_url("https://example.com/path?id=1")
    url_canonicalizer.canonicalize_url("https://example.com/path?id=1")
    info = url_canonicalizer.canonicalize_url.cache_info()  # type: ignore[attr-defined]
    assert info.hits >= 1

    url_canonicalizer.configure_canonicalization_cache(2048)
    url_canonicalizer.clear_canonicalization_cache()
    assert hasattr(url_canonicalizer.canonicalize_url, "cache_info")


def test_canonicalize_handles_empty_input() -> None:
    assert url_canonicalizer.canonicalize_url("") == ""
    assert url_canonicalizer.canonicalize_url("   ") == ""


def test_canonicalize_normalizes_host_and_path() -> None:
    assert url_canonicalizer.canonicalize_url("https://example.com") == "https://example.com/"
    assert url_canonicalizer.canonicalize_url("example.org") == "https://example.org/"


def test_canonicalize_filters_amp_and_duplicates() -> None:
    normalized = url_canonicalizer.canonicalize_url(
        "https://example.com/post?amp=1&a=1&a=&utm_source=x"
    )
    assert normalized == "https://example.com/post?a=1"


def test_canonicalize_converts_non_http_scheme() -> None:
    assert (
        url_canonicalizer.canonicalize_url("ftp://Example.com:21/data")
        == "https://example.com:21/data"
    )


def test_canonicalize_preserves_non_web_scheme_without_host() -> None:
    assert url_canonicalizer.canonicalize_url("mailto:") == "mailto:"
