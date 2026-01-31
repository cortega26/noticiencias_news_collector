import pytest
from news_collector.utils.refinery_helper import has_no_activity

def test_has_no_activity_none():
    assert has_no_activity(None) is True

def test_has_no_activity_empty_list():
    assert has_no_activity([]) is True

def test_has_no_activity_with_items():
    assert has_no_activity(["event1"]) is False
    assert has_no_activity([1, 2, 3]) is False

def test_has_no_activity_unexpected_types():
    # If it behaves truthy/falsy
    assert has_no_activity({}) is True
    assert has_no_activity({"a": 1}) is False
