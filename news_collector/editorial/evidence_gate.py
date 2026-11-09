"""Evidence grounding gate (plan 212): block drafts that invent specifics.

Pure policy module (no I/O, no network). It promotes the advisory grounding
findings that separate faithful drafts from fabricated ones into a verdict the
publication engine can enforce *before* any branch or PR exists.

A "specific" is a checkable token that survives translation from the English
sources: a number, a vague quantity ("cientos"), an acronym or chemical code
("DMT", "LC-MS/MS", "TREM2") and a DOI. A draft is blocked when it carries at
least ``DEFAULT_THRESHOLD`` distinct specifics that the ingested evidence does
not contain, or ``SHORT_SOURCE_THRESHOLD`` when the evidence is too short to
ground anything (thin evidence is where the fabrications came from, so a short
source fails closed instead of skipping the check).

What this does NOT catch: comparative or world-knowledge claims with no
distinctive token ("duplica los catálogos", "no hay pequeños mamíferos"),
wrong dates, or a wrong person name. Those need claim-level verification
(plans 209 and 212 phase 2), not a lexical gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from news_collector.editorial.grounding import (
    ERROR,
    MIN_SOURCE_CHARS,
    check_grounding,
    extract_claim_segments,
    fold_text,
)

GATE_ERROR_CODE = "editorial_unsupported_specifics"
DEFAULT_THRESHOLD = 2
SHORT_SOURCE_CHARS = MIN_SOURCE_CHARS
SHORT_SOURCE_THRESHOLD = 1

_GATED_KINDS = frozenset({"number", "vague_quantifier"})
_QUOTED_VALUE_RE = re.compile(r"«([^»]+)»")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Za-z]*[A-Z0-9][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*\b")
_ROMAN_RE = re.compile(r"[IVXLCDM]+")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s)>\]\"']+")

# Spanish acronyms and their English source-side equivalents: either form in
# the evidence grounds the acronym (the sources are English, the drafts Spanish).
_ACRONYM_EQUIVALENTS: Dict[str, Tuple[str, ...]] = {
    "adn": ("dna",),
    "arn": ("rna",),
    "lcr": ("csf",),
    "imao": ("maoi", "mao inhibitor"),
    "vih": ("hiv",),
    "sida": ("aids",),
    "oms": ("who",),
    "onu": ("un",),
    "ue": ("eu",),
    "tac": ("ct",),
    "rmn": ("mri",),
    "pib": ("gdp",),
    "uci": ("icu",),
}
# Boilerplate or structural tokens that never need evidence: the AI image
# disclosure ("generada con IA") and the "EE. UU." fragments.
_ALWAYS_ALLOWED = frozenset({"ia", "uu", "ee"})
# Words skipped when matching an initialism to its long form ("técnica de
# reemplazo mitocondrial (TRM)").
_INITIALISM_STOPWORDS = frozenset(
    {"de", "del", "la", "el", "los", "las", "y", "e", "en", "para", "por", "con"}
)
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


@dataclass(frozen=True)
class UnsupportedSpecific:
    kind: str
    value: str
    field: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"kind": self.kind, "value": self.value, "field": self.field}


@dataclass(frozen=True)
class EvidenceGateDecision:
    blocked: bool
    threshold: int
    source_chars: int
    short_source: bool
    unsupported: Tuple[UnsupportedSpecific, ...] = field(default_factory=tuple)

    def by_kind(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.unsupported:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def stage_details(self, top: int = 12) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "threshold": self.threshold,
            "source_chars": self.source_chars,
            "short_source": self.short_source,
            "unsupported_count": len(self.unsupported),
            "by_kind": self.by_kind(),
            "unsupported": [item.as_dict() for item in self.unsupported[:top]],
        }

    def message(self) -> str:
        shown = ", ".join(f"{i.kind}:{i.value}" for i in self.unsupported[:8])
        extra = len(self.unsupported) - 8
        if extra > 0:
            shown += f" (+{extra} more)"
        source = (
            f"the ingested evidence is too short ({self.source_chars} chars)"
            if self.short_source
            else "the ingested evidence does not contain them"
        )
        return (
            f"Evidence gate: {len(self.unsupported)} specific(s) in the draft are "
            f"not supported by the source ({source}; threshold "
            f"{self.threshold}): {shown}. Publication blocked pending review."
        )


def _folded_contains(haystack: str, needle: str) -> bool:
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack)
        is not None
    )


def _acronym_supported(token: str, folded_source: str) -> bool:
    folded = fold_text(token)
    if folded in _ALWAYS_ALLOWED:
        return True
    if _folded_contains(folded_source, folded):
        return True
    return any(
        _folded_contains(folded_source, eq)
        for eq in _ACRONYM_EQUIVALENTS.get(folded, ())
    )


def _defined_in_text(token: str, text: str) -> bool:
    """True when ``text`` expands ``token`` as ``long form (TOKEN)``.

    The initials of the words right before the parenthesis must spell the
    token, so ``fecundación in vitro (FIV)`` counts but ``(DMT)`` after an
    unrelated phrase does not. The long form's own words are not verified here;
    their numbers and codes still go through the other checks.
    """
    wanted = token.lower()
    for match in re.finditer(rf"\(\s*{re.escape(token)}\s*\)", text):
        words = _WORD_RE.findall(text[: match.start()])[-(len(wanted) + 4) :]
        for start in range(len(words)):
            tail = [w for w in words[start:] if w.lower() not in _INITIALISM_STOPWORDS]
            if "".join(w[0].lower() for w in tail) == wanted:
                return True
    return False


def _is_acronym(token: str) -> bool:
    if _ROMAN_RE.fullmatch(token):
        return False
    return len(token) >= 2 and (token.isupper() or any(c.isdigit() for c in token))


def _lexical_specifics(
    segments: List[Tuple[str, str]], source_text: str
) -> List[UnsupportedSpecific]:
    folded_source = fold_text(source_text)
    whole_article = "\n".join(text for _, text in segments)
    lowered_source = source_text.lower()
    found: List[UnsupportedSpecific] = []
    for field_name, text in segments:
        for token in _ACRONYM_RE.findall(text):
            if (
                _is_acronym(token)
                and not _acronym_supported(token, folded_source)
                and not _defined_in_text(token, whole_article)
            ):
                found.append(UnsupportedSpecific("acronym", token, field_name))
        for doi in _DOI_RE.findall(text):
            if doi.rstrip(".,;").lower() not in lowered_source:
                found.append(UnsupportedSpecific("doi", doi.rstrip(".,;"), field_name))
    return found


def _numeric_specifics(
    markdown: str, source_text: str, allow_terms: Iterable[str]
) -> List[UnsupportedSpecific]:
    report = check_grounding(
        markdown, source_text, allow_terms=allow_terms, min_source_chars=0
    )
    found: List[UnsupportedSpecific] = []
    for finding in report.findings:
        if finding.severity != ERROR or finding.kind not in _GATED_KINDS:
            continue
        match = _QUOTED_VALUE_RE.search(finding.detail)
        value = match.group(1) if match else finding.snippet.strip()
        found.append(UnsupportedSpecific(finding.kind, value, finding.field))
    return found


def _distinct(items: Iterable[UnsupportedSpecific]) -> Tuple[UnsupportedSpecific, ...]:
    seen: set[Tuple[str, str]] = set()
    unique: List[UnsupportedSpecific] = []
    for item in items:
        key = (item.kind, fold_text(item.value))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


def evaluate_evidence_gate(
    markdown: str,
    source_text: str,
    *,
    allow_terms: Iterable[str] = (),
    threshold: int = DEFAULT_THRESHOLD,
    short_source_threshold: int = SHORT_SOURCE_THRESHOLD,
) -> EvidenceGateDecision:
    """Return the gate verdict for one refined Markdown draft.

    Raises nothing for odd input; a defect in the checker itself propagates so
    the caller can fail closed (a gate must never silently pass on its own
    error, unlike the advisory grounding stage).
    """
    source = source_text or ""
    short = len(source.strip()) < SHORT_SOURCE_CHARS
    limit = short_source_threshold if short else threshold
    segments = extract_claim_segments(markdown or "")
    unsupported = _distinct(
        _numeric_specifics(markdown or "", source, allow_terms)
        + _lexical_specifics(segments, source)
    )
    return EvidenceGateDecision(
        blocked=len(unsupported) >= limit,
        threshold=limit,
        source_chars=len(source),
        short_source=short,
        unsupported=unsupported,
    )
