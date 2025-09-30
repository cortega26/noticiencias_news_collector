#!/usr/bin/env python
"""Profile ingestion -> normalize -> enrich -> score pipeline variants."""

from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import mean

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.enrichment.pipeline import EnrichmentPipeline
from src.scoring import create_scorer
from types import SimpleNamespace

from src.utils.dedupe import normalize_article_text


DATA_PATH = ROOT / "tests" / "data" / "dev_ranking.json"


def load_articles():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    articles = []
    for sample in raw:
        for item in sample["articles"]:
            articles.append(item["article"])
    return articles


def simulate_ingestion(articles):
    normalized = []
    for art in articles:
        metadata = art.get("article_metadata", {}) or {}
        title = metadata.get("normalized_title") or art.get("title", "")
        summary = metadata.get("normalized_summary") or art.get("summary", "")
        normalized.append(
            {
                **art,
                "article_metadata": metadata,
                "normalized_data": normalize_article_text(title, summary),
            }
        )
    return normalized


def profile_variant(label: str, scorer_mode: str):
    start = time.perf_counter()
    articles = load_articles()

    ingest_start = time.perf_counter()
    normalized = simulate_ingestion(articles)
    ingest_time = time.perf_counter() - ingest_start

    enrichment = EnrichmentPipeline()
    enrich_start = time.perf_counter()
    enriched = []
    for art in normalized:
        metadata = art["article_metadata"]
        enrichment_payload = enrichment.enrich_article(
            {
                "title": art.get("title"),
                "summary": art.get("summary"),
                "content": metadata.get("normalized_summary", ""),
                "language": metadata.get("enrichment", {}).get("language"),
            }
        )
        metadata.setdefault("enrichment", {}).update(enrichment_payload)
        enriched.append(art)
    enrich_time = time.perf_counter() - enrich_start

    scorer = create_scorer(mode=scorer_mode)
    score_start = time.perf_counter()
    scores = []
    per_article_times = []
    for art in enriched:
        defaults = {
            "article_metadata": art.get("article_metadata", {}),
            "source_id": art.get("source_id"),
            "source_name": art.get("source_name"),
            "id": art.get("id", art.get("article_id", -1)),
            "peer_reviewed": art.get("article_metadata", {})
            .get("source_metadata", {})
            .get("peer_reviewed", False),
            "is_preprint": art.get("article_metadata", {})
            .get("source_metadata", {})
            .get("is_preprint", False),
            "published_date": art.get("published_date"),
            "word_count": art.get("word_count", 400),
            "duplication_confidence": art.get("duplication_confidence", 0.0),
            "cluster_id": art.get("cluster_id"),
            "doi": art.get("article_metadata", {})
            .get("source_metadata", {})
            .get("doi"),
            "journal": art.get("article_metadata", {})
            .get("source_metadata", {})
            .get("journal"),
        }
        article_ns = SimpleNamespace(**{**art, **defaults})
        article_start = time.perf_counter()
        scores.append(scorer.score_article(article_ns))
        per_article_times.append(time.perf_counter() - article_start)
    score_time = time.perf_counter() - score_start

    total = time.perf_counter() - start
    avg_score = mean(entry["final_score"] for entry in scores)
    throughput = len(enriched) / total * 3600 if total else 0.0
    score_p95 = 0.0
    if per_article_times:
        ordered = sorted(per_article_times)
        idx = max(int(len(ordered) * 0.95) - 1, 0)
        score_p95 = ordered[idx]

    print(f"Variant: {label}")
    print(f"  ingest_time  : {ingest_time:.4f}s")
    print(f"  enrich_time  : {enrich_time:.4f}s")
    print(f"  score_time   : {score_time:.4f}s")
    print(f"  total_time   : {total:.4f}s")
    print(f"  avg_score    : {avg_score:.3f}")
    print(f"  throughput   : {throughput:.1f} articles/hour")
    print(f"  score_p95    : {score_p95*1000:.2f} ms/article")
    print()


def main():
    profile_variant("baseline-basic", scorer_mode="basic")
    profile_variant("optimized-advanced", scorer_mode="advanced")


if __name__ == "__main__":
    main()
