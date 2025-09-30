#!/usr/bin/env python
"""Compare current scorer outputs against a baseline snapshot."""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterable, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from src.scoring import feature_scorer
from src.scoring.feature_scorer import FeatureBasedScorer


@dataclass
class ArticleResult:
    article_id: str
    final_score: float
    should_include: bool
    baseline_score: float | None = None
    baseline_should_include: bool | None = None

    @property
    def score_delta(self) -> float | None:
        if self.baseline_score is None:
            return None
        return self.final_score - self.baseline_score


@dataclass
class Dataset:
    entries: List[Dict[str, object]]
    frozen_at: datetime | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "tests" / "data" / "scoring_golden.json",
        help="Path to JSON with article payloads. Defaults to the scoring golden dataset.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Optional JSON file containing baseline scores. "
            "If omitted, expected values from the dataset are used when available."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        action="append",
        default=[5, 10],
        help="K values for precision@K (can be repeated). Defaults to 5 and 10.",
    )
    parser.add_argument(
        "--report-top",
        type=int,
        default=5,
        help="Number of largest score deltas to display in the summary table.",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> Dataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    frozen_at: datetime | None = None
    if isinstance(raw, Mapping):
        frozen = raw.get("frozen_at")
        if isinstance(frozen, str):
            frozen_at = datetime.fromisoformat(frozen.replace("Z", "+00:00"))
        entries = raw.get("articles") or raw.get("items") or raw.get("samples")
        if entries is None:
            raise ValueError("Dataset JSON must contain an 'articles' array or be a list")
    else:
        entries = raw
    if not isinstance(entries, list):
        raise TypeError("Dataset entries must be a list")
    return Dataset(entries=list(entries), frozen_at=frozen_at)


def load_baseline(entries: Sequence[Dict[str, object]], baseline_path: Path | None) -> Dict[str, Dict[str, object]]:
    if baseline_path is None:
        baseline: Dict[str, Dict[str, object]] = {}
        for entry in entries:
            expected = entry.get("expected") if isinstance(entry, Mapping) else None
            if isinstance(expected, Mapping):
                article_id = str(entry.get("id") or entry.get("article", {}).get("id"))
                baseline[article_id] = {
                    "final_score": expected.get("final_score"),
                    "should_include": expected.get("should_include"),
                }
        return baseline

    raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    if isinstance(raw, Mapping) and "articles" in raw:
        raw = raw["articles"]
    baseline: Dict[str, Dict[str, object]] = {}
    if isinstance(raw, Mapping):
        iterator: Iterable = raw.items()
        for article_id, payload in iterator:
            if isinstance(payload, Mapping):
                baseline[str(article_id)] = {
                    "final_score": payload.get("final_score"),
                    "should_include": payload.get("should_include"),
                }
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            article_id = str(item.get("id"))
            if not article_id:
                continue
            baseline[article_id] = {
                "final_score": item.get("final_score"),
                "should_include": item.get("should_include"),
            }
    else:
        raise TypeError("Baseline payload must be a mapping or list")
    return baseline


def to_namespace(article_payload: Mapping[str, object]) -> SimpleNamespace:
    prepared = dict(article_payload)
    prepared.setdefault("article_metadata", {})
    return SimpleNamespace(**prepared)


@contextmanager
def freeze_datetime(target: datetime | None):
    if target is None:
        yield
        return
    original = feature_scorer.datetime

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz:
                return target.astimezone(tz)
            return target

    feature_scorer.datetime = _FrozenDateTime
    try:
        yield
    finally:
        feature_scorer.datetime = original


def score_articles(entries: Sequence[Dict[str, object]], baseline_map: Mapping[str, Dict[str, object]]) -> List[ArticleResult]:
    scorer = FeatureBasedScorer()
    results: List[ArticleResult] = []

    for entry in entries:
        article_info: Mapping[str, object]
        if isinstance(entry, Mapping) and "article" in entry:
            article_info = entry["article"]  # type: ignore[assignment]
        else:
            article_info = entry  # type: ignore[assignment]

        article_id = str(
            (entry.get("id") if isinstance(entry, Mapping) else None)
            or article_info.get("id")
        )
        article_obj = to_namespace(article_info)
        scored = scorer.score_article(article_obj)

        baseline = baseline_map.get(article_id)
        baseline_score = (
            float(baseline["final_score"]) if baseline and baseline.get("final_score") is not None else None
        )
        baseline_include = (
            bool(baseline["should_include"]) if baseline and baseline.get("should_include") is not None else None
        )

        results.append(
            ArticleResult(
                article_id=article_id,
                final_score=float(scored["final_score"]),
                should_include=bool(scored["should_include"]),
                baseline_score=baseline_score,
                baseline_should_include=baseline_include,
            )
        )

    return results


def precision_at_k(results: Sequence[ArticleResult], positives: Mapping[str, bool], k: int) -> float:
    if k <= 0:
        return 0.0
    ranked = sorted(results, key=lambda item: item.final_score, reverse=True)[:k]
    if not ranked:
        return 0.0
    hits = sum(1 for item in ranked if positives.get(item.article_id))
    return hits / min(k, len(ranked))


def compute_coverage(results: Sequence[ArticleResult], positives: Mapping[str, bool]) -> float:
    baseline_positive_ids = {article_id for article_id, flag in positives.items() if flag}
    if not baseline_positive_ids:
        return 1.0
    current_positive_ids = {item.article_id for item in results if item.should_include}
    return len(baseline_positive_ids & current_positive_ids) / len(baseline_positive_ids)


def main() -> None:
    args = parse_args()
    dataset = load_dataset(args.dataset)
    baseline_map = load_baseline(dataset.entries, args.baseline)

    with freeze_datetime(dataset.frozen_at):
        results = score_articles(dataset.entries, baseline_map)

    positive_lookup = {
        article_id: bool(payload.get("should_include"))
        for article_id, payload in baseline_map.items()
    }

    print("=== Score Delta Summary ===")
    ranked_by_delta = sorted(
        [
            item
            for item in results
            if item.score_delta is not None and item.baseline_should_include is not None
        ],
        key=lambda x: abs(x.score_delta or 0.0),
        reverse=True,
    )

    if ranked_by_delta:
        print(f"Top {min(args.report_top, len(ranked_by_delta))} absolute score changes:")
        for item in ranked_by_delta[: args.report_top]:
            baseline_flag = "Y" if item.baseline_should_include else "N"
            current_flag = "Y" if item.should_include else "N"
            delta = item.score_delta or 0.0
            print(
                f"  - {item.article_id}: Δscore={delta:+.4f} | baseline_included={baseline_flag} | current_included={current_flag}"
            )
    else:
        print("No baseline values found in dataset; skipping delta table.")

    unique_k = sorted(set(k for k in args.top_k if isinstance(k, int) and k > 0))
    if not unique_k:
        unique_k = [5]

    print("\nPrecision against baseline inclusions:")
    for k in unique_k:
        precision = precision_at_k(results, positive_lookup, k)
        print(f"  Precision@{k}: {precision:.3f}")

    coverage = compute_coverage(results, positive_lookup)
    print(f"\nBaseline coverage by current scorer: {coverage:.3f}")

    missing_baseline = [item.article_id for item in results if item.article_id not in baseline_map]
    if missing_baseline:
        print("\nWarning: baseline scores missing for the following articles:")
        for article_id in missing_baseline:
            print(f"  - {article_id}")


if __name__ == "__main__":
    main()
