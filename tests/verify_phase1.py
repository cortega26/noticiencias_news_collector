
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from news_collector.collectors.rss_collector import RSSCollector
from news_collector.components.editorial.ai_editor import EditorAgent

# =============================================================================
# 1. Circuit Breaker Testing
# =============================================================================

@patch('news_collector.storage.database.DatabaseManager')
@patch('news_collector.infrastructure.requests_client.RobustRequestsClient')
def test_circuit_breaker_skips_cooldown(mock_client_cls, mock_db_cls):
    """
    Verifies that RSSCollector acts as a Circuit Breaker when source is in COOLDOWN.
    """
    # Setup Mocks
    mock_db = MagicMock()
    # mock_get_db.return_value = mock_db # Removed

    # Mock DB state: Source is in COOLDOWN until tomorrow
    next_retry = datetime.now(timezone.utc) + timedelta(hours=4)
    mock_db.get_source_circuit_state.return_value = {
        "status": "COOLDOWN",
        "next_retry_at": next_retry,
        "consecutive_failures": 3,
        "is_active": True
    }

    collector = RSSCollector()
    collector.db_manager = mock_db # Ensure it uses our mock

    # Execution
    source_config = {"url": "http://broken.source", "name": "Broken Source", "min_delay_seconds": 1}
    # Mock _fetch_feed to ensure it's NOT called
    collector._fetch_feed = MagicMock()

    # Mock _respect_robots to avoid network calls (httpx.get)
    collector._respect_robots = MagicMock(return_value=(True, 0.0))

    result = collector.collect_from_source("broken_source_id", source_config)

    # Assertions
    assert result["success"] is True
    assert "Circuit Breaker: Skipped" in result["error_message"]
    collector._fetch_feed.assert_not_called()
    print("\n✅ Circuit Breaker Test Passed: Cooldown observed.")


# =============================================================================
# 2. Translation Guardrails Testing
# =============================================================================

@patch('news_collector.components.editorial.ai_editor.OllamaProvider')
def test_critic_pass_rejects_bad_content(mock_provider_cls):
    """
    Verifies that EditorAgent rejects content if the Critic (LLM Guard) flags it.
    """
    agent = EditorAgent("http://mockjson", "mock-model")

    # Mock MVS flow:
    # 1. Translation -> "Translated text"
    # 2. Adaptation -> "Adapted text"
    # 3. Critic -> {"valid": False, "reason": "Engrish"}

    # We mock _send_prompt to handle sequence of calls or use side_effect
    # But simpler to mock _critic_pass internal calls or _send_prompt outcomes.

    # Let's mock _send_prompt responses
    # Call 1: Translation -> "Hola"
    # Call 2: Adaptation -> "Hola Mundo"
    # Call 3: Critic -> '{"valid": false, "reason": "Not Science"}'

    agent._send_prompt = MagicMock(side_effect=[
        "Hola",          # Translate
        "Hola Mundo",    # Adapt
        '{"score": 10, "reason": "Not Science"}' # Critic (Score < 70)
    ])

    # Execution
    raw_article = {"content": "Hello World " * 100} # Valid length

    try:
        agent.process_article(raw_article)
        raise AssertionError("Should have raised ValueError due to Critic Rejection")
    except ValueError as e:
        assert "Translation Guardrail" in str(e)
        assert "Not Spanish or Not Science" in str(e)
        print("✅ Critic Guardrail Test Passed: Rejected invalid content.")

@patch('news_collector.components.editorial.ai_editor.OllamaProvider')
def test_headline_schema_validation(mock_provider_cls):
    """
    Verifies that _generate_headlines validates output against Pydantic schema.
    """
    agent = EditorAgent("http://mock", "mock")

    # Mock return with missing fields
    bad_json = '{"direct": "Title"}' # Missing others

    agent._send_prompt = MagicMock(return_value=bad_json)

    try:
        # We access private method to test schema directly or mock _extract_json
        agent._generate_headlines("Content")
        raise AssertionError("Should raise ValueError (Schema Validation)")
    except ValueError as e:
        # Expect PydanticValidationError wrapped in ValueError
        assert "Schema Validation Failed" in str(e) or "validation error" in str(e).lower()
        print("✅ Schema Guardrail Test Passed: Detected malformed JSON.")

if __name__ == "__main__":
    # Manual run support
    test_circuit_breaker_skips_cooldown(MagicMock(), MagicMock())
    test_critic_pass_rejects_bad_content(MagicMock())
    test_headline_schema_validation(MagicMock())
    print("\n🎉 ALL PHASE 1 VERIFICATION TESTS PASSED")
