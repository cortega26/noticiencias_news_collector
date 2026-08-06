from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from news_collector.config import settings as config_settings
from news_collector.infrastructure.llm import health
from news_collector.system import bootstrap


def test_verify_llm_health_resolves_full_config_not_snapshot(monkeypatch) -> None:
    """_verify_llm_health() must resolve the provider from the full Config.

    Regression: when no config is passed, the old fallback used
    refresh_runtime_config() — the RuntimeConfigSnapshot, which carries no
    `.nvidia` attribute — so resolve_health_checker() fell through to
    OllamaHealthChecker() and disabled the LLM system even with a healthy
    NVIDIA key configured (see collector.log 2026-08-06).
    """
    full_config = SimpleNamespace(
        nvidia=SimpleNamespace(api_key="nvapi-test"),
        gemini=SimpleNamespace(api_key=None),
        ollama=SimpleNamespace(
            api_url="http://localhost:11434/api/generate", model="qwen2.5:32b"
        ),
    )

    received: dict = {}

    class _FakeChecker:
        def check(self, config, logger):
            received["config"] = config
            return health.HealthResult(healthy=True)

    monkeypatch.setattr(config_settings, "get_config", lambda: full_config)
    monkeypatch.setattr(health, "resolve_health_checker", lambda cfg: _FakeChecker())
    monkeypatch.setattr(config_settings.RUNTIME, "llm_system_available", False)

    bootstrap._verify_llm_health(MagicMock(), [], config=None)

    assert config_settings.RUNTIME.llm_system_available is True
    assert (
        getattr(getattr(received["config"], "nvidia", None), "api_key", None)
        is not None
    )


def test_verify_llm_health_uses_explicit_config(monkeypatch) -> None:
    """An explicit config argument must win over the module get_config()."""
    explicit_config = SimpleNamespace(
        nvidia=SimpleNamespace(api_key="nvapi-explicit"),
        gemini=SimpleNamespace(api_key=None),
        ollama=SimpleNamespace(
            api_url="http://localhost:11434/api/generate", model="qwen2.5:32b"
        ),
    )

    received: dict = {}

    class _FakeChecker:
        def check(self, config, logger):
            received["config"] = config
            return health.HealthResult(healthy=True)

    called_with_no_arg = []

    def _boom():
        raise AssertionError("get_config should not be called when config is passed")

    monkeypatch.setattr(config_settings, "get_config", _boom)
    monkeypatch.setattr(health, "resolve_health_checker", lambda cfg: _FakeChecker())
    monkeypatch.setattr(config_settings.RUNTIME, "llm_system_available", False)

    bootstrap._verify_llm_health(MagicMock(), [], config=explicit_config)

    assert received["config"] is explicit_config
    assert config_settings.RUNTIME.llm_system_available is True


def test_preflight_llm_provider_disables_llm_on_admission_failure(monkeypatch) -> None:
    config = SimpleNamespace(
        gemini=SimpleNamespace(api_key=None),
        ollama=SimpleNamespace(
            api_url="http://localhost:11434/api/generate",
            model="qwen2.5:32b",
        ),
        scoring=SimpleNamespace(llm_model="qwen2.5:32b"),
        editorial_auditor=SimpleNamespace(health_timeout_seconds=1),
    )

    tags_response = MagicMock()
    tags_response.raise_for_status.return_value = None
    tags_response.json.return_value = {"models": [{"name": "qwen2.5:32b"}]}

    generate_response = MagicMock()
    generate_response.status_code = 500
    generate_response.json.return_value = {
        "error": "model requires more system memory (19.1 GiB) than is available (1.0 GiB)"
    }
    generate_response.text = '{"error":"model requires more system memory (19.1 GiB) than is available (1.0 GiB)"}'

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: tags_response)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: generate_response)
    monkeypatch.setattr(config_settings.RUNTIME, "llm_system_available", True)

    warnings = bootstrap.preflight_llm_provider(config=config, logger=MagicMock())

    assert config_settings.RUNTIME.llm_system_available is False
    assert any("requires more system memory" in warning for warning in warnings)
