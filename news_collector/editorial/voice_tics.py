"""Deterministic voice-tic lint for generated Spanish prose.

Benchmark evidence (`reports/evaluation/routing-glm53/REPORT.md`, per-stage
observations): LLM critics on both arms repeatedly flagged the same
stylistic tics — "Imagina…" openings, "No es X, es Y", "no solo… sino
también" — and passing outputs still carried them (6 hits across 23 ok
articles). LLM judgment is nondeterministic, so these need a cheap
deterministic backstop. The voice contract already bans them
(`EDITORIAL_VOICE.md`, `prompts.yaml` editor_critic voice_score); this
module enforces that ban without an LLM call.

Pure stdlib: no network, no DB, no LLM. Output is advisory (fail-open) —
consumers log/record findings but never block publication, mirroring
`readability.check_english_spillover` (the translation critic stays the
judge for language; the editorial critic stays the judge for voice).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n.*?\n---\s*", re.DOTALL)
_QUOTED_RE = re.compile(r'"[^"]*"|“[^”]*"')


@dataclass(frozen=True)
class VoiceTic:
    """One advisory voice-tic finding. Severity is always advisory."""

    code: str
    message: str
    count: int
    snippets: tuple[str, ...] = ()
    severity: str = field(default="warn")


# (code, regex, human message). Patterns target the *editorial voice*
# failure, not legitimate contrast: "no es X, es Y" fires only on the
# comma-spliced tic shape the critics kept flagging, and every pattern is
# matched outside quoted spans (quoted source speech is not our voice).
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "imagina_opening",
        r"(?m)^\s*(?:imagina(?:te|mos)?(?:\s+que|\s+por\b)?)",
        "Apertura 'Imagina…' prohibida por el repertorio de aperturas",
    ),
    (
        "no_es_X_es_Y",
        r"no es [^,.\n]{1,60}?,\s*es\b",
        "Tic 'No es X, es Y' (contraste mecánico; reescribir)",
    ),
    (
        "no_solo_sino",
        r"no s[oó]lo [^.\n]{1,80}?sino tambi[eé]n",
        "Tic 'no solo X sino también Y' (muletilla; reescribir)",
    ),
    (
        "mundo_donde",
        r"en un mundo donde",
        "Apertura prohibida 'En un mundo donde'",
    ),
    (
        "sin_lugar_a_dudas",
        r"sin lugar a dudas",
        "Muletilla de certeza editorial ('sin lugar a dudas')",
    ),
    (
        "cabe_destacar",
        r"cabe destacar|es importante (?:notar|destacar)|cabe señalar",
        "Muletilla metadiscursiva ('cabe destacar' / 'es importante notar')",
    ),
)

# Voseo forms banned by the voice contract (panhispanic tuteo only).
# Imperatives + present conjugations, word-boundaried; "mantenelo"-style
# enclitics covered by the imperative stems (mantené).
_VOSEO = (
    "mirá",
    "fijate",
    "usá",
    "elegí",
    "tené",
    "decí",
    "hacé",
    "reescribí",
    "mantené",
    "conservá",
    "asegurate",
    "podés",
    "tenés",
    "querés",
    "sabés",
    "vos",
)

_VOSEO_RE = re.compile(r"(?<![\wáéíóúüñ])(" + "|".join(_VOSEO) + r")(?![\wáéíóúüñ])")

_COMPILED: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (code, re.compile(pattern, re.IGNORECASE), message)
    for code, pattern, message in _PATTERNS
)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _QUOTED_RE.finditer(text)]


def _in_spans(offset: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in spans)


def _snippet(text: str, offset: int, width: int = 60) -> str:
    start = max(0, offset - width // 2)
    return text[start : start + width].strip()[:width]


def _unquoted_hits(
    pattern: re.Pattern[str], body: str, quoted: list[tuple[int, int]]
) -> list[re.Match[str]]:
    """Matches of `pattern` outside quoted spans (quoted speech is the
    source's voice, not ours)."""
    return [
        match
        for match in pattern.finditer(body)
        if not _in_spans(match.start(), quoted)
    ]


def _to_finding(
    code: str, message: str, body: str, hits: list[re.Match[str]]
) -> VoiceTic:
    return VoiceTic(
        code=code,
        message=f"{message}: {len(hits)} ocurrencia(s)",
        count=len(hits),
        snippets=tuple(_snippet(body, hit.start()) for hit in hits[:3]),
    )


def check_voice_tics(markdown: str | None) -> list[VoiceTic]:
    """Return advisory voice-tic findings for generated article markdown.

    Frontmatter is stripped and quoted spans are excluded (quoted speech is
    the source's voice, not ours). `None`/empty input yields no findings —
    never raises, never blocks.
    """
    if not markdown or not isinstance(markdown, str):
        return []
    body = _strip_frontmatter(markdown)
    if not body.strip():
        return []
    quoted = _quoted_spans(body)
    findings = []
    for code, pattern, message in _COMPILED:
        hits = _unquoted_hits(pattern, body, quoted)
        if hits:
            findings.append(_to_finding(code, message, body, hits))
    # "vos" alone is a strong signal but also a substring risk; the
    # word-boundaried regex below already constrains it. Report once.
    voseo_hits = _unquoted_hits(_VOSEO_RE, body.lower(), quoted)
    if voseo_hits:
        findings.append(
            _to_finding(
                "voseo",
                "Voseo rioplatense prohibido (tuteo neutro requerido)",
                body,
                voseo_hits,
            )
        )
    return findings
