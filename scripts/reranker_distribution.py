#!/usr/bin/env python
"""Compare source/topic distributions before and after reranker."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from config import SCORING_CONFIG

from src.reranker import rerank_articles


def summarize(counter: Counter, total: int) -> Dict[str, str]:
    return {key: f"{value} ({value / total:.1%})" for key, value in counter.items()}


def main() -> None:
    data_path = ROOT / "tests" / "data" / "dev_ranking.json"
    samples = json.loads(data_path.read_text(encoding="utf-8"))

    for sample in samples:
        query = sample["query"]
        original_articles = [item["article"] for item in sample["articles"]]

        original_source_counts = Counter(a["source_id"] for a in original_articles)
        original_topic_counts = Counter()
        for article in original_articles:
            for topic in (
                article.get("article_metadata", {})
                .get("enrichment", {})
                .get("topics", [])
            ):
                original_topic_counts[topic] += 1

        reranked = rerank_articles(
            original_articles,
            limit=5,
            source_cap_percentage=SCORING_CONFIG.get("source_cap_percentage", 0.5),
            topic_cap_percentage=SCORING_CONFIG.get("topic_cap_percentage", 0.6),
            seed=SCORING_CONFIG.get("reranker_seed", 1337),
        )

        reranked_source_counts = Counter(a["source_id"] for a in reranked)
        reranked_topic_counts = Counter()
        for article in reranked:
            for topic in (
                article.get("article_metadata", {})
                .get("enrichment", {})
                .get("topics", [])
            ):
                reranked_topic_counts[topic] += 1

        print(f"Query: {query}")
        print(
            "  Before (sources):",
            summarize(original_source_counts, len(original_articles)),
        )
        print(
            "  Before (topics) :",
            summarize(original_topic_counts, sum(original_topic_counts.values()) or 1),
        )
        print("  After  (sources):", summarize(reranked_source_counts, len(reranked)))
        print(
            "  After  (topics) :",
            summarize(reranked_topic_counts, sum(reranked_topic_counts.values()) or 1),
        )
        print()


if __name__ == "__main__":
    main()
