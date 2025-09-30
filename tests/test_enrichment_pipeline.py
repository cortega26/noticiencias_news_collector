import json
from pathlib import Path

import pytest

from src.enrichment.pipeline import EnrichmentPipeline


DATA_PATH = Path(__file__).resolve().parent / "data" / "golden_articles.json"


with DATA_PATH.open(encoding="utf-8") as fh:
    GOLDEN_ARTICLES = json.load(fh)


@pytest.mark.parametrize(
    "sample", GOLDEN_ARTICLES, ids=[entry["id"] for entry in GOLDEN_ARTICLES]
)
def test_enrichment_matches_golden(sample):
    expected = sample["expected"]
    pipeline = EnrichmentPipeline()
    result = pipeline.enrich_article(sample)

    assert result["language"] == expected["language"]
    assert result["sentiment"] == expected["sentiment"]
    assert result["topics"] == expected["topics"]
    assert result["entities"] == expected["entities"]
