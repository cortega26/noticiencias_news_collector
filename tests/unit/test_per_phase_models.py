
import pytest
from pydantic import ValidationError
from noticiencias.config_schema import OllamaConfig
from news_collector.components.editorial.ai_editor import EditorAgent

class MockProvider:
    def __init__(self, api_url, model, timeout):
        self.models = ["llama3.2:latest", "llama3.3:latest", "mistral:7b"]
    
    def list_models(self):
        return self.models

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
        OllamaConfig(model="") # empty might be handled by min length if pattern requires it (regex ^[a-zA-Z0-9])

def test_model_resolution(monkeypatch):
    # Mock EditorAgent's provider initialization to avoid real network calls
    monkeypatch.setattr("news_collector.components.editorial.ai_editor.OllamaProvider", MockProvider)
    # Also need to mock load_config used in __init__ for min_content_length
    monkeypatch.setattr("news_collector.components.editorial.ai_editor.load_config", lambda: type("C", (), {"text_processing": type("TP", (), {"min_content_length": 100})})())
    
    # Mock prompts loading
    monkeypatch.setattr("news_collector.components.editorial.ai_editor.EditorAgent._load_prompts", lambda self: {})

    agent = EditorAgent(
        api_url="http://mock",
        model="llama3.3:latest",
        translator_model="mistral:7b",
        editor_model="missing-model:latest", # Should fallback
        headlines_model=None # Should use legacy
    )
    
    # translator_model exists -> usage
    assert agent.translator_model == "mistral:7b"
    
    # editor_model missing -> fallback to legacy (self.model)
    # self.model is "llama3.3:latest"
    assert agent.editor_model == "llama3.3:latest"
    
    # headlines_model None -> legacy
    assert agent.headlines_model == "llama3.3:latest"

def test_resolve_model_method(monkeypatch):
     monkeypatch.setattr("news_collector.components.editorial.ai_editor.OllamaProvider", MockProvider)
     monkeypatch.setattr("news_collector.components.editorial.ai_editor.load_config", lambda: type("C", (), {"text_processing": type("TP", (), {"min_content_length": 100})})())
     monkeypatch.setattr("news_collector.components.editorial.ai_editor.EditorAgent._load_prompts", lambda self: {})
     
     agent = EditorAgent("http://mock", "base:latest")
     
     # Test with valid specific
     res = agent._resolve_model("mistral:7b", "Test")
     assert res == "mistral:7b"
     
     # Test with invalid specific
     res = agent._resolve_model("foobar:9000", "Test")
     assert res == "base:latest"
