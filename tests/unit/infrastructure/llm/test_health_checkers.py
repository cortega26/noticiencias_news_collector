"""LLM health checkers and provider resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from noticiencias.config_schema import Config

from news_collector.infrastructure.llm import health
from news_collector.infrastructure.llm.factory import _is_empty_response, get_provider


def _cfg(nvidia_key=None, gemini_key=None):
    cfg = Config()
    cfg.nvidia.api_key = nvidia_key
    cfg.gemini.api_key = gemini_key
    return cfg


@pytest.mark.parametrize(
    ("checker", "target", "cfg_kwargs", "label"),
    [
        (
            health.NvidiaHealthChecker,
            "news_collector.infrastructure.llm.nvidia_provider.NvidiaProvider",
            {"nvidia_key": "k"},
            "NVIDIA",
        ),
        (
            health.GeminiHealthChecker,
            "news_collector.infrastructure.llm.gemini_provider.GeminiProvider",
            {"gemini_key": "k"},
            "Gemini",
        ),
    ],
)
def test_cloud_checkers_ok_failed_and_error(checker, target, cfg_kwargs, label):
    cfg = _cfg(**cfg_kwargs)
    logger = MagicMock()
    with patch(target) as provider_cls:
        provider_cls.return_value.check_health.return_value = (True, "ok")
        assert checker().check(cfg, logger).healthy is True

        provider_cls.return_value.check_health.return_value = (False, "http_500")
        result = checker().check(cfg, logger)
        assert result.healthy is False and result.disable_llm is True
        assert "http_500" in result.error and label in result.error

        provider_cls.return_value.check_health.side_effect = ValueError("boom")
        result = checker().check(cfg, logger)
        assert result.healthy is False and "boom" in result.error

        provider_cls.return_value.check_health.side_effect = RuntimeError("strict")
        with pytest.raises(RuntimeError):
            checker().check(cfg, None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("availability", "missing model"),
        ("registry", "model configuration error"),
        ("request", "unreachable"),
        ("unexpected", "Ollama health check error"),
    ],
)
def test_ollama_checker_error_paths(error, expected):
    from news_collector.infrastructure.llm import model_registry as mr

    errors = {
        "availability": mr.ModelAvailabilityError("missing model"),
        "registry": mr.ModelRegistryError("bad"),
        "request": requests.ConnectionError("down"),
        "unexpected": ValueError("weird"),
    }
    with patch.object(mr, "preflight_ollama_models", side_effect=errors[error]):
        result = health.OllamaHealthChecker().check(_cfg(), MagicMock())
    assert result.healthy is False and expected in result.error


def test_ollama_checker_ok_and_runtime_error():
    from news_collector.infrastructure.llm import model_registry as mr

    with patch.object(mr, "preflight_ollama_models", return_value=None):
        assert health.OllamaHealthChecker().check(_cfg(), None).healthy is True
    with patch.object(mr, "preflight_ollama_models", side_effect=RuntimeError("x")):
        with pytest.raises(RuntimeError):
            health.OllamaHealthChecker().check(_cfg(), None)


def test_resolve_health_checker_priority():
    assert isinstance(
        health.resolve_health_checker(_cfg("k")), health.NvidiaHealthChecker
    )
    assert isinstance(
        health.resolve_health_checker(_cfg(None, "g")), health.GeminiHealthChecker
    )
    assert isinstance(health.resolve_health_checker(_cfg()), health.OllamaHealthChecker)


def test_get_provider_includes_gemini_and_overrides_ollama_style_model():
    chain = get_provider(config=_cfg(None, "g"), model="llama3.2:latest")
    names = [p.__class__.__name__ for p in chain.providers]
    assert names == ["GeminiProvider", "OllamaProvider"]
    assert chain.providers[0].model == "gemini-2.5-flash"


def test_is_empty_response_ignores_non_text_values():
    assert _is_empty_response(SimpleNamespace()) is False
    assert _is_empty_response(["x"]) is False


def test_openai_compat_checker_with_logger_and_probe_exception(monkeypatch):
    from noticiencias.config_schema import LLMEndpointConfig

    from news_collector.infrastructure.llm.openai_compat_provider import (
        OpenAICompatProvider,
    )

    monkeypatch.setenv("HEALTH_TEST_KEY", "k")
    cfg = _cfg()
    cfg.llm_endpoints = [
        LLMEndpointConfig(
            name="probe",
            base_url="https://x.test/v1",
            model="m",
            api_key_env="HEALTH_TEST_KEY",
        )
    ]
    logger = MagicMock()
    checker = health.OpenAICompatHealthChecker()

    monkeypatch.setattr(
        OpenAICompatProvider, "check_health", lambda *_a, **_k: (True, "ok")
    )
    assert checker.check(cfg, logger).healthy is True
    monkeypatch.setattr(
        OpenAICompatProvider, "check_health", lambda *_a, **_k: (False, "http_500")
    )
    assert checker.check(cfg, logger).healthy is False

    def _boom(*_a, **_k):
        raise ValueError("network")

    monkeypatch.setattr(OpenAICompatProvider, "check_health", _boom)
    assert "network" in checker.check(cfg, logger).error

    monkeypatch.delenv("HEALTH_TEST_KEY")
    assert checker.check(cfg, logger).healthy is False
    assert logger.warning.called
