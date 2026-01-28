
import pytest
from unittest.mock import MagicMock, patch
from news_collector.infrastructure.llm.provider import OllamaProvider

class TestOllamaFix:

    def test_model_normalization_adds_latest_tag_if_missing(self):
        """Step E.1: When model is `llama3.3` (no tag), it should become `llama3.3:latest`."""
        provider = OllamaProvider(model="llama3.3")
        assert provider.model == "llama3.3:latest"

    def test_model_normalization_preserves_existing_tag(self):
        """Step E.2: When model is `llama3.3:latest`, it should stay `llama3.3:latest`."""
        provider = OllamaProvider(model="llama3.3:latest")
        assert provider.model == "llama3.3:latest"
        
        provider_custom = OllamaProvider(model="mistral:instruct")
        assert provider_custom.model == "mistral:instruct"

    def test_api_url_normalization_handles_base_url(self):
        """Step E.3a: When api_url is base (`http://localhost:11434`), it appends `/api/generate`."""
        provider = OllamaProvider(api_url="http://localhost:11434")
        assert provider.api_url == "http://localhost:11434/api/generate"

    def test_api_url_normalization_handles_endpoint_url(self):
        """Step E.3b: When api_url is endpoint (`.../api/generate`), it stays valid."""
        provider = OllamaProvider(api_url="http://localhost:11434/api/generate")
        assert provider.api_url == "http://localhost:11434/api/generate"

    @patch("news_collector.infrastructure.llm.provider.requests.post")
    def test_sync_generation_uses_normalized_values(self, mock_post):
        """Verify the actual request uses the normalized values."""
        # Setup
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Init with "bad" values
        provider = OllamaProvider(
            api_url="http://127.0.0.1:9999", # Base URL
            model="llama3.3"                 # Missing tag
        )

        # We need to bypass the strict system check mocking locally.
        # Since `settings` is imported inside `generate_sync`, we must patch it at the source: `news_collector.config.settings`.
        # We'll use a mock for the settings object itself if needed, or just set the attribute.
        
        # We need to mock `news_collector.config.settings` where it is defined.
        with patch("news_collector.config.settings") as mock_settings:
            mock_settings.LLM_SYSTEM_AVAILABLE = True
            provider.generate_sync(prompt="Test")

        # Assert
        # 1. URL should be normalized
        expected_url = "http://127.0.0.1:9999/api/generate"
        # 2. Payload should have normalized model
        expected_payload = {
            "model": "llama3.3:latest",
            "prompt": "Test",
            "stream": False
        }

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        
        assert args[0] == expected_url
        assert kwargs["json"] == expected_payload
