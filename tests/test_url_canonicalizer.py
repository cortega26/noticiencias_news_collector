import pytest

from src.utils.url_canonicalizer import canonicalize_url


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
def test_canonicalize_positive(raw, expected):
    assert canonicalize_url(raw) == expected


@pytest.mark.parametrize("raw, expected", NEGATIVE_CASES)
def test_canonicalize_negative(raw, expected):
    assert canonicalize_url(raw) == expected
