"""Plan 101 coverage backfill: PreScorer pure-helper branches.

Exercises _extract_balanced_segment and _parse_selected_indices directly
(no LLM, no config) to pin their edge-case behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from noticiencias.config_manager import load_config

from news_collector.collectors.rss_collector import RSSCollector
from news_collector.scoring.pre_scorer import PreScorer


def test_extract_balanced_segment_no_brace_returns_none():
    assert PreScorer._extract_balanced_segment("plain text", "{", "}") is None


def test_extract_balanced_segment_nested():
    text = 'prefix {"a": [1, {"b": 2}]} suffix'
    assert PreScorer._extract_balanced_segment(text, "{", "}") == '{"a": [1, {"b": 2}]}'


def test_extract_balanced_segment_ignores_braces_in_strings():
    text = '{"a": "br}ace"} trailing'
    assert PreScorer._extract_balanced_segment(text, "{", "}") == '{"a": "br}ace"}'


def test_extract_balanced_segment_unbalanced_returns_none():
    assert PreScorer._extract_balanced_segment('{"a": 1', "{", "}") is None


def _stub_scorer():
    return PreScorer(llm_client=MagicMock())


def test_parse_selected_indices_variants():
    parse = _stub_scorer()._parse_selected_indices
    assert parse({"selected_indices": [2, 0]}) == [2, 0]
    assert parse({"selected_indices": "nope"}) == []
    assert parse([1, 0]) == [1, 0]
    assert parse("") == []
    assert parse(None) == []


def test_collector_wires_explicit_config_to_prescorer():
    """The production chain passes bootstrap config into PreScorer explicitly."""
    collector = RSSCollector(config=load_config())
    assert isinstance(collector.pre_scorer, PreScorer)
    assert collector.pre_scorer.model_name == collector.pre_scorer.llm.model


def test_collector_accepts_injected_prescorer_client():
    """A fake llm_client keeps RSSCollector construction ambient-free."""
    collector = RSSCollector(config=load_config())
    fake = MagicMock()
    fake.model = "injected-model"
    collector.pre_scorer = PreScorer(llm_client=fake)
    assert collector.pre_scorer.model_name == "injected-model"
