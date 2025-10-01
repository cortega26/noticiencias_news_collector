"""Deterministic article enrichment pipeline backed by configurable NLP models."""

from __future__ import annotations

from typing import Mapping, MutableMapping

from config.settings import ENRICHMENT_CONFIG
from src.contracts import ArticleEnrichmentModel, ArticleForEnrichmentModel
from src.enrichment.nlp_stack import ConfigurableNLPStack, LRUCache
from src.utils.dedupe import normalize_article_text, sha256_hex
from src.utils.text_cleaner import detect_language_simple


class EnrichmentPipeline:
    """Enrich articles with multilingual entities, topics, and sentiment."""

    def __init__(
        self,
        config: Mapping[str, object] | None = None,
        nlp_stack: ConfigurableNLPStack | None = None,
    ) -> None:
        self._config = dict(config or ENRICHMENT_CONFIG)
        self._nlp_stack = nlp_stack or ConfigurableNLPStack(self._config)
        cache_size = int(self._config.get("result_cache_size", 256))
        self._cache: LRUCache = LRUCache(cache_size)

    @property
    def model_version(self) -> str:
        """Return the active enrichment model version."""

        return self._nlp_stack.model_version

    def enrich_article(
        self, article: Mapping[str, object] | ArticleForEnrichmentModel
    ) -> MutableMapping[str, object]:
        payload = (
            article
            if isinstance(article, ArticleForEnrichmentModel)
            else ArticleForEnrichmentModel.model_validate(article)
        )

        normalized_title, normalized_summary, normalized_text = normalize_article_text(
            payload.title, payload.summary or payload.content
        )

        cache_key = sha256_hex(
            "|".join(
                (
                    self.model_version,
                    normalized_title,
                    normalized_summary,
                )
            )
        )
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        detected_language = payload.language or detect_language_simple(
            f"{payload.title} {payload.summary}"
        )
        language = self._nlp_stack.resolve_language(detected_language)

        combined_text = (
            normalized_text
            or " ".join(
                part
                for part in (payload.title, payload.summary, payload.content)
                if part
            ).strip()
        )

        analysis = self._nlp_stack.analyze(
            language,
            combined_text,
            extra_texts=(payload.title, payload.summary or "", payload.content or ""),
        )

        result = {
            "language": language,
            "normalized_title": normalized_title,
            "normalized_summary": normalized_summary,
            "entities": list(analysis.entities),
            "topics": list(analysis.topics),
            "sentiment": analysis.sentiment,
            "model_version": self.model_version,
        }

        validated = ArticleEnrichmentModel.model_validate(result)
        result_dict = validated.model_dump()
        self._cache.put(cache_key, result_dict)
        return result_dict


enrichment_pipeline = EnrichmentPipeline()

__all__ = ["EnrichmentPipeline", "enrichment_pipeline"]
