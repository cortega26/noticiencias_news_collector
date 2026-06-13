"""Tests for scripts/repair_images.py has_valid_image guards.

has_valid_image must never raise on a non-string `image` value (e.g. a YAML
list or dict) and must return False for empty / remote-URL strings.
"""

from __future__ import annotations

from scripts.repair_images import has_valid_image


def test_non_string_list_returns_false_without_exception():
    assert has_valid_image({"image": ["a", "b"]}) is False


def test_non_string_dict_returns_false_without_exception():
    assert has_valid_image({"image": {"src": "x"}}) is False


def test_remote_url_returns_false():
    assert has_valid_image({"image": "http://example.com/y.jpg"}) is False


def test_empty_string_returns_false():
    assert has_valid_image({"image": ""}) is False


def test_missing_image_returns_false():
    assert has_valid_image({}) is False
