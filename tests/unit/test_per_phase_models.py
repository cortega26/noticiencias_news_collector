import pytest
from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.infrastructure.llm.model_registry import InvalidModelIdError
from noticiencias.config_schema import OllamaConfig
from pydantic import ValidationError


class MockProvider:
    def __init__(self, api_url, model, timeout):
        self.api_url = api_url
        self.model = model
        self.timeout = timeout


def _mock_min_length_config():
    return type(
        "C", (), {"text_processing": type("TP", (), {"min_content_length": 100})}
    )()


def test_config_validation():
    # Valid names
    OllamaConfig(model="llama3.2")
    OllamaConfig(model="llama3.2:latest")
    OllamaConfig(model="my-custom-model.123")

    # Invalid names
    with pytest.raises(ValidationError):
        OllamaConfig(model="Invalid Space")
    with pytest.raises(ValidationError):
        OllamaConfig(model="<script>")
    with pytest.raises(ValidationError):
        OllamaConfig(model="")


def test_model_resolution_without_network(monkeypatch):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.OllamaProvider", MockProvider
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    agent = EditorAgent(
        api_url="http://mock",
        model="llama3.3",  # canonicalized to :latest
        translator_model="mistral:7b",
        editor_model="qwen2.5:14b",
        headlines_model=None,  # uses base model
    )

    assert agent.model == "llama3.3:latest"
    assert agent.translator_model == "mistral:7b"
    assert agent.editor_model == "qwen2.5:14b"
    assert agent.headlines_model == "llama3.3:latest"


def test_invalid_stage_override_fails_fast(monkeypatch):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.OllamaProvider", MockProvider
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    with pytest.raises(InvalidModelIdError) as excinfo:
        EditorAgent(
            api_url="http://mock",
            model="llama3.3:latest",
            translator_model="bad model",
        )
    message = str(excinfo.value)
    assert "translator" in message
    assert "bad model" in message
    assert "Use '<model>:<tag>'" in message
