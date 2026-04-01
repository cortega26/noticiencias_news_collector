from unittest.mock import MagicMock, patch

from news_collector.system import bootstrap


def test_ollama_health_check_graceful_failure():
    # Patch requests.get globally, since bootstrap.py imports it locally but uses the global module
    # Also patch Gemini API key to None so the Ollama path is exercised
    with (
        patch("requests.get", side_effect=Exception("Connection refused")),
        patch("news_collector.config.settings.CONFIG") as mock_cfg,
        patch(
            "news_collector.infrastructure.llm.model_registry.resolve_ollama_stage_models",
            return_value={"default": "llama3.3:latest"},
        ),
    ):
        mock_cfg.gemini.api_key = None
        mock_cfg.ollama.api_url = "http://localhost:11434/api/generate"

        # Mock config
        mock_config = {"url": "http://foo"}  # dummy

        # We need to mock module logger creation to verify warning
        mock_logger = MagicMock()

        # Setup DB/Collector mocks to be healthy so we check only LLM impact
        mock_db = MagicMock()
        mock_db.get_health_status.return_value = {"failed_sources": 0}
        mock_collector = MagicMock()
        mock_collector.is_healthy.return_value = True

        res = bootstrap.check_system_health(
            mock_db, mock_collector, mock_logger, mock_config
        )

        # Should return healthy=True (issues are handled as warnings for LLM to avoid blocking boot)
        assert "warnings" in res
        assert any("LLM Provider unreachable" in w for w in res["warnings"])

        # Ensure it didn't crash
        assert res["healthy"]
