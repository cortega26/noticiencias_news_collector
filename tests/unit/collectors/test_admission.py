"""Characterization + unit tests for the shared article-admission policy.

Plan 034 (centralize article admission): the previous state had a dead,
never-called policy on BaseCollector plus a weaker RSS-only override.
These tests lock in current behavior at today's config values (min_title_length=10,
min_content_length=500 per config.toml) and make every accept/reject boundary
explicit, so a future config or code change shows an intentional diff here
rather than a silent regression.
"""

from __future__ import annotations

import dataclasses

import pytest
from news_collector.collectors.admission import (
    AdmissionReason,
    evaluate_admission,
)
from news_collector.config.settings import get_runtime_config
from news_collector.contracts import CollectorArticleModel

VALID_URL = "https://example.com/article"


def _article(**overrides) -> CollectorArticleModel:
    fields = {
        "url": VALID_URL,
        "title": "A sufficiently long scientific headline",
        "summary": "",
        "content": "x" * 600,
        "source_id": "src-1",
        "source_name": "Source One",
        "category": "science",
        "published_date": "2026-01-01T00:00:00Z",
    }
    fields.update(overrides)
    return CollectorArticleModel(**fields)


@pytest.fixture
def config():
    return get_runtime_config()


def test_valid_article_is_accepted(config):
    decision = evaluate_admission(_article(), config)
    assert decision.accepted is True
    assert decision.reason is None


def test_empty_title_is_rejected(config):
    # CollectorArticleModel itself enforces Field(min_length=10) on title,
    # so an empty title never reaches evaluate_admission in practice — this
    # documents that structural guarantee rather than re-testing this module.
    with pytest.raises(Exception):
        _article(title="")


def test_short_title_below_configured_minimum_is_rejected(config):
    snapshot = dataclasses.replace(
        config,
        text_processing_config={
            **config.text_processing_config,
            "min_title_length": 20,
        },
    )
    # 10-19 chars: passes CollectorArticleModel's hardcoded min_length=10,
    # but is shorter than an operator-configured min_title_length=20 — this
    # is exactly the "configuration has no effect" bug plan 034 targets.
    decision = evaluate_admission(_article(title="Fifteen chars!!"), snapshot)
    assert decision.accepted is False
    assert decision.reason is AdmissionReason.TITLE_TOO_SHORT
    assert decision.details["min_required"] == 20


def test_title_at_exact_configured_boundary_is_accepted(config):
    title = "x" * 10  # default min_title_length is 10
    assert config.text_processing_config.get("min_title_length", 10) == 10
    decision = evaluate_admission(_article(title=title), config)
    assert decision.accepted is True


def test_content_shorter_than_configured_minimum_is_rejected(config):
    assert config.text_processing_config.get("min_content_length") == 500
    decision = evaluate_admission(_article(content="x" * 499), config)
    assert decision.accepted is False
    assert decision.reason is AdmissionReason.CONTENT_TOO_SHORT
    assert decision.details == {"length": 499, "min_required": 500}


def test_content_at_exact_configured_boundary_is_accepted(config):
    decision = evaluate_admission(_article(content="x" * 500), config)
    assert decision.accepted is True


def test_summary_only_articles_are_exempt_from_content_length(config):
    """The summary_only exception must survive centralization unchanged."""
    decision = evaluate_admission(
        _article(content="short content", content_mode="summary_only"), config
    )
    assert decision.accepted is True


def test_configured_penalty_phrase_title_is_structurally_accepted(config):
    """Intentional non-change: penalty_keywords stays a soft scoring signal,
    not a hard admission rejection. Plan 034 explicitly keeps hard-structural
    rejection (title/content length) separate from soft editorial scoring
    (see news_collector.scoring.basic_scorer) — an editorially undesirable
    but structurally valid article must still be admitted here."""
    penalty_keywords = config.text_processing_config["penalty_keywords"]
    assert penalty_keywords, "fixture assumes config.toml defines penalty_keywords"
    decision = evaluate_admission(
        _article(title=f"{penalty_keywords[0]} — a long enough clickbait headline"),
        config,
    )
    assert decision.accepted is True
    assert decision.reason is None


def test_non_http_scheme_is_rejected_by_contract():
    """Documents the fixed behavior: canonicalize_url() preserves non-web
    schemes (mailto:, ftp:, javascript:) instead of force-rewriting them into
    https (news_collector/utils/url_canonicalizer.py). A ftp:// URL therefore
    reaches CollectorArticleModel untouched and fails Pydantic AnyHttpUrl
    validation — it is rejected by the contract, not silently coerced into a
    bogus https URL. This module intentionally does not re-implement scheme
    checking; the scheme rejection lives in the contract boundary."""
    with pytest.raises(Exception):
        _article(url="ftp://example.com/article")
