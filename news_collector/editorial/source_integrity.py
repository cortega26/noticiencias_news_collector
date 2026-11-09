"""Deterministic source and claim integrity rules for generated articles.

Plan 211. Four draft PRs reached the frontend with defects no gate caught: an
invented DOI and paper title (HTTP 404), a source dated two years before the
article, a university homepage listed as a source, author claims marked
``confirmed`` although an independent expert disputed them, a loose headline
line at the top of the body, a ``#hashtag`` that breaks a frontend test, and a
person named differently in the frontmatter and in the body.

The generation model produces ``sources`` and ``fact_check`` itself, so it
cannot police them. These rules compare the generated fields with the
*ingested evidence* and repair or flag what they find.

Pure stdlib: no network, no DB, no LLM. ``ground_sources``,
``downgrade_unattributed_certainty`` and the two body sanitizers repair their
input; the ``find_*`` helpers are advisory and only report.

Complements ``editorial/grounding.py`` (numbers, scope, hype), which stays
advisory and is not duplicated here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

# A DOI is a stable identifier: it either appears in the evidence or it does
# not. Trailing punctuation is not part of the identifier.
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:)]}'\""

# Source dates are kept only when they are plausible for the article: not after
# it and at most this many days before it.
SOURCE_DATE_MAX_AGE_DAYS = 90


def _norm_url(url: str) -> str:
    """Compare URLs ignoring scheme, ``www.``, query, fragment and trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}".lower()


def _doi_of(url: str) -> str | None:
    match = _DOI_RE.search(url)
    if not match:
        return None
    return match.group(0).rstrip(_TRAILING_PUNCT).lower()


def _is_homepage(url: str) -> bool:
    parts = urlsplit(url.strip())
    return bool(parts.netloc) and parts.path.strip("/") == ""


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class SourceGrounding:
    """Outcome of :func:`ground_sources`."""

    sources: list[dict[str, Any]]
    dropped: list[str] = field(default_factory=list)
    dates_removed: list[str] = field(default_factory=list)
    primary_added: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.dropped or self.dates_removed or self.primary_added)


def _is_grounded(
    url: str, *, primary: str | None, evidence_norm: str, evidence: str
) -> bool:
    if primary and _norm_url(url) == primary:
        return True
    if _is_homepage(url):
        return False
    if _norm_url(url) in evidence_norm:
        return True
    doi = _doi_of(url)
    return doi is not None and doi in evidence.lower()


def ground_sources(
    sources: Sequence[Mapping[str, Any]],
    *,
    source_url: str | None,
    source_title: str | None,
    source_publisher: str | None,
    evidence_text: str,
    article_date: Any,
) -> SourceGrounding:
    """Keep only sources the ingested evidence supports.

    A source survives when its URL is the article's own ``source_url``, occurs
    literally in ``evidence_text``, or is a DOI that occurs there. Bare
    homepages are never sources. When nothing survives, the primary source is
    added with the known title and publisher, so ``sources`` is never empty
    because of this rule. A date survives only when ISO, not after the article and at most
    ``SOURCE_DATE_MAX_AGE_DAYS`` before it.
    """
    primary = _norm_url(source_url) if source_url else None
    evidence_norm = " ".join(
        _norm_url(m.group(0).rstrip(_TRAILING_PUNCT))
        for m in re.finditer(r"https?://[^\s\"'<>)\]]+", evidence_text)
    )
    published = _as_date(article_date)

    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    dates_removed: list[str] = []
    for raw in sources:
        item = dict(raw)
        url = str(item.get("url") or "").strip()
        if not url or not _is_grounded(
            url, primary=primary, evidence_norm=evidence_norm, evidence=evidence_text
        ):
            dropped.append(url or str(item.get("title") or "(sin URL)"))
            continue
        when = item.get("date")
        if when:
            parsed = _as_date(when)
            ok = (
                parsed is not None
                and published is not None
                and parsed <= published
                and published - parsed <= timedelta(days=SOURCE_DATE_MAX_AGE_DAYS)
            )
            if not ok:
                dates_removed.append(f"{url} ({when})")
                item.pop("date")
        kept.append(item)

    if not kept and not source_url:
        # Nothing to ground against and no primary source to fall back on:
        # dropping everything would leave the article without sources.
        return SourceGrounding([dict(s) for s in sources])

    primary_added = False
    if source_url and not kept:
        entry: dict[str, Any] = {
            "title": (source_title or source_url).strip(),
            "url": source_url,
        }
        if source_publisher:
            entry["publisher"] = source_publisher
        kept.insert(0, entry)
        primary_added = True
    return SourceGrounding(kept, dropped, dates_removed, primary_added)


