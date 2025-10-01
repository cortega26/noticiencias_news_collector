"""Configurable NLP stack with pluggable providers (spaCy, pattern-based)."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Optional, Sequence

from src.utils.dedupe import sha256_hex
from src.utils.text_cleaner import normalize_text

try:  # pragma: no cover - optional dependency
    import spacy
    from spacy.language import Language
    from spacy.pipeline import EntityRuler
except ImportError:  # pragma: no cover - spaCy is optional at runtime
    spacy = None  # type: ignore[assignment]
    Language = None  # type: ignore[assignment]
    EntityRuler = None  # type: ignore[assignment]


@dataclass(frozen=True)
class NLPResult:
    """Immutable container with NLP outputs."""

    entities: tuple[str, ...]
    topics: tuple[str, ...]
    sentiment: str


class LRUCache:
    """Simple LRU cache suitable for deterministic test scenarios."""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = max(0, int(maxsize))
        self._store: "OrderedDict[str, object]" = OrderedDict()

    def get(self, key: str) -> Optional[object]:
        if self._maxsize == 0:
            return None
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def put(self, key: str, value: object) -> None:
        if self._maxsize == 0:
            return
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)


class ConfigurableNLPStack:
    """NLP engine driven entirely by configuration."""

    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = config
        registry = config.get("models", {})
        if not isinstance(registry, Mapping) or not registry:
            raise ValueError("ENRICHMENT_CONFIG must define at least one model")

        model_key = config.get("default_model")
        if not isinstance(model_key, str):
            raise ValueError("ENRICHMENT_CONFIG requires a 'default_model' key")

        if model_key not in registry:
            raise KeyError(f"Model '{model_key}' not defined in ENRICHMENT_CONFIG")

        model_config_obj = registry[model_key]
        if not isinstance(model_config_obj, Mapping):
            raise TypeError("Model configuration must be a mapping")

        self._model_config = model_config_obj
        requested_provider = (
            str(self._model_config.get("provider", "pattern")).lower()
        )
        self._provider = requested_provider
        if requested_provider == "spacy" and spacy is None:
            # Fall back transparently when spaCy is not available in the runtime.
            self._provider = "pattern"

        self.model_version = str(
            self._model_config.get("version", model_key)
        )
        self._default_topic = str(
            self._model_config.get("default_topic", "general")
        )
        default_language = str(
            self._model_config.get("default_language", "en")
        )
        languages = self._model_config.get("languages", [default_language])
        if not isinstance(languages, Iterable):
            raise TypeError("Model languages definition must be iterable")
        self._supported_languages = {
            str(language).lower() for language in languages
        }
        self._supported_languages.add(default_language.lower())
        self._default_language = default_language.lower()
        self._analysis_cache = LRUCache(
            maxsize=int(config.get("analysis_cache_size", 512))
        )
        self._nlp_models: MutableMapping[str, Language] = {}

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def supported_languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._supported_languages))

    def resolve_language(self, language: Optional[str]) -> str:
        if language:
            normalized = language.lower()
            if normalized in self._supported_languages:
                return normalized
        return self._default_language

    def analyze(
        self,
        language: str,
        text: str,
        *,
        extra_texts: Sequence[str] | None = None,
    ) -> NLPResult:
        lang = self.resolve_language(language)
        texts: list[str] = [part for part in [text, *(extra_texts or [])] if part]
        if not texts:
            return NLPResult((), (self._default_topic,), "neutral")

        cache_key_parts = [self.model_version, lang]
        cache_key_parts.extend(normalize_text(part).lower() for part in texts)
        cache_key = sha256_hex("|".join(cache_key_parts))
        cached = self._analysis_cache.get(cache_key)
        if isinstance(cached, NLPResult):
            return cached

        combined_text = " ".join(texts)
        entities = self._extract_entities(lang, texts)
        topics = self._infer_topics(lang, combined_text.lower())
        sentiment = self._score_sentiment(lang, combined_text.lower())
        result = NLPResult(entities, topics, sentiment)
        self._analysis_cache.put(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------
    def _extract_entities(
        self, language: str, texts: Sequence[str]
    ) -> tuple[str, ...]:
        if self.provider == "spacy" and spacy is not None:
            doc_entities = self._extract_entities_spacy(language, texts)
            if doc_entities:
                return doc_entities
        return self._extract_entities_pattern(language, texts)

    def _extract_entities_spacy(
        self, language: str, texts: Sequence[str]
    ) -> tuple[str, ...]:
        nlp = self._get_spacy_model(language)
        if nlp is None:
            return ()
        seen: "OrderedDict[str, None]" = OrderedDict()
        for text in texts:
            if not text:
                continue
            for ent in nlp(text).ents:
                candidate = ent.text.strip()
                if candidate and candidate not in seen:
                    seen[candidate] = None
        return tuple(seen.keys())

    def _get_spacy_model(self, language: str) -> Optional[Language]:
        if spacy is None:
            return None
        if language in self._nlp_models:
            return self._nlp_models[language]
        patterns = self._resolve_entity_patterns(language)
        try:
            nlp = spacy.blank(language)
        except Exception:  # pragma: no cover - spaCy may not support language
            return None
        if patterns and EntityRuler is not None:
            ruler = nlp.add_pipe("entity_ruler")
            ruler.add_patterns(patterns)
        self._nlp_models[language] = nlp
        return nlp

    def _extract_entities_pattern(
        self, language: str, texts: Sequence[str]
    ) -> tuple[str, ...]:
        patterns = self._resolve_entity_patterns(language)
        if not patterns:
            return ()
        combined = " ".join(texts)
        lowered = combined.lower()
        matches: list[tuple[int, str]] = []
        for pattern in patterns:
            term = str(pattern.get("pattern", "")).strip()
            if not term:
                continue
            alias = str(pattern.get("alias", term)).strip()
            case_sensitive = bool(pattern.get("case_sensitive", False))
            haystack = combined if case_sensitive else lowered
            needle = term if case_sensitive else term.lower()
            index = haystack.find(needle)
            if index >= 0:
                matches.append((index, alias))
        matches.sort(key=lambda item: item[0])
        ordered: "OrderedDict[str, None]" = OrderedDict()
        for _, alias in matches:
            if alias:
                ordered.setdefault(alias, None)
        return tuple(ordered.keys())

    def _resolve_entity_patterns(self, language: str) -> list[dict[str, object]]:
        entities_config = self._model_config.get("entities", {})
        if not isinstance(entities_config, Mapping):
            return []
        patterns_cfg = entities_config.get("patterns", {})
        if not isinstance(patterns_cfg, Mapping):
            return []
        resolved: list[dict[str, object]] = []
        shared_patterns = patterns_cfg.get("shared", [])
        if isinstance(shared_patterns, Iterable):
            resolved.extend(self._normalize_entity_patterns(shared_patterns))
        language_specific = patterns_cfg.get(language, [])
        if isinstance(language_specific, Iterable):
            resolved.extend(self._normalize_entity_patterns(language_specific))
        return resolved

    @staticmethod
    def _normalize_entity_patterns(patterns: Iterable[object]) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for pattern in patterns:
            if isinstance(pattern, Mapping):
                normalized.append(dict(pattern))
            elif isinstance(pattern, str):
                normalized.append({"label": "MISC", "pattern": pattern})
        return normalized

    # ------------------------------------------------------------------
    # Topic inference
    # ------------------------------------------------------------------
    def _infer_topics(self, language: str, text_lower: str) -> tuple[str, ...]:
        topics_config = self._model_config.get("topics", {})
        if not isinstance(topics_config, Mapping) or not topics_config:
            return (self._default_topic,)
        detected: "OrderedDict[str, None]" = OrderedDict()
        for topic, topic_config in topics_config.items():
            if not isinstance(topic_config, Mapping):
                continue
            keywords_cfg = topic_config.get("keywords", {})
            if not isinstance(keywords_cfg, Mapping):
                continue
            candidates: list[str] = []
            shared_kw = keywords_cfg.get("shared", [])
            if isinstance(shared_kw, Iterable):
                candidates.extend(str(word).lower() for word in shared_kw)
            lang_kw = keywords_cfg.get(language, [])
            if isinstance(lang_kw, Iterable):
                candidates.extend(str(word).lower() for word in lang_kw)
            if any(self._keyword_present(text_lower, keyword) for keyword in candidates):
                detected.setdefault(str(topic), None)
        if not detected:
            detected[self._default_topic] = None
        return tuple(detected.keys())[:5]

    # ------------------------------------------------------------------
    # Sentiment scoring
    # ------------------------------------------------------------------
    def _score_sentiment(self, language: str, text_lower: str) -> str:
        sentiment_cfg = self._model_config.get("sentiment", {})
        if not isinstance(sentiment_cfg, Mapping):
            return "neutral"
        lexicon_cfg = sentiment_cfg.get("lexicon", {})
        if not isinstance(lexicon_cfg, Mapping):
            return str(sentiment_cfg.get("default", "neutral"))
        positives = set()
        negatives = set()
        shared_positive = lexicon_cfg.get("shared_positive", [])
        if isinstance(shared_positive, Iterable):
            positives.update(str(word).lower() for word in shared_positive)
        shared_negative = lexicon_cfg.get("shared_negative", [])
        if isinstance(shared_negative, Iterable):
            negatives.update(str(word).lower() for word in shared_negative)
        lang_lexicon = lexicon_cfg.get(language, {})
        if isinstance(lang_lexicon, Mapping):
            lang_pos = lang_lexicon.get("positive", [])
            if isinstance(lang_pos, Iterable):
                positives.update(str(word).lower() for word in lang_pos)
            lang_neg = lang_lexicon.get("negative", [])
            if isinstance(lang_neg, Iterable):
                negatives.update(str(word).lower() for word in lang_neg)
        pos_hits = sum(1 for word in positives if self._keyword_present(text_lower, word))
        neg_hits = sum(1 for word in negatives if self._keyword_present(text_lower, word))
        if pos_hits > neg_hits:
            return "positive"
        if neg_hits > pos_hits:
            return "negative"
        tie_breaker = str(sentiment_cfg.get("tie_breaker", "neutral"))
        default_sentiment = str(sentiment_cfg.get("default", "neutral"))
        return tie_breaker if (pos_hits or neg_hits) else default_sentiment

    # ------------------------------------------------------------------
    @staticmethod
    def _keyword_present(text_lower: str, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        if " " in keyword:
            return keyword in text_lower
        return re.search(rf"\b{re.escape(keyword)}\b", text_lower) is not None


__all__ = [
    "ConfigurableNLPStack",
    "LRUCache",
    "NLPResult",
]
