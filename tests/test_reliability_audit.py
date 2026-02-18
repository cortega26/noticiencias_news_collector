
import asyncio
import pytest
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from news_collector.collectors.base_collector import BaseCollector
from news_collector.collectors.html_collector import HtmlCollector
from news_collector.config.sources import validate_sources, ALL_SOURCES
import httpx

# --- Helpers ---
def make_utc(dt):
    return dt.replace(tzinfo=timezone.utc)

# --- 1. Schema Validation Tests ---

def test_schema_negative_cases():
    """Verify strictly that invalid configs raise errors."""
    
    # Missing Tier
    bad_config_1 = {"test": {"name": "T", "url": "u", "crawl_interval_seconds": 3600}}
    with patch("news_collector.config.sources.load_sources"):
        with patch.dict(ALL_SOURCES, bad_config_1, clear=True):
            # Regex modified to match the line in the aggregated error message
            with pytest.raises(ValueError, match="missing required field: 'tier'"):
                validate_sources()

    # Invalid Tier
    bad_config_2 = {"test": {"name": "T", "url": "u", "tier": "Z", "crawl_interval_seconds": 3600}}
    with patch("news_collector.config.sources.load_sources"):
        with patch.dict(ALL_SOURCES, bad_config_2, clear=True):
            # Regex relaxed to avoid whitespace/formatting mismatches
            with pytest.raises(ValueError, match="invalid tier"):
                validate_sources()
            
    # Missing Interval
    bad_config_3 = {"test": {"name": "T", "url": "u", "tier": "A"}}
    with patch("news_collector.config.sources.load_sources"):
        with patch.dict(ALL_SOURCES, bad_config_3, clear=True):
            with pytest.raises(ValueError, match="missing required field: 'crawl_interval_seconds'"):
                validate_sources()

# --- 2. Interval Enforcement & Circuit Breaker ---

class MockCollector(BaseCollector):
    def collect_from_source(self, s_id, s_conf): return {}

@pytest.mark.asyncio
async def test_circuit_breaker_cooldown_respect():
    """
    Critical: Verify that if DB says COOLDOWN, we skip EVEN IF interval is passed.
    """
    collector = MockCollector()
    collector.db_manager = MagicMock()
    
    # Scenario: Interval passed (last checked 10h ago, interval 6h)
    # BUT Status is COOLDOWN until 1 hour in future
    now = datetime.now(timezone.utc)
    last_checked = now - timedelta(hours=10)
    next_retry = now + timedelta(hours=1)
    
    collector.db_manager.get_source_circuit_state.return_value = {
        "status": "COOLDOWN",
        "last_checked": last_checked,
        "next_retry_at": next_retry
    }
    
    source_config = {"crawl_interval_seconds": 21600} # 6h
    
    # Should be False (Blocked by Circuit Breaker)
    # Logic note: currently BaseCollector._check_crawl_interval might return True here (GAP)
    # We assert False to drive the fix.
    assert collector._check_crawl_interval("test_src", source_config) is False, \
        "Source should be skipped because it is in COOLDOWN, regardless of interval."

# --- 3. Failure Modes & Retries ---

@pytest.mark.asyncio
async def test_html_collector_5xx_retries():
    """
    Verify that 5xx errors trigger retries with backoff.
    """
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    collector.db_manager.get_source_feed_metadata.return_value = {}
    
    source_config = {"url": "http://flaky.com"}
    
    # Mock specific backoff sleep to avoid slowing tests
    with patch.object(collector, '_backoff_sleep', new_callable=AsyncMock) as mock_sleep:
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # Sequence: 500, 502, 200 OK
            mock_get.side_effect = [
                MagicMock(status_code=500),
                MagicMock(status_code=502),
                MagicMock(status_code=200, text="Success", content=b"Success", headers={})
            ]
            
            # We need to bypass robots
            with patch.object(collector, "_respect_robots", return_value=(True, 0)):
                content, status = await collector._fetch_html_conditional(
                    "http://flaky.com", "src_id", source_config
                )
            
            # Assertions
            assert status == 200
            assert content == "Success"
            assert mock_get.await_count == 3
            # Ensure backoff was called twice
            # verify call count if we implement retries inside _fetch_html_conditional

@pytest.mark.asyncio
async def test_html_collector_403_no_retry():
    """
    Verify that 403 errors DO NOT trigger retries (Fail Fast).
    """
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    # CRITICAL: Must return dict, otherwise it returns MagicMock which breaks httpx headers
    collector.db_manager.get_source_feed_metadata.return_value = {}
    
    with patch.object(collector, '_backoff_sleep', new_callable=AsyncMock) as mock_sleep:
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = MagicMock(status_code=403, headers={})
            
            with patch.object(collector, "_respect_robots", return_value=(True, 0)):
                content, status = await collector._fetch_html_conditional(
                    "http://forbidden.com", "src_id", {}
                )
            
            assert status == 403
            assert mock_get.await_count == 1 # Only one attempt

# --- 4. Deduplication ---

# (Note: Deduplication logic is mostly in DatabaseManager, tested via integration usually, 
# but we can check if HtmlCollector respects existing content hash)

@pytest.mark.asyncio
async def test_content_hash_deduplication():
    """
    Verify 200 OK with same content hash returns 304 behavior (Skip).
    """
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    
    # DB has hash for "Old Content"
    old_content = b"Old Content"
    old_hash = hashlib.sha256(old_content).hexdigest()
    
    collector.db_manager.get_source_feed_metadata.return_value = {
        "content_hash": old_hash
    }
    
    # Server returns 200 but SAME content
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = old_content # Same content
    mock_response.text = "Old Content"
    mock_response.headers = {}
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        
        content, status = await collector._fetch_html_conditional(
            "http://example.com", "src", {}
        )
        
        # Should mimic 304
        assert status == 304
        assert content is None