# Categorical wording: what a source usually attributes to its authors and an
# article must not state as established fact when it carries an uncertainty note.
_CATEGORICAL_RE = re.compile(
    r"\b(m[aá]s\s+(?:antigu[ao]|s[oó]lid[ao]|import\w+|grande)s?|"
    r"prim(?:er|era|eros|eras)|[uú]nic[oa]s?|"
    r"explica(?:n|r[ií]a)?|demuestr\w+|demostr\w+|confirm[oó]\w*|"
    r"prueba(?:s)?\s+(?:qu[ií]mica|definitiva|concluyente)\w*|"
    r"resuelve\w*|cura\w*|causa(?:n)?)\b",
    re.IGNORECASE,
)


def downgrade_unattributed_certainty(
    fact_check: Sequence[Mapping[str, Any]],
    *,
    requires_uncertainty_note: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Lower ``confirmed`` to ``uncertain`` for categorical claims under a caveat.

    Only applies when the article declares an uncertainty note. ``uncertain`` is
    advisory and never blocks, so this cannot mask a ``disputed`` verdict; the
    disputed gate reads the verifier's own output, not this list.
    """
    items = [dict(item) for item in fact_check]
    if not requires_uncertainty_note:
        return items, []
    downgraded: list[str] = []
    for item in items:
        label = str(item.get("label") or "")
        if item.get("status") == "confirmed" and _CATEGORICAL_RE.search(label):
            item["status"] = "uncertain"
            downgraded.append(label)
    return items, downgraded


_HASHTAG_RE = re.compile(r"(?<![\w&/#])#(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]\w)")


def strip_stray_hashtags(body: str) -> tuple[str, int]:
    """Remove the ``#`` of inline hashtags; Markdown headings are untouched."""
    out: list[str] = []
    count = 0
    in_fence = False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence or re.match(r"\s{0,3}#{1,6}\s", line):
            out.append(line)
            continue
        new, n = _HASHTAG_RE.subn("", line)
        count += n
        out.append(new)
    return "\n".join(out), count


_SENTENCE_END = '.?!…»"”:;'
_MAX_HEADLINE_LEN = 160


def strip_leading_headline_line(body: str) -> tuple[str, str | None]:
    """Drop a loose headline line that duplicates the title at the top of the body.

    The line must be a single short line, either fully bold or without closing
    punctuation, followed by a blank line and a paragraph. Real lead sentences
    end in punctuation, so they are never removed.
    """
    stripped = body.lstrip("\n")
    lines = stripped.split("\n")
    if len(lines) < 3 or lines[1].strip():
        return body, None
    first = lines[0].strip()
    if not first or first.startswith(("#", ">", "-", "|", "<", "* ", "1.")):
        return body, None
    fully_bold = first.startswith("**") and first.endswith("**") and len(first) > 4
    if len(first) > _MAX_HEADLINE_LEN:
        return body, None
    if not (fully_bold or first[-1] not in _SENTENCE_END) or not lines[2].strip():
        return body, None
    return "\n".join(lines[2:]).lstrip("\n"), first


_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñü]{2,})\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñü]{2,})\b"
)


def find_name_inconsistencies(frontmatter_texts: Iterable[str], body: str) -> list[str]:
    """Full names in the frontmatter whose surname appears in the body alone.

    ``Valeriy Mazur`` in a summary while the body says ``Pavlo Mazur`` is the
    pattern. Advisory: place names and institutions can match too.
    """
    flagged: list[str] = []
    for text in frontmatter_texts:
        for match in _NAME_RE.finditer(text):
            full, surname = match.group(0), match.group(2)
            if full in body or full in flagged:
                continue
            if re.search(rf"\b{re.escape(surname)}\b", body):
                flagged.append(full)
    return flagged


_SECOND_PERSON_RE = re.compile(
    r"\b(tus?|te has preguntado|has o[ií]do|imagina|sab[ií]as que|puedes)\b",
    re.IGNORECASE,
)


def find_second_person_address(body: str) -> list[str]:
    """Spans addressing the reader directly; the house voice is third person."""
    return [m.group(0) for m in _SECOND_PERSON_RE.finditer(body)]
