from __future__ import annotations

import os
from pathlib import Path

import pytest
from news_collector.infrastructure.llm.model_registry import (
    InvalidModelIdError,
    MissingModelConfigurationError,
    ModelSource,
    NoWarnPolicyViolationError,
    NonCanonicalModelIdError,
    UnknownModelStageError,
    canonicalize_model_id,
    get_all_stages,
    get_model_for_stage,
    get_resolved_model_map_data,
    resolve_ollama_model_map,
)
from noticiencias.config_manager import load_config


def _load_tmp_config(
    tmp_path: Path,
    *,
    config_body: str,
    environ: dict[str, str] | None = None,
):
    config_file = tmp_path / "config.toml"
    config_file.write_text(config_body, encoding="utf-8")
    # Keep .env local to avoid fallback to project-level .env during tests.
    (tmp_path / ".env").write_text("", encoding="utf-8")
    return load_config(config_file, environ=environ or {})


def test_canonicalize_accepts_tagged_id():
    assert (
        canonicalize_model_id("llama3.3:latest", stage="default") == "llama3.3:latest"
    )


def test_canonicalize_normalizes_missing_tag():
    assert canonicalize_model_id("llama3.3", stage="default") == "llama3.3:latest"


def test_canonicalize_rejects_whitespace():
    with pytest.raises(InvalidModelIdError):
        canonicalize_model_id("llama3.3 latest", stage="default")


def test_pinned_mode_rejects_latest_and_missing_tag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOTICIENCIAS_LLM_PINNED", "1")
    with pytest.raises(InvalidModelIdError):
        canonicalize_model_id("llama3.3:latest", stage="default")
    with pytest.raises(InvalidModelIdError):
        canonicalize_model_id("llama3.3", stage="default")
    assert canonicalize_model_id("llama3.3:70b", stage="default") == "llama3.3:70b"


