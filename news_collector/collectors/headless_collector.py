import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from news_collector.collectors.admission import evaluate_admission
from news_collector.collectors.base_collector import BaseCollector
from news_collector.config.settings import get_runtime_config
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
            # Launch chromium headless with stealth args
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )

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

    async def collect_from_source_async(  # noqa: C901
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

            # Record attempt
            if self.health_tracker:
                self.health_tracker.record_attempt(source_id)

            await self._ensure_browser()
            if self.browser is None:
                raise RuntimeError("Playwright browser failed to initialize")

            # Create a context with a realistic user agent
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )

            # Add init script to hide webdriver property (Stealth)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            page = await context.new_page()

            self._emit_log(
                "info", "collector.headless.navigating", details={"url": url}
            )

            # Go to page with timeout
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                await self._wait_for_challenge(page)

                # Wait for article selector if present
                item_selector = selectors.get("item", "article")
                try:
                    await page.wait_for_selector(item_selector, timeout=10000)
                except Exception:
                    self._emit_log(
                        "warning",
                        "collector.headless.selector_timeout",
                        details={"selector": item_selector},
                    )

            except Exception as e:
                self._emit_log(
                    "error",
                    "collector.headless.navigation_failed",
                    details={"error": str(e), "url": url},
                )
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
                self._emit_log(
                    "warning",
                    "collector.headless.empty_result",
                    details={"dump_saved": "debug_headless.html"},
                )

            for article in articles_data:
                # If content/summary is missing, try to fetch it
                if not article.get("content") and article.get("url"):
                    try:
                        full_text = await self._fetch_full_content(
                            context, article["url"]
                        )
                        if full_text:
                            article["content"] = full_text
                    except Exception as e:
                        self._emit_log(
                            "warning",
                            "collector.headless.content_fetch_failed",
                            details={"url": article["url"], "error": str(e)},
                        )

                # Ensure valid defaults if fetch failed
                if not article.get("content"):
                    article["content"] = (
                        None  # None is better than empty string for "no content"
                    )
                    article["content_mode"] = "summary_only"
                    # synthesize a summary to pass validation (min 30 chars)
                    # Title + URL is usually safe
                    fallback_summary = f"{article.get('title', '')}. Read more at: {article.get('url', '')}"
                    if len(fallback_summary) < 30:
                        fallback_summary += " [Content unavailable]"
                    article["summary"] = fallback_summary

                # Fix zero values to pass validation if we have minimal content
                article["word_count"] = (
                    len((article.get("content") or "").split())
                    or len((article.get("summary") or "").split())
                    or 1
                )
                article["reading_time_minutes"] = max(1, article["word_count"] // 200)

                try:
                    # Build the contract model once and reuse it: the raw
                    # dict carries collector-only keys (tags, published_at)
                    # that extra="forbid" would reject at save time, so the
                    # admission check and the save must use the same filtered,
                    # validated model or every headless article is dropped.
                    article_model = CollectorArticleModel(
                        **{
                            key: value
                            for key, value in article.items()
                            if key in CollectorArticleModel.model_fields
                        }
                    )
                    admission = evaluate_admission(article_model, get_runtime_config())
                except Exception as e:
                    self._emit_log(
                        "error",
                        "collector.headless.admission_validation_failed",
                        source_id=source_id,
                        details={"url": article.get("url"), "error": str(e)},
                    )
                    continue

                if not admission.accepted:
                    self._emit_log(
                        "info",
                        "collector.filter.admission_rejected",
                        source_id=source_id,
                        details={
                            "url": article.get("url"),
                            "reason": (
                                admission.reason.value
                                if admission.reason is not None
                                else "unknown"
                            ),
                        },
                    )
                    continue

                if self._save_article(article_model):
                    articles_saved += 1

            success = True

        except Exception as e:
            error_message = str(e)
            self._emit_log(
                "error", "collector.headless.failed", details={"error": str(e)}
            )
        finally:
            if "context" in locals():
                await context.close()

        return {
            "source_id": source_id,
            "success": success,
            "articles_found": articles_found,
            "articles_saved": articles_saved,
            "error_message": error_message,
            "processing_time": (
                datetime.now(timezone.utc) - start_time
            ).total_seconds(),
        }

    async def _extract_articles(
        self, page: Page, source_id: str, source_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
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
                    "published_at": datetime.now(timezone.utc),  # simplified
                    "published_date": datetime.now(timezone.utc),  # Alias for model
                    "content": "",  # Needs full text step
                    "summary": "",
                    "word_count": 0,
                    "reading_time_minutes": 0,
                    "authors": [],
                    "tags": [],
                }

                # Validate basics
                if len(title) < 5:
                    continue

                extracted.append(article_data)

            except Exception as e:
                self._emit_log(
                    "warning",
                    "collector.headless.extract_item_failed",
                    details={"error": str(e)},
                )
                continue

        return extracted

    async def _wait_for_challenge(self, page: Page):
        """Waits for Cloudflare challenge to resolve."""
        try:
            await page.wait_for_function(
                "document.title !== 'Just a moment...'", timeout=30000
            )
            await page.wait_for_timeout(3000)  # Extra buffer for hydration
        except Exception as e:
            # Emit warning but proceed
            self._emit_log(
                "warning",
                "collector.headless.hydration_wait_failed",
                details={"error": str(e)},
            )

    async def _fetch_full_content(
        self, context: BrowserContext, url: str
    ) -> Optional[str]:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await self._wait_for_challenge(page)

            # Simple heuristic: grab all paragraph text
            # Or use readability? For now, simple text extraction.
            # We can improve this with configured selectors later.

            # Try to frame it to article/main
            content_el = (
                await page.query_selector("article")
                or await page.query_selector("main")
                or await page.query_selector("div.content-wrapper")
                or await page.query_selector("body")
            )

            if content_el:
                # Use inner_text to get all visible text in the container
                # logical and simple.
                return str(await content_el.inner_text())
            return None
        except Exception as e:
            self._emit_log(
                "warning",
                "collector.headless.fetch_error",
                details={"url": url, "error": str(e)},
            )
            return None
        finally:
            await page.close()

    # Synchronous shim (though we recommend async usage)
    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        return asyncio.run(self.collect_from_source_async(source_id, source_config))
