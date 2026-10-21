"""Cloudflare R2 reader over the Cloudflare REST API (plan 186).

R2 report intake lives as JSON objects in the bucket
``noticiencias-reports`` (key ``reports/YYYY-MM-DD/<uuid>.json``, written
by the frontend Worker). This module is a *thin reader* over the existing
:class:`~news_collector.infrastructure.requests_client.RobustRequestsClient`
— it adds no S3/boto3 dependency (none exists in ``requirements.lock``)
and talks to the documented Cloudflare REST object endpoints:

    list:  GET /client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects
           ?cursor=&per_page=&prefix=
           -> {result: [{key, ...}], result_info: {cursor, is_truncated}}
    get:   GET /client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects/{key}
           -> raw object body; 404 -> typed ``R2ObjectMissing``

The object-key path rule from the Cloudflare docs is followed exactly:
slashes within a key are sent literally (never ``%2F``); every other
reserved/unsafe character is percent-encoded as usual.

I/O stays at the edge (LAW-B4): this module owns the network calls and
never touches storage or pure logic. All state needed to authenticate
comes from the environment (``CLOUDFLARE_ACCOUNT_ID``,
``CLOUDFLARE_R2_API_TOKEN``, ``CLOUDFLARE_R2_REPORT_BUCKET``) and is
resolved *before* any request is possible — missing credentials raise
:class:`R2ConfigurationError` before the HTTP client exists. The bearer
token is never logged: request-context diagnostics go through the shared
client's :func:`~news_collector.infrastructure.requests_client._redact_headers`
(and its retry logger, which extracts statuses/URLs only).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from news_collector.contracts.reader_reports import R2KeyPage
from news_collector.infrastructure.requests_client import (
    RobustRequestsClient,
    _redact_headers,
)
from news_collector.utils.logger import get_logger
from news_collector.utils.warn_once import warn_once

logger = get_logger().create_module_logger(__name__)

API_BASE_URL = "https://api.cloudflare.com/client/v4"
DEFAULT_PREFIX = "reports/"
DEFAULT_BUCKET = "noticiencias-reports"
ACCOUNT_ID_ENV = "CLOUDFLARE_ACCOUNT_ID"
TOKEN_ENV = "CLOUDFLARE_R2_API_TOKEN"  # noqa: S105 # nosec B105 - env-var NAME constant, not a credential (credentials stay in the environment / .env)
BUCKET_ENV = "CLOUDFLARE_R2_REPORT_BUCKET"

# Cloudflare REST list endpoint per-page bounds (developers.cloudflare.com).
MIN_PER_PAGE = 1
MAX_PER_PAGE = 1000


class R2ConfigurationError(RuntimeError):
    """Missing/invalid Cloudflare credentials or bucket name.

    Raised before any I/O — resolving credentials must not perform a
    single request when the configuration is absent.
    """


class R2TransportError(RuntimeError):
    """Non-404 request failure (auth rejection, 5xx, non-JSON envelope...).

    Carries only the HTTP status and error type — never headers or body
    content — so no credential value can leak through logs.
    """

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        self.status = status
        super().__init__(message)


class R2ObjectMissing(RuntimeError):
    """The requested object key does not exist (R2 object GET 404).

    Carries ``r2_object_missing = True`` so pure logic can recognize it
    duck-typed by flag, without importing this network module.
    """

    r2_object_missing: bool = True

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"R2 object not found: {key}")


@dataclass(frozen=True)
class R2Credentials:
    """Resolved per-run credentials (values never logged or serialized)."""

    account_id: str
    api_token: str
    bucket: str


def _read_env(name: str, environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Read one variable: explicit mapping, else the process env, then .env.

    Mirrors the flat-env-var precedent (``CLOUDFLARE_AI_API_KEY`` for
    Workers AI): config.toml stays untouched for these R2-only values and
    ``config_manager`` does not export .env keys on its own. When
    ``environ`` is given it IS the environment — the .env fallback is
    skipped, which keeps tests fully deterministic.
    """
    if environ is not None:
        value = environ.get(name, "").strip()
        return value or None
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        from noticiencias.config_manager import load_env_overrides

        return str(load_env_overrides().get(name, "")).strip() or None
    except Exception as err:  # noqa: BLE001 - a broken .env must not break resolution
        warn_once(
            logger,
            f"r2-env-read:{name}",
            "Could not read .env while resolving {} ({}: {}); treating it as unset",
            name,
            err.__class__.__name__,
            err,
        )
        return None


def load_r2_credentials(
    environ: Optional[Dict[str, str]] = None,
) -> R2Credentials:
    """Resolve and validate R2 credentials — no I/O, typed failure first.

    ``CLOUDFLARE_ACCOUNT_ID`` and ``CLOUDFLARE_R2_API_TOKEN`` are required
    (the token needs Workers R2 Storage Edit on the account);
    ``CLOUDFLARE_R2_REPORT_BUCKET`` defaults to ``noticiencias-reports``.
    The error names the missing variables — never their values.
    """
    account_id = _read_env(ACCOUNT_ID_ENV, environ)
    token = _read_env(TOKEN_ENV, environ)
    bucket = _read_env(BUCKET_ENV, environ) or DEFAULT_BUCKET

    if not account_id and not token:
        raise R2ConfigurationError(
            "Cloudflare R2 credentials missing: set "
            f"{ACCOUNT_ID_ENV} and {TOKEN_ENV} (see .env.example)"
        )
    if not account_id:
        raise R2ConfigurationError(
            f"Cloudflare R2 credentials missing: set {ACCOUNT_ID_ENV}"
        )
    if not token:
        raise R2ConfigurationError(
            f"Cloudflare R2 credentials missing: set {TOKEN_ENV}"
        )
    if not bucket.strip():
        raise R2ConfigurationError(f"Cloudflare R2 bucket empty: {BUCKET_ENV}")
    return R2Credentials(account_id=account_id, api_token=token, bucket=bucket)


