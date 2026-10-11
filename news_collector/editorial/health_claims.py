"""Deterministic guarantee-language check for health-scope prose.

Benchmark evidence (`reports/evaluation/routing-glm53/REPORT.md`): the
challenger arm failed the same salud article 3/3 with therapeutic
overgeneralizations ("Un CAC de cero garantiza que no habrá eventos
cardiovasculares"). The in-flow grounded gate caught them, but only after
full drafting + verification. Guarantee phrasing is detectable with
regexes, so flag it deterministically and early.

Health-scoped via `health_scope.is_health_scope` (the single definition of
health scope — reused here, never redefined). Outside health scope this
module is silent: "garantiza" in a technology article is not our problem.

Pure stdlib: no network, no DB, no LLM. Output is advisory (fail-open) —
consumers log/record findings but never block publication, mirroring
`readability` and `voice_tics` (the fact-check verifier stays the judge).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from news_collector.editorial.health_scope import is_health_scope

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n.*?\n---\s*", re.DOTALL)
_QUOTED_RE = re.compile(r'"[^"]*"|“[^”]*"')


@dataclass(frozen=True)
class GuaranteeFinding:
    """One advisory guarantee-language finding. Severity is always advisory."""

    code: str
    message: str
    count: int
    snippets: tuple[str, ...] = ()
    severity: str = field(default="warn")


# Guarantee phrasing that a health article must never state without
# qualification. Matched outside quoted spans (a quoted clinician is the
# source's voice, not ours — though editors should still prefer paraphrase).
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "garantiza",
        r"garantiz[ao](?:n)?\b",
        "Verbo 'garantizar' en contexto de salud (ningún resultado clínico se garantiza)",
    ),
    (
        "cero_riesgo",
        r"cero riesgo|riesgo cero|ning[uú]n riesgo|sin (?:ning[uú]n|ningun) riesgo",
        "Afirmación de riesgo cero en salud",
    ),
    (
        "cura_definitiva",
        r"cura definitiva|curaci[oó]n definitiva|curar[áa] (?:por completo|definitivamente)",
        "Afirmación de cura definitiva",
    ),
    (
        "todos_los_pacientes",
        r"todos los pacientes|todas las personas\b.{0,40}?(?:mejor|cur|proteg|benefici)",
        "Generalización universal sobre pacientes/personas",
    ),
    (
        "sin_efectos",
        r"sin efectos secundarios|sin contraindicaciones",
        "Afirmación de ausencia total de efectos adversos",
    ),
    (
        "cien_por_cien",
        r"100\s?%\s*(?:seguro|eficaz|efectivo|exitoso)|totalmente seguro|completamente eficaz",
        "Eficacia/seguridad absoluta (100 %)",
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (code, re.compile(pattern, re.IGNORECASE), message)
    for code, pattern, message in _PATTERNS
)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _QUOTED_RE.finditer(text)]


def _snippet(text: str, offset: int, width: int = 60) -> str:
    start = max(0, offset - width // 2)
    return text[start : start + width].strip()[:width]


def find_guarantee_language(
    body: Any,
    category: Any = None,
    *,
    categories: Any = None,
    metadata_category: Any = None,
) -> list[GuaranteeFinding]:
    """Return advisory guarantee-language findings for health-scope prose.

    Silent (empty list) outside health scope, on degenerate input, or when
    matches occur only inside quoted spans. Never raises, never blocks.
    """
    if not isinstance(body, str) or not body.strip():
        return []
    if not is_health_scope(
        categories=categories,
        category=category,
        metadata_category=metadata_category,
        text=body,
    ):
        return []
    text = _strip_frontmatter(body)
    if not text.strip():
        return []
    quoted = _quoted_spans(text)
    findings: list[GuaranteeFinding] = []
    for code, pattern, message in _COMPILED:
        hits = [
            match
            for match in pattern.finditer(text)
            if not any(start <= match.start() < end for start, end in quoted)
        ]
        if hits:
            findings.append(
                GuaranteeFinding(
                    code=code,
                    message=f"{message}: {len(hits)} ocurrencia(s)",
                    count=len(hits),
                    snippets=tuple(_snippet(text, h.start()) for h in hits[:3]),
                )
            )
    return findings
