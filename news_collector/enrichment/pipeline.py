"""
Module role: Deterministic article enrichment pipeline for extracting multilingual entities, topics, and sentiment.

Inputs:
- Article payloads (ArticleForEnrichmentModel or raw dictionaries).
- Enrichment NLP configuration settings.

Outputs:
- Strictly validated ArticleEnrichmentModel dictionaries containing normalized text, entities, topics, sentiment, and model version.

Side effects:
- May cache computation results in an in-memory LRU cache to optimize repeated queries.
- No network or database calls. Uses local NLP models for analysis.

Invariants:
- Must return deterministically identical outputs for identically normalized inputs across the same model version.
- Must gracefully handle missing content by combining available title and summary fields.
- Deduplication must utilize sha256 hashing of normalized input texts.

Failure modes:
- Unrecognized or improperly structured Pydantic input models will raise validation errors.
- Unsupported detected languages fallback gracefully as determined by the NLP stack.
"""

from __future__ import annotations

from typing import Mapping, MutableMapping

from news_collector.config.settings import get_runtime_config
from news_collector.enrichment.nlp_stack import ConfigurableNLPStack, LRUCache
from news_collector.utils.dedupe import normalize_article_text, sha256_hex
from news_collector.utils.text_cleaner import detect_language_simple


class EnrichmentPipeline:
    """Enrich articles with multilingual entities, topics, and sentiment."""

    def __init__(
        self,
        config: Mapping[str, object] | None = None,
        nlp_stack: ConfigurableNLPStack | None = None,
    ) -> None:
        self._config = dict(config or get_runtime_config().enrichment_config)
        self._nlp_stack = nlp_stack or ConfigurableNLPStack(self._config)
        cache_size = int(self._config.get("result_cache_size", 256))
        self._cache: LRUCache = LRUCache(cache_size)

    @property
    def model_version(self) -> str:
        """Return the active enrichment model version."""

        return self._nlp_stack.model_version

    def enrich_article(
        self, article: Mapping[str, object]
    ) -> MutableMapping[str, object]:
        payload_title = str(article.get("title") or "")
        payload_summary = str(article.get("summary") or "")
        payload_content = str(article.get("content") or "")
        payload_language = article.get("language")

        normalized_title, normalized_summary, normalized_text = normalize_article_text(
            payload_title, payload_summary or payload_content
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

        detected_language = payload_language or detect_language_simple(
            f"{payload_title} {payload_summary}"
        )
        language = self._nlp_stack.resolve_language(
            str(detected_language) if detected_language is not None else None
        )

        combined_text = (
            normalized_text
            or " ".join(
                part
                for part in (payload_title, payload_summary, payload_content)
                if part
            ).strip()
        )

        analysis = self._nlp_stack.analyze(
            language,
            combined_text,
            extra_texts=(payload_title, payload_summary or "", payload_content or ""),
        )

        from typing import Any

        result: MutableMapping[str, Any] = {
            "language": language,
            "normalized_title": normalized_title,
            "normalized_summary": normalized_summary,
            "entities": list(analysis.entities),
            "topics": list(analysis.topics),
            "sentiment": analysis.sentiment,
            "model_version": self.model_version,
        }

        self._cache.put(cache_key, result)
        return result


enrichment_pipeline = EnrichmentPipeline()

__all__ = ["EnrichmentPipeline", "enrichment_pipeline"]
