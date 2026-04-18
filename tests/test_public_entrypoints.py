import os
from unittest.mock import patch

from news_collector.infrastructure.llm.model_registry import (
    ModelAvailabilityError,
    ModelRegistryError,
)


class TestPublicEntrypoints:

    def test_core_config_manager_entrypoints(self):
        """Task 1: Verify from core.config_manager import CONFIG, get_config work."""
        from core.config_manager import CONFIG, get_config

        # Verify get_config is callable and returns config
        cfg = get_config()
        assert cfg.ollama.api_url is not None
        assert cfg.ollama.model is not None

        # Verify CONFIG is a Config instance (loaded)
        assert CONFIG.ollama.api_url == cfg.ollama.api_url
        assert CONFIG.ollama.model == cfg.ollama.model

    def test_bootstrap_system_entrypoint_exists_and_runs(self):
        """Task 2: Verify from news_collector.system.bootstrap import bootstrap_system works."""
        import importlib

        import news_collector.system.bootstrap as b

        importlib.reload(b)
        from news_collector.system.bootstrap import bootstrap_system

        # Verify it is callable
        assert callable(bootstrap_system)

        # We need to mock requests to avoid actual network calls and potential failures if offline
        with patch.dict(os.environ, {"NOTICIENCIAS_LLM_NO_WARN": "0"}, clear=False):
            with patch(
                "news_collector.infrastructure.llm.model_registry.preflight_ollama_models",
                return_value={"default": "llama3.3:latest"},
            ):
                warnings = bootstrap_system()

                assert isinstance(warnings, list)
                if warnings:
                    print(f"Unexpected warnings: {warnings}")

    def test_bootstrap_system_returns_warnings_on_failure(self):
        """Task 2b: Verify it returns warnings instead of raising exception."""
        from news_collector.system.bootstrap import bootstrap_system

        with patch.dict(os.environ, {"NOTICIENCIAS_LLM_NO_WARN": "0"}, clear=False):
            with patch(
                "news_collector.infrastructure.llm.model_registry.preflight_ollama_models",
                side_effect=ModelAvailabilityError(
                    "Ollama preflight failed to reach /api/tags: Connection refused"
                ),
            ):

                warnings = bootstrap_system()

                assert isinstance(warnings, list)
                assert len(warnings) > 0
                assert any(
                    "preflight failed" in w or "health check" in w for w in warnings
                )

    def test_bootstrap_strict_mode_fails_fast(self):
        from news_collector.system.bootstrap import bootstrap_system

        with patch.dict(os.environ, {"NOTICIENCIAS_LLM_STRICT": "1"}, clear=False):
            with patch(
                "news_collector.infrastructure.llm.model_registry.preflight_ollama_models",
                side_effect=ModelAvailabilityError(
                    "Ollama preflight failed to reach /api/tags: Connection refused"
                ),
            ):
                with patch("news_collector.config.settings.LLM_SYSTEM_AVAILABLE", True):
                    try:
                        bootstrap_system()
                        assert False, "Expected strict mode bootstrap failure"
                    except RuntimeError as exc:
                        msg = str(exc)
                        assert (
                            "Ollama preflight failed" in msg
                            or "Ollama model configuration error" in msg
                            or "Gemini health check" in msg
                        )

    def test_bootstrap_no_warn_mode_fails_fast_on_registry_warnings(self):
        from news_collector.system.bootstrap import bootstrap_system

        with patch.dict(
            os.environ,
            {"NOTICIENCIAS_LLM_NO_WARN": "1", "NOTICIENCIAS_LLM_STRICT": "0"},
            clear=False,
        ):
            # Also force Ollama path so registry error is reached
            with patch(
                "news_collector.config.settings.refresh_runtime_config"
            ) as mock_refresh:
                mock_cfg = mock_refresh.return_value
                mock_cfg.gemini.api_key = None
                mock_cfg.ollama.api_url = "http://localhost:11434/api/generate"
                with patch(
                    "news_collector.infrastructure.llm.model_registry.preflight_ollama_models",
                    side_effect=ModelRegistryError("NO_WARN mode forbids inheritance"),
                ):
                    with patch(
                        "news_collector.config.settings.LLM_SYSTEM_AVAILABLE", True
                    ):
                        try:
                            bootstrap_system()
                            assert False, "Expected NO_WARN bootstrap failure"
                        except RuntimeError as exc:
                            assert "Ollama model configuration error" in str(exc)
