"""One structural admission policy for the collection boundary.

Every collector (RSS, HTML, Reddit) must apply this exact check, exactly
once, before duplicate lookup and persistence. It only decides structural
admissibility (title/content length) — soft editorial signals (clickbait
phrasing, credibility keywords) are scoring's job, not admission's; see
``news_collector.scoring.basic_scorer`` for that separate, unrelated
concern. Conflating the two here would make admission reject articles for
subjective quality reasons, which is out of this module's scope.

URL scheme is not re-checked here: ``CollectorArticleModel.url`` is typed
``AnyHttpUrl``, so a non-http(s) URL already fails Pydantic validation
before an ``evaluate_admission`` call is ever reached.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from news_collector.config.settings import RuntimeConfigSnapshot
from news_collector.contracts import CollectorArticleModel


class AdmissionReason(str, enum.Enum):
    TITLE_TOO_SHORT = "title_too_short"
    CONTENT_TOO_SHORT = "content_too_short"
    TOO_OLD = "too_old"


@dataclass(frozen=True)
class AdmissionDecision:
    accepted: bool
    reason: Optional[AdmissionReason] = None
    details: Dict[str, Any] = field(default_factory=dict)


def effective_max_age_days(config: RuntimeConfigSnapshot) -> int:
    """Single age cutoff (days) for collection *and* candidacy.

    The smaller of ``collection.recent_days_threshold`` and
    ``scoring.candidate_max_age_days``: collection can never be looser than the
    window in which an article may still be a publication candidate, so nothing
    is downloaded/scored that candidacy would discard anyway.
    """
    collection = int(config.collection_config.get("recent_days_threshold", 30))
    candidacy = int(config.scoring_config.get("candidate_max_age_days", 30))
    return max(1, min(collection, candidacy))


def is_too_old(
    published: Optional[datetime],
    max_age_days: int,
    now: Optional[datetime] = None,
) -> bool:
    """True when ``published`` is older than ``max_age_days`` before ``now``.

    Naive datetimes are taken as UTC. A missing date cannot be judged, so it is
    never "too old" (scoring already treats it as collected-today, penalised).
    """
    if not isinstance(published, datetime):
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return published < reference - timedelta(days=max_age_days)


def evaluate_admission(
    article: CollectorArticleModel, config: RuntimeConfigSnapshot
) -> AdmissionDecision:
    """Decide whether ``article`` may proceed to duplicate check + persistence.

    Pure: reads only from ``article`` and ``config``, never mutates either,
    performs no I/O. Every collector's real save path must call this exactly
    once per candidate article.
    """
    max_age = effective_max_age_days(config)
    if is_too_old(article.published_date, max_age):
        return AdmissionDecision(
            accepted=False,
            reason=AdmissionReason.TOO_OLD,
            details={
                "published_date": article.published_date.isoformat(),
                "max_age_days": max_age,
            },
        )

    min_title_length = config.text_processing_config.get("min_title_length", 10)
    title_length = len((article.title or "").strip())
    if title_length < min_title_length:
        return AdmissionDecision(
            accepted=False,
            reason=AdmissionReason.TITLE_TOO_SHORT,
            details={"length": title_length, "min_required": min_title_length},
        )

    if article.content_mode != "summary_only":
        min_content_length = config.text_processing_config.get(
            "min_content_length", 1000
        )
        content_length = len(article.content or "")
        if content_length < min_content_length:
            return AdmissionDecision(
                accepted=False,
                reason=AdmissionReason.CONTENT_TOO_SHORT,
                details={
                    "length": content_length,
                    "min_required": min_content_length,
                },
            )

    return AdmissionDecision(accepted=True)
