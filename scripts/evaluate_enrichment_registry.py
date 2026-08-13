#!/usr/bin/env python
"""Baseline offline evaluator for plan 048 Step 3 (curated enrichment registry spike).

Runs the shipped enrichment pipeline (pattern_v1) against a reviewed,
gold-labeled subset of a corpus built to the `tests/data/enrichment_eval.jsonl`
schema, and reports precision/recall/F1 for topics and entities, per-language
slices, general/multi-label rates, latency, and top error clusters.

Per the plan's own Step 3 Verify line, an evaluation corpus with fewer than
200 reviewed (gold-labeled) records is NOT sufficient evaluation evidence —
this script says so explicitly in its report rather than presenting a
small-sample number as a real baseline.

Usage:
    python scripts/evaluate_enrichment_registry.py \\
        --model pattern_v1 \\
        --corpus tests/data/enrichment_eval.jsonl \\
        --output reports/evaluation/enrichment-pattern-v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from news_collector.enrichment.pipeline import EnrichmentPipeline  # noqa: E402

MIN_SUFFICIENT_EVIDENCE = 200


def _load_reviewed_records(corpus_path: Path) -> List[Dict[str, Any]]:
    records = []
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("review_status") == "reviewed":
            records.append(rec)
    return records


def _set_prf(predicted: Sequence[str], gold: Sequence[str]) -> Dict[str, float]:
    pred_set, gold_set = set(predicted), set(gold)
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (
        (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _aggregate(per_record: List[Dict[str, float]]) -> Dict[str, float]:
    if not per_record:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "micro_precision": 0.0,
            "micro_recall": 0.0,
            "micro_f1": 0.0,
        }
    macro_p = sum(r["precision"] for r in per_record) / len(per_record)
    macro_r = sum(r["recall"] for r in per_record) / len(per_record)
    macro_f1 = sum(r["f1"] for r in per_record) / len(per_record)
    tp = sum(r["tp"] for r in per_record)
    fp = sum(r["fp"] for r in per_record)
    fn = sum(r["fn"] for r in per_record)
    micro_p = tp / (tp + fp) if (tp + fp) else 1.0
    micro_r = tp / (tp + fn) if (tp + fn) else 1.0
    micro_f1 = (
        (2 * micro_p * micro_r / (micro_p + micro_r)) if (micro_p + micro_r) else 0.0
    )
    return {
        "precision": round(macro_p, 4),
        "recall": round(macro_r, 4),
        "f1": round(macro_f1, 4),
        "micro_precision": round(micro_p, 4),
        "micro_recall": round(micro_r, 4),
        "micro_f1": round(micro_f1, 4),
    }


def evaluate(
    records: List[Dict[str, Any]], pipeline: EnrichmentPipeline
) -> Dict[str, Any]:
    topic_scores: List[Dict[str, float]] = []
    entity_scores: List[Dict[str, float]] = []
    by_language: Dict[str, List[Dict[str, float]]] = {}
    fp_topics: Counter = Counter()
    fn_topics: Counter = Counter()
    fp_entities: Counter = Counter()
    fn_entities: Counter = Counter()
    general_count = 0
    multi_label_count = 0
    durations_ms: List[float] = []
    changed_examples: List[Dict[str, Any]] = []

    for rec in records:
        start = time.perf_counter()
        result = pipeline.enrich_article(
            {"title": rec["title"], "summary": rec["summary"]}
        )
        durations_ms.append((time.perf_counter() - start) * 1000)

        predicted_topics = list(result.get("topics", []))
        predicted_entities = list(result.get("entities", []))
        gold_topics = rec["gold_topics"] or []
        gold_entities = rec["gold_entities"] or []

        t_score = _set_prf(predicted_topics, gold_topics)
        e_score = _set_prf(predicted_entities, gold_entities)
        topic_scores.append(t_score)
        entity_scores.append(e_score)
        by_language.setdefault(rec["language"], []).append(t_score)

        for topic in set(predicted_topics) - set(gold_topics):
            fp_topics[topic] += 1
        for topic in set(gold_topics) - set(predicted_topics):
            fn_topics[topic] += 1
        for ent in set(predicted_entities) - set(gold_entities):
            fp_entities[ent] += 1
        for ent in set(gold_entities) - set(predicted_entities):
            fn_entities[ent] += 1

        if predicted_topics == ["general"]:
            general_count += 1
        if len(predicted_topics) > 1:
            multi_label_count += 1

        if t_score["f1"] < 1.0 or e_score["f1"] < 1.0:
            changed_examples.append(
                {
                    "id": rec["id"],
                    "language": rec["language"],
                    "predicted_topics": predicted_topics,
                    "gold_topics": gold_topics,
                    "predicted_entities": predicted_entities,
                    "gold_entities": gold_entities,
                }
            )

    n = len(records)
    return {
        "record_count": n,
        "sufficient_evidence": n >= MIN_SUFFICIENT_EVIDENCE,
        "evidence_note": (
            (
                f"{n} reviewed record(s) — per plan 048's own Step 3 Verify line, "
                f"fewer than {MIN_SUFFICIENT_EVIDENCE} reviewed records is NOT "
                "sufficient evaluation evidence. Treat these numbers as a "
                "small-sample sanity check, not a baseline to make an adoption "
                "decision against."
            )
            if n < MIN_SUFFICIENT_EVIDENCE
            else "Sufficient reviewed evidence per the plan's own threshold."
        ),
        "topics": _aggregate(topic_scores),
        "entities": _aggregate(entity_scores),
        "by_language": {
            lang: _aggregate(scores) for lang, scores in by_language.items()
        },
        "general_rate": round(general_count / n, 4) if n else 0.0,
        "multi_label_rate": round(multi_label_count / n, 4) if n else 0.0,
        "latency_ms": {
            "mean": round(sum(durations_ms) / n, 3) if n else 0.0,
            "max": round(max(durations_ms), 3) if durations_ms else 0.0,
        },
        "top_false_positive_topics": fp_topics.most_common(5),
        "top_false_negative_topics": fn_topics.most_common(5),
        "top_false_positive_entities": fp_entities.most_common(5),
        "top_false_negative_entities": fn_entities.most_common(5),
        "changed_examples": changed_examples[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="pattern_v1")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--compare",
        default=None,
        help="Candidate model name to compare against (plan 048 Step 4): "
        "evaluates the same corpus with the candidate config from "
        "scripts/enrichment_candidate.py and reports per-metric deltas. "
        "The candidate is NOT wired into production config.toml.",
    )
    args = parser.parse_args()

    records = _load_reviewed_records(args.corpus)
    pipeline = EnrichmentPipeline()

    corpus_hash = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
    report = {
        "model": args.model,
        "model_version": pipeline.model_version,
        "corpus_path": str(args.corpus),
        "corpus_sha256": corpus_hash,
        **evaluate(records, pipeline),
    }

    # Optional paired comparison against a curated candidate (plan 048
    # Step 4): evaluate the same corpus with the candidate config and
    # attach the delta. The candidate lives in scripts/enrichment_candidate.py
    # and is NOT wired into production config.
    if args.compare:
        try:
            from scripts.enrichment_candidate import CANDIDATE_CONFIG
        except ImportError as exc:  # pragma: no cover - defensive
            print(
                f"error: --compare {args.compare!r} requested but "
                f"scripts/enrichment_candidate.py is unavailable: {exc}",
                file=sys.stderr,
            )
            return 2
        candidate_pipeline = EnrichmentPipeline(config=CANDIDATE_CONFIG)
        candidate_report = evaluate(records, candidate_pipeline)
        baseline = {k: report[k] for k in ("topics", "entities") if k in report}
        report["candidate"] = {
            "model": args.compare,
            "model_version": candidate_pipeline.model_version,
            **candidate_report,
            "delta_topics_f1": round(
                candidate_report["topics"]["f1"] - report["topics"]["f1"], 4
            ),
            "delta_topics_precision": round(
                candidate_report["topics"]["precision"] - report["topics"]["precision"],
                4,
            ),
            "delta_topics_recall": round(
                candidate_report["topics"]["recall"] - report["topics"]["recall"], 4
            ),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"Evaluated {report['record_count']} reviewed record(s) against model_version={report['model_version']}"
    )
    print(report["evidence_note"])
    if args.compare:
        cand = report["candidate"]
        print(
            f"Candidate {cand['model_version']}: topics F1 {cand['topics']['f1']:.3f} "
            f"(delta {cand['delta_topics_f1']:+.3f}), precision {cand['topics']['precision']:.3f} "
            f"(delta {cand['delta_topics_precision']:+.3f}), recall {cand['topics']['recall']:.3f} "
            f"(delta {cand['delta_topics_recall']:+.3f})"
        )
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
