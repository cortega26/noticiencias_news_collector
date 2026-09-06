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
from collections.abc import Iterator, Mapping
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


# --- Capability-overclaim counterweight (plan 083) -------------------------
#
# Codex P1 on PR #153: an article whose `uncertainty_note` said GlucoFM "aún
# no ha sido validado en estudios clínicos" still asserted, in `why_it_matters`,
# that it "permite una detección temprana y un manejo personalizado de la
# glucosa" — a present-tense clinical capability the post itself disclaims.
# `requires_uncertainty_note` only guarantees the *note* is visible; nothing
# reconciled the reader-facing narrative with it.
#
# This is a DETECTOR, not a rewriter. It runs only when a counterweight is in
# force, scans the two fields written to sell the finding to the reader
# (`why_it_matters`, `headlines_variants.benefit`), and returns a description
# of each offending sentence for the caller to log. It never edits the text:
# deterministically rewriting Spanish clinical prose ("permite" → "podría
# permitir") mangles compound sentences ("… e identifica …" → "… e podría
# identificar …"), and this module publishes through PRs a human merges — the
# warning gives that reviewer, and the Codex re-review, exactly what they need.
# `summary_points` (the study's measured results) and the article body (judged
# by the fidelity critic) are out of scope. Fail-open: never raises.

# Present-indicative capability verbs (3rd person, singular/plural) whose plain
# present tense asserts a working capability.
_CAPABILITY_VERBS: frozenset[str] = frozenset(
    {
        "permite",
        "permiten",
        "detecta",
        "detectan",
        "predice",
        "predicen",
        "identifica",
        "identifican",
        "diagnostica",
        "diagnostican",
        "anticipa",
        "anticipan",
        "posibilita",
        "posibilitan",
        "habilita",
        "habilitan",
    }
)

# The claim is only flagged when the sentence is about a clinical/health
# outcome — a generic architectural statement ("el modelo permite reutilizar
# representaciones") is left alone.
_CLINICAL_CONTEXT_RE = re.compile(
    r"cl[íi]nic|diagn[óo]stic|detecci[óo]n|s[íi]ntoma|enfermedad|diabet|"
    r"glucos|insulin|c[áa]ncer|tumor|alzheimer|card[íi]ac|pacient|"
    r"riesgo|salud|terap|tratamiento|c[ée]lula",
    re.IGNORECASE,
)

# A hedge in the ~4 words before the verb means the claim is not a bare
# present-tense assertion — skip it.
_PRE_HEDGE_RE = re.compile(
    r"\b(podr[íi]a|podr[íi]an|puede|pueden|podr[áa]|podr[áa]n|"
    r"ayuda\s+a|ayudan\s+a|busca|buscan|pretende|pretenden|aspira\s+a)"
    r"(?:\s+\S+){0,3}\s+$",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _sentence_has_bare_capability_claim(sentence: str) -> bool:
    """True when a clinical sentence contains an un-hedged present-indicative
    capability verb."""
    if not _CLINICAL_CONTEXT_RE.search(sentence):
        return False
    for match in _WORD_RE.finditer(sentence):
        if match.group(0).lower() not in _CAPABILITY_VERBS:
            continue
        if _PRE_HEDGE_RE.search(sentence[: match.start()]):
            continue
        return True
    return False


def find_capability_overclaims(text: Any) -> list[str]:
    """Return the sentences of `text` that assert a clinical capability in the
    bare present indicative. Empty for non-strings and clean text."""
    if not isinstance(text, str) or not text.strip():
        return []
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in sentences if _sentence_has_bare_capability_claim(s)]


def _has_counterweight(requires_uncertainty_note: Any, uncertainty_note: Any) -> bool:
    if requires_uncertainty_note:
        return True
    return isinstance(uncertainty_note, str) and bool(uncertainty_note.strip())


def _iter_narrative_fields(fields: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield `(label, text)` for every reader-facing narrative string that a
    capability overclaim would surface in."""
    raw_why = fields.get("why_it_matters")
    if isinstance(raw_why, list):
        for index, item in enumerate(raw_why):
            yield f"why_it_matters[{index}]", item

    raw_headlines = fields.get("headlines_variants")
    if isinstance(raw_headlines, Mapping):
        yield "headlines_variants.benefit", raw_headlines.get("benefit")


def find_unvalidated_capability_claims(
    fields: Mapping[str, Any],
    *,
    requires_uncertainty_note: bool,
    uncertainty_note: Any,
) -> list[str]:
    """Flag reader-facing narrative that contradicts a declared uncertainty
    counterweight.

    Runs only when `requires_uncertainty_note` is true or a non-empty
    `uncertainty_note` is present. Scans `why_it_matters` (list) and
    `headlines_variants.benefit` (str) for present-tense clinical-capability
    assertions. Returns a list of `"<field>: <sentence>"` strings for the
    caller to log — it never edits `fields`. Never raises.
    """
    if not _has_counterweight(requires_uncertainty_note, uncertainty_note):
        return []

    return [
        f"{label}: {sentence}"
        for label, text in _iter_narrative_fields(fields)
        for sentence in find_capability_overclaims(text)
    ]
