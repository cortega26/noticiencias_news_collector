from src.reranker import rerank_articles


ARTICLES = [
    {
        "id": 1,
        "source_id": "source_a",
        "source_name": "Source A",
        "final_score": 0.95,
        "published_date": "2025-09-30T08:00:00+00:00",
        "article_metadata": {"enrichment": {"topics": ["science"]}},
    },
    {
        "id": 2,
        "source_id": "source_a",
        "source_name": "Source A",
        "final_score": 0.90,
        "published_date": "2025-09-29T10:00:00+00:00",
        "article_metadata": {"enrichment": {"topics": ["science"]}},
    },
    {
        "id": 3,
        "source_id": "source_b",
        "source_name": "Source B",
        "final_score": 0.85,
        "published_date": "2025-09-30T09:00:00+00:00",
        "article_metadata": {"enrichment": {"topics": ["health"]}},
    },
    {
        "id": 4,
        "source_id": "source_c",
        "source_name": "Source C",
        "final_score": 0.80,
        "published_date": "2025-09-28T12:00:00+00:00",
        "article_metadata": {"enrichment": {"topics": ["climate"]}},
    },
    {
        "id": 5,
        "source_id": "source_d",
        "source_name": "Source D",
        "final_score": 0.75,
        "published_date": "2025-09-27T15:00:00+00:00",
        "article_metadata": {"enrichment": {"topics": ["science"]}},
    },
]


def test_reranker_respects_source_cap():
    reranked = rerank_articles(
        ARTICLES,
        limit=4,
        source_cap_percentage=0.25,
        topic_cap_percentage=1.0,
        seed=123,
    )
    source_ids = [item["source_id"] for item in reranked]
    assert source_ids.count("source_a") == 1


def test_reranker_respects_topic_cap():
    reranked = rerank_articles(
        ARTICLES, limit=4, source_cap_percentage=1.0, topic_cap_percentage=0.5, seed=123
    )
    topics = []
    for item in reranked:
        topics.extend(
            item.get("article_metadata", {}).get("enrichment", {}).get("topics", [])
        )
    assert topics.count("science") <= 2


def test_reranker_tie_breaker_deterministic():
    first = rerank_articles(
        ARTICLES, limit=4, source_cap_percentage=1.0, topic_cap_percentage=1.0, seed=7
    )
    second = rerank_articles(
        ARTICLES, limit=4, source_cap_percentage=1.0, topic_cap_percentage=1.0, seed=7
    )
    assert [a["id"] for a in first] == [a["id"] for a in second]
