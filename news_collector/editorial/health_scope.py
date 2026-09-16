"""Health-scope policy: the single definition of "health-related article".

Owned here (plan 111) so the editorial auditor's sampling triggers and the
pre-PR capability-overclaim gate cannot drift apart (AGENTS §7 refactor
trigger: one decision rule, one owner). Pure: no I/O, no config, no
imports beyond stdlib — runnable anywhere policy code runs (LAW-B4).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Category labels that mark health scope. Both languages, lowercase —
#: callers compare case-insensitively. Mirrors the auditor's historical
#: trigger list verbatim (moved here, not redefined).
HEALTH_TRIGGER_CATEGORIES: tuple[str, ...] = (
    "health",
    "medicine",
    "biology",
    "salud",
    "biología",
    "medicina",
)

#: Content keywords that mark health scope (same provenance as above).
HEALTH_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "tratamiento",
    "therapy",
    "treatment",
    "drug",
    "patients",
    "prevent",
    "cura",
    "fármaco",
    "terapia",
    "clinical",
    "clínico",
    "prevención",
    "vaccine",
    "vacuna",
    "cancer",
    "cáncer",
    "alzheimer",
    "milagro",
)

_CONTENT_SCAN_CHARS = 5000


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def is_health_scope(
    *,
    categories: Iterable[Any] | None = None,
    category: Any = None,
    metadata_category: Any = None,
    text: Any = None,
) -> bool:
    """True when any category label matches, or any keyword appears in text.

    `categories` covers the multi-label frontmatter shape; `category` /
    `metadata_category` cover the raw/resolved singular shapes. Category
    comparison is exact-lowercase (same as the auditor). Keyword scanning
    is deliberately substring over the first 5000 characters — broader
    than the auditor's word-boundary sampling regex, because this
    predicate gates a precise downstream check (the overclaim detector),
    so recall beats precision here. The shared LISTS are what must never
    drift; the two matchers serve different call sites on purpose.
    """
    labels = [_norm(category), _norm(metadata_category)]
    if categories is not None:
        try:
            labels.extend(_norm(each) for each in categories)
        except TypeError:
            labels.append(_norm(categories))
    if any(label in HEALTH_TRIGGER_CATEGORIES for label in labels if label):
        return True
    body = _norm(text)[:_CONTENT_SCAN_CHARS]
    if not body:
        return False
    return any(keyword in body for keyword in HEALTH_TRIGGER_KEYWORDS)
