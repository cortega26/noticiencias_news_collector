"""Deterministic Spanish readability signals for a general audience.

Plan 065 — "Readability gates". Noticiencias writes for the "lector hispano
no especialista" (EDITORIAL_VOICE.md §2: short sentences, zero unexplained
jargon), but the pipeline had no objective legibility measure — only a crude
sentence-length heuristic in the pre-scorer. This module fills that gap
without any LLM cost:

- Spanish syllable counting (diphthong/hiatus/triphthong rules).
- Fernández-Huerta (IFH) and Flesch-Szigriszt (IFSZ) perspicuidad scores,
  the two validated Spanish adaptations of Flesch Reading Ease.
- Advisory headline checks derived from the editorial-voice contract
  (speculative adjectives, clickbait phrasing, shouting, length).

Pure stdlib: no network, no DB, no LLM. All consumers treat the output as
advisory (fail-open) — a readability heuristic must never block publication.

Formulas (any-length form, S=syllables, P=words, F=sentences)::

    IFH  = 206.84 − 60.0 × (S/P) − 1.02 × (P/F)
    IFSZ = 206.84 − 62.3 × (S/P) − (P/F)

IFSZ is the primary score (better validated for Spanish); IFH is reported
alongside for comparability. Grade bands follow the Fernández-Huerta table
(90+ muy fácil … <15 muy difícil).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STRONG_VOWELS = frozenset("aeoáéó")
_WEAK_VOWELS = frozenset("iuüíú")
_ACCENTED_WEAK = frozenset("íú")

_WORD_RE = re.compile(r"[a-záéíóúüñ]+(?:-[a-záéíóúüñ]+)*")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+")
_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n.*?\n---\s*", re.DOTALL)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_DECIMAL_GUARD_RE = re.compile(r"(\d)\.(\d)")

# Abbreviations whose trailing period must not split sentences. Lowercase,
# without the period; matched case-insensitively ("EE. UU." is normalized
# separately because of its internal space).
_ABBREVIATIONS = (
    "sr",
    "sra",
    "srta",
    "dr",
    "dra",
    "ud",
    "uds",
    "ej",
    "pág",
    "págs",
    "núm",
    "art",
    "cap",
    "vol",
    "eds",
    "etc",
    "vs",
    "ing",
    "arq",
    "lic",
)
_ABBREV_RE = re.compile(r"\b(?:" + "|".join(_ABBREVIATIONS) + r")\.", re.IGNORECASE)
_EEUU_RE = re.compile(r"\bEE\s*\.?\s*UU\s*\.?")

HEADLINE_MAX_CHARS = 110
HEADLINE_MIN_CHARS = 20

# EDITORIAL_VOICE.md §2.4 rule 2: speculative adjectives may only appear
# quoting an identified source, never as editorial voice.
SPECULATIVE_ADJECTIVES = (
    "revolucionario",
    "revolucionaria",
    "revolucionarios",
    "revolucionarias",
    "increíble",
    "increíbles",
    "increible",
    "increibles",
    "histórico",
    "histórica",
    "históricos",
    "históricas",
    "historico",
    "historica",
    "historicos",
    "historicas",
    "asombroso",
    "asombrosa",
    "asombrosos",
    "asombrosas",
    "milagroso",
    "milagrosa",
    "milagrosos",
    "milagrosas",
)

# EDITORIAL_VOICE.md §2.4: betrayed curiosity gaps / manufactured emotion.
CLICKBAIT_PHRASES = (
    "no vas a creer",
    "no creerás",
    "no lo creerás",
    "te dejará sin palabras",
    "cambiará tu vida",
    "cambiara tu vida",
    "va a cambiar tu vida",
    "lo que pasó después",
    "nadie te cuenta",
)

# Legitimate all-caps tokens that must not trip the shouting check.
ACRONYM_ALLOWLIST = frozenset(
    {"COVID", "ADN", "ARN", "VIH", "SIDA", "ONU", "OTAN", "EEUU", "GPS", "LED"}
)

_READABILITY_GRADES = (
    (90, "muy fácil"),
    (80, "fácil"),
    (70, "bastante fácil"),
    (60, "normal"),
    (50, "bastante difícil"),
    (30, "difícil"),
    (float("-inf"), "muy difícil"),
)

_DOT_PLACEHOLDER = "<dot>"


def count_syllables_es(word: str) -> int:
    """Count Spanish syllables in a single word.

    Rules: maximal vowel runs split on consonants; inside a run, a new
    syllable starts at a weak vowel carrying the written accent (í/ú) or
    after one, and between two strong vowels (a, e, o). Everything else —
    unaccented weak+strong / strong+weak / weak+weak, including triphthongs
    — is one syllable. `h` is transparent between vowels; word-final `y`
    acts as a vowel; silent `u` in "qu"/"gu" + e/i (qué, guerra — but never
    with diaeresis: pingüino) is skipped. Words without vowels (digits,
    abbreviations) count 1.
    """
    naked = word.lower().replace("h", "")
    if not naked:
        return 0
    chars = list(naked)
    silent = set()
    for j, ch in enumerate(chars):
        if (
            ch == "u"
            and j > 0
            and chars[j - 1] in ("g", "q")
            and j + 1 < len(chars)
            and chars[j + 1] in ("e", "i", "é", "í")
        ):
            silent.add(j)
    last = len(chars) - 1
    # Vowel stream with consonant boundaries preserved as None.
    seq: list[str | None] = []
    for i, ch in enumerate(chars):
        if i in silent:
            continue
        if ch in _STRONG_VOWELS or ch in _WEAK_VOWELS:
            seq.append(ch)
        elif ch == "y" and i == last:
            seq.append("y")
        else:
            seq.append(None)

    total = 0
    run: list[str] = []
    for item in seq + [None]:
        if item is None:
            total += _count_run_syllables(run)
            run = []
        else:
            run.append(item)
    return total or 1


def _count_run_syllables(run: list[str]) -> int:
    if not run:
        return 0
    count = 1
    for prev, curr in zip(run, run[1:], strict=False):
        if (
            curr in _ACCENTED_WEAK
            or prev in _ACCENTED_WEAK
            or (prev in _STRONG_VOWELS and curr in _STRONG_VOWELS)
        ):
            count += 1
        # else: diphthong / triphthong — same syllable
    return count


def split_sentences_es(text: str) -> list[str]:
    """Split Spanish prose into sentences without breaking on abbreviations
    ("Sr.", "EE. UU."), decimal numbers ("3.5") or ellipses."""
    guarded = _DECIMAL_GUARD_RE.sub(rf"\1{_DOT_PLACEHOLDER}\2", text)
    guarded = _ABBREV_RE.sub(
        lambda m: m.group(0).replace(".", _DOT_PLACEHOLDER), guarded
    )
    guarded = _EEUU_RE.sub("EEUU", guarded)
    parts = _SENTENCE_SPLIT_RE.split(guarded)
    return [
        part.replace(_DOT_PLACEHOLDER, ".").strip() for part in parts if part.strip()
    ]


def count_words_es(text: str) -> list[str]:
    """Tokenize Spanish words (lowercased, keeps ñ/accents, splits hyphens)."""
    return _WORD_RE.findall(text.lower())


def fernandez_huerta_ifh(syllables: int, words: int, sentences: int) -> float | None:
    """Fernández-Huerta lecturabilidad (1959), any-length form."""
    if words <= 0 or sentences <= 0:
        return None
    return 206.84 - 60.0 * (syllables / words) - 1.02 * (words / sentences)


def szigriszt_ifsz(syllables: int, words: int, sentences: int) -> float | None:
    """Flesch-Szigriszt perspicuidad (1993), the better-validated Spanish
    adaptation. Primary score reported by this module."""
    if words <= 0 or sentences <= 0:
        return None
    return 206.84 - 62.3 * (syllables / words) - (words / sentences)


def readability_grade(score: float | None) -> str:
    """Fernández-Huerta grade band for a 0–100 perspicuidad score."""
    if score is None:
        return "sin contenido"
    for threshold, label in _READABILITY_GRADES:
        if score >= threshold:
            return label
    return "muy difícil"  # pragma: no cover - guarded by -inf band


def readability_suitability(score: float | None) -> float | None:
    """Map a 0–100 score to 0..1 general-audience suitability.

    1.0 ≈ press-grade easy (≥75), 0.0 ≈ academic (<15). Continuous so it can
    later weight scoring; bands stay human-readable via `readability_grade`.
    """
    if score is None:
        return None
    return round(min(1.0, max(0.0, (score - 15.0) / 60.0)), 3)


def _strip_markdown_noise(text: str) -> str:
    body = _FRONTMATTER_RE.sub("", text)
    body = _FENCED_CODE_RE.sub(" ", body)
    body = _INLINE_CODE_RE.sub(" ", body)
    return _URL_RE.sub(" ", body)


@dataclass(frozen=True)
class ReadabilityReport:
    """Deterministic legibility snapshot of an article body."""

    words: int
    sentences: int
    syllables: int
    avg_syllables_per_word: float
    avg_words_per_sentence: float
    ifsz: float | None
    ifh: float | None
    grade: str
    suitability: float | None

    def stage_details(self) -> dict[str, Any]:
        """Payload for `record_stage("readability", ...)` (None values are
        dropped by the recorder, so empty content still yields a valid row)."""
        return {
            "ifsz": self.ifsz,
            "ifh": self.ifh,
            "grade": self.grade,
            "suitability": self.suitability,
            "words": self.words,
            "sentences": self.sentences,
            "syllables": self.syllables,
        }


def analyze_body_readability(markdown: str) -> ReadabilityReport:
    """Score the narrative body of a Markdown article (frontmatter, code and
    URLs excluded). Never raises on odd input — empty text yields a
    zero-count report with null scores."""
    body = _strip_markdown_noise(markdown or "")
    words = count_words_es(body)
    sentences = split_sentences_es(body)
    syllables = sum(count_syllables_es(word) for word in words)
    word_count = len(words)
    sentence_count = len(sentences)
    ifsz = szigriszt_ifsz(syllables, word_count, sentence_count)
    ifh = fernandez_huerta_ifh(syllables, word_count, sentence_count)
    return ReadabilityReport(
        words=word_count,
        sentences=sentence_count,
        syllables=syllables,
        avg_syllables_per_word=round(syllables / word_count, 3) if word_count else 0.0,
        avg_words_per_sentence=(
            round(word_count / sentence_count, 2) if sentence_count else 0.0
        ),
        ifsz=round(ifsz, 2) if ifsz is not None else None,
        ifh=round(ifh, 2) if ifh is not None else None,
        grade=readability_grade(ifsz),
        suitability=readability_suitability(ifsz),
    )


@dataclass(frozen=True)
class HeadlineIssue:
    """One advisory finding about a headline. Severity is always advisory —
    the headline critic (LLM) remains the quality judge; these are cheap
    deterministic tripwires from the editorial-voice contract."""

    code: str
    message: str
    severity: str = field(default="warn")


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r'"[^"]*"|“[^”]*"', text):
        spans.append(match.span())
    return spans


def _unquoted(text: str) -> str:
    """Blank out double-quoted spans (attributed quotes are legitimate even
    when they contain strong adjectives — voice §2.4 rule 2)."""
    chars = list(text)
    for start, end in _quoted_spans(text):
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def check_headline(headline: str | list[str] | None) -> list[HeadlineIssue]:
    """Run deterministic voice-contract checks over a headline. Returns []
    when clean; never raises. List payloads (the model sometimes returns a
    list for `direct`) are judged on their first element."""
    if isinstance(headline, (list, tuple)):
        headline = headline[0] if headline else ""
    text = str(headline or "").strip()
    if not text:
        return [HeadlineIssue("empty", "El titular está vacío.")]
    issues: list[HeadlineIssue] = []
    if len(text) > HEADLINE_MAX_CHARS:
        issues.append(
            HeadlineIssue(
                "too-long",
                f"El titular supera {HEADLINE_MAX_CHARS} caracteres "
                f"({len(text)}): la voz pide frases cortas.",
            )
        )
    if len(text) < HEADLINE_MIN_CHARS:
        issues.append(
            HeadlineIssue(
                "too-short",
                f"El titular es muy corto ({len(text)} caracteres): "
                "probablemente sin gancho.",
            )
        )
    if text.endswith("."):
        issues.append(
            HeadlineIssue("trailing-period", "El titular termina en punto (sobra).")
        )
    if "!!" in text:
        issues.append(
            HeadlineIssue("shouting", "Doble exclamación: sensacionalismo tipográfico.")
        )
    shouting = sorted(
        {
            re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token)
            for token in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.]+\.?", text)
            if len(re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token)) >= 3
            and re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token).isupper()
        }
        - ACRONYM_ALLOWLIST
    )
    if shouting:
        issues.append(
            HeadlineIssue(
                "all-caps",
                f"Palabras en mayúsculas sostenidas ({', '.join(shouting[:3])}): "
                "verificar que no gritan.",
            )
        )
    plain = _unquoted(text).lower()
    flagged_adj = sorted(
        {
            adj
            for adj in SPECULATIVE_ADJECTIVES
            if re.search(r"\b" + re.escape(adj) + r"\b", plain)
        }
    )
    if flagged_adj:
        issues.append(
            HeadlineIssue(
                "speculative-adjective",
                f"Adjetivo especulativo sin atribución ({', '.join(flagged_adj)}): "
                "la voz §2.4 solo lo permite citando a una fuente.",
            )
        )
    flagged_bait = sorted(
        {phrase for phrase in CLICKBAIT_PHRASES if phrase in text.lower()}
    )
    if flagged_bait:
        issues.append(
            HeadlineIssue(
                "clickbait-phrase",
                f"Frase de clickbait ({', '.join(flagged_bait)}): cruza la "
                "línea roja de sensacionalismo.",
            )
        )
    return issues
