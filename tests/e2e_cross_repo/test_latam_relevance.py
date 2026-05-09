import json
from pathlib import Path

from news_collector.scoring.latam_relevance import (
    rank_candidates_for_latam_audience,
    score_candidate_for_latam_audience,
)


def test_latam_relevance_golden_ranking():
    fixture_path = (
        Path(__file__).resolve().parents[1] / "data" / "latam_relevance_golden.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    candidates = fixture["candidates"]
    ranked_indices = rank_candidates_for_latam_audience(candidates)
    ranked_ids = [candidates[idx]["id"] for idx in ranked_indices]

    assert ranked_ids == fixture["expected_order"]


def test_latam_relevance_penalizes_low_value_institutional_noise():
    high_value = {
        "title": "Brazil study tracks dengue spread with new public health data",
        "summary": (
            "Researchers in Brazil analyzed public health records and satellite "
            "signals to improve dengue early warning systems across urban regions."
        ),
        "source_name": "Public Health Journal",
    }
    low_value = {
        "title": "Campus leadership award celebrates donor partnership",
        "summary": (
            "The university announced an internal award and a new donor-backed "
            "partnership during a campus leadership breakfast."
        ),
        "source_name": "University News",
    }

    assert score_candidate_for_latam_audience(
        high_value
    ) > score_candidate_for_latam_audience(low_value)
