
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from news_collector.collectors.base_collector import BaseCollector
from news_collector.collectors.html_collector import HtmlCollector

class MockCollector(BaseCollector):
    # Minimal concrete implementation for testing BaseCollector logic
    def collect_from_source(self, source_id, source_config):
        return {"success": True, "articles_found": 1}

@pytest.mark.asyncio
async def test_crawl_interval_enforcement_skip():
    """Test that source is skipped if interval has not passed."""
    collector = MockCollector()
    collector.db_manager = MagicMock()
    
    # Setup: Last checked 1 hour ago, Interval 6 hours
    last_checked = datetime.now(timezone.utc) - timedelta(hours=1)
    collector.db_manager.get_source_circuit_state.return_value = {
        "last_checked": last_checked,
        "status": "ACTIVE"
    }
    
    source_config = {"crawl_interval_seconds": 21600} # 6 hours
    source_id = "test_source"
    
    # Act
    # We test the internal check method directly first
    should_run = collector._check_crawl_interval(source_id, source_config)
    
    # Assert
    assert should_run is False

@pytest.mark.asyncio
async def test_crawl_interval_enforcement_run():
    """Test that source runs if interval has passed."""
    collector = MockCollector()
    collector.db_manager = MagicMock()
    
    # Setup: Last checked 7 hours ago, Interval 6 hours
    last_checked = datetime.now(timezone.utc) - timedelta(hours=7)
    collector.db_manager.get_source_circuit_state.return_value = {
        "last_checked": last_checked,
        "status": "ACTIVE"
    }
    
    source_config = {"crawl_interval_seconds": 21600}
    source_id = "test_source"
    
    assert collector._check_crawl_interval(source_id, source_config) is True

@pytest.mark.asyncio
async def test_html_collector_conditional_fetch_304():
    """Test HtmlCollector handles 304 Not Modified correctly."""
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    collector.db_manager.get_source_circuit_state.return_value = None # Assume no interval block
    
    # Mock DB returning existing ETag
    collector.db_manager.get_source_feed_metadata.return_value = {
        "etag": '"12345"',
        "last_modified": "Wed, 21 Oct 2025 07:28:00 GMT"
    }
    
    source_config = {"url": "http://example.com", "crawl_interval_seconds": 0}
    
    # Mock httpx response
    mock_response = MagicMock()
    mock_response.status_code = 304
    mock_response.headers = {}
    
    # Patch the class to check constructor args
    with patch("httpx.AsyncClient") as mock_client_cls:
        # Setup the mock instance returned by constructor
        mock_instance = mock_client_cls.return_value
        # Setup __aenter__ to return the mock instance (context manager)
        mock_instance.__aenter__.return_value = mock_instance
        # Setup get method on the instance
        mock_instance.get = AsyncMock(return_value=mock_response)

        # Disable robots check for simplicity
        with patch.object(collector, "_respect_robots", return_value=(True, 0)):
             result = await collector.collect_from_source_async("test_html", source_config)

             assert result["success"] is True
             assert result["articles_found"] == 0
             
             # Verify headers were passed to AsyncClient constructor
             call_kwargs = mock_client_cls.call_args.kwargs
             assert call_kwargs['headers']['If-None-Match'] == '"12345"'

@pytest.mark.asyncio
async def test_html_collector_conditional_fetch_200():
    """Test HtmlCollector handles 200 OK and updates metadata."""
    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    # Mock no existing ETag
    collector.db_manager.get_source_feed_metadata.return_value = {}
    
    source_config = {"url": "http://example.com", "crawl_interval_seconds": 0}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>Article</body></html>"
    mock_response.content = b"<html><body>Article</body></html>"
    mock_response.headers = {"ETag": '"new-etag"'}
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
         # Disable robots & extraction
        with patch.object(collector, "_respect_robots", return_value=(True, 0)):
            with patch.object(collector, "_extract_articles_from_html", return_value=[]): 
                result = await collector.collect_from_source_async("test_html", source_config)
                
                assert result["success"] is True
                # Check that metdata update was called
                collector.db_manager.update_source_feed_metadata.assert_called()
                call_args = collector.db_manager.update_source_feed_metadata.call_args[1]
                assert call_args['etag'] == '"new-etag"'
