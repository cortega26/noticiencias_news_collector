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
from datetime import datetime, timedelta, timezone

import pytest

from news_collector.collectors.admission import (
    AdmissionReason,
    effective_max_age_days,
    evaluate_admission,
    is_too_old,
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
        # Relative: the admission policy now rejects items past the age cutoff.
        "published_date": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
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


# ------------------------------------------------------------- age cutoff


def test_effective_cutoff_is_the_smaller_of_collection_and_candidacy(config):
    def snap(collection, candidacy):
        return dataclasses.replace(
            config,
            collection_config={
                **config.collection_config,
                "recent_days_threshold": collection,
            },
            scoring_config={
                **config.scoring_config,
                "candidate_max_age_days": candidacy,
            },
        )

    assert effective_max_age_days(snap(365, 30)) == 30  # collection never looser
    assert effective_max_age_days(snap(7, 30)) == 7
    assert effective_max_age_days(snap(90, 90)) == 90
    assert effective_max_age_days(config) == 30  # shipped config.toml


def test_is_too_old_boundaries_naive_and_missing_dates():
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert is_too_old(now - timedelta(days=29), 30, now) is False
    assert is_too_old(now - timedelta(days=31), 30, now) is True
    assert is_too_old(now + timedelta(days=2), 30, now) is False  # future-dated
    assert is_too_old((now - timedelta(days=40)).replace(tzinfo=None), 30, now) is True
    assert is_too_old(None, 30, now) is False
    assert is_too_old("2020-01-01", 30, now) is False  # not a datetime: unjudgeable


def test_old_article_is_rejected_with_too_old_reason(config):
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    decision = evaluate_admission(_article(published_date=old), config)
    assert decision.accepted is False and decision.reason is AdmissionReason.TOO_OLD
    assert decision.details["max_age_days"] == 30


def test_article_just_inside_the_window_is_accepted(config):
    recent = (datetime.now(timezone.utc) - timedelta(days=29)).isoformat()
    assert evaluate_admission(_article(published_date=recent), config).accepted is True


def test_collection_cutoff_never_exceeds_default_retention(config):
    """Seen-tracking relies on stored rows: retention must outlive the cutoff."""
    import inspect

    from news_collector.storage.analytics_repository import AnalyticsRepository

    keep = (
        inspect.signature(AnalyticsRepository.cleanup_old_data)
        .parameters["days_to_keep"]
        .default
    )
    assert keep >= effective_max_age_days(config)
