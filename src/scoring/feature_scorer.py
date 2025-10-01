"""Advanced feature-based scorer providing explanations and penalties."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from config import SCORING_CONFIG
from src.utils.dedupe import normalize_article_text
from pydantic import ValidationError

from src.contracts import ScoringRequestModel


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

        content_quality_cfg = self.config.get("content_quality_heuristics", {})
        self.content_title_length_divisor = float(
            content_quality_cfg.get("title_length_divisor", 120.0)
        )
        self.content_summary_length_divisor = float(
            content_quality_cfg.get("summary_length_divisor", 400.0)
        )
        self.content_entity_target_count = float(
            content_quality_cfg.get("entity_target_count", 5.0)
        )
        weights = content_quality_cfg.get("weights", {})
        self.content_weights = {
            "title": float(weights.get("title", 0.4)),
            "summary": float(weights.get("summary", 0.4)),
            "entity": float(weights.get("entity", 0.2)),
        }

        engagement_cfg = self.config.get("engagement_heuristics", {})
        sentiment_cfg = engagement_cfg.get("sentiment_scores", {})
        self.sentiment_scores = {
            "positive": float(sentiment_cfg.get("positive", 0.7)),
            "negative": float(sentiment_cfg.get("negative", 0.6)),
            "neutral": float(sentiment_cfg.get("neutral", 0.5)),
        }
        # Allow additional custom sentiment labels
        for label, value in sentiment_cfg.items():
            self.sentiment_scores[str(label).lower()] = float(value)

        self.fallback_sentiment = float(engagement_cfg.get("fallback_sentiment", 0.5))
        self.word_count_divisor = float(engagement_cfg.get("word_count_divisor", 800.0))
        self.engagement_weights = {
            "external": float(engagement_cfg.get("external_weight", 0.6)),
            "length": float(engagement_cfg.get("length_weight", 0.4)),
        }

        self._validate_content_quality_config()
        self._validate_engagement_config()

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

        result = {
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

        try:
            validated = ScoringRequestModel.model_validate(result)
        except ValidationError as exc:
            identifier = getattr(article, "id", getattr(article, "url", "unknown"))
            raise ValueError(
                f"Invalid scoring payload for article {identifier}: {exc}"
            ) from exc

        return validated.model_dump()

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

        title_score = min(
            len(normalized_title) / self.content_title_length_divisor, 1.0
        )
        summary_score = min(
            len(normalized_summary) / self.content_summary_length_divisor, 1.0
        )

        richness = 0.0
        entities = metadata.get("enrichment", {}).get("entities") if metadata else None
        if entities:
            richness = min(len(entities) / self.content_entity_target_count, 1.0)

        quality = (
            self.content_weights["title"] * title_score
            + self.content_weights["summary"] * summary_score
            + self.content_weights["entity"] * richness
        )
        return max(0.0, min(1.0, quality))

    def _engagement_score(self, article: Any) -> float:
        metadata = _get_attr(article, "article_metadata", {}) or {}
        enrichment = metadata.get("enrichment", {}) if metadata else {}
        sentiment = enrichment.get("sentiment")
        sentiment_score = self.fallback_sentiment
        if isinstance(sentiment, str):
            sentiment_score = self.sentiment_scores.get(
                sentiment.lower(), self.fallback_sentiment
            )
        elif isinstance(sentiment, dict):
            label = str(sentiment.get("label", "")).lower()
            sentiment_score = self.sentiment_scores.get(label, self.fallback_sentiment)

        word_count = _get_attr(article, "word_count", 400) or 400
        length_score = min(word_count / self.word_count_divisor, 1.0)

        engagement_features = (
            metadata.get("engagement_features", {}) if metadata else {}
        )
        external_score = engagement_features.get("score")
        if external_score is not None:
            external = max(0.0, min(1.0, float(external_score)))
        else:
            external = sentiment_score

        combined = (
            self.engagement_weights["external"] * external
            + self.engagement_weights["length"] * length_score
        )
        return max(0.0, min(1.0, combined))

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

    # Configuration validators ---------------------------------------------

    def _validate_content_quality_config(self) -> None:
        if self.content_title_length_divisor <= 0:
            raise ValueError(
                "content_quality_heuristics.title_length_divisor must be > 0"
            )
        if self.content_summary_length_divisor <= 0:
            raise ValueError(
                "content_quality_heuristics.summary_length_divisor must be > 0"
            )
        if self.content_entity_target_count <= 0:
            raise ValueError(
                "content_quality_heuristics.entity_target_count must be > 0"
            )

        weight_sum = sum(self.content_weights.values())
        if weight_sum <= 0.0:
            raise ValueError(
                "content_quality_heuristics.weights must sum to a positive value"
            )
        for key, value in self.content_weights.items():
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"content_quality_heuristics.weights.{key} must be between 0 and 1"
                )
        if abs(weight_sum - 1.0) > 1e-3:
            raise ValueError("content_quality_heuristics.weights must sum to 1.0")

    def _validate_engagement_config(self) -> None:
        for label, value in self.sentiment_scores.items():
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"engagement_heuristics.sentiment_scores.{label} must be between 0 and 1"
                )
        if self.fallback_sentiment < 0.0 or self.fallback_sentiment > 1.0:
            raise ValueError(
                "engagement_heuristics.fallback_sentiment must be between 0 and 1"
            )
        if self.word_count_divisor <= 0:
            raise ValueError("engagement_heuristics.word_count_divisor must be > 0")

        weight_sum = sum(self.engagement_weights.values())
        if weight_sum <= 0.0:
            raise ValueError(
                "engagement_heuristics weights must sum to a positive value"
            )
        if abs(weight_sum - 1.0) > 1e-3:
            raise ValueError("engagement_heuristics weights must sum to 1.0")
        for key, value in self.engagement_weights.items():
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"engagement_heuristics.{key}_weight must be between 0 and 1"
                )


__all__ = ["FeatureBasedScorer"]