def encode_object_key_in_path(key: str) -> str:
    """Percent-encode a key for the REST object URL path.

    Cloudflare's contract: slashes are sent literally (``%2F`` is invalid
    in the key path); other reserved/unsafe characters are percent-encoded
    as usual.
    """
    return "/".join(quote(segment, safe="") for segment in key.split("/"))


class R2ReportClient:
    """Read-only R2 object access for the reports bucket via the REST API.

    Fails fast on configuration errors (before the HTTP client exists),
    maps object 404 to :class:`R2ObjectMissing`, and converts status and
    transport failures into :class:`R2TransportError` with bounded,
    credential-free diagnostics.
    """

    def __init__(
        self,
        credentials: Optional[R2Credentials] = None,
        *,
        http: Optional[RobustRequestsClient] = None,
        timeout: float = 30.0,
    ) -> None:
        # Credentials resolve (and fail typed) before any HTTP client is
        # built — a misconfigured environment cannot reach the network.
        self.credentials = credentials or load_r2_credentials()
        self.http = http or RobustRequestsClient(timeout=timeout)
        self._base_url = (
            f"{API_BASE_URL}/accounts/{self.credentials.account_id}"
            f"/r2/buckets/{self.credentials.bucket}"
        )

    # -- listing ------------------------------------------------------

    def list_report_keys(
        self,
        *,
        prefix: str = DEFAULT_PREFIX,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> R2KeyPage:
        """One listing page: object keys plus the next cursor (or None)."""
        if limit < MIN_PER_PAGE:
            raise ValueError(f"limit must be at least {MIN_PER_PAGE}")
        params: Dict[str, Any] = {"per_page": min(limit, MAX_PER_PAGE)}
        if prefix:
            params["prefix"] = prefix
        if cursor:
            params["cursor"] = cursor

        response = self._request_raw(f"{self._base_url}/objects", params=params)
        body = self._decode_json_envelope(response, context="listing")
        result = body.get("result")
        result = [] if result is None else result
        if not isinstance(result, list):
            raise R2TransportError("r2 listing 'result' is not a list")
        keys: list[str] = []
        for item in result:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                keys.append(str(item["key"]))
            else:
                raise R2TransportError("r2 listing has a non-key result entry")

        result_info = body.get("result_info")
        next_cursor: Optional[str] = None
        if isinstance(result_info, dict):
            candidate = result_info.get("cursor")
            if (
                result_info.get("is_truncated") is True
                and isinstance(candidate, str)
                and candidate
            ):
                next_cursor = candidate
        return R2KeyPage(keys=tuple(keys), next_cursor=next_cursor)

    # -- object body --------------------------------------------------

    def get_object(self, key: str) -> bytes:
        """Raw object body bytes for ``key`` (404 -> :class:`R2ObjectMissing`)."""
        if not key.strip():
            raise ValueError("object key must be a non-empty string")
        url = f"{self._base_url}/objects/{encode_object_key_in_path(key)}"
        response = self._request_raw(url)
        if response.status_code == 404:
            raise R2ObjectMissing(key)
        if not 200 <= response.status_code < 300:
            raise R2TransportError(
                f"r2 object request rejected (status={response.status_code})",
                status=response.status_code,
            )
        return response.content

    # -- internals ----------------------------------------------------

    def _request_raw(
        self, url: str, *, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET with the bearer header; transport failures -> typed error.

        The Authorization header only ever appears through
        ``_redact_headers`` (debug logs) and never in exception text.
        """
        headers = {"Authorization": f"Bearer {self.credentials.api_token}"}
        logger.debug(
            "r2 GET {url} headers={headers}", url=url, headers=_redact_headers(headers)
        )
        try:
            return self.http.get(url, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001 - transport failure, typed
            logger.warning(
                "r2 request transport failure (error_type={})", type(exc).__name__
            )
            raise R2TransportError(
                f"r2 request transport failure ({type(exc).__name__})"
            ) from exc

    def _decode_json_envelope(
        self, response: requests.Response, *, context: str
    ) -> Dict[str, Any]:
        """Decode + sanity-check the Cloudflare JSON response envelope."""
        if response.status_code == 404:
            # Only the object GET has a meaningful 404 (missing object);
            # a listing 404 means a missing bucket/endpoint.
            raise R2TransportError(
                f"r2 {context} target not found (status=404)", status=404
            )
        if not 200 <= response.status_code < 300:
            raise R2TransportError(
                f"r2 {context} rejected (status={response.status_code})",
                status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise R2TransportError(f"r2 {context} response is not JSON") from exc
        if not isinstance(body, dict):
            raise R2TransportError(f"r2 {context} envelope is not an object")
        if body.get("success") is False:
            errors = body.get("errors")
            first_code = (
                errors[0].get("code")
                if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                else None
            )
            raise R2TransportError(f"r2 {context} reports failure (code={first_code})")
        return body

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "R2ReportClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


__all__ = [
    "ACCOUNT_ID_ENV",
    "API_BASE_URL",
    "BUCKET_ENV",
    "DEFAULT_BUCKET",
    "DEFAULT_PREFIX",
    "MAX_PER_PAGE",
    "MIN_PER_PAGE",
    "R2ConfigurationError",
    "R2Credentials",
    "R2ObjectMissing",
    "R2ReportClient",
    "R2TransportError",
    "TOKEN_ENV",
    "encode_object_key_in_path",
    "load_r2_credentials",
]
