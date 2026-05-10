from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from news_collector.config import settings as config_settings
from news_collector.system import bootstrap


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
