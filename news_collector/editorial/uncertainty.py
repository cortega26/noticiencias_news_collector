"""Uncertainty-counterweight enforcement (EDITORIAL_VOICE.md §2.4.3).

The editorial voice requires: a curiosity-gap (or stakes) hook over a
preliminary finding ⇒ a mandatory, *visible* uncertainty note. The frontend already
renders it (`TrustPanel.astro`: amber callout when required, plain line
otherwise) — but the backend never guaranteed the invariant, so articles
shipped with `requires_uncertainty_note: true` and no note at all (silent
contract violation, invisible in the UI).

This module closes that gap deterministically: no network, no DB, no LLM.
Fail-open throughout — a generic visible caveat beats an invisible
requirement, and nothing here ever blocks publication.
"""

from __future__ import annotations

import re
from typing import Any

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

# Fallback when a note is required but the model provided none. Deliberately
# generic and honest — it claims nothing specific about the study.
GENERIC_UNCERTAINTY_NOTE = (
    "Los hallazgos presentados son preliminares y podrían matizarse a medida "
    "que aparezcan más estudios o datos. Interpreta estas conclusiones con "
    "cautela."
)

# Hooks that promise the reader something (plan 067: curiosity_gap;
# plan 070: stakes joins — same promise-to-reader dynamics over
# preliminary findings). `question` stays out deliberately: interrogative
# hooks are normally answered in-body and the fidelity critic already
# judges hook-body match; forcing caveats there would dilute the signal.
_COUNTERWEIGHT_HOOKS = frozenset({"curiosity_gap", "stakes"})

# First-word prefixes (case-insensitive) of the free-text `confidence`
# field that suggest a preliminary finding. Observed in the wild: "Alta",
# "Moderada", "Moderada-alta". Anything else (including non-strings and
# empties) fails open to False.
_PRELIMINARY_CONFIDENCE_PREFIXES = ("moderada", "media", "baja")


def hook_needs_counterweight(pattern_used: Any) -> bool:
    """True for hooks that promise the reader something over a finding
    (validator §2.4 rule 3 names the curiosity gap; stakes joins it —
    other patterns are judged by the fidelity critic instead)."""
    if not isinstance(pattern_used, str):
        return False
    normalized = pattern_used.strip().lower().replace(" ", "_")
    return normalized in _COUNTERWEIGHT_HOOKS


def confidence_suggests_preliminary(confidence: Any) -> bool:
    """Whether the Stage 6 self-assessed confidence reads as preliminary."""
    if not isinstance(confidence, str) or not confidence.strip():
        return False
    first = re.split(r"[\s\-–—:;,.]+", confidence.strip().lower())[0]
    return first.startswith(_PRELIMINARY_CONFIDENCE_PREFIXES)


def resolve_uncertainty_counterweight(
    headlines: dict[str, Any] | None, confidence: Any
) -> tuple[bool, str | None]:
    """Enforce the counterweight invariant, returning
    `(requires_uncertainty_note, uncertainty_note_or_None)`.

    - A provided non-empty note is ALWAYS kept, even without the flag
      (today it is silently dropped — lost content).
    - A curiosity-gap hook over a preliminary finding forces the flag on.
    - A required-but-missing note falls back to the generic caveat.
    """
    source = headlines if isinstance(headlines, dict) else {}
    requires = bool(source.get("requires_uncertainty_note", False))
    raw_note = source.get("uncertainty_note")
    if isinstance(raw_note, str):
        note: str | None = raw_note.strip() or None
    elif raw_note:
        note = str(raw_note)
    else:
        note = None

    if not requires and (
        hook_needs_counterweight(source.get("pattern_used"))
        and confidence_suggests_preliminary(confidence)
    ):
        requires = True
        logger.warning(
            "Curiosity-gap hook over a preliminary finding without the "
            "required flag — enforcing the uncertainty counterweight."
        )

    if requires and not note:
        logger.warning(
            "requires_uncertainty_note without a note — publishing with "
            "the generic caveat instead of an invisible requirement."
        )
        note = GENERIC_UNCERTAINTY_NOTE

    return requires, note
