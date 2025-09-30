"""Golden regression tests for the feature-based scorer."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.scoring import feature_scorer
from src.scoring.feature_scorer import FeatureBasedScorer

DATA_PATH = Path(__file__).resolve().parent / "data" / "scoring_golden.json"
ABS_TOL = 1e-6


def _load_dataset() -> Dict[str, Any]:
    with DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _to_article_namespace(payload: Dict[str, Any]) -> SimpleNamespace:
    article_payload = dict(payload)
    article_payload.setdefault("article_metadata", {})
    return SimpleNamespace(**article_payload)


class _FrozenDateTime(datetime):
    """Helper used to freeze `datetime.now` inside the scorer module."""

    frozen_value: datetime = datetime.now()

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz:
            return cls.frozen_value.astimezone(tz)
        return cls.frozen_value


@pytest.mark.parametrize("component", [
    "source_credibility",
    "recency",
    "content_quality",
    "engagement",
])
def test_scoring_components_match_golden(monkeypatch: pytest.MonkeyPatch, component: str) -> None:
    golden_data = _load_dataset()
    frozen_at = datetime.fromisoformat(golden_data["frozen_at"].replace("Z", "+00:00"))
    _FrozenDateTime.frozen_value = frozen_at
    monkeypatch.setattr(feature_scorer, "datetime", _FrozenDateTime)

    scorer = FeatureBasedScorer()
    scored_entries = []

    for entry in golden_data["articles"]:
        article_obj = _to_article_namespace(entry["article"])
        score = scorer.score_article(article_obj)

        expected = entry["expected"]
        assert score["should_include"] == expected["should_include"]
        assert score["final_score"] == pytest.approx(expected["final_score"], abs=ABS_TOL)
        assert score["components"][component] == pytest.approx(
            expected["components"][component], abs=ABS_TOL
        )
        assert score["penalties"]["diversity_penalty"] == pytest.approx(
            expected["penalties"]["diversity_penalty"], abs=ABS_TOL
        )

        scored_entries.append({"id": entry["id"], "score": score["final_score"]})

    ranked = sorted(scored_entries, key=lambda item: item["score"], reverse=True)
    actual_ranks = {item["id"]: idx + 1 for idx, item in enumerate(ranked)}

    for entry in golden_data["articles"]:
        assert actual_ranks[entry["id"]] == entry["expected"]["rank"]
