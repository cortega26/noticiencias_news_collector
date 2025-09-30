"""Advanced feature-based scorer providing explanations and penalties."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from config import SCORING_CONFIG
from src.utils.dedupe import normalize_article_text


def _get_attr(obj: Any, name: str, default=None):
    return getattr(obj, name, default) if hasattr(obj, name) else obj.get(name, default)


@dataclass
class FeatureWeights:
    source_credibility: float
    freshness: float
    content_quality: float
    engagement: float

    def items(self):
        return {
            "source_credibility": self.source_credibility,
            "freshness": self.freshness,
            "content_quality": self.content_quality,
            "engagement": self.engagement,
        }.items()


class FeatureBasedScorer:
    """Advanced scorer with freshness decay, diversity penalty, and explanations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or SCORING_CONFIG
        weights_cfg = self.config.get("feature_weights", {})
        self.weights = FeatureWeights(
            source_credibility=weights_cfg.get("source_credibility", 0.30),
            freshness=weights_cfg.get("freshness", 0.25),
            content_quality=weights_cfg.get("content_quality", 0.25),
            engagement=weights_cfg.get("engagement", 0.20),
        )
        freshness_cfg = self.config.get("freshness", {})
        self.half_life_hours = freshness_cfg.get("half_life_hours", 18.0)
        self.max_decay_hours = freshness_cfg.get("max_decay_hours", 168.0)
        diversity_cfg = self.config.get("diversity_penalty", {})
        self.diversity_weight = diversity_cfg.get("weight", 0.15)
        self.diversity_max_penalty = diversity_cfg.get("max_penalty", 0.3)
        self.minimum_score = self.config.get("minimum_score", 0.3)

    def score_article(
        self, article: Any, source_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        features = {}
        contributions = {}

        source_score = self._source_credibility(article, source_config)
        features["source_credibility"] = source_score
        contributions["source_credibility"] = (
            source_score * self.weights.source_credibility
        )

        freshness_score = self._freshness_score(article)
        features["freshness"] = freshness_score
        contributions["freshness"] = freshness_score * self.weights.freshness

        content_score = self._content_quality_score(article)
        features["content_quality"] = content_score
        contributions["content_quality"] = content_score * self.weights.content_quality

        engagement_score = self._engagement_score(article)
        features["engagement"] = engagement_score
        contributions["engagement"] = engagement_score * self.weights.engagement

        raw_score = sum(contributions.values())

        diversity_penalty, diversity_reason = self._diversity_penalty(article)
        final_score = max(0.0, min(1.0, raw_score - diversity_penalty))

        explanation = {
            "features": {
                name: {
                    "score": features[name],
                    "weight": getattr(
                        self.weights, name if name != "engagement" else "engagement"
                    ),
                    "contribution": contributions[name],
                }
                for name in features
            },
            "penalties": {
                "diversity_penalty": diversity_penalty,
                "diversity_reason": diversity_reason,
            },
            "raw_score": raw_score,
        }

        components = {
            "source_credibility": source_score,
            "recency": freshness_score,
            "content_quality": content_score,
            "engagement": engagement_score,
        }

        return {
            "final_score": final_score,
            "should_include": final_score >= self.minimum_score,
            "components": components,
            "weights": {
                "source_credibility": self.weights.source_credibility,
                "recency": self.weights.freshness,
                "content_quality": self.weights.content_quality,
                "engagement": self.weights.engagement,
            },
            "penalties": {"diversity_penalty": diversity_penalty},
            "why_ranked": explanation,
            "explanation": explanation,
        }

    # Feature calculators -------------------------------------------------

    def _source_credibility(
        self, article: Any, source_config: Optional[Dict[str, Any]]
    ) -> float:
        if source_config:
            base_score = source_config.get("credibility_score", 0.5)
        else:
            metadata = _get_attr(article, "article_metadata", {}) or {}
            base_score = metadata.get("source_metadata", {}).get("credibility_score")
            if base_score is None:
                base_score = metadata.get("credibility_score", 0.5)
            if base_score is None:
                base_score = _get_attr(article, "credibility_score", 0.5)
        return float(max(0.0, min(1.0, base_score)))

    def _freshness_score(self, article: Any) -> float:
        published_date = _get_attr(article, "published_date")
        if not published_date:
            return 0.5
        if isinstance(published_date, str):
            try:
                published_date = datetime.fromisoformat(published_date)
            except ValueError:
                published_date = None
        if not published_date:
            return 0.5
        if published_date.tzinfo is None:
            published_date = published_date.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = max(0.0, (now - published_date).total_seconds() / 3600.0)
        if age_hours <= 0:
            return 1.0
        if age_hours >= self.max_decay_hours:
            return 0.0
        decay = math.exp(-math.log(2) * age_hours / self.half_life_hours)
        return max(0.0, min(1.0, decay))

    def _content_quality_score(self, article: Any) -> float:
        metadata = _get_attr(article, "article_metadata", {}) or {}
        normalized_title = metadata.get("normalized_title")
        normalized_summary = metadata.get("normalized_summary")
        if not normalized_title or not normalized_summary:
            title = _get_attr(article, "title", "") or ""
            summary = _get_attr(article, "summary", "") or ""
            normalized_title, normalized_summary, _ = normalize_article_text(
                title, summary
            )

        title_score = min(len(normalized_title) / 120.0, 1.0)
        summary_score = min(len(normalized_summary) / 400.0, 1.0)

        richness = 0.0
        entities = metadata.get("enrichment", {}).get("entities") if metadata else None
        if entities:
            richness = min(len(entities) / 5.0, 1.0)

        quality = 0.4 * title_score + 0.4 * summary_score + 0.2 * richness
        return max(0.0, min(1.0, quality))

    def _engagement_score(self, article: Any) -> float:
        metadata = _get_attr(article, "article_metadata", {}) or {}
        enrichment = metadata.get("enrichment", {}) if metadata else {}
        sentiment = enrichment.get("sentiment")
        sentiment_score = 0.5
        if sentiment == "positive":
            sentiment_score = 0.7
        elif sentiment == "negative":
            sentiment_score = 0.6
        elif sentiment == "neutral":
            sentiment_score = 0.5

        word_count = _get_attr(article, "word_count", 400) or 400
        length_score = min(word_count / 800.0, 1.0)

        engagement_features = (
            metadata.get("engagement_features", {}) if metadata else {}
        )
        external_score = engagement_features.get("score")
        if external_score is not None:
            external = max(0.0, min(1.0, float(external_score)))
        else:
            external = sentiment_score

        return max(0.0, min(1.0, 0.6 * external + 0.4 * length_score))

    def _diversity_penalty(self, article: Any) -> tuple[float, str]:
        duplication_confidence = (
            _get_attr(article, "duplication_confidence", 0.0) or 0.0
        )
        penalty = min(
            self.diversity_weight * duplication_confidence, self.diversity_max_penalty
        )
        reason = (
            f"penalized by {penalty:.2f} due to duplication confidence {duplication_confidence:.2f}"
            if duplication_confidence
            else "no penalty"
        )
        return penalty, reason


__all__ = ["FeatureBasedScorer"]
