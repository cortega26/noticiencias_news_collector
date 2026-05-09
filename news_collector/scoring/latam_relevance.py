"""Deterministic ranking helpers for a LatAm public-interest science audience."""

from __future__ import annotations

from typing import Any, Dict, List

LATAM_KEYWORDS = (
    "latinoamerica",
    "latinoamérica",
    "mexico",
    "méxico",
    "brazil",
    "brasil",
    "argentina",
    "chile",
    "peru",
    "perú",
    "colombia",
    "bogotá",
    "santiago",
    "buenos aires",
    "andes",
    "amazonas",
    "conicet",
    "unam",
    "fapesp",
    "fiocruz",
)

SCIENCE_PRIORITY_KEYWORDS = (
    "study",
    "research",
    "scientists",
    "researchers",
    "analysis",
    "data",
    "evidence",
    "climate",
    "drought",
    "heat wave",
    "glacier",
    "health",
    "dengue",
    "vaccine",
    "virus",
    "astronomy",
    "observatory",
    "space",
    "satellite",
    "ai",
    "artificial intelligence",
    "model",
    "discovery",
    "detect",
    "reveals",
    "public health",
    "education",
    "policy",
)

LOW_VALUE_KEYWORDS = (
    "campus",
    "student life",
    "alumni",
    "alumni engagement",
    "dean",
    "provost",
    "vice provost",
    "office of",
    "breakfast",
    "mentorship portal",
    "award",
    "leadership",
    "fundraiser",
    "fundraising",
    "donor",
    "commencement",
    "menu",
    "newsletter",
    "partnership",
    "partnership announcement",
    "product partnership",
    "administrative",
    "internal update",
    "student government",
    "portal",
)


def score_candidate_for_latam_audience(candidate: Dict[str, Any]) -> float:
    title = str(candidate.get("title") or "")
    summary = str(candidate.get("summary") or "")
    source_name = str(candidate.get("source_name") or candidate.get("source_id") or "")
    text = f"{title} {summary} {source_name}".lower()

    score = 0.0
    score += sum(4.0 for keyword in LATAM_KEYWORDS if keyword in text)
    score += sum(2.5 for keyword in SCIENCE_PRIORITY_KEYWORDS if keyword in text)
    score -= sum(3.5 for keyword in LOW_VALUE_KEYWORDS if keyword in text)
    score += min(len(summary) / 140.0, 1.5)
    score += min(len(title) / 80.0, 0.5)

    if any(word in text for word in ("study", "research", "scientists", "data")):
        score += 1.0

    if "partnership" in text or "portal" in text:
        score -= 1.0

    return score


def rank_candidates_for_latam_audience(
    candidates: List[Dict[str, Any]],
) -> List[int]:
    scored = [
        (score_candidate_for_latam_audience(candidate), -idx, idx)
        for idx, candidate in enumerate(candidates)
    ]
    scored.sort(reverse=True)
    return [idx for _score, _stable_idx, idx in scored]