def test_strict_mode_rejects_implicit_normalization(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOTICIENCIAS_LLM_STRICT", "1")
    with pytest.raises(NonCanonicalModelIdError):
        canonicalize_model_id("llama3.3", stage="default")


def test_precedence_env_overrides_config(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=(
            "[ollama]\n"
            'model = "base-config:13b"\n'
            'translator_model = "translator-config:7b"\n'
            "[scoring]\n"
            'llm_model = "score-config:8b"\n'
        ),
        environ={
            "NOTICIENCIAS__OLLAMA__TRANSLATOR_MODEL": "translator-env:9b",
            "NOTICIENCIAS__SCORING__LLM_MODEL": "score-env:32b",
        },
    )
    resolved = resolve_ollama_model_map(cfg)
    assert resolved["translator"].model_id == "translator-env:9b"
    assert resolved["translator"].source == ModelSource.ENV
    assert resolved["scoring"].model_id == "score-env:32b"
    assert resolved["scoring"].source == ModelSource.ENV
    assert resolved["default"].source == ModelSource.CONFIG


def test_precedence_config_overrides_defaults(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "base-config:13b"\n'),
    )
    resolved = resolve_ollama_model_map(cfg)
    assert resolved["default"].model_id == "base-config:13b"
    assert resolved["default"].source == ModelSource.CONFIG


def test_stage_unset_is_explicitly_inherited(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "base-config:13b"\n'),
    )
    resolved = resolve_ollama_model_map(cfg)
    translator = resolved["translator"]
    assert translator.model_id == "base-config:13b"
    assert translator.source == ModelSource.INHERITED
    assert translator.inherited is True
    assert translator.notes and "inherited from 'default'" in translator.notes


def test_defaults_source_is_default(tmp_path: Path):
    cfg = _load_tmp_config(tmp_path, config_body="")
    resolved = resolve_ollama_model_map(cfg)
    assert resolved["default"].source == ModelSource.DEFAULT


def test_resolved_map_covers_all_registered_stages(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=(
            "[ollama]\n"
            'model = "llama3.3:70b"\n'
            'translator_model = "llama3.2:7b"\n'
            'editor_model = "qwen2.5:14b"\n'
            'headlines_model = "mistral:7b"\n'
            "[scoring]\n"
            'llm_model = "llama3.1:8b"\n'
        ),
    )
    resolved = resolve_ollama_model_map(cfg)
    assert set(resolved.keys()) == set(get_all_stages())
    for stage in get_all_stages():
        assert resolved[stage].model_id
        assert ":" in resolved[stage].model_id


def test_no_silent_normalization_visible_in_map(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "llama3.3"\n'),
    )
    resolved_data = get_resolved_model_map_data(cfg)
    assert resolved_data["default"]["model_id"] == "llama3.3:latest"
    assert resolved_data["default"]["raw_value"] == "llama3.3"
    assert resolved_data["default"]["normalized"] is True


def test_get_model_for_unknown_stage_fails_fast():
    with pytest.raises(UnknownModelStageError) as excinfo:
        get_model_for_stage(
            "embedding", config={"ollama": {"model": "llama3.3:latest"}}
        )
    assert "embedding" in str(excinfo.value)
    assert "Register this stage in model_registry.py" in str(excinfo.value)
    assert "Supported stages" in str(excinfo.value)


def test_missing_base_model_fails_fast_with_remediation():
    bad = {"ollama": {"model": ""}, "scoring": {}}
    with pytest.raises(MissingModelConfigurationError) as excinfo:
        resolve_ollama_model_map(bad)
    assert "default" in str(excinfo.value)
    assert "Set a value like" in str(excinfo.value)


def test_invalid_override_error_contains_stage_and_value():
    bad = {
        "ollama": {"model": "llama3.3:latest", "translator_model": "bad model"},
        "scoring": {},
    }
    with pytest.raises(InvalidModelIdError) as excinfo:
        resolve_ollama_model_map(bad)
    message = str(excinfo.value)
    assert "translator" in message
    assert "bad model" in message
    assert "Use '<model>:<tag>'" in message


def test_pinned_mode_env_applies_to_resolver(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOTICIENCIAS_LLM_PINNED", "1")
    bad = {
        "ollama": {"model": "llama3.3:latest"},
        "scoring": {"llm_model": "llama3.2:32b"},
    }
    with pytest.raises(InvalidModelIdError) as excinfo:
        resolve_ollama_model_map(bad)
    assert "Pinned mode forbids ':latest'" in str(excinfo.value)


def test_resolved_map_is_deterministic_json(tmp_path: Path):
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "llama3.3"\n'),
    )
    first = get_resolved_model_map_data(cfg)
    second = get_resolved_model_map_data(cfg)
    assert first == second


def test_no_warn_rejects_normalization(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("NOTICIENCIAS_LLM_NO_WARN", "1")
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "llama3.3"\n'),
    )
    with pytest.raises(NoWarnPolicyViolationError) as excinfo:
        resolve_ollama_model_map(cfg)
    message = str(excinfo.value)
    assert "NO_WARN" in message
    assert "default" in message
    assert "normalized" in message


def test_no_warn_rejects_inheritance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("NOTICIENCIAS_LLM_NO_WARN", "1")
    cfg = _load_tmp_config(
        tmp_path,
        config_body=("[ollama]\n" 'model = "llama3.3:70b"\n'),
    )
    with pytest.raises(NoWarnPolicyViolationError) as excinfo:
        resolve_ollama_model_map(cfg)
    message = str(excinfo.value)
    assert "translator" in message
    assert "inherited" in message


def test_no_warn_passes_with_explicit_stage_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("NOTICIENCIAS_LLM_NO_WARN", "1")
    monkeypatch.setenv("NOTICIENCIAS_LLM_PINNED", "1")
    cfg = _load_tmp_config(
        tmp_path,
        config_body=(
            "[ollama]\n"
            'model = "llama3.3:70b"\n'
            'translator_model = "llama3.2:7b"\n'
            'editor_model = "qwen2.5:14b"\n'
            'headlines_model = "mistral:7b"\n'
            'enrichment_model = "llama3.2:3b"\n'
            "[scoring]\n"
            'llm_model = "llama3.1:8b"\n'
        ),
    )
    resolved = resolve_ollama_model_map(cfg)
    assert set(resolved.keys()) == set(get_all_stages())
    assert all(not stage_data.normalized for stage_data in resolved.values())
    assert all(not stage_data.inherited for stage_data in resolved.values())
