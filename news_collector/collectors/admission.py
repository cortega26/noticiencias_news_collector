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
from typing import Any, Dict, Optional

from news_collector.config.settings import RuntimeConfigSnapshot
from news_collector.contracts import CollectorArticleModel


class AdmissionReason(str, enum.Enum):
    TITLE_TOO_SHORT = "title_too_short"
    CONTENT_TOO_SHORT = "content_too_short"


@dataclass(frozen=True)
class AdmissionDecision:
    accepted: bool
    reason: Optional[AdmissionReason] = None
    details: Dict[str, Any] = field(default_factory=dict)


def evaluate_admission(
    article: CollectorArticleModel, config: RuntimeConfigSnapshot
) -> AdmissionDecision:
    """Decide whether ``article`` may proceed to duplicate check + persistence.

    Pure: reads only from ``article`` and ``config``, never mutates either,
    performs no I/O. Every collector's real save path must call this exactly
    once per candidate article.
    """
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
