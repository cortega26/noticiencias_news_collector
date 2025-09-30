#!/usr/bin/env python
"""Offline evaluation for ranking metrics (NDCG@k, Precision@k, MRR)."""

from __future__ import annotations

import json
from math import log2
from pathlib import Path
from types import SimpleNamespace
from typing import List, Dict

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from src.scoring.feature_scorer import FeatureBasedScorer


def dcg(relevances: List[float], k: int) -> float:
    result = 0.0
    for i, rel in enumerate(relevances[:k]):
        result += (2**rel - 1) / log2(i + 2)
    return result


def ndcg(relevances: List[float], k: int) -> float:
    ideal = sorted(relevances, reverse=True)
    ideal_dcg = dcg(ideal, k)
    if ideal_dcg == 0:
        return 0.0
    return dcg(relevances, k) / ideal_dcg


def precision_at_k(relevances: List[float], k: int, threshold: float = 1.0) -> float:
    topk = relevances[:k]
    relevant = sum(1 for rel in topk if rel >= threshold)
    return relevant / k


def mrr(relevances: List[float], threshold: float = 1.0) -> float:
    for idx, rel in enumerate(relevances, start=1):
        if rel >= threshold:
            return 1.0 / idx
    return 0.0


def load_dev_set() -> List[Dict[str, object]]:
    path = ROOT / "tests" / "data" / "dev_ranking.json"
    return json.loads(path.read_text(encoding="utf-8"))


def to_article_obj(article_dict: Dict[str, object]) -> SimpleNamespace:
    metadata = article_dict.get("article_metadata", {}) or {}
    data = dict(article_dict)
    data["article_metadata"] = metadata
    return SimpleNamespace(**data)


def evaluate() -> None:
    dev_set = load_dev_set()
    scorer = FeatureBasedScorer()

    ndcg_scores_5 = []
    precision_scores_5 = []
    mrr_scores = []

    for sample in dev_set:
        scored_items = []
        for item in sample["articles"]:
            article_obj = to_article_obj(item["article"])
            score_data = scorer.score_article(article_obj)
            scored_items.append(
                {
                    "id": item["article"]["id"],
                    "score": score_data["final_score"],
                    "relevance": item["relevance"],
                }
            )
        scored_items.sort(key=lambda x: x["score"], reverse=True)
        relevances = [entry["relevance"] for entry in scored_items]
        ndcg_scores_5.append(ndcg(relevances, 5))
        precision_scores_5.append(precision_at_k(relevances, 5))
        mrr_scores.append(mrr(relevances))

    print(f"Queries evaluated: {len(dev_set)}")
    print(f"NDCG@5      : {sum(ndcg_scores_5)/len(ndcg_scores_5):.3f}")
    print(f"Precision@5 : {sum(precision_scores_5)/len(precision_scores_5):.3f}")
    print(f"MRR         : {sum(mrr_scores)/len(mrr_scores):.3f}")


if __name__ == "__main__":
    evaluate()
