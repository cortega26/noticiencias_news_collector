"""Mutation-driven tests for ``collectors.admission`` (surviving mutants of the pilot run).

The module had 100 % line coverage but 18/102 mutants survived: nothing pinned the
built-in defaults (used when a config key is absent), the exact age boundary, the
floor of the age window, or the ``details`` payload that callers log and count.
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


def _cfg(**overrides):
    return dataclasses.replace(get_runtime_config(), **overrides)


def _article(**overrides) -> CollectorArticleModel:
    fields = {
        "url": "https://example.com/article",
        "title": "A sufficiently long scientific headline",
        "summary": "",
        "content": "x" * 3000,
        "source_id": "src-1",
        "source_name": "Source One",
        "category": "science",
        "published_date": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    fields.update(overrides)
    return CollectorArticleModel(**fields)


# ----------------------------------------------------------- age window defaults


def test_age_window_defaults_to_30_days_when_keys_are_absent():
    assert effective_max_age_days(_cfg(collection_config={}, scoring_config={})) == 30


def test_each_missing_key_falls_back_to_30_independently():
    assert (
        effective_max_age_days(
            _cfg(collection_config={"recent_days_threshold": 45}, scoring_config={})
        )
        == 30
    )
    assert (
        effective_max_age_days(
            _cfg(collection_config={}, scoring_config={"candidate_max_age_days": 12})
        )
        == 12
    )
    assert (
        effective_max_age_days(
            _cfg(collection_config={"recent_days_threshold": 7}, scoring_config={})
        )
        == 7
    )
    # the collection default (30) must bind when candidacy is looser
    assert (
        effective_max_age_days(
            _cfg(collection_config={}, scoring_config={"candidate_max_age_days": 100})
        )
        == 30
    )


@pytest.mark.parametrize("configured", [0, -5])
def test_age_window_never_drops_below_one_day(configured):
    cfg = _cfg(
        collection_config={"recent_days_threshold": configured},
        scoring_config={"candidate_max_age_days": configured},
    )
    assert effective_max_age_days(cfg) == 1


def test_exact_cutoff_is_not_too_old_but_one_second_later_is():
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    boundary = now - timedelta(days=30)
    assert is_too_old(boundary, 30, now=now) is False
    assert is_too_old(boundary - timedelta(seconds=1), 30, now=now) is True


# --------------------------------------------------------- content/title defaults


def test_title_and_content_minimums_default_to_10_and_1000():
    cfg = _cfg(text_processing_config={})
    at_limit = _article(content="x" * 1000)
    assert evaluate_admission(at_limit, cfg).accepted is True
    short = evaluate_admission(_article(content="x" * 999), cfg)
    assert short.reason is AdmissionReason.CONTENT_TOO_SHORT
    assert short.details == {"length": 999, "min_required": 1000}


def test_title_default_minimum_is_10():
    cfg = _cfg(text_processing_config={})
    article = _article()
    object.__setattr__(
        article, "title", "123456789"
    )  # 9 chars, model bypassed on purpose
    decision = evaluate_admission(article, cfg)
    assert decision.reason is AdmissionReason.TITLE_TOO_SHORT
    assert decision.details == {"length": 9, "min_required": 10}


# ------------------------------------------------------------- details payloads


def test_too_old_details_carry_the_iso_date_and_effective_window():
    published = datetime.now(timezone.utc) - timedelta(days=90)
    cfg = _cfg(
        collection_config={"recent_days_threshold": 30},
        scoring_config={"candidate_max_age_days": 30},
    )
    decision = evaluate_admission(_article(published_date=published.isoformat()), cfg)
    assert decision.accepted is False and decision.reason is AdmissionReason.TOO_OLD
    assert decision.details == {
        "published_date": _article(
            published_date=published.isoformat()
        ).published_date.isoformat(),
        "max_age_days": 30,
    }


def test_title_too_short_details_carry_length_and_minimum():
    cfg = _cfg(
        text_processing_config={
            **get_runtime_config().text_processing_config,
            "min_title_length": 50,
        }
    )
    decision = evaluate_admission(_article(), cfg)
    assert decision.reason is AdmissionReason.TITLE_TOO_SHORT
    assert decision.details["length"] == len("A sufficiently long scientific headline")
    assert decision.details["min_required"] == 50
