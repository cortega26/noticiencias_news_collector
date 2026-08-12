import pytest

from news_collector.utils.slug import slugify


def test_basic_ascii():
    assert slugify("Hello World") == "hello-world"


def test_unicode_normalized():
    assert slugify("Ñoño café") == "nono-cafe"


def test_special_chars_replaced():
    assert slugify("foo/bar:baz") == "foo-bar-baz"


def test_consecutive_dashes_collapsed():
    assert slugify("foo   bar") == "foo-bar"


def test_empty_string_returns_fallback():
    assert slugify("") == "article"


def test_all_non_ascii_returns_fallback():
    assert slugify("日本語") == "article"


def test_custom_fallback():
    assert slugify("", fallback="post") == "post"


def test_leading_trailing_dashes_stripped():
    assert slugify("---hello---") == "hello"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Simple Title", "simple-title"),
        ("2026-05-22", "2026-05-22"),
        ("already-a-slug", "already-a-slug"),
    ],
)
def test_common_inputs(value, expected):
    assert slugify(value) == expected
