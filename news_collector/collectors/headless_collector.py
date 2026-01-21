
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from urllib.parse import urljoin

from news_collector.collectors.base_collector import BaseCollector
from news_collector.contracts import CollectorArticleModel
# from news_collector.utils.url_utils import normalize_url # Removed invalid import

class HeadlessCollector(BaseCollector):
    """
    Collector that uses a headless browser (Playwright) to scrape content.
    Useful for sites that block standard HTTP requests (403) or render content via JS.
    """

    def __init__(self, logger_factory=None):
        super().__init__(logger_factory)
        self.browser: Optional[Browser] = None
        self.playwright = None

    async def _ensure_browser(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
        
        if not self.browser:
            # Launch chromium headless
            self.browser = await self.playwright.chromium.launch(headless=True)

    async def _close_browser(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def close(self):
        """Public method to close browser resources."""
        await self._close_browser()

    async def collect_from_source_async(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Implementation of the async collection logic using Headless Browser.
        """
        start_time = datetime.now(timezone.utc)
        articles_found = 0
        articles_saved = 0
        error_message = None
        success = False

        try:
            url = source_config.get("url")
            selectors = source_config.get("selectors", {})
            
            if not url:
                raise ValueError(f"Source {source_id} missing 'url' config")

            await self._ensure_browser()
            
            # Create a context with a realistic user agent
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()
            
            self._emit_log("info", "collector.headless.navigating", details={"url": url})
            
            # Go to page with timeout
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for article selector if present
                item_selector = selectors.get("item", "article")
                try:
                    await page.wait_for_selector(item_selector, timeout=5000)
                except Exception:
                    self._emit_log("warning", "collector.headless.selector_timeout", details={"selector": item_selector})

            except Exception as e:
                self._emit_log("error", "collector.headless.navigation_failed", details={"error": str(e), "url": url})
                # Capture screenshot on failure if debugging?
                # await page.screenshot(path="debug_fail.png")
                raise e

            # Extract articles
            articles_data = await self._extract_articles(page, source_id, source_config)
            articles_found = len(articles_data)

            if articles_found == 0:
                content = await page.content()
                with open("debug_headless.html", "w") as f:
                    f.write(content)
                self._emit_log("warning", "collector.headless.empty_result", details={"dump_saved": "debug_headless.html"})

            for article in articles_data:
                # If content/summary is missing, try to fetch it
                if not article.get("content") and article.get("url"):
                    try:
                        full_text = await self._fetch_full_content(context, article["url"])
                        if full_text:
                            article["content"] = full_text
                            # Update word count
                            article["word_count"] = len(full_text.split())
                    except Exception as e:
                        self._emit_log("warning", "collector.headless.content_fetch_failed", details={"url": article["url"], "error": str(e)})

                if self._save_article(article):
                    articles_saved += 1
            
            success = True

        except Exception as e:
            error_message = str(e)
            self._emit_log("error", "collector.headless.failed", details={"error": str(e)})
        finally:
            if 'context' in locals():
                await context.close()
            # We don't close the browser here to reuse it across sources if possible?
            # actually BaseCollector creates a new instance or reuses?
            # For now, let's keep browser open if we process multiple sources, 
            # but usually dispatcher might call us once per source if initialized per source.
            # If initialized once for multiple sources (dispatcher logic), we should close at end.
            # For this specific method, we just close context.
            pass

        return {
            "source_id": source_id,
            "success": success,
            "articles_found": articles_found,
            "articles_saved": articles_saved,
            "error_message": error_message,
            "processing_time": (datetime.now(timezone.utc) - start_time).total_seconds(),
        }

    async def _extract_articles(self, page: Page, source_id: str, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        selectors = source_config.get("selectors", {})
        item_selector = selectors.get("item", "article")
        title_selector = selectors.get("title", "h2")
        link_selector = selectors.get("link", "a")
        
        # summary not always present on index, might need full text fetch
        
        extracted = []
        
        # Get all item elements
        items = await page.query_selector_all(item_selector)
        
        for item in items:
            try:
                # Extract title
                title_el = await item.query_selector(title_selector)
                title = await title_el.inner_text() if title_el else ""
                
                # Extract link
                link_el = await item.query_selector(link_selector)
                link_href = await link_el.get_attribute("href") if link_el else ""
                
                # Normalize URL
                if link_href:
                    link_href = urljoin(page.url, link_href)
                
                if not title or not link_href:
                    continue

                # For OpenAI research, we might want to click through? 
                # Or just save the metadata and let a separate full-text fetcher handle it (which would also need headless)
                
                # Ideally, we get summary here or fetch content.
                # For now, simplistic approach:
                
                article_data = {
                    "source_id": source_id,
                    "source_name": source_id,  # Default to ID if name not known
                    "category": source_config.get("category", "General"),
                    "title": title.strip(),
                    "url": link_href,
                    "published_at": datetime.now(timezone.utc), # simplified
                    "published_date": datetime.now(timezone.utc), # Alias for model
                    "content": "", # Needs full text step
                    "summary": "",
                    "word_count": 0,
                    "reading_time_minutes": 0,
                    "authors": [],
                    "tags": []
                }
                
                # Validate basics
                if len(title) < 5:
                    continue
                    
                extracted.append(article_data)
                
            except Exception as e:
                continue
                
        return extracted

    async def _fetch_full_content(self, context: BrowserContext, url: str) -> Optional[str]:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Simple heuristic: grab all paragraph text
            # Or use readability? For now, simple text extraction.
            # We can improve this with configured selectors later.
            
            # Try to frame it to article/main
            content_el = await page.query_selector("article") or await page.query_selector("main") or await page.query_selector("body")
            
            if content_el:
                # Extract text from p tags
                # This needs to be robust. 
                # using evaluate to get text content is faster
                text = await content_el.evaluate("""(element) => {
                    return Array.from(element.querySelectorAll('p, h2, h3, li'))
                        .map(p => p.innerText)
                        .filter(t => t.length > 20)
                        .join('\\n\\n');
                }""")
                return text
            return None
        except Exception:
            return None
        finally:
            await page.close()

    # Synchronous shim (though we recommend async usage)
    def collect_from_source(self, source_id: str, source_config: Dict[str, Any]) -> Dict[str, Any]:
        return asyncio.run(self.collect_from_source_async(source_id, source_config))
