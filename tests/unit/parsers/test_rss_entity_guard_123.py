"""Plan 123 step 6 (investigate-first): feed entity-expansion guard SKIPPED.

Fixture probes against the pinned feedparser 6.0.14 prove no guard is
needed: the parser is sgmllib-based and never expands DTD entities
(internal or external). These regression tests pin that behavior — if a
future feedparser upgrade starts expanding entities, they fail loudly and
the guard must be built then.
"""

import time

import feedparser

from news_collector.logic.parsers.rss_parser import RssParser


def _billion_laughs() -> str:
    """Classic exponential-entity payload: 10x fan-out over 9 levels would
    expand to 10^10 chars if the parser resolved DTD entities."""
    xml = '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "1234567890">'
    prev = "a"
    for i in range(1, 10):
        xml += '<!ENTITY e%d "%s">' % (i, "".join("&%s;" % prev for _ in range(10)))
        prev = "e%d" % i
    xml += (
        ']><rss version="2.0"><channel><title>T</title>'
        "<link>http://example.com/</link><description>d</description>"
        "<item><title>&e9;</title><link>http://example.com/1</link>"
        "<description>d</description></item></channel></rss>"
    )
    return xml


def test_pinned_feedparser_does_not_expand_entities():
    """A 740-byte billion-laughs payload must parse fast with no expansion."""
    payload = _billion_laughs()
    assert len(payload) < 2000
    parser = RssParser()
    started = time.time()
    parsed = parser.parse_feed_content(payload)
    elapsed = time.time() - started
    assert elapsed < 5, f"entity expansion suspected: {elapsed:.1f}s parse"
    titles = [e.get("title", "") for e in parser.extract_items(parsed, {"id": "t"})]
    assert all(len(t) < 1000 for t in titles), "entity expansion detected"


def test_pinned_feedparser_ignores_external_entities():
    """XXE exfiltration must be inert (no file content in parsed output)."""
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY xxe SYSTEM '
        '"file:///etc/passwd">]><rss version="2.0"><channel><title>T</title>'
        "<link>http://example.com/</link><description>d</description>"
        "<item><title>&xxe;</title><link>http://example.com/1</link>"
        "<description>d</description></item></channel></rss>"
    )
    parser = RssParser()
    parsed = parser.parse_feed_content(xxe)
    titles = [e.get("title", "") for e in parser.extract_items(parsed, {"id": "t"})]
    assert not any("root:" in t for t in titles), "external entity resolved!"


def test_feedparser_pin_still_applies():
    """The skip-guard decision is only valid for the probed major line."""
    assert feedparser.__version__.startswith("6.")
