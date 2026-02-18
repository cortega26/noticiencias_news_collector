#!/usr/bin/env python
"""Sanity check enrichment accuracy against golden dataset."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.enrichment.pipeline import EnrichmentPipeline


def main() -> None:
    data_path = ROOT / "tests" / "data" / "golden_articles.json"
    samples = json.loads(data_path.read_text(encoding="utf-8"))

    pipeline = EnrichmentPipeline()
    total = len(samples)
    correct_language = correct_sentiment = correct_topics = correct_entities = 0

    for sample in samples:
        expected = sample["expected"]
        result = pipeline.enrich_article(sample)

        if result["language"] == expected["language"]:
            correct_language += 1
        if result["sentiment"] == expected["sentiment"]:
            correct_sentiment += 1
        if result["topics"] == expected["topics"]:
            correct_topics += 1
        if result["entities"] == expected["entities"]:
            correct_entities += 1

    print("Samples:", total)
    print(
        f"Language accuracy : {correct_language}/{total} ({correct_language / total:.2%})"
    )
    print(
        f"Sentiment accuracy: {correct_sentiment}/{total} ({correct_sentiment / total:.2%})"
    )
    print(
        f"Topics accuracy   : {correct_topics}/{total} ({correct_topics / total:.2%})"
    )
    print(
        f"Entities accuracy : {correct_entities}/{total} ({correct_entities / total:.2%})"
    )


if __name__ == "__main__":
    main()
