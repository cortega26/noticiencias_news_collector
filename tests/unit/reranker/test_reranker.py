from news_collector.reranker.reranker import rerank_articles


def test_rerank_sorting():
    articles = [
        {"id": 1, "final_score": 0.5},
        {"id": 2, "final_score": 0.9},
        {"id": 3, "final_score": 0.1},
    ]

    ranked = rerank_articles(
        articles, limit=3, source_cap_percentage=1.0, topic_cap_percentage=1.0, seed=42
    )
    assert ranked[0]["id"] == 2


def test_rerank_empty():
    assert rerank_articles([], 3, 1.0, 1.0, 42) == []


def test_rerank_filtering():
    # A source cap of 0.5 on a limit of 2 allows one article per source.
    articles = [
        {"id": 1, "final_score": 0.3, "source_id": "a"},
        {"id": 2, "final_score": 0.2, "source_id": "a"},
        {"id": 3, "final_score": 0.1, "source_id": "b"},
    ]

    ranked = rerank_articles(
        articles, limit=2, source_cap_percentage=0.5, topic_cap_percentage=1.0, seed=42
    )
    assert [article["id"] for article in ranked] == [1, 3]
