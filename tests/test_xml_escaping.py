import pytest

from news_collector.perf.load_replay import escape


def test_custom_xml_escape():
    assert escape("a & b") == "a &amp; b"
    assert escape("<i>italic</i>") == "&lt;i&gt;italic&lt;/i&gt;"
    assert escape("safe string") == "safe string"
    assert escape("&<>") == "&amp;&lt;&gt;"
