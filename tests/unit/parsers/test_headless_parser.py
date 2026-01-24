import sys
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

# Mock playwright using patch.dict in the test or setup, not globally here
# We will do it inside the tests or setUp


import pytest

# from news_collector.collectors.headless_collector import HeadlessCollector
# Import moved to tests


@pytest.fixture
def headless_collector():
    # We need to mock the module BEFORE importing the class
    mock_playwright = MagicMock()
    with patch.dict(sys.modules, {"playwright": mock_playwright, "playwright.async_api": mock_playwright}):
        from news_collector.collectors.headless_collector import HeadlessCollector
        collector = HeadlessCollector()
        collector.health_tracker = MagicMock()
        yield collector


@pytest.mark.asyncio
async def test_headless_fetches_full_content_when_missing(headless_collector):
    """
    Verifies that if an article in the feed is missing content,
    _fetch_full_content is called to retrieve it.
    """
    source_config = {
        "url": "https://openai.com/research",
        "selectors": {"item": "div.item", "title": "h2", "link": "a"},
    }

    # Mock browser and context
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    headless_collector.browser = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
    mock_page.content.return_value = "<html>Debug content</html>"
    # Create a property mock for page.url if accessed as attribute, or a method if functional?
    # Playwright page.url is property.
    type(mock_page).url = PropertyMock(
        return_value="https://openai.com/blog"
    )  # requires PropertyMock import

    # Mock _ensure_browser so it doesn't try to launch real playwright
    with patch.object(headless_collector, "_ensure_browser", new_callable=AsyncMock):
        # Mock _emit_log to avoid side effects
        with patch.object(headless_collector, "_emit_log"):
            # Mock items found on index page
            mock_item = AsyncMock()
            # Setup query_selector for title/link
            mock_title_el = AsyncMock()
            mock_title_el.inner_text.return_value = "Test Article Title"

            mock_link_el = AsyncMock()
            mock_link_el.get_attribute.return_value = "https://openai.com/article/1"

            mock_item.query_selector.side_effect = lambda sel: (
                mock_title_el if sel == "h2" else mock_link_el if sel == "a" else None
            )

            mock_page.query_selector_all.return_value = [mock_item]

            # Mock content fetching logic
            with patch.object(
                headless_collector, "_fetch_full_content", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = "Full article content fetched separately."

                # Mock _save_article to always succeed (BaseCollector dependency)
                with patch.object(
                    headless_collector, "_save_article", return_value=True
                ):
                    # Run collection
                    result = await headless_collector.collect_from_source_async(
                        "test_source", source_config
                    )

                    # Verify
                    assert (
                        result["success"] is True
                    ), f"Collection failed: {result.get('error_message')}"
                    assert (
                        result["articles_found"] == 1
                    ), "Expected 1 article found during extraction"
                    assert result["articles_saved"] == 1

                    # Verify content fetch was triggered
                    mock_fetch.assert_called_once()
                    args, _ = mock_fetch.call_args
                    assert "https://openai.com/article/1" in args[1]  # url is 2nd arg
