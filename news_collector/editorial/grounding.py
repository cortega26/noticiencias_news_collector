"""Deterministic editorial grounding check (advisory).

Article 2315 passed every gate yet published figures, populations and scope
claims that its source never made ("miles de células", "millones de personas en
América Latina", rodent/fibrosis/GMP), plus stray typography (U+2011, U+202F).
The ``fact_check`` block is produced by the same model that writes the text, so
it cannot catch this. This module compares the generated article against the
*source text* with cheap, explainable rules:

1. ``number``            – every figure in the generated fields must occur in the source.
2. ``vague_quantifier``  – "miles/millones/decenas…" need a matching source quantifier.
3. ``scope_claim``       – populations/regions/models absent from the source.
4. ``overclaim``         – hype lexicon ("revolucionario", "sin precedentes"…).
5. ``hygiene``           – invisible/non-breaking characters, untranslated glossary terms.
6. ``fact_check``        – a ``confirmed`` item whose label is itself ungrounded.

Pure stdlib + PyYAML: no network, no DB, no LLM. Like readability, the output is
advisory (fail-open) until the backtest shows a precision worth blocking on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import yaml

# Below this many characters the stored source is usually a feed teaser, not the
# text the article was written from: grounding against it would be all noise.
MIN_SOURCE_CHARS = 1500

ERROR = "error"
WARN = "warn"

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
_WORD_BOUNDARY = r"(?<!\w){}(?!\w)"

# Frontmatter fields whose text is the article's own claims (glossary, sources
# and dates are reference material and are not checked).
_CLAIM_FIELDS = (
    "title",
    "excerpt",
    "summary_points",
    "why_it_matters",
    "fact_check",
    "headlines_variants",
    "confidence",
    "uncertainty_note",
)

_EN_UNITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)
_ES_UNITS = (
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciséis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
)

_ES_NUMBER_WORDS = tuple(_ES_UNITS[1:]) + (
    "treinta",
    "cuarenta",
    "cincuenta",
    "sesenta",
    "setenta",
    "ochenta",
    "noventa",
    "cien",
    "ciento",
)

_NUMBER_WORDS = {
    **{w: str(i) for i, w in enumerate(_EN_UNITS)},
    **{w: str(i) for i, w in enumerate(_ES_UNITS)},
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
    "hundred": "100",
    "treinta": "30",
    "cuarenta": "40",
    "cincuenta": "50",
    "sesenta": "60",
    "setenta": "70",
    "ochenta": "80",
    "noventa": "90",
    "cien": "100",
}

# (Spanish regex, source alternatives). Flagged when the generated text uses the
# Spanish form and the source contains none of the alternatives.
_VAGUE = (
    (r"miles", ("thousand",)),
    (r"millones", ("million",)),
    (r"billones", ("billion", "trillion")),
    (r"decenas", ("dozens", "tens of", "ten ")),
    (r"cientos|centenares", ("hundreds", "hundred")),
)

_SCOPE = (
    (
        "América Latina / Latinoamérica",
        r"am[eé]rica latina|latinoam[eé]rica|iberoam[eé]rica",
        ("latin america", "latam", "south america"),
    ),
    (
        "modelos en roedores",
        r"roedores?|ratones?|murin[oa]s?",
        ("rodent", "mice", "mouse", "murine", "rat ", "rats"),
    ),
    ("fibrosis", r"fibrosis", ("fibro",)),
    (
        "manufactura GMP",
        r"\bGMP\b|buenas pr[aá]cticas de fabricaci[oó]n",
        ("gmp", "good manufacturing"),
    ),
    (
        "ensayo clínico / humanos",
        r"ensayos? cl[ií]nicos?",
        ("clinical trial", "clinical study", "patients", "participants"),
    ),
    (
        "a nivel mundial",
        r"en todo el mundo|a nivel mundial|globalmente",
        ("worldwide", "global", "around the world", "world"),
    ),
)

# (Spanish regex, English source equivalents): a faithful translation of hype
# that the source itself uses is not the writer's overclaim.
_OVERCLAIMS = (
    (r"revolucionari[oa]s?", ("revolutionary", "revolutionize", "revolutionise")),
    (r"sin precedentes", ("unprecedented", "never before", "first of its kind")),
    (r"milagros[oa]s?", ("miracle", "miraculous")),
    (r"cambiar[aá] (?:para siempre|el mundo)", ("change the world", "forever")),
    (r"soluci[oó]n definitiva", ("ultimate solution", "definitive solution", "cure")),
    (r"soluci[oó]n de salud p[uú]blica", ("public health solution",)),
    (
        r"(?:paso|momento|d[ií]a|hito) hist[oó]rico",
        ("historic", "milestone", "landmark"),
    ),
    (r"gran avance", ("breakthrough", "major advance", "major step")),
)

_HYGIENE_CHARS = {
    "\u2011": "guion no separable (U+2011)",
    "\u202f": "espacio fino no separable (U+202F)",
    "\u00a0": "espacio no separable (U+00A0)",
    "\u200b": "espacio de ancho cero (U+200B)",
    "\u2060": "word joiner (U+2060)",
    "\ufeff": "BOM (U+FEFF)",
}
_HYGIENE_REPAIR = {
    "\u2011": "-",
    "\u202f": " ",
    "\u00a0": " ",
    "\u200b": "",
    "\u2060": "",
    "\ufeff": "",
}

_ANGLICISMS = (
    "bead",
    "beads",
    "insulin-producing",
    "scale-up",
    "outcome",
    "outcomes",
    "workflow",
    "endpoint",
    "endpoints",
    "cutoff",
)


@dataclass(frozen=True)
class GroundingFinding:
    kind: str
    severity: str
    field: str
    snippet: str
    detail: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "field": self.field,
            "snippet": self.snippet,
            "detail": self.detail,
        }


@dataclass
class GroundingReport:
    findings: List[GroundingFinding] = field(default_factory=list)
    checked_fields: int = 0
    source_chars: int = 0
    skipped_reason: str = ""

    @property
    def errors(self) -> List[GroundingFinding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> List[GroundingFinding]:
        return [f for f in self.findings if f.severity == WARN]

    def by_kind(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out

    def stage_details(self, top: int = 5) -> Dict[str, Any]:
        ranked = sorted(self.findings, key=lambda f: f.severity != ERROR)
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "by_kind": self.by_kind(),
            "source_chars": self.source_chars,
            "skipped_reason": self.skipped_reason,
            "findings": [f.as_dict() for f in ranked[:top]],
        }


# ---------------------------------------------------------------- normalizing


def normalize_text_hygiene(text: str) -> str:
    """Deterministic repair of invisible/non-breaking characters."""
    for bad, good in _HYGIENE_REPAIR.items():
        text = text.replace(bad, good)
    return text


_GROUPED_SPACE_RE = re.compile(r"(?<=\d)[ ](?=\d{3}(?!\d))")


def repair_text_hygiene(text: str) -> Tuple[str, int]:
    """``normalize_text_hygiene`` plus the number of characters it replaced."""
    repaired = normalize_text_hygiene(text)
    return repaired, sum(text.count(bad) for bad in _HYGIENE_REPAIR)


def _fold(text: str) -> str:
    """Lowercase NFKC text with space-grouped thousands joined ("30 000" -> "30000")."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return _GROUPED_SPACE_RE.sub("", folded)


