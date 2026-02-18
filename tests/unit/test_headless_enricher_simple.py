
import unittest
from unittest.mock import MagicMock, patch
import os

class TestHeadlessEnricherLogic(unittest.TestCase):
    
    @patch("news_collector.enrichment.headless_enricher.sync_playwright")
    @patch.dict(os.environ, {"ENABLE_HEADLESS": "true", "HEADLESS_MAX_SOURCES_PER_RUN": "100"})
    def test_enrich_flow(self, mock_playwright):
        from news_collector.enrichment.headless_enricher import HeadlessEnricher, budget_manager
        
        # Reset budget and manager
        budget_manager.reset()
        
        # Mock Playwright
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        
        mock_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        
        mock_page.inner_text.return_value = "Content"
        mock_page.content.return_value = "<html>Content</html>"
        
        enricher = HeadlessEnricher()
        
        config = {"name": "test", "headless_allowed_actions": []}
        result = enricher.enrich("http://example.com", config)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "Content")
        
        # Verify calls
        mock_p.chromium.launch.assert_called()
        mock_page.goto.assert_called_with("http://example.com", wait_until="domcontentloaded", timeout=30000)

if __name__ == "__main__":
    unittest.main()
