import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from news_collector.collectors.async_rss_collector import AsyncRSSCollector

class TestSecurityRedirects(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_loop_protection(self):
        """Test that the collector stops after max redirects."""
        collector = AsyncRSSCollector()
        collector.db_manager = MagicMock()
        collector.db_manager.get_source_feed_metadata.return_value = {}
        collector._emit_log = MagicMock()

        # Mock httpx client
        client = AsyncMock()
        
        # Setup specific responses for multiple calls
        # 301, 301, 301, ... -> Loop
        redirect_response = MagicMock()
        redirect_response.status_code = 301
        redirect_response.headers = {"Location": "http://example.com/loop"}
        
        # Configure client.get to return redirect every time
        client.get.return_value = redirect_response
        
        # Run
        with patch('news_collector.collectors.async_rss_collector.validate_url_safety_sync') as mock_validate:
             result = await collector._fetch_feed_async("source-1", "http://example.com", client)
        
        # Expectation: (None, None) due to Too Many Redirects
        self.assertEqual(result, (None, None))
        
        # Expect 6 calls (initial + 5 redirects)
        self.assertEqual(client.get.call_count, 6)
        
        # Expect log
        collector._emit_log.assert_called_with(
            "error", 
            "collector.feed.too_many_redirects", 
            source_id="source-1", 
            details={"max": 5}
        )

    async def test_ssrf_validation_on_redirect(self):
        """Test that validation is called for the redirect target."""
        collector = AsyncRSSCollector()
        collector.db_manager = MagicMock()
        collector.db_manager.get_source_feed_metadata.return_value = {}
        
        client = AsyncMock()
        
        # 1. First response: Redirect to unsafe IP
        resp1 = MagicMock()
        resp1.status_code = 301
        resp1.headers = {"Location": "http://169.254.169.254/latest"}
        
        # 2. Setup client to return resp1
        client.get.return_value = resp1
        
        # Mock validation to raise error on the second call (the redirect)
        with patch('news_collector.collectors.async_rss_collector.validate_url_safety_sync') as mock_validate:
            def side_effect(url):
                if "169.254" in url:
                    raise ValueError("SSRF Risk")
                return True
            mock_validate.side_effect = side_effect
            
            result = await collector._fetch_feed_async("source-1", "http://example.com", client)

        # Expect failure
        self.assertEqual(result, (None, None))
        # Should have called get only once (stopped before second get)
        self.assertEqual(client.get.call_count, 1)

if __name__ == '__main__':
    unittest.main()
