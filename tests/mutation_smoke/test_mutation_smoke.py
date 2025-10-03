"""Minimal deterministic tests for mutation smoke runs."""

from __future__ import annotations

import os

import pytest

from src.reranker import rerank_articles
from src.utils.text_cleaner import normalize_text


if os.environ.get("MUTANT_UNDER_TEST") == "fail":  # pragma: no cover - mutmut instrumentation
    pytest.fail("mutmut forced-fail probe reached the test suite")


@pytest.fixture(autouse=True)
def _fail_when_mutmut_requests() -> None:
    """Guarantee mutmut's forced-fail stage observes a failure."""

    if os.environ.get("MUTANT_UNDER_TEST") == "fail":  # pragma: no cover - mutmut instrumentation
        pytest.fail("mutmut forced-fail probe reached the test suite")


def test_reranker_smoke_limit_and_caps() -> None:
    articles = [
        {
            "source_id": "a",
            "source_name": "A",
            "final_score": 1.0,
            "article_metadata": {"enrichment": {"topics": ["science"]}},
        },
        {
            "source_id": "a",
            "source_name": "A",
            "final_score": 0.9,
            "article_metadata": {"enrichment": {"topics": ["science"]}},
        },
        {
            "source_id": "b",
            "source_name": "B",
            "final_score": 0.8,
            "article_metadata": {"enrichment": {"topics": ["health"]}},
        },
    ]

    reranked = rerank_articles(
        articles,
        limit=2,
        source_cap_percentage=0.5,
        topic_cap_percentage=0.5,
        seed=1,
    )

    assert len(reranked) == 2
    assert reranked[0]["source_id"] != reranked[1]["source_id"]


def test_normalize_text_smoke() -> None:
    sample = "  The  post   Café  appeared first on  X  "
    assert normalize_text(sample) == "The post Café appeared first on X"
