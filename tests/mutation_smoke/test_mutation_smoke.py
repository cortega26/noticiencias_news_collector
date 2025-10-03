"""Minimal deterministic tests for mutation smoke runs."""

from src.reranker import rerank_articles
from src.utils.text_cleaner import normalize_text


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
