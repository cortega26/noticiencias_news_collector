import json
from unittest.mock import MagicMock, patch
import pytest
from news_collector.components.editorial.ai_editor import EditorAgent
from pathlib import Path

@pytest.fixture
def agent():
    return EditorAgent(api_url="http://mock", model="mock-model")

def test_scientific_entities_loading(agent):
    """Test that scientific entities are correctly loaded from JSON."""
    entities_context = agent._load_scientific_entities()
    assert "LISTA CANÓNICA DE ENTIDADES CIENTÍFICAS" in entities_context
    assert "Dark Energy Survey -> Observatorio de la Energía Oscura" in entities_context
    assert "Very Large Telescope -> Very Large Telescope" in entities_context

def test_translator_prompt_injection(agent):
    """Test that the translator system prompt receives the canonical list."""
    with patch.object(agent, '_send_prompt', return_value="Translated Content") as mock_send:
        agent._translate_scientific("Some content about Dark Energy Survey")
        
        # Verify the system prompt passed to _send_prompt
        args, kwargs = mock_send.call_args
        system_prompt = kwargs.get('system', '')
        
        assert "LISTA CANÓNICA DE ENTIDADES CIENTÍFICAS" in system_prompt
        assert "Dark Energy Survey" in system_prompt

def test_critic_prompt_injection_and_logic(agent):
    """Test that the critic prompt receives the canonical list and instructions."""
    # Enable the guard for this test
    with patch.dict('os.environ', {'ENABLE_TRANSLATION_GUARD': 'true'}):
        with patch.object(agent, '_send_prompt') as mock_send:
            # Mock a passing response to allow us to check the prompt input
            mock_send.return_value = '{"score": 90, "reason": "Good"}'
            
            agent._critic_pass("Contenido en español")
            
            args, kwargs = mock_send.call_args
            prompt_sent = args[0]
            
            # Verify Prompt Content
            assert "[CRITICAL] Does it respect proper nouns?" in prompt_sent
            assert "LISTA CANÓNICA DE ENTIDADES CIENTÍFICAS" in prompt_sent
            assert "Dark Energy Survey" in prompt_sent
            assert "SCORE MUST BE 0" in prompt_sent

def test_critic_rejects_bad_terminology(agent):
    """Simulate the Critic rejecting a mistranslation."""
    with patch.dict('os.environ', {'ENABLE_TRANSLATION_GUARD': 'true'}):
         with patch.object(agent, '_send_prompt') as mock_send:
            # Mock the LLM correctly identifying the error
            mock_send.return_value = '{"score": 10, "reason": "Incorrect translation of Dark Energy Survey"}'
            
            result = agent._critic_pass("La Encuesta de Energía Oscura reportó...")
            
            assert result is False

def test_critic_accepts_good_terminology(agent):
    """Simulate the Critic accepting a correct translation."""
    with patch.dict('os.environ', {'ENABLE_TRANSLATION_GUARD': 'true'}):
         with patch.object(agent, '_send_prompt') as mock_send:
            mock_send.return_value = '{"score": 95, "reason": "Correct terminology"}'
            
            result = agent._critic_pass("El Observatorio de la Energía Oscura reportó...")
            
            assert result is True
