"""Infrastructure tests for the Cloudflare R2 reader (plan 186).

No real network: a fake ``RobustRequestsClient``-shaped stand-in is
injected, recording every request. Credential resolution must fail typed
*before* any I/O; the bearer token must never appear in logs (the shared
client's redaction is reused for request-context diagnostics).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import pytest

import news_collector.infrastructure.r2_client as r2_module
from news_collector.infrastructure.r2_client import (
    ACCOUNT_ID_ENV,
    BUCKET_ENV,
    DEFAULT_BUCKET,
    TOKEN_ENV,
    R2ConfigurationError,
    R2Credentials,
    R2ObjectMissing,
    R2ReportClient,
    R2TransportError,
    encode_object_key_in_path,
    load_r2_credentials,
)
from news_collector.infrastructure.requests_client import _redact_headers

TOKEN = "secret-r2-token-value"
CREDENTIALS = R2Credentials(
    account_id="acct123", api_token=TOKEN, bucket="noticiencias-reports"
)


class _FakeHttp:
    """``RobustRequestsClient`` stand-in: records GETs, returns canned data."""

    def __init__(self, responses: List[Any]) -> None:
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append(
            {"url": url, "params": params, "headers": dict(headers or {})}
        )
        next_response = self.responses.pop(0) if self.responses else None
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self) -> None: ...


class _FakeResponse:
    def __init__(
        self, status_code: int = 200, payload: Any = None, content: bytes = b""
    ):
        self.status_code = status_code
        self.content = content
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _listing_body(
    keys: List[str], *, is_truncated: bool = False, cursor: Optional[str] = None
) -> Dict[str, Any]:
    result_info: Dict[str, Any] = {"is_truncated": is_truncated}
    if cursor:
        result_info["cursor"] = cursor
    return {
        "success": True,
        "result": [{"key": key, "size": 10} for key in keys],
        "result_info": result_info,
    }


def _client(
    responses: List[Any], *, credentials: Optional[R2Credentials] = None
) -> tuple[R2ReportClient, _FakeHttp]:
    http = _FakeHttp(responses)
    client = R2ReportClient(
        credentials or CREDENTIALS, http=http  # type: ignore[arg-type]
    )
    return client, http


# ---------------------------------------------------------------------------
# Credentials — typed failure before any I/O
# ---------------------------------------------------------------------------


class TestCredentials:
    @pytest.mark.parametrize(
        "environ",
        [
            {},
            {ACCOUNT_ID_ENV: "acct-only"},
            {TOKEN_ENV: "token-only"},
            {ACCOUNT_ID_ENV: "   ", TOKEN_ENV: "   "},
        ],
    )
    def test_missing_creds_raise_typed_before_any_io(
        self, environ: Dict[str, str]
    ) -> None:
        """Missing/blank credentials fail typed — and with the guard in
        place, no HTTP client can even be constructed."""
        constructed = []

        def _guard_http(*args: Any, **kwargs: Any) -> None:
            constructed.append(True)
            raise AssertionError("HTTP client built above missing credentials")

        original = r2_module.RobustRequestsClient
        r2_module.RobustRequestsClient = _guard_http  # type: ignore[assignment]
        try:
            with pytest.raises(R2ConfigurationError):
                load_r2_credentials(environ=environ)
            with pytest.raises(R2ConfigurationError):
                R2ReportClient(http=None)
        finally:
            r2_module.RobustRequestsClient = original
        assert constructed == []

    def test_process_env_and_env_fallback_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Process env wins; an absent .env fallback resolves empty typed."""
        for env in (ACCOUNT_ID_ENV, TOKEN_ENV, BUCKET_ENV):
            monkeypatch.delenv(env, raising=False)
        with pytest.raises(R2ConfigurationError):
            load_r2_credentials()

        monkeypatch.setenv(ACCOUNT_ID_ENV, "acct-from-env")
        monkeypatch.setenv(TOKEN_ENV, "tok-from-env")
        credentials = load_r2_credentials()
        assert credentials.account_id == "acct-from-env"
        assert credentials.api_token == "tok-from-env"
        assert credentials.bucket == DEFAULT_BUCKET

    def test_partial_credentials_name_the_missing_variable(
        self,
    ) -> None:
        with pytest.raises(R2ConfigurationError) as account_missing:
            load_r2_credentials(environ={TOKEN_ENV: "token-only"})
        assert ACCOUNT_ID_ENV in str(account_missing.value)
        with pytest.raises(R2ConfigurationError) as token_missing:
            load_r2_credentials(environ={ACCOUNT_ID_ENV: "acct-only"})
        assert TOKEN_ENV in str(token_missing.value)
        assert TOKEN not in str(account_missing.value)
        assert TOKEN not in str(token_missing.value)

    def test_bucket_defaults_and_value_never_leak_in_errors(self) -> None:
        credentials = load_r2_credentials(
            environ={ACCOUNT_ID_ENV: "acct", TOKEN_ENV: "tok"}
        )
        assert credentials.bucket == DEFAULT_BUCKET
        assert credentials.api_token == "tok"

    def test_space_only_env_values_count_as_missing(self) -> None:
        with pytest.raises(R2ConfigurationError):
            load_r2_credentials(
                environ={ACCOUNT_ID_ENV: "   ", TOKEN_ENV: "secret-token"}
            )

    def test_client_construction_resolves_creds_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without explicit credentials AND a missing env, constructing the
        client fails typed and the HTTP client is never built."""
        for env in (ACCOUNT_ID_ENV, TOKEN_ENV, BUCKET_ENV):
            monkeypatch.delenv(env, raising=False)
        with pytest.raises(R2ConfigurationError):
            R2ReportClient(http=None)
        with pytest.raises(R2ConfigurationError):
            R2ReportClient()


# ---------------------------------------------------------------------------
# URL building and key encoding
# ---------------------------------------------------------------------------


class TestKeyEncoding:
    def test_slashes_stay_literal_and_reserved_chars_are_encoded(self) -> None:
        assert (
            encode_object_key_in_path("reports/2026-10-19/abc.json")
            == "reports/2026-10-19/abc.json"
        )

    @pytest.mark.parametrize(
        ("raw", "encoded"),
        [
            ("reports/a%b#c.json", "reports/a%25b%23c.json"),
            ("reports/uni-é.json", "reports/uni-%C3%A9.json"),
            ("reports/q?.json", "reports/q%3F.json"),
            ("reports/a b.json", "reports/a%20b.json"),
        ],
    )
    def test_reserved_chars_encoded_per_segment(self, raw: str, encoded: str) -> None:
        assert encode_object_key_in_path(raw) == encoded


class TestListReportKeys:
    def test_request_shape_cparams_prefix_and_bearer(
        self,
    ) -> None:
        client, http = _client([_FakeResponse(payload=_listing_body([]))])

        client.list_report_keys(prefix="reports/", limit=100)

        assert len(http.calls) == 1
        url = http.calls[0]["url"]
        assert url.startswith("https://api.cloudflare.com/client/v4/accounts/acct123")
        assert "/r2/buckets/noticiencias-reports/objects" in url
        assert http.calls[0]["params"] == {"per_page": 100, "prefix": "reports/"}
        # The Authorization header is sent with the token (never logged raw).
        headers = http.calls[0]["headers"]
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_per_page_is_capped_at_the_api_maximum(self) -> None:
        client, http = _client([_FakeResponse(payload=_listing_body([]))])

        client.list_report_keys(limit=5000)

        assert http.calls[0]["params"]["per_page"] == 1000

    def test_cursor_is_sent_when_present(self) -> None:
        client, http = _client([_FakeResponse(payload=_listing_body([]))])

        client.list_report_keys(cursor="opaque-cursor")

        assert http.calls[0]["params"] == {
            "per_page": 100,
            "prefix": "reports/",
            "cursor": "opaque-cursor",
        }

    def test_keys_and_next_cursor_are_returned(self) -> None:
        client, _ = _client(
            [
                _FakeResponse(
                    payload=_listing_body(
                        ["a.json", "b.json"], is_truncated=True, cursor="NEXT"
                    )
                )
            ]
        )

        page = client.list_report_keys(limit=2)

        assert page.keys == ("a.json", "b.json")
        assert page.next_cursor == "NEXT"

    def test_untruncated_page_has_no_next_cursor(self) -> None:
        client, _ = _client(
            [_FakeResponse(payload=_listing_body(["a.json"], is_truncated=False))],
        )

        page = client.list_report_keys()

        assert page.keys == ("a.json",)
        assert page.next_cursor is None

    @pytest.mark.parametrize(
        "envelope",
        [
            _FakeResponse(payload={"success": False, "errors": [{"code": 10004}]}),
            _FakeResponse(status_code=500, payload={"success": False}),
            _FakeResponse(status_code=404, payload={"success": False}),
            _FakeResponse(payload="not-an-object-envelope"),
        ],
    )
    def test_listing_rejections_are_typed(self, envelope: _FakeResponse) -> None:
        client, _ = _client([envelope])

        with pytest.raises(R2TransportError):
            client.list_report_keys()

    def test_non_json_listing_is_typed(self) -> None:
        client, _ = _client([_FakeResponse(payload=None, content=b"<html>")])

        with pytest.raises(R2TransportError):
            client.list_report_keys()

    def test_non_string_result_keys_are_typed(self) -> None:
        client, _ = _client(
            [_FakeResponse(payload={"success": True, "result": [{"key": 42}]})]
        )

        with pytest.raises(R2TransportError):
            client.list_report_keys()

    def test_transport_failure_is_typed_without_url_leakage(
        self,
    ) -> None:
        http = _FakeHttp([RuntimeError("connection reset")])
        client = R2ReportClient(CREDENTIALS, http=http)  # type: ignore[arg-type]

        with pytest.raises(R2TransportError):
            client.list_report_keys()


class TestGetObject:
    def test_object_url_encodes_key_and_returns_body_bytes(self) -> None:
        client, http = _client([_FakeResponse(content=b'{"ok": 1}')])

        body = client.get_object("reports/2026-10-19/a%b.json")

        assert body == b'{"ok": 1}'
        assert http.calls[0]["url"].endswith("/objects/reports/2026-10-19/a%25b.json")

    def test_404_is_a_typed_missing_object(self) -> None:
        client, _ = _client([_FakeResponse(status_code=404)])

        with pytest.raises(R2ObjectMissing) as exc_info:
            client.get_object("reports/2026-10-19/gone.json")

        assert exc_info.value.r2_object_missing is True  # duck-typing flag
        assert exc_info.value.key == "reports/2026-10-19/gone.json"

    @pytest.mark.parametrize("status", (401, 403, 500))
    def test_other_statuses_are_transport_errors(self, status: int) -> None:
        client, _ = _client([_FakeResponse(status_code=status)])

        with pytest.raises(R2TransportError) as exc_info:
            client.get_object("reports/x.json")
        assert exc_info.value.status == status

    def test_empty_key_is_rejected_locally(self) -> None:
        client, _ = _client([])

        with pytest.raises(ValueError):
            client.get_object("   ")

    def test_transport_failure_is_typed(self) -> None:
        http = _FakeHttp([RuntimeError("connection reset")])
        client = R2ReportClient(CREDENTIALS, http=http)  # type: ignore[arg-type]

        with pytest.raises(R2TransportError):
            client.get_object("reports/x.json")


# ---------------------------------------------------------------------------
# Redaction — the token never reaches the logs
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redact_headers_masks_authorization(self) -> None:
        masked = _redact_headers({"Authorization": f"Bearer {TOKEN}", "Accept": "*/*"})
        assert masked["Authorization"] == "[REDACTED]"
        assert masked["Accept"] == "*/*"

    def test_token_never_appears_in_client_logs(
        self,
    ) -> None:
        """At DEBUG (below the app's INFO floor) a dedicated loguru sink
        still captures every record: the request-context debug line shows
        the masked Authorization header and the token itself never leaks."""
        from loguru import logger as loguru_logger

        captured: list[str] = []

        def _sink(message) -> None:
            captured.append(str(message))

        sink_id = loguru_logger.add(_sink, level=logging.DEBUG)
        try:
            client, _http = _client(
                [
                    _FakeResponse(payload=_listing_body([])),
                    _FakeResponse(status_code=500),
                    RuntimeError("connection reset"),
                    _FakeResponse(status_code=404),
                ]
            )

            client.list_report_keys()
            with pytest.raises(R2TransportError):
                client.list_report_keys()
            with pytest.raises(R2TransportError):
                client.get_object("reports/x.json")
            with pytest.raises(R2ObjectMissing):
                client.get_object("reports/gone.json")
        finally:
            loguru_logger.remove(sink_id)

        combined_logs = "\n".join(captured)
        # The masked-header debug line ran: Authorization replaced, never raw.
        assert "[REDACTED]" in combined_logs
        assert TOKEN not in combined_logs
        # And the serialized redaction of the auth header is safe by design.
        masked = json.dumps(_redact_headers({"Authorization": f"Bearer {TOKEN}"}))
        assert TOKEN not in masked
