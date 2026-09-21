"""Boundary tests for the LLM failure taxonomy (mutation-driven, see docs/dev/TEST_SUITE_AUDIT.md).

The chain's failover/cooldown/disable decisions all hang on this mapping, so the exact
status-code edges and the shape of the raised error must be pinned.
"""

from __future__ import annotations

import httpx
import pytest
import requests

from news_collector.infrastructure.llm.failure_kinds import (
    EmptyResponseError,
    FailureKind,
    _status_kind,
    classify_exception,
    retry_after_seconds,
)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (None, FailureKind.UNKNOWN),
        (200, FailureKind.UNKNOWN),
        (399, FailureKind.UNKNOWN),
        (400, FailureKind.CLIENT_ERROR),
        (404, FailureKind.CLIENT_ERROR),
        (401, FailureKind.AUTH),
        (403, FailureKind.AUTH),
        (429, FailureKind.RATE_LIMITED),
        (499, FailureKind.CLIENT_ERROR),
        (500, FailureKind.HTTP_5XX),
        (501, FailureKind.HTTP_5XX),
        (503, FailureKind.HTTP_5XX),
    ],
)
def test_status_kind_edges(status, kind):
    assert _status_kind(status) is kind


def _requests_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def test_requests_http_error_uses_its_response_status():
    for status, kind in (
        (500, FailureKind.HTTP_5XX),
        (429, FailureKind.RATE_LIMITED),
        (400, FailureKind.CLIENT_ERROR),
    ):
        assert classify_exception(_requests_error(status)) is kind


def test_requests_http_error_without_a_response_is_unknown_not_a_crash():
    assert classify_exception(requests.HTTPError("boom")) is FailureKind.UNKNOWN


def test_httpx_status_error_uses_its_response_status():
    request = httpx.Request("POST", "https://x.test")
    error = httpx.HTTPStatusError(
        "bad", request=request, response=httpx.Response(503, request=request)
    )
    assert classify_exception(error) is FailureKind.HTTP_5XX


def test_empty_response_error_message_and_kind():
    err = EmptyResponseError()
    assert str(err) == "provider returned empty_response"
    assert err.kind is FailureKind.EMPTY_RESPONSE
    custom = EmptyResponseError(FailureKind.INVALID_JSON)
    assert str(custom) == "provider returned invalid_json"
    assert classify_exception(custom) is FailureKind.INVALID_JSON


def test_retry_after_from_a_real_response_is_case_insensitive_and_tolerant():
    response = requests.Response()
    response.status_code = 429  # falsy Response: must not be truthiness-tested
    response.headers["retry-after"] = "12"
    error = requests.HTTPError("429", response=response)
    assert retry_after_seconds(error) == 12.0

    response.headers["Retry-After"] = "soon"
    assert retry_after_seconds(error) is None  # non-numeric (HTTP-date) -> None
    del response.headers["Retry-After"]
    assert retry_after_seconds(error) is None  # header absent
    assert retry_after_seconds(requests.HTTPError("no response")) is None


def test_explicit_retry_after_attribute_wins_over_the_header():
    class Limited(Exception):
        retry_after = 7

        class response:  # noqa: N801 - minimal stand-in
            headers = {"Retry-After": "99"}

    assert retry_after_seconds(Limited()) == 7.0