def _number_forms(token: str) -> set[str]:
    """Readings of a numeric token (Spanish and English separators)."""
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        # Grouped thousands ("1,500" / "1.500"): only the integer reading, or
        # "1,500" in a source would also ground an unsupported "1,5".
        return {token, re.sub(r"[.,]", "", token)}
    forms = {token, token.replace(",", ".")}
    return {f.rstrip("0").rstrip(".") if "." in f else f for f in forms}


def _numbers_in(text: str) -> List[Tuple[str, set[str], int]]:
    text = _fold(text)
    out = [
        (m.group(0), _number_forms(m.group(0)), m.start())
        for m in _NUMBER_RE.finditer(text)
    ]
    return out


def _source_number_set(source: str) -> set[str]:
    folded = _fold(source)
    forms: set[str] = set()
    for _, f, _pos in _numbers_in(folded):
        forms |= f
    for word, digits in _NUMBER_WORDS.items():
        if re.search(_WORD_BOUNDARY.format(re.escape(word)), folded):
            forms.add(digits)
    return forms


def _snippet(text: str, start: int, width: int = 70) -> str:
    lo, hi = max(0, start - width // 2), min(len(text), start + width)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


# ------------------------------------------------------------------- parsing


def _split_frontmatter(markdown: str) -> Tuple[Mapping[str, Any], str]:
    match = _FRONTMATTER_RE.match(markdown or "")
    if not match:
        return {}, markdown or ""
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        loaded = None
    return (loaded if isinstance(loaded, dict) else {}), match.group(2)


def _field_texts(value: Any) -> List[str]:
    """Strings inside a frontmatter value (str, mapping values, list items or
    ``label``/``text`` of list-of-mapping items such as ``fact_check``)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [v for v in value.values() if isinstance(v, str)]
    texts: List[str] = []
    if isinstance(value, Sequence):
        for item in value:
            if isinstance(item, Mapping):
                item = item.get("label") or item.get("text")
            if isinstance(item, str):
                texts.append(item)
    return texts


def extract_claim_segments(markdown: str) -> List[Tuple[str, str]]:
    """``(field, text)`` pairs of the article's own claims (frontmatter fields
    plus body). Tolerates missing/invalid frontmatter (body only)."""
    meta, body = _split_frontmatter(markdown)
    segments = [
        (key, text) for key in _CLAIM_FIELDS for text in _field_texts(meta.get(key))
    ]
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    if body.strip():
        segments.append(("body", body))
    return segments


# --------------------------------------------------------------------- rules


def _check_numbers(
    field_name: str, text: str, source_numbers: set[str]
) -> List[GroundingFinding]:
    out = []
    for raw, forms, pos in _numbers_in(text):
        if forms & source_numbers:
            continue
        out.append(
            GroundingFinding(
                "number",
                ERROR,
                field_name,
                _snippet(text, pos),
                f"la cifra «{raw}» no aparece en la fuente",
            )
        )
    return out


def _check_vague(field_name: str, text: str, source: str) -> List[GroundingFinding]:
    out = []
    folded = _fold(text)
    for pattern, alternatives in _VAGUE:
        for m in re.finditer(_WORD_BOUNDARY.format(f"(?:{pattern})"), folded):
            if any(a in source for a in alternatives):
                continue
            before = folded[max(0, m.start() - 16) : m.start()]
            if re.search(r"[\d$€]\s*$", before) or re.search(
                r"(?<!\w)(?:mil|" + "|".join(_ES_NUMBER_WORDS) + r")\s+$", before
            ):
                continue  # "2.200 millones", "treinta mil millones": a figure
            out.append(
                GroundingFinding(
                    "vague_quantifier",
                    ERROR,
                    field_name,
                    _snippet(text, m.start()),
                    f"«{m.group(0)}» sin cantidad equivalente en la fuente",
                )
            )
    return out


def _check_scope(
    field_name: str, text: str, source: str, allow: Iterable[str]
) -> List[GroundingFinding]:
    out = []
    folded = _fold(text)
    allowed = {_fold(a) for a in allow}
    for label, pattern, alternatives in _SCOPE:
        if _fold(label) in allowed:
            continue
        if label.startswith("América Latina") and field_name == "why_it_matters":
            continue  # editorial-voice framing for the LatAm audience
        for m in re.finditer(pattern, folded, flags=re.IGNORECASE):
            if m.group(0) in allowed or any(a in source for a in alternatives):
                continue
            out.append(
                GroundingFinding(
                    "scope_claim",
                    WARN,
                    field_name,
                    _snippet(text, m.start()),
                    f"alcance «{label}» no respaldado por la fuente",
                )
            )
            break  # one finding per label per segment
    return out


def _check_overclaims(
    field_name: str, text: str, source: str
) -> List[GroundingFinding]:
    out = []
    folded = _fold(text)
    for pattern, alternatives in _OVERCLAIMS:
        m = re.search(pattern, folded)
        if (
            m
            and m.group(0) not in source
            and not any(a in source for a in alternatives)
        ):
            out.append(
                GroundingFinding(
                    "overclaim",
                    WARN,
                    field_name,
                    _snippet(text, m.start()),
                    f"lenguaje exagerado «{m.group(0)}»",
                )
            )
    return out


def _check_hygiene(field_name: str, text: str) -> List[GroundingFinding]:
    out = []
    for char, name in _HYGIENE_CHARS.items():
        idx = text.find(char)
        if idx != -1:
            out.append(
                GroundingFinding(
                    "hygiene",
                    WARN,
                    field_name,
                    _snippet(text, idx),
                    f"carácter especial: {name} ({text.count(char)}×)",
                )
            )
    folded = text.lower()
    for term in _ANGLICISMS:
        m = re.search(_WORD_BOUNDARY.format(re.escape(term)), folded)
        if m:
            out.append(
                GroundingFinding(
                    "hygiene",
                    WARN,
                    field_name,
                    _snippet(text, m.start()),
                    f"anglicismo sin traducir «{term}»",
                )
            )
    return out


def check_grounding(
    markdown: str,
    source_text: str,
    *,
    allow_terms: Iterable[str] = (),
    min_source_chars: int = MIN_SOURCE_CHARS,
) -> GroundingReport:
    """Compare a generated Markdown article with its source text.

    Never raises on odd input. A missing/too-short source yields an empty report
    with ``skipped_reason='source_too_short'``: nothing reliable to ground
    against, so no signal rather than a false alarm.
    """
    report = GroundingReport(source_chars=len(source_text or ""))
    if len((source_text or "").strip()) < min_source_chars:
        report.skipped_reason = "source_too_short"
        return report
    source = _fold(source_text)
    source_numbers = _source_number_set(source_text)
    allow = tuple(allow_terms)

    segments = extract_claim_segments(markdown)
    report.checked_fields = len(segments)
    ungrounded_fact_labels: List[str] = []
    for field_name, text in segments:
        found: List[GroundingFinding] = []
        found += _check_numbers(field_name, text, source_numbers)
        found += _check_vague(field_name, text, source)
        found += _check_scope(field_name, text, source, allow)
        found += _check_overclaims(field_name, text, source)
        found += _check_hygiene(field_name, text)
        report.findings += found
        if field_name == "fact_check" and any(f.severity == ERROR for f in found):
            ungrounded_fact_labels.append(text)

    for label in ungrounded_fact_labels:
        report.findings.append(
            GroundingFinding(
                "fact_check",
                WARN,
                "fact_check",
                label[:70],
                "ítem de fact_check con cifras/cantidades no respaldadas",
            )
        )
    return report
