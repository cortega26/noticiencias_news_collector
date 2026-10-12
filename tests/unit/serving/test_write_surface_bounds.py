"""Hermetic unit coverage for the admin write-surface bounds (plan 123).

The TestClient rejection tests for the serving hardening live in
``tests/test_serving_admin_api.py``, whose module-level ``pytestmark =
pytest.mark.e2e`` deselects all of it from the unit profile (``make type``).
These tests mirror their intent by calling the pure bound helpers directly:
no TestClient, no network, no database.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from news_collector.config.runtime import is_explicit_development
from news_collector.serving import api as serving_api

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
    serving_api._validate_prompts_payload(
        {"auditor": {"system": "Eres un auditor."}, "editor": {"system": "Edita."}}
    )


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
                "token": "SHOULD-NOT-PERSIST",
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
