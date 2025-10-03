from typing import Dict, List

from hypothesis import given, settings
from hypothesis import strategies as st

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


article_strategy = st.fixed_dictionaries(
    {
        "final_score": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        "published_date": st.text(),
        "source_id": st.text(min_size=1),
        "source_name": st.text(min_size=1),
        "article_metadata": st.dictionaries(
            keys=st.sampled_from(["enrichment"]),
            values=st.dictionaries(
                keys=st.sampled_from(["topics"]),
                values=st.lists(st.text(min_size=1), max_size=3),
                max_size=1,
            ),
            max_size=1,
        ),
    }
).map(lambda d: {**d, "id": hash((d["source_id"], d["published_date"])) & 0xFFFFFFFF})


@given(
    articles=st.lists(article_strategy, min_size=1, max_size=20),
    limit=st.integers(min_value=1, max_value=10),
    source_cap=st.floats(min_value=0.1, max_value=1.0),
    topic_cap=st.floats(min_value=0.1, max_value=1.0),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
@settings(max_examples=50)
def test_reranker_never_exceeds_caps(
    articles: List[Dict[str, object]],
    limit: int,
    source_cap: float,
    topic_cap: float,
    seed: int,
) -> None:
    result = rerank_articles(
        articles,
        limit=limit,
        source_cap_percentage=source_cap,
        topic_cap_percentage=topic_cap,
        seed=seed,
    )

    assert len(result) <= limit

    if not result:
        return

    max_source = max(1, int(limit * source_cap))
    max_topic = max(1, int(limit * topic_cap))

    source_counts = {}
    topic_counts = {}

    for article in result:
        source = article.get("source_id") or article.get("source_name") or "unknown"
        topics = (
            article.get("article_metadata", {}).get("enrichment", {}).get("topics", [])
        )
        unique_topics = set(topics)
        source_counts[source] = source_counts.get(source, 0) + 1
        for topic in unique_topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

        assert source_counts[source] <= max_source
        for topic in unique_topics:
            assert topic_counts[topic] <= max_topic


@given(articles=st.lists(article_strategy, max_size=20), seed=st.integers(0, 2**32 - 1))
@settings(max_examples=50)
def test_reranker_is_seed_deterministic(
    articles: List[Dict[str, object]], seed: int
) -> None:
    first = rerank_articles(
        articles,
        limit=10,
        source_cap_percentage=0.5,
        topic_cap_percentage=0.5,
        seed=seed,
    )
    second = rerank_articles(
        articles,
        limit=10,
        source_cap_percentage=0.5,
        topic_cap_percentage=0.5,
        seed=seed,
    )
    assert first == second
