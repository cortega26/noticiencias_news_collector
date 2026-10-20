"""Read-only reader-report identity resolution (plan 185).

A report arrives with a public URL. The backend must never trust a
reader-supplied ``refinery_id`` or content revision: it resolves both from
``Article.published_url`` and the article's latest publication attempt.
This module performs **no writes and no HTTP** — ``unresolved`` and
``ambiguous`` are typed outcomes, never guesses.

The URL match normalizes both sides (scheme/host case, default ports,
trailing slash, query/fragment) so a report for ``/posts/x?utm=...`` still
finds the stored canonical ``/posts/x``. Matching necessarily reads every
non-null ``published_url``; at current volume that is cheap, and a future
slice can add a normalized/indexed column if it stops being so.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from news_collector.contracts.reader_reports import ReportIdentity, is_noticiencias_host
from news_collector.storage.models import Article, PublicationAttemptRecord

# Stable reasons persisted in ``reader_reports.resolution_reason``.
REASON_INVALID_URL = "invalid_article_url"
REASON_UNSUPPORTED_SCHEME = "unsupported_article_url_scheme"
REASON_UNSUPPORTED_HOST = "unsupported_article_url_host"
REASON_NO_MATCH = "no_published_url_match"
REASON_AMBIGUOUS = "ambiguous_published_url"
REASON_RESOLVED = "matched_published_url"

_CONTENT_FINGERPRINT_STAGE = "publication_content_fingerprint"
_DEFAULT_PORTS = {"http": 80, "https": 443}


class PublishedUrlError(ValueError):
    """A URL cannot be normalized to a public Noticiencias article URL."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}{(': ' + detail) if detail else ''}")


def normalize_published_url(url: str) -> str:
    """Normalize an http(s) Noticiencias URL for identity matching.

    Rules: lowercase scheme/host, drop default ports, drop query/fragment,
    keep the path (case and percent-encoding preserved), and strip trailing
    slashes. Other schemes and hosts are rejected with a typed
    :class:`PublishedUrlError` — never silently rewritten to a guess.
    """
    if not isinstance(url, str) or not url.strip():
        raise PublishedUrlError(REASON_INVALID_URL, "URL is empty")
    text = url.strip()
    # Browsers normalize backslashes as path separators; urlsplit does not.
    # Rejecting them avoids validating/ matching a different host than the
    # one a browser would visit.
    if any(char.isspace() for char in text) or "\\" in text:
        raise PublishedUrlError(REASON_INVALID_URL, "URL contains whitespace/backslash")

    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise PublishedUrlError(REASON_INVALID_URL, "URL is malformed") from exc

    scheme = parsed.scheme.lower()
    if not scheme:
        raise PublishedUrlError(REASON_INVALID_URL, "URL has no scheme")
    if scheme not in _DEFAULT_PORTS:
        raise PublishedUrlError(REASON_UNSUPPORTED_SCHEME, scheme)
    if not hostname:
        raise PublishedUrlError(REASON_INVALID_URL, "URL has no host")
    hostname = hostname.lower()
    if not is_noticiencias_host(hostname):
        raise PublishedUrlError(REASON_UNSUPPORTED_HOST, hostname)

    authority = hostname
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        authority = f"{hostname}:{port}"

    path = parsed.path.rstrip("/")
    return f"{scheme}://{authority}{path}"


def _matching_variants(canonical_url: str) -> set[str]:
    """The canonical URL plus its http/https twin.

    The stored ``published_url`` may use either scheme for the same deployed
    revision (legacy http rows, https callbacks), so a report must match
    both without treating the scheme as article identity.
    """
    parsed = urlsplit(canonical_url)
    variants: set[str] = set()
    for scheme in _DEFAULT_PORTS:
        candidate = f"{scheme}://{parsed.netloc}{parsed.path}"
        try:
            variants.add(normalize_published_url(candidate))
        except PublishedUrlError:  # pragma: no cover - canonical is already valid
            continue
    return variants


def _nonempty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _content_sha256_from_details(details: Any) -> str | None:
    """Extract ``content_sha256`` from a publication attempt's JSON details.

    Primary shape (plan 185): ``details["stages"]`` is the attempt summary's
    stage list, and the ``publication_content_fingerprint`` stage carries
    ``details.content_sha256``. The attempt rows written by
    ``DatabaseManager.mark_article_published`` also store the digest directly
    as ``details["content_sha256"]``; use it when no stage summary exists.
    Malformed/absent values return ``None`` so the caller can fall back.
    """
    if not isinstance(details, dict):
        return None

    stages = details.get("stages")
    if isinstance(stages, list):
        for stage in reversed(stages):
            if not isinstance(stage, dict):
                continue
            if stage.get("name") != _CONTENT_FINGERPRINT_STAGE:
                continue
            stage_details = stage.get("details")
            if isinstance(stage_details, dict):
                digest = _nonempty_string(stage_details.get("content_sha256"))
                if digest:
                    return digest
            digest = _nonempty_string(stage.get("content_sha256"))
            if digest:
                return digest

    return _nonempty_string(details.get("content_sha256"))


def _latest_attempt_content_sha256(connection: Any, article_id: int) -> str | None:
    """Digest from the latest publication attempt for ``article_id``.

    "Latest" uses the repository-wide ``(attempt_number, id)`` tie-break
    (``attempt_number`` alone is not unique — see ``DatabaseManager``).
    """
    statement = (
        select(PublicationAttemptRecord.details)
        .where(PublicationAttemptRecord.article_id == article_id)
        .order_by(
            PublicationAttemptRecord.attempt_number.desc(),
            PublicationAttemptRecord.id.desc(),
        )
        .limit(1)
    )
    details = connection.execute(statement).scalar_one_or_none()
    return _content_sha256_from_details(details)


def resolve_report_identity(url: str, db: Any) -> ReportIdentity:
    """Resolve a reader report URL to a published article revision.

    Returns ``resolved`` with ``refinery_id = str(Article.id)``,
    the article's normalized canonical URL and a content revision, or a
    typed ``unresolved``/``ambiguous`` outcome. Read-only: the caller owns
    persisting the outcome onto a ``reader_reports`` row.
    """
    try:
        canonical_url = normalize_published_url(url)
    except PublishedUrlError as exc:
        return ReportIdentity(status="unresolved", reason=exc.reason)

    variants = _matching_variants(canonical_url)
    with db.engine.connect() as connection:
        rows = connection.execute(
            select(Article.id, Article.published_url, Article.content_hash).where(
                Article.published_url.is_not(None)
            )
        ).all()

        matches: list[tuple[int, str, str | None]] = []
        for row in rows:
            published_url = row.published_url
            try:
                normalized = normalize_published_url(published_url)
            except PublishedUrlError:
                # A legacy/invalid stored URL is not evidence for this report.
                continue
            if normalized in variants:
                matches.append((row.id, normalized, row.content_hash))

        if not matches:
            return ReportIdentity(status="unresolved", reason=REASON_NO_MATCH)
        if len(matches) > 1:
            return ReportIdentity(status="ambiguous", reason=REASON_AMBIGUOUS)

        article_id, matched_url, fallback_hash = matches[0]
        content_sha256 = (
            _latest_attempt_content_sha256(connection, article_id) or fallback_hash
        )
        return ReportIdentity(
            status="resolved",
            canonical_url=matched_url,
            refinery_id=str(article_id),
            content_sha256=content_sha256,
            reason=REASON_RESOLVED,
        )
