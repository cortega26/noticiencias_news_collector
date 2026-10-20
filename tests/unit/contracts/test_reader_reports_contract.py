"""Contract tests for reader reports (plan 185).

Pure boundary validation — no DB, no I/O. Mirrors the frontend Worker's
six problem types, per-field caps, noticiencias.com host rule and optional
email.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from news_collector.contracts.reader_reports import (
    MAX_ARTICLE_URL_LENGTH,
    MAX_CONTENT_SNIPPET_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_EMAIL_LENGTH,
    MAX_EVIDENCE_URL_LENGTH,
    MAX_TECH_FIELD_LENGTH,
    READER_PROBLEM_TYPE_VALUES,
    READER_REPORT_STATUS_VALUES,
    READER_RESOLUTION_STATUS_VALUES,
    ReaderReportPayload,
    ReportIdentity,
    is_noticiencias_host,
)

VALID_URL = "https://noticiencias.com/posts/2026-10-20-example"


def _payload(**overrides: object) -> ReaderReportPayload:
    data: dict[str, object] = {
        "problem_type": "content_factual",
        "article_url": VALID_URL,
    }
    data.update(overrides)
    return ReaderReportPayload(**data)


@pytest.mark.parametrize("problem_type", READER_PROBLEM_TYPE_VALUES)
def test_every_worker_problem_type_is_accepted(problem_type: str) -> None:
    assert _payload(problem_type=problem_type).problem_type == problem_type


def test_problem_type_is_required_and_closed() -> None:
    with pytest.raises(ValidationError):
        ReaderReportPayload()
    with pytest.raises(ValidationError):
        _payload(problem_type="content_vibes")


def test_unknown_fields_are_rejected_like_the_worker() -> None:
    with pytest.raises(ValidationError):
        ReaderReportPayload(
            problem_type="technical_site",
            reporter_ip="203.0.113.7",  # not in the Worker's ALLOWED_KEYS
        )


def test_optional_fields_are_optional() -> None:
    payload = ReaderReportPayload(problem_type="technical_visual")
    assert payload.article_url is None
    assert payload.description is None
    assert payload.content_snippet is None
    assert payload.evidence_url is None
    assert payload.tech_browser is None
    assert payload.tech_os is None
    assert payload.reporter_email is None


def test_empty_optional_strings_become_absent() -> None:
    payload = ReaderReportPayload(
        problem_type="technical_site",
        article_url="",
        description="",
        content_snippet="",
        evidence_url="",
        tech_browser="",
        tech_os="",
        reporter_email="",
    )
    assert payload.article_url is None
    assert payload.reporter_email is None


def test_article_url_requires_noticiencias_host() -> None:
    assert _payload(article_url="https://www.noticiencias.com/x").article_url
    for bad_url in (
        "https://evilnoticiencias.com/x",
        "https://noticiencias.com.evil.example/x",
        "https://example.com/x",
    ):
        with pytest.raises(ValidationError, match="noticiencias.com"):
            _payload(article_url=bad_url)


def test_article_url_requires_absolute_web_url() -> None:
    for bad_url in (
        "noticiencias.com/posts/x",
        "/posts/x",
        "javascript:alert(1)",
        "ftp://noticiencias.com/posts/x",
        "https://noticiencias.com\\@evil.example/x",
        "https://noticiencias.com/posts x",
        "https://noticiencias.com:abc/posts/x",
    ):
        with pytest.raises(ValidationError):
            _payload(article_url=bad_url)


def test_is_noticiencias_host_is_dot_boundary() -> None:
    assert is_noticiencias_host("noticiencias.com")
    assert is_noticiencias_host("sub.noticiencias.com")
    assert is_noticiencias_host("NOTICIENCIAS.COM")
    assert not is_noticiencias_host("evilnoticiencias.com")
    assert not is_noticiencias_host("noticiencias.com.evil.example")
    assert not is_noticiencias_host("")


def test_article_url_length_bound() -> None:
    prefix = "https://noticiencias.com/"
    at_limit = prefix + "a" * (MAX_ARTICLE_URL_LENGTH - len(prefix))
    assert len(at_limit) == MAX_ARTICLE_URL_LENGTH
    assert _payload(article_url=at_limit).article_url == at_limit
    with pytest.raises(ValidationError):
        _payload(article_url=at_limit + "a")


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("description", MAX_DESCRIPTION_LENGTH),
        ("content_snippet", MAX_CONTENT_SNIPPET_LENGTH),
        ("tech_browser", MAX_TECH_FIELD_LENGTH),
        ("tech_os", MAX_TECH_FIELD_LENGTH),
    ],
)
def test_text_length_bounds(field: str, limit: int) -> None:
    assert getattr(_payload(**{field: "a" * limit}), field) == "a" * limit
    with pytest.raises(ValidationError):
        _payload(**{field: "a" * (limit + 1)})


def test_evidence_url_length_and_scheme() -> None:
    prefix = "https://example.com/"
    at_limit = prefix + "a" * (MAX_EVIDENCE_URL_LENGTH - len(prefix))
    assert _payload(evidence_url=at_limit).evidence_url == at_limit
    with pytest.raises(ValidationError):
        _payload(evidence_url=at_limit + "a")
    for bad_url in ("javascript:alert(1)", "data:text/html,x", "not a url"):
        with pytest.raises(ValidationError):
            _payload(evidence_url=bad_url)


def test_email_optional_and_bounded() -> None:
    assert _payload().reporter_email is None
    assert (
        _payload(reporter_email="reader@example.com").reporter_email
        == "reader@example.com"
    )
    with pytest.raises(ValidationError):
        _payload(reporter_email="not-an-email")
    at_limit = "a" * (MAX_EMAIL_LENGTH - len("@example.com")) + "@example.com"
    assert len(at_limit) == MAX_EMAIL_LENGTH
    assert _payload(reporter_email=at_limit).reporter_email == at_limit
    with pytest.raises(ValidationError):
        _payload(
            reporter_email="a" * (MAX_EMAIL_LENGTH - len("@example.com") + 1)
            + "@example.com"
        )


@pytest.mark.parametrize("status", READER_REPORT_STATUS_VALUES)
def test_report_status_vocabulary(status: str) -> None:
    identity = ReportIdentity(status="resolved", reason="matched", refinery_id="1")
    assert identity.status == "resolved"
    assert status in READER_REPORT_STATUS_VALUES


@pytest.mark.parametrize("status", READER_RESOLUTION_STATUS_VALUES)
def test_resolution_status_vocabulary(status: str) -> None:
    identity = ReportIdentity(status=status, reason="reason")  # type: ignore[arg-type]
    assert identity.status == status


def test_report_identity_shape_and_validation() -> None:
    identity = ReportIdentity(
        status="resolved",
        canonical_url=VALID_URL,
        refinery_id="42",
        content_sha256="a" * 64,
        reason="matched_published_url",
    )
    assert identity.refinery_id == "42"
    with pytest.raises(ValidationError):
        ReportIdentity(status="guessed", reason="nope")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ReportIdentity(status="unresolved", reason="")
    with pytest.raises(ValidationError):
        ReportIdentity(status="unresolved", reason="r", unknown="x")
