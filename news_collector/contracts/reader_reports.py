"""Typed contracts for reader-submitted reports (plan 185).

These shapes mirror the frontend Worker's report contract
(``workers/src/utils/validate.ts`` in the frontend repo) at the backend
boundary: the same six problem types, the same per-field length caps, the
same ``noticiencias.com`` / ``*.noticiencias.com`` host rule, and an optional
reporter email. Pure Pydantic — no I/O, no storage imports (LAW-B1).
"""

from __future__ import annotations

import re
from typing import Literal, Optional
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirrors VALID_PROBLEM_TYPES in the Worker — keep both lists in sync.
ReaderProblemType = Literal[
    "content_factual",
    "content_source",
    "content_interpretation",
    "content_translation",
    "technical_site",
    "technical_visual",
]

READER_PROBLEM_TYPE_VALUES: tuple[ReaderProblemType, ...] = (
    "content_factual",
    "content_source",
    "content_interpretation",
    "content_translation",
    "technical_site",
    "technical_visual",
)

# Mirrors MAX_LENGTHS in the Worker — keep both lists in sync.
MAX_ARTICLE_URL_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 5000
MAX_CONTENT_SNIPPET_LENGTH = 2000
MAX_EVIDENCE_URL_LENGTH = 2000
MAX_TECH_FIELD_LENGTH = 200
MAX_EMAIL_LENGTH = 320  # RFC 5321 max mailbox length

ReaderReportStatus = Literal[
    "new",
    "triaged",
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
]

READER_REPORT_STATUS_VALUES: tuple[ReaderReportStatus, ...] = (
    "new",
    "triaged",
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
)

ReaderResolutionStatus = Literal["unresolved", "resolved", "ambiguous"]

READER_RESOLUTION_STATUS_VALUES: tuple[ReaderResolutionStatus, ...] = (
    "unresolved",
    "resolved",
    "ambiguous",
)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_noticiencias_host(hostname: str) -> bool:
    """Dot-boundary host check shared by the contract and the resolver.

    Accepts ``noticiencias.com`` and ``*.noticiencias.com`` only — never
    lookalikes such as ``evilnoticiencias.com``. Mirrors
    ``isNoticienciasHost`` in the Worker.
    """
    hostname = hostname.lower()
    return hostname == "noticiencias.com" or hostname.endswith(".noticiencias.com")


def _parse_web_url(value: str, *, field_label: str) -> SplitResult:
    """Parse an absolute http(s) URL without performing any I/O.

    Rejects whitespace and backslashes because browser URL parsers normalize
    them differently from :func:`urllib.parse.urlsplit`; accepting them here
    could validate a URL whose real host differs from the checked host.
    """
    text = value.strip()
    if not text or any(char.isspace() for char in text) or "\\" in text:
        raise ValueError(f"{field_label} no es una URL válida")
    try:
        parsed = urlsplit(text)
        # Force access so an invalid port (e.g. ":abc") raises here.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_label} no es una URL válida") from exc
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"{field_label} no es una URL válida")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"{field_label} no es una URL válida")
    return parsed


class ReaderReportPayload(BaseModel):
    """Validated reader report body, matching the Worker payload.

    Every field except ``problem_type`` is optional. Empty optional strings
    are normalized to ``None`` (the Worker treats ``""`` as absent too).
    Unknown keys are rejected, like the Worker's ``ALLOWED_KEYS`` check.
    """

    problem_type: ReaderProblemType
    article_url: Optional[str] = Field(default=None, max_length=MAX_ARTICLE_URL_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    content_snippet: Optional[str] = Field(
        default=None, max_length=MAX_CONTENT_SNIPPET_LENGTH
    )
    evidence_url: Optional[str] = Field(
        default=None, max_length=MAX_EVIDENCE_URL_LENGTH
    )
    tech_browser: Optional[str] = Field(default=None, max_length=MAX_TECH_FIELD_LENGTH)
    tech_os: Optional[str] = Field(default=None, max_length=MAX_TECH_FIELD_LENGTH)
    reporter_email: Optional[str] = Field(default=None, max_length=MAX_EMAIL_LENGTH)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "article_url",
        "description",
        "content_snippet",
        "evidence_url",
        "tech_browser",
        "tech_os",
        "reporter_email",
        mode="before",
    )
    @classmethod
    def _blank_becomes_absent(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("article_url")
    @classmethod
    def _validate_article_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = _parse_web_url(value, field_label="URL del artículo")
        if not is_noticiencias_host(parsed.hostname or ""):
            raise ValueError("URL del artículo debe ser de noticiencias.com")
        return value

    @field_validator("evidence_url")
    @classmethod
    def _validate_evidence_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _parse_web_url(value, field_label="URL de evidencia")
        return value

    @field_validator("reporter_email")
    @classmethod
    def _validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("Correo electrónico no es válido")
        return value


class ReportIdentity(BaseModel):
    """Typed outcome of resolving a report URL to a published revision.

    ``resolved`` always carries ``canonical_url`` and ``refinery_id``;
    ``unresolved``/``ambiguous`` never invent one — they carry a stable
    ``reason`` instead. The resolver never guesses an article.
    """

    status: ReaderResolutionStatus
    canonical_url: Optional[str] = None
    refinery_id: Optional[str] = None
    content_sha256: Optional[str] = None
    reason: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")
