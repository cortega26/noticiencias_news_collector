from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from news_collector.infrastructure.llm.model_registry import ModelAvailabilityError
from news_collector.system import bootstrap


def test_ollama_health_check_graceful_failure():
    with (
        patch(
            "news_collector.infrastructure.llm.model_registry.preflight_ollama_models",
            side_effect=ModelAvailabilityError(
                "Ollama preflight failed to reach /api/tags: Connection refused"
            ),
        ),
        patch("news_collector.config.settings.get_config") as mock_config,
    ):
        mock_cfg = mock_config.return_value
        mock_cfg.nvidia = SimpleNamespace(api_key=None)
        mock_cfg.gemini = SimpleNamespace(api_key=None)
        mock_cfg.ollama = SimpleNamespace(
            api_url="http://localhost:11434/api/generate",
            model="qwen2.5:32b",
        )
        mock_cfg.scoring = SimpleNamespace(llm_model="qwen2.5:32b")
        mock_cfg.editorial_auditor = SimpleNamespace(health_timeout_seconds=1)

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
        assert any("Ollama preflight failed" in w for w in res["warnings"])

        # Ensure it didn't crash
        assert res["healthy"]
