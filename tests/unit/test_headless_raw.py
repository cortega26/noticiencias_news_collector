import os
from unittest.mock import MagicMock, patch

print("DEBUG: Script started", flush=True)

try:
    # Patch environment manually
    os.environ["ENABLE_HEADLESS"] = "true"
    os.environ["HEADLESS_MAX_SOURCES_PER_RUN"] = "100"

    # Patch sync_playwright manually
    print("DEBUG: Patching playwright", flush=True)
    with patch(
        "news_collector.enrichment.headless_enricher.sync_playwright"
    ) as mock_playwright:
        print("DEBUG: Importing HeadlessEnricher", flush=True)
        from news_collector.enrichment.headless_enricher import (
            HeadlessEnricher,
            budget_manager,
        )

        print("DEBUG: Resetting budget", flush=True)
        budget_manager.reset()

        # Mock Playwright
        print("DEBUG: Configuring mocks", flush=True)
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

        print("DEBUG: Instantiating Enricher", flush=True)
        enricher = HeadlessEnricher()

        print("DEBUG: Running enrich", flush=True)
        config = {"name": "test", "headless_allowed_actions": []}
        result = enricher.enrich("http://example.com", config)

        print(f"DEBUG: Result: {result}", flush=True)

except Exception as e:
    print(f"DEBUG: Exception: {e}", flush=True)
    import traceback

    traceback.print_exc()

print("DEBUG: Script finished", flush=True)
