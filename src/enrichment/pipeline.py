"""Deterministic article enrichment pipeline with caching and retries."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from src.utils.dedupe import normalize_article_text, sha256_hex
from src.utils.text_cleaner import detect_language_simple
from textblob import TextBlob


TOPIC_KEYWORDS = {
    "space": {
        "en": ["space", "planet", "nasa", "mars", "spaceship", "moon"],
        "es": ["espacio", "planeta", "nasa", "marte", "luna"],
    },
    "science": {
        "en": ["science", "research", "study", "scientist", "laboratory"],
        "es": ["ciencia", "investigación", "estudio", "científicos"],
    },
    "health": {
        "en": ["health", "vaccine", "medical", "hospital", "virus", "cancer"],
        "es": ["salud", "vacuna", "médico", "hospital", "virus", "cáncer"],
    },
    "technology": {
        "en": ["technology", "software", "startup", "ai", "robot", "quantum"],
        "es": ["tecnología", "software", "startup", "robot", "inteligencia artificial"],
    },
    "climate": {
        "en": ["climate", "emissions", "wildfire", "temperature", "carbon"],
        "es": ["clima", "emisiones", "incendio", "temperatura", "carbono"],
    },
    "economy": {
        "en": ["economy", "inflation", "market", "funding", "stocks"],
        "es": ["economía", "inflación", "mercado", "financiamiento", "acciones"],
    },
}

SPANISH_POSITIVE = {
    "bueno",
    "positiva",
    "positivo",
    "éxito",
    "avance",
    "ganó",
    "mejoría",
    "crecimiento",
}
SPANISH_NEGATIVE = {
    "malo",
    "negativa",
    "negativo",
    "crisis",
    "pérdida",
    "riesgo",
    "empeora",
    "caída",
}
ENGLISH_POSITIVE = {
    "positive",
    "success",
    "successful",
    "growth",
    "improves",
    "record",
    "wins",
    "breakthrough",
    "boost",
}
ENGLISH_NEGATIVE = {
    "negative",
    "decline",
    "crisis",
    "loss",
    "drop",
    "risk",
    "fails",
    "problem",
    "warning",
}
ENTITY_CONNECTORS = {
    "de",
    "del",
    "of",
    "the",
    "la",
    "el",
    "los",
    "las",
    "da",
    "do",
    "di",
    "du",
    "en",
}


def _extract_entities(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"[\wÁÉÍÓÚÑáéíóúñ]+", text)
    entities: List[str] = []
    current: List[str] = []

    def flush_current() -> None:
        if not current:
            return
        significant = [word for word in current if word[0].isupper() or word.isupper()]
        joined = " ".join(current)
        if not significant:
            return
        if len(joined) < 3 and not any(
            word.isupper() and len(word) <= 3 for word in significant
        ):
            return
        entity = joined
        if entity not in entities:
            entities.append(entity)

    for token in tokens:
        lower = token.lower()
        if token[0].isupper() or token.isupper():
            current.append(token)
        elif current and lower in ENTITY_CONNECTORS:
            current.append(lower)
        else:
            flush_current()
            current = []
    flush_current()
    return entities[:10]


def _infer_topics(language: str, text_lower: str) -> List[str]:
    topics: List[str] = []
    for topic, mapping in TOPIC_KEYWORDS.items():
        keywords = mapping.get(language, []) + mapping.get("en", [])
        if any(_keyword_present(text_lower, kw) for kw in keywords):
            topics.append(topic)
    if not topics:
        topics.append("general")
    return topics[:5]


def _sentiment_label(language: str, text: str) -> str:
    if not text:
        return "neutral"
    if language == "es":
        text_lower = text.lower()
        pos_hits = sum(1 for word in SPANISH_POSITIVE if word in text_lower)
        neg_hits = sum(1 for word in SPANISH_NEGATIVE if word in text_lower)
        if pos_hits > neg_hits:
            return "positive"
        if neg_hits > pos_hits:
            return "negative"
        return "neutral"
    text_lower = text.lower()
    pos_hits = sum(1 for word in ENGLISH_POSITIVE if word in text_lower)
    neg_hits = sum(1 for word in ENGLISH_NEGATIVE if word in text_lower)
    if pos_hits > neg_hits:
        return "positive"
    if neg_hits > pos_hits:
        return "negative"
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    if polarity > 0.1:
        return "positive"
    if polarity < -0.1:
        return "negative"
    return "neutral"


def _keyword_present(text_lower: str, keyword: str) -> bool:
    keyword = keyword.lower()
    if " " in keyword:
        return keyword in text_lower
    return re.search(rf"\b{re.escape(keyword)}\b", text_lower) is not None


class EnrichmentPipeline:
    """Deterministic enrichment pipeline with caching and simple retries."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, object]] = {}

    def enrich_article(self, article: Dict[str, object]) -> Dict[str, object]:
        title = str(article.get("title", "") or "")
        summary = str(article.get("summary", "") or "")
        content = str(article.get("content", "") or "")

        normalized_title, normalized_summary, normalized_text = normalize_article_text(
            title, summary or content
        )
        cache_key = sha256_hex(f"{normalized_title}|{normalized_summary}")
        if cache_key in self._cache:
            return self._cache[cache_key]

        language = article.get("language") or detect_language_simple(
            f"{title} {summary}"
        )
        language = language if language in ("en", "es") else "en"

        combined_text = (
            normalized_text or f"{normalized_title} {normalized_summary}".strip()
        )
        text_for_topics = combined_text.lower()

        result: Optional[Dict[str, object]] = None
        last_exception: Optional[Exception] = None
        for _ in range(3):
            try:
                entities_source = summary or title
                entities = _extract_entities(entities_source)
                if not entities and title:
                    entities = _extract_entities(title)
                topics = _infer_topics(language, text_for_topics)
                sentiment = _sentiment_label(language, combined_text)
                result = {
                    "language": language,
                    "normalized_title": normalized_title,
                    "normalized_summary": normalized_summary,
                    "entities": entities,
                    "topics": topics,
                    "sentiment": sentiment,
                }
                break
            except Exception as exc:  # pragma: no cover
                last_exception = exc
        if result is None:
            raise last_exception or RuntimeError("Enrichment pipeline failed")

        self._cache[cache_key] = result
        return result


enrichment_pipeline = EnrichmentPipeline()
