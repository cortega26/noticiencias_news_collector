#!/usr/bin/env python
"""Recompute hashes, simhash, and clusters for historical articles."""

from __future__ import annotations

from typing import List, Tuple

from src.storage.database import DatabaseManager
from src.storage.models import Article
from src.utils.dedupe import (
    duplication_confidence,
    generate_cluster_id,
    hamming_distance,
    normalize_article_text,
    sha256_hex,
    simhash64,
)


def main():
    db = DatabaseManager()
    session = db.SessionLocal()
    clusters: List[Tuple[str, int]] = []  # (cluster_id, centroid_simhash)
    try:
        articles: List[Article] = (
            session.query(Article).order_by(Article.id.asc()).all()
        )
        for article in articles:
            norm_title, norm_summary, normalized_text = normalize_article_text(
                article.title or "", article.summary or ""
            )
            basis = normalized_text or article.url
            article.content_hash = sha256_hex(basis)
            article.simhash = simhash64(basis)
            meta = article.article_metadata or {}
            meta.setdefault("normalized_title", norm_title)
            meta.setdefault("normalized_summary", norm_summary)
            meta.setdefault("original_url", meta.get("original_url", article.url))
            article.article_metadata = meta

            if not clusters:
                cluster_id = generate_cluster_id()
                clusters.append((cluster_id, article.simhash or 0))
                article.cluster_id = cluster_id
                article.duplication_confidence = 1.0
                continue

            best_cluster = None
            best_distance = None
            for cluster_id, centroid_hash in clusters:
                if not article.simhash:
                    continue
                dist = hamming_distance(article.simhash, centroid_hash)
                if best_distance is None or dist < best_distance:
                    best_cluster = cluster_id
                    best_distance = dist

            if (
                article.simhash
                and best_distance is not None
                and best_distance <= db.simhash_threshold
            ):
                article.cluster_id = best_cluster
                article.duplication_confidence = duplication_confidence(best_distance)
            else:
                new_cluster = generate_cluster_id()
                clusters.append((new_cluster, article.simhash or 0))
                article.cluster_id = new_cluster
                article.duplication_confidence = 0.0

        session.commit()
        print(
            f"Reclustered {len(articles)} articles with simhash threshold {db.simhash_threshold}."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
