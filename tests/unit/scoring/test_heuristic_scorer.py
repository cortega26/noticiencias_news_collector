from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from news_collector.scoring.heuristic_scorer import HeuristicScorer
from news_collector.storage.models import Article


@dataclass
class _StubArticle:
    title: str = ""
    summary: str | None = None
    content: str | None = None


def _score(scorer: HeuristicScorer, article: _StubArticle) -> float:
    return scorer.calculate_score(cast(Article, article))


def test_empty_article_returns_bounded_float() -> None:
    score = _score(HeuristicScorer(), _StubArticle())

    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_data_density_rewards_quantitative_evidence() -> None:
    scorer = HeuristicScorer()
    low_data = _StubArticle(
        content="Researchers describe a careful observational study."
    )
    high_data = _StubArticle(
        content="In 2024, researchers studied n=120 people and found 35% improved at p<0.05."
    )

    assert _score(scorer, high_data) > _score(scorer, low_data)


def test_latam_keyword_increases_composite_score() -> None:
    scorer = HeuristicScorer()
    generic = _StubArticle(
        content="Researchers measured water quality across the region."
    )
    regional = _StubArticle(content="Researchers measured water quality across Chile.")

    assert _score(scorer, regional) > _score(scorer, generic)


def test_low_value_keyword_overrides_latam_affinity() -> None:
    scorer = HeuristicScorer()

    assert scorer._calculate_latam_affinity("Public health research in Chile") == 1.0
    assert scorer._calculate_latam_affinity("Campus research in Chile") == 0.0


def test_wow_factor_saturates_after_four_distinct_hits() -> None:
    scorer = HeuristicScorer()
    four_hits = "breakthrough discovery first new"
    eight_hits = "breakthrough discovery first new major study evidence record"

    assert scorer._evaluate_wow_factor(four_hits) == 1.0
    assert scorer._evaluate_wow_factor(eight_hits) == 1.0


def test_score_is_clamped_and_rounded_to_four_decimals() -> None:
    score = _score(
        HeuristicScorer(),
        _StubArticle(
            title="Major breakthrough study in Chile",
            summary="In 2025, 75% improved with p<0.01.",
            content='Researchers found new evidence.\n\n<p>"Result" http://example.test</p>',
        ),
    )

    assert 0.0 <= score <= 1.0
    assert round(score, 4) == score


def test_score_is_deterministic_for_identical_input() -> None:
    scorer = HeuristicScorer()
    article = _StubArticle(
        title="Discovery in the Atacama",
        summary="A 2024 study found significant evidence.",
        content="The research identified a new record after 120 observations.",
    )

    assert _score(scorer, article) == _score(scorer, article)
