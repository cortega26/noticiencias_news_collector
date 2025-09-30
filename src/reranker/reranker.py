"""Deterministic reranker enforcing source/topic caps and tie-breaking."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List


def rerank_articles(
    articles: List[Dict[str, object]],
    limit: int,
    source_cap_percentage: float,
    topic_cap_percentage: float,
    seed: int,
) -> List[Dict[str, object]]:
    if not articles:
        return []

    rng = random.Random(seed)
    shuffled = articles[:]
    rng.shuffle(shuffled)

    def tie_key(article: Dict[str, object]):
        return (
            article.get("final_score", 0.0),
            article.get("published_date", ""),
            article.get("source_name", article.get("source_id", "")),
        )

    shuffled.sort(key=tie_key, reverse=True)

    max_source = max(1, int(limit * source_cap_percentage))
    max_topic = max(1, int(limit * topic_cap_percentage))
    source_counts = defaultdict(int)
    topic_counts = defaultdict(int)

    reranked: List[Dict[str, object]] = []
    for article in shuffled:
        if len(reranked) >= limit:
            break

        source = article.get("source_id") or article.get("source_name") or "unknown"
        topics = (
            article.get("article_metadata", {}).get("enrichment", {}).get("topics", [])
        )

        if source_counts[source] >= max_source:
            continue
        if topics and any(topic_counts[t] >= max_topic for t in topics):
            continue

        reranked.append(article)
        source_counts[source] += 1
        for t in topics:
            topic_counts[t] += 1

    return reranked[:limit]


__all__ = ["rerank_articles"]
