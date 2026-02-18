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
    # If reranker has min_score logic, test it
    pass
