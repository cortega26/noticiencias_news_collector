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


# --- Replica-scope mismatch (Codex P2 on frontend PR #191) --------------------
#
# Article 2451 (Vesuvius scrolls) passed every gate with an `uncertainty_note`
# stating the technique was tested on modern lab-made replicas and is untested
# on the authentic Herculaneum scrolls — while `summary_points[2]` said the
# team scanned "los rollos" and recovered legible words, which reads as an
# archaeological recovery from the originals. Same bug class as plan 083
# (reader-facing narrative vs declared counterweight) but non-clinical and in
# the summary fields, which the capability-overclaim detector above
# deliberately excludes.
#
# This is a DETECTOR, not a rewriter. It runs only when the counterweight
# signals replica/preliminary-experimental scope, scans `summary_points` and
# `excerpt`, and returns `"<field>: <sentence>"` strings for the caller to log
# (and, via grounding, into the PR body). It never edits `fields`.
# Fail-open: never raises.

# The note confines the result to replicas/models when it mentions them, the
# lab, or that the authentic object was not (yet) tested.
_REPLICA_SCOPE_NOTE_RE = re.compile(
    r"r[ée]plicas?|laboratorio|a[úu]n no se ha probado|no se ha probado|"
    r"sin probar en|aut[ée]nticos?|modelos? experimentales?|in vitro|"
    r"simulaci[óo]n",
    re.IGNORECASE,
)

# Completed-result verbs (stems cover indicative forms): asserting that words,
# signals or effects were obtained.
_RESULT_VERB_STEMS = (
    "recuper",
    "logr",
    "obtuv",
    "obten",
    "demostr",
    "demuestra",
    "demuestran",
    "detect",
    "revel",
    "leyeron",
    "identific",
    "confirm",
    "probaron",
    "prueba",
    "prueban",
    "descubr",
    "encontr",
    "hall",
)
_RESULT_VERB_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(_RESULT_VERB_STEMS) + r")",
    re.IGNORECASE,
)

# The authentic object whose confusion with replicas/models is plausible.
# Kept tight on purpose: bare "textos"/"fragmentos" alone do not count.
_AUTHENTIC_OBJECT_RE = re.compile(
    r"(?<!\w)(?:los|el|las|la)\s+"
    r"(?:rollos?|pergaminos?|manuscritos?|papiros?|tintas?|pacientes?|enfermos?)\b",
    re.IGNORECASE,
)

# A scope qualifier in the same sentence means the result is correctly
# attributed — not a bare authentic-object claim.
_SCOPE_QUALIFIER_RE = re.compile(
    r"r[ée]plicas?|modelos?|experimental(?:es)?|laboratorio|simula|artificial(?:es)?|"
    r"de prueba|piloto|preliminar(?:es)?|referencia|muestras?",
    re.IGNORECASE,
)


def _note_signals_replica_scope(uncertainty_note: Any) -> bool:
    return isinstance(uncertainty_note, str) and bool(
        _REPLICA_SCOPE_NOTE_RE.search(uncertainty_note)
    )


# A prospective hedge in the same sentence means the claim is framed as future
# work, not as an obtained result — skip it (mirrors _PRE_HEDGE_RE above).
_PROSPECTIVE_HEDGE_RE = re.compile(
    r"podr[íi]a[n]?|posibilidad|posibles?|potencial(?:es)?|abriendo camino|"
    r"abr\w+ la (?:posibilidad|puerta)|allan\w+|en el futuro|permitir[íi]a[n]?|"
    r"hipot[ée]tic",
    re.IGNORECASE,
)


def _sentence_has_bare_authentic_result(sentence: str) -> bool:
    """True when a sentence asserts an obtained result on the authentic object
    without replica/model qualification."""
    if _PROSPECTIVE_HEDGE_RE.search(sentence):
        return False
    if not _RESULT_VERB_RE.search(sentence):
        return False
    if not _AUTHENTIC_OBJECT_RE.search(sentence):
        return False
    return not _SCOPE_QUALIFIER_RE.search(sentence)


def _iter_scope_fields(fields: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield `(label, text)` for the summary-level strings a replica-scope
    mismatch would surface in: `summary_points`, `excerpt`, and the
    reader-facing `fact_check` labels (Codex P2 on frontend PR #191, second
    pass: a `confirmed` label presented replica-ink lead as authentic)."""
    raw_points = fields.get("summary_points")
    if isinstance(raw_points, list):
        for index, item in enumerate(raw_points):
            yield f"summary_points[{index}]", item
    yield "excerpt", fields.get("excerpt")
    raw_checks = fields.get("fact_check")
    if isinstance(raw_checks, list):
        for index, item in enumerate(raw_checks):
            label = item.get("label") if isinstance(item, Mapping) else None
            yield f"fact_check[{index}]", label


def _scan_text_for_scope(label: str, text: Any) -> list[str]:
    """`<label>: <sentence>` entries for the bare authentic-result sentences
    in one scope field. Empty for non-strings and clean text."""
    if not isinstance(text, str) or not text.strip():
        return []
    return [
        f"{label}: {sentence.strip()}"
        for sentence in _SENTENCE_SPLIT_RE.split(text.strip())
        if sentence.strip() and _sentence_has_bare_authentic_result(sentence.strip())
    ]


def find_replica_scope_mismatches(
    fields: Mapping[str, Any],
    *,
    requires_uncertainty_note: bool,
    uncertainty_note: Any,
) -> list[str]:
    """Flag summary-level results presented on the authentic object while the
    declared counterweight confines them to replicas/models.

    Runs only when `requires_uncertainty_note` is true or a non-empty
    `uncertainty_note` is present AND the note signals replica scope. Scans
    `summary_points` (list), `excerpt` (str) and `fact_check` labels for
    result assertions on the authentic object without replica qualification.
    Returns a list of `"<field>: <sentence>"` strings for the caller to log
    — it never edits `fields`. Never raises.
    """
    if not _has_counterweight(requires_uncertainty_note, uncertainty_note):
        return []
    if not _note_signals_replica_scope(uncertainty_note):
        return []

    out: list[str] = []
    for label, text in _iter_scope_fields(fields):
        out.extend(_scan_text_for_scope(label, text))
    return out


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
