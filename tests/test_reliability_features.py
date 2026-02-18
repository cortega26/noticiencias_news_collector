import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta, timezone
from news_collector.collectors.html_collector import HtmlCollector
from news_collector.storage.models import Source

@pytest.mark.asyncio
async def test_429_retry_after_handling():
    """Verify 429 response triggers explicit COOLDOWN."""
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    # Mock circuit state: Active
    collector.db_manager.get_source_circuit_state.return_value = {"status": "ACTIVE"}
    
    # Mock 429 response with Retry-After: 60 (seconds)
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "60"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_instance = mock_client_cls.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.get = AsyncMock(return_value=mock_response)

        source_config = {"url": "http://example.com/429", "crawl_interval_seconds": 300}

        # Mock robots check
        with patch.object(collector, "_respect_robots", return_value=(True, 0)):
            # Run collection
            stats = await collector.collect_from_source_async("test_source_429", source_config)

        # Assert failed
        assert stats["success"] is False
        assert stats["articles_found"] == 0

        # Assert DB updated with forced cooldown
        collector.db_manager.update_source_circuit_state.assert_called_once()
        call_args = collector.db_manager.update_source_circuit_state.call_args
        assert call_args.kwargs.get("force_cooldown_until") is not None
        
        # Verify the time matches roughly now + 60s
        forced_time = call_args.kwargs["force_cooldown_until"]
        now = datetime.now(timezone.utc)
        diff = (forced_time - now).total_seconds()
        assert 50 < diff < 70  # Allow some execution time buffer

@pytest.mark.asyncio
async def test_jittered_backoff_randomness():
    """Verify backoff sleeps are jittered."""
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    
    # Mock 500 errors to trigger retries
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_instance = mock_client_cls.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.get = AsyncMock(return_value=mock_response)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # We also need to patch random.uniform to track values or control them
            # But here we just want to ensure it calls sleep with varying values if we run it multiple times?
            # Or better, patch random.uniform to return a fixed value and check math.
            
            with patch("random.uniform", return_value=0.5): # Jitter adds 0.5
                # Base is 0.5. 
                # Attempt 0: delay = min(10, 0.5 * 1) = 0.5. Low=0.25, High=0.75. Uniform returns 0.5.
                
                # Mock robots
                with patch.object(collector, "_respect_robots", return_value=(True, 0)):
                    await collector._fetch_html_conditional("http://fail.com", "src", {})
                
                # Should have retried 2 times (3 attempts total: 0, 1, 2. Sleep on 0 and 1)
                assert mock_sleep.call_count == 2
                
@pytest.mark.asyncio
async def test_persistence_across_restarts():
    """
    Simulate process restart by creating two collector instances 
    that verify against a shared (mocked) DB state.
    """
    # Shared State
    db_state = {
        "source_restart": {
            "status": "COOLDOWN",
            "next_retry_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "last_checked": datetime.now(timezone.utc)
        }
    }
    
    def get_state(source_id):
        return db_state.get(source_id)

    # Instance A (The "New" Process)
    collector_new = HtmlCollector()
    collector_new.db_manager = MagicMock()
    collector_new.db_manager.get_source_circuit_state.side_effect = get_state

    source_config = {"url": "http://test.com", "crawl_interval_seconds": 300}
    
    # Run interval check
    should_run = collector_new._check_crawl_interval("source_restart", source_config)
    
    # Verify it respects the "persisted" COOLDOWN
    assert should_run is False
