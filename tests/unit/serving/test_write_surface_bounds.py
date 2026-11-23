"""Hermetic unit coverage for the admin write-surface bounds (plan 123).

The TestClient rejection tests for the serving hardening live in
``tests/test_serving_admin_api.py``, whose module-level ``pytestmark =
pytest.mark.e2e`` deselects all of it from the unit profile (``make type``).
These tests mirror their intent by calling the pure bound helpers directly:
no TestClient, no network, no database.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException, Request
from starlette.types import Message, Scope

from news_collector.config.runtime import is_explicit_development
from news_collector.serving import admin_images
from news_collector.serving import api as serving_api
from news_collector.storage.database import DatabaseManager

# ---------------------------------------------------------------------------
# _validate_prompts_payload
# ---------------------------------------------------------------------------


def test_prompts_rejects_too_many_entries() -> None:
    payload = {f"p{i}": {"system": "s"} for i in range(101)}
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_prompts_payload(payload)
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("bad_name", ["", "   ", 123, "x" * 65])
def test_prompts_rejects_bad_names(bad_name: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_prompts_payload({bad_name: {"system": "s"}})  # type: ignore[dict-item]
    assert exc_info.value.status_code == 422


def test_prompts_name_length_boundary() -> None:
    serving_api._validate_prompts_payload({"x" * 64: {"system": "s"}})
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_prompts_payload({"x" * 65: {"system": "s"}})
    assert exc_info.value.status_code == 422


def test_prompts_rejects_non_dict_body() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_prompts_payload({"editor": "just a string"})
    assert exc_info.value.status_code == 422


def test_prompts_rejects_oversize_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serving_api, "_ADMIN_PROMPTS_MAX_BYTES", 16)
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_prompts_payload({"editor": {"system": "s"}})
    assert exc_info.value.status_code == 413


def test_prompts_accepts_valid_payload() -> None:
    result = serving_api._validate_prompts_payload(
        {"auditor": {"system": "Eres un auditor."}, "editor": {"system": "Edita."}}
    )
    assert result is None


# ---------------------------------------------------------------------------
# _check_config_payload_size
# ---------------------------------------------------------------------------


def test_config_size_accepts_normal_payload() -> None:
    assert (
        serving_api._check_config_payload_size({"app": {"environment": "development"}})
        is None
    )


def test_config_size_rejects_oversize_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serving_api, "_ADMIN_CONFIG_MAX_BYTES", 10)
    with pytest.raises(HTTPException) as exc_info:
        serving_api._check_config_payload_size({"app": {"environment": "development"}})
    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# _normalize_config_section / _normalize_config_payload
# ---------------------------------------------------------------------------


def _section_state(known: object = ()) -> dict:
    return {
        "known_sections": set(known),  # type: ignore[arg-type]
        "normalized": {},
        "dropped_sections": [],
        "dropped_keys": [],
    }


def test_config_section_rejects_foreign_key() -> None:
    state = _section_state({"app", "database"})
    with pytest.raises(HTTPException) as exc_info:
        serving_api._normalize_config_section("evil_section", {"x": 1}, **state)
    assert exc_info.value.status_code == 422


def test_config_section_drops_privileged_section() -> None:
    state = _section_state({"app", "database", "paths"})
    serving_api._normalize_config_section("database", {"host": "evil.example"}, **state)
    assert state["normalized"] == {}
    assert state["dropped_sections"] == ["database"]


@pytest.mark.parametrize("key", ["sources", "meta"])
def test_config_section_drops_readonly_extras(key: str) -> None:
    state = _section_state({"app"})
    serving_api._normalize_config_section(key, {"anything": 1}, **state)
    assert state["normalized"] == {}
    assert state["dropped_sections"] == []
    assert state["dropped_keys"] == []


@pytest.mark.parametrize(
    "key,value",
    [("environment", "development"), ("debug", True), ("timezone", "UTC")],
)
def test_config_section_moves_snapshot_aliases_under_app(
    key: str, value: object
) -> None:
    state = _section_state({"app"})
    serving_api._normalize_config_section(key, value, **state)
    assert state["normalized"] == {"app": {key: value}}


def test_config_section_rejects_non_dict_value() -> None:
    state = _section_state({"app"})
    with pytest.raises(HTTPException) as exc_info:
        serving_api._normalize_config_section("app", "development", **state)
    assert exc_info.value.status_code == 422


def test_config_section_drops_unknown_keys_within_allowlist() -> None:
    state = _section_state({"app", "ollama"})
    serving_api._normalize_config_section(
        "ollama", {"model": "m", "api_url": "http://evil.example"}, **state
    )
    assert state["normalized"] == {"ollama": {"model": "m"}}
    assert state["dropped_keys"] == ["ollama.api_url"]


def test_config_section_with_only_unknown_keys_merges_nothing() -> None:
    state = _section_state({"app", "ollama"})
    serving_api._normalize_config_section(
        "ollama", {"api_url": "http://evil.example"}, **state
    )
    assert state["normalized"] == {}
    assert state["dropped_keys"] == ["ollama.api_url"]


def test_config_payload_merges_allowlisted_patch() -> None:
    normalized = serving_api._normalize_config_payload(
        {"github": {"target_repo_url": "https://github.com/o/r.git"}}
    )
    assert normalized == {"github": {"target_repo_url": "https://github.com/o/r.git"}}


def test_config_payload_normalizes_snapshot_shape() -> None:
    normalized = serving_api._normalize_config_payload(
        {
            "environment": "development",
            "debug": False,
            "timezone": "UTC",
            "sources": {"x": 1},
            "meta": {"y": 2},
            "scoring": {"weights": {"recency": 0.3}},
        }
    )
    assert normalized == {
        "app": {"environment": "development", "debug": False, "timezone": "UTC"},
        "scoring": {"weights": {"recency": 0.3}},
    }


def test_config_payload_drops_privileged_sections_but_keeps_allowlisted() -> None:
    normalized = serving_api._normalize_config_payload(
        {
            "github": {"target_repo_url": "https://github.com/o/r.git"},
            "database": {"host": "evil.example"},
            "ollama": {"api_url": "http://evil.example:11434"},
        }
    )
    assert "database" not in normalized
    assert normalized["github"] == {"target_repo_url": "https://github.com/o/r.git"}
    assert "ollama" not in normalized


def test_config_payload_drops_secrets() -> None:
    normalized = serving_api._normalize_config_payload(
        {
            "github": {
                "token": "DROPPED",
                "target_repo_url": "https://github.com/o/r.git",
            }
        }
    )
    assert normalized == {"github": {"target_repo_url": "https://github.com/o/r.git"}}


def test_config_payload_empty_string_optional_becomes_none() -> None:
    normalized = serving_api._normalize_config_payload({"ollama": {"model": ""}})
    assert normalized == {"ollama": {"model": None}}


def test_config_payload_rejects_foreign_section() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._normalize_config_payload(
            {"app": {"environment": "development"}, "evil_section": {"x": 1}}
        )
    assert exc_info.value.status_code == 422


def test_config_payload_rejects_non_dict_section() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._normalize_config_payload({"app": "development"})
    assert exc_info.value.status_code == 422


def test_config_payload_rejects_oversize_before_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serving_api, "_ADMIN_CONFIG_MAX_BYTES", 10)
    with pytest.raises(HTTPException) as exc_info:
        serving_api._normalize_config_payload({"app": {"environment": "development"}})
    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# _validate_publish_article_url (hermetic: literal IPs / scheme / shape only,
# so validate_url_safety never performs a DNS lookup)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_url", ["", "   "])
def test_publish_url_rejects_blank(raw_url: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_publish_article_url(raw_url)
    assert exc_info.value.status_code == 422


def test_publish_url_rejects_unparseable() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_publish_article_url("::::")
    assert exc_info.value.status_code == 422


def test_publish_url_rejects_blocked_scheme() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_publish_article_url("ftp://example.com/article")
    assert exc_info.value.status_code == 422


def test_publish_url_rejects_loopback() -> None:
    with pytest.raises(HTTPException) as exc_info:
        serving_api._validate_publish_article_url("http://127.0.0.1/x")
    assert exc_info.value.status_code == 422


def test_publish_url_accepts_public_url() -> None:
    assert (
        serving_api._validate_publish_article_url("http://93.184.216.34/x")
        == "https://93.184.216.34/x"
    )


WEBHOOK = "/api/v1/webhook/frontend"
UPLOAD = "/v1/admin/images/fixture/upload"


async def _asgi_request(app, path, chunks, *, headers=(), method="POST"):
    messages: list[Message] = []
    reads = 0
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": list(headers),
    }

    async def receive() -> Message:
        nonlocal reads
        chunk = chunks[reads]
        reads += 1
        if chunk is None:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": chunk, "more_body": reads < len(chunks)}

    async def send(message: Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    body = b"".join(m.get("body", b"") for m in messages[1:])
    return messages[0]["status"], json.loads(body), reads


@pytest.fixture
def bounded_app(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_API_KEY", "webhook-fixture")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-fixture")
    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "bounds.db"})
    try:
        yield serving_api.create_app(database_manager=db)
    finally:
        db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [WEBHOOK, UPLOAD])
async def test_unauthenticated_write_never_reads_body(bounded_app, path):
    status, result, reads = await _asgi_request(bounded_app, path, [])
    assert (status, reads) == (401, 0)
    assert result["detail"] == "Missing Authorization header"


@pytest.mark.asyncio
@pytest.mark.parametrize("path, expected", [(WEBHOOK, 413), (UPLOAD, 401)])
async def test_declared_size_and_auth_precedence(
    bounded_app, monkeypatch, path, expected
):
    monkeypatch.setattr(serving_api, "_WEBHOOK_MAX_BODY_BYTES", 8)
    monkeypatch.setattr(admin_images, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(admin_images, "_MULTIPART_OVERHEAD_BYTES", 4)
    status, _, reads = await _asgi_request(
        bounded_app, path, [], headers=[(b"content-length", b"9")]
    )
    assert (status, reads) == (expected, 0)


@pytest.mark.asyncio
async def test_interrupted_upload_keeps_bad_request_response(bounded_app):
    headers = [
        (b"authorization", b"Bearer admin-fixture"),
        (b"content-type", b"multipart/form-data; boundary=fixture"),
    ]
    status, result, reads = await _asgi_request(
        bounded_app, UPLOAD, [None], headers=headers
    )
    assert (status, reads) == (400, 1)
    assert result["detail"] == "There was an error parsing the body"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, token, content_type",
    [
        (WEBHOOK, b"webhook-fixture", b"application/json"),
        (UPLOAD, b"admin-fixture", b"multipart/form-data; boundary=fixture"),
    ],
)
async def test_budget_stops_stream_before_parser(
    bounded_app, monkeypatch, path, token, content_type
):
    monkeypatch.setattr(serving_api, "_WEBHOOK_MAX_BODY_BYTES", 8)
    monkeypatch.setattr(admin_images, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(admin_images, "_MULTIPART_OVERHEAD_BYTES", 4)

    def parser_must_not_run(*_args, **_kwargs):
        pytest.fail("Over-budget requests must never enter the parser")

    monkeypatch.setattr(Request, "json", parser_must_not_run)
    monkeypatch.setattr(Request, "form", parser_must_not_run)
    headers = [
        (b"authorization", b"Bearer " + token),
        (b"content-type", content_type),
    ]
    declared, _, reads = await _asgi_request(
        bounded_app, path, [], headers=[*headers, (b"content-length", b"9")]
    )
    assert (declared, reads) == (413, 0)
    streamed, result, reads = await _asgi_request(
        bounded_app, path, [b"abcd", b"abcde", b"unread"], headers=headers
    )
    assert (streamed, reads) == (413, 2)
    assert "too large" in result["detail"]


@pytest.mark.asyncio
async def test_webhook_accepts_exact_budget_and_preserves_422(bounded_app, monkeypatch):
    payload = json.dumps(
        {
            "event": "validation_result",
            "commit_sha": "fixture",
            "frontend_ref": "fixture",
            "branch": "main",
            "status": "pass",
            "diagnostics": [],
            "run_url": "https://github.com/example/repo/actions/runs/1",
        }
    ).encode()
    monkeypatch.setattr(serving_api, "_WEBHOOK_MAX_BODY_BYTES", len(payload))
    headers = [
        (b"authorization", b"Bearer webhook-fixture"),
        (b"content-type", b"application/json"),
    ]
    status, _, reads = await _asgi_request(
        bounded_app, WEBHOOK, [payload[:16], payload[16:]], headers=headers
    )
    assert (status, reads) == (202, 2)
    invalid, _, _ = await _asgi_request(bounded_app, WEBHOOK, [b"{"], headers=headers)
    assert invalid == 422


# ---------------------------------------------------------------------------
# is_explicit_development
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "environment,expected",
    [
        ("development", True),
        ("unset", False),
        ("", False),
        ("Development", False),
        (" production ", False),
        ("production", False),
        (None, False),
        (123, False),
    ],
)
def test_is_explicit_development(environment: object, expected: bool) -> None:
    assert is_explicit_development(environment) is expected
