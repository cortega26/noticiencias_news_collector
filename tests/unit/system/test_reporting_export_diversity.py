"""Export shortlist diversity caps (plan 068).

`export_latest_articles` must apply the same deterministic source/topic
caps as `get_top_articles` (same operator-tunable scoring-config knobs),
so a dominant source or topic cannot fill the publishable shortlist.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from news_collector.storage.models import Article
from news_collector.system import reporting


def _article(
    id: int,
    source: str,
    score: float,
    topics: tuple[str, ...] = (),
) -> Article:
    return Article(
        id=id,
        title=f"title {id}",
        url=f"https://example.com/{id}",
        summary="summary",
        content="content",
        source_id=source,
        source_name=source,
        final_score=score,
        article_metadata={"enrichment": {"topics": list(topics)}},
    )


def _system(
    articles: list[Article], monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    monkeypatch.setattr(
        reporting,
        "get_runtime_config",
        lambda: SimpleNamespace(
            scoring_config={
                "candidate_max_age_days": 30,
                "source_cap_percentage": 0.5,
                "topic_cap_percentage": 0.5,
                "reranker_seed": 42,
            }
        ),
    )
    return SimpleNamespace(
        is_initialized=True,
        db_manager=SimpleNamespace(
            get_articles_by_score=lambda **kwargs: list(articles)
        ),
        logger=None,
    )


def test_export_applies_source_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = [
        _article(1, "dom", 0.90),
        _article(2, "dom", 0.80),
        _article(3, "dom", 0.70),
        _article(4, "dom", 0.60),
        _article(5, "other", 0.65),
    ]
    payload = reporting.export_latest_articles(_system(articles, monkeypatch), limit=2)
    # limit=2 with a 0.5 cap ⇒ at most 1 per source: the minority article
    # survives despite scoring below the dominant runner-up.
    assert [a["id"] for a in payload["articles"]] == [1, 5]
    assert payload["article_count"] == 2


def test_export_applies_topic_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = [
        _article(1, "s1", 0.90, ("mars",)),
        _article(2, "s2", 0.80, ("mars",)),
        _article(3, "s3", 0.70, ("mars",)),
        _article(4, "s4", 0.60, ("europa",)),
    ]
    payload = reporting.export_latest_articles(_system(articles, monkeypatch), limit=2)
    assert [a["id"] for a in payload["articles"]] == [1, 4]
    assert payload["article_count"] == 2


def test_export_empty_input_exports_empty_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = reporting.export_latest_articles(_system([], monkeypatch), limit=10)
    assert payload["articles"] == []
    assert payload["article_count"] == 0


def test_export_rerank_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = [_article(i, f"s{i % 3}", 0.9 - i * 0.01) for i in range(12)]
    first = reporting.export_latest_articles(_system(articles, monkeypatch), limit=6)
    second = reporting.export_latest_articles(_system(articles, monkeypatch), limit=6)
    assert [a["id"] for a in first["articles"]] == [a["id"] for a in second["articles"]]
