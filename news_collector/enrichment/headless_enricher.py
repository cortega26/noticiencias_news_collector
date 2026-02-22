"""Headless Enricher module using Playwright with strict budgets."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

PlaywrightTimeoutError: type[Exception]

try:
    from playwright.sync_api import TimeoutError as _PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright as _sync_playwright

    PlaywrightTimeoutError = _PlaywrightTimeoutError
    sync_playwright: Any = _sync_playwright
except ImportError:
    sync_playwright = None  # Handle missing dependency gracefully
    PlaywrightTimeoutError = TimeoutError

logger = logging.getLogger(__name__)


class HeadlessBudgetManager:
    """Tracks global usage of headless resources per process execution."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HeadlessBudgetManager, cls).__new__(cls)
            cls._instance.reset()
        return cls._instance

    def reset(self):
        self.sources_attempted = 0
        self.total_seconds_used = 0.0
        self.max_sources = int(os.getenv("HEADLESS_MAX_SOURCES_PER_RUN", "5"))
        self.max_total_seconds = float(
            os.getenv("HEADLESS_MAX_TOTAL_SECONDS_PER_RUN", "180")
        )

    def can_attempt(self) -> bool:
        if self.sources_attempted >= self.max_sources:
            return False
        return not self.total_seconds_used >= self.max_total_seconds

    def record_usage(self, duration: float):
        self.sources_attempted += 1
        self.total_seconds_used += duration


budget_manager = HeadlessBudgetManager()


class HeadlessEnricher:
    """
    Enriches articles by rendering JS content via Playwright (Headless).
    Strictly controlled by budget and allowed actions.
    """

    def __init__(self, logger_factory=None):
        self.enabled = os.getenv("ENABLE_HEADLESS", "false").lower() == "true"
        self.logger = (
            logger_factory.create_module_logger("enrichment.headless")
            if logger_factory
            else logging.getLogger(__name__)
        )

        if self.enabled and sync_playwright is None:
            self.logger.error("Headless enabled but playwright not installed.")
            self.enabled = False

    def _execute_enrich(
        self,
        url: str,
        source_config: Dict[str, Any],
        proxy_settings: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Internal method to execute a single enrichment attempt.
        """
        # Per-source timeout
        max_duration = source_config.get("headless_max_seconds", 30)
        if sync_playwright is None:
            raise RuntimeError("playwright is not installed")

        start_time = time.time()
        error = None
        content = None
        success = False
        raw_content = None

        browser = None
        try:
            with sync_playwright() as p:
                # Launch browser
                # Note: Playwright proxy is set at browser or context level
                # For sync_playwright, we usually launch a browser instance
                launch_options: dict[str, Any] = {"headless": True}
                if proxy_settings:
                    # Requests dict is {'http': url, 'https': url}
                    # Playwright expects {'server': url, 'username': ..., 'password': ...}
                    # We assume the URL in proxy_settings['http'] is the server URL
                    proxy_url = proxy_settings.get("http")
                    if proxy_url:
                        launch_options["proxy"] = {"server": proxy_url}

                browser = p.chromium.launch(**launch_options)

                # Context with strict timeouts
                context = browser.new_context(
                    user_agent="NoticienciasNewsCollector/1.0 (Headless; +http://noticiencias.com)",
                    java_script_enabled=True,
                    bypass_csp=True,
                )

                context.set_default_timeout(max_duration * 1000)

                page = context.new_page()

                # 1. Navigate
                try:
                    page.goto(
                        url, wait_until="domcontentloaded", timeout=max_duration * 1000
                    )
                except PlaywrightTimeoutError:
                    raise TimeoutError("Navigation timeout")  # noqa: B904

                # 2. Allowed Actions
                self._perform_actions(
                    page, source_config.get("headless_allowed_actions", [])
                )

                # Capture raw HTML
                raw_content = page.content()

                # 3. Extract Content
                page.evaluate("""() => {
                    const noise = document.querySelectorAll('script, style, nav, footer, header, aside, noscript, iframe, svg, [aria-hidden="true"]');
                    noise.forEach(el => el.remove());
                }""")

                content = page.inner_text("body") or ""
                content = " ".join(content.split())  # Cleanup whitespace

                success = True
                browser.close()

        except Exception as e:
            error = str(e)
            if browser:
                with contextlib.suppress(Exception):
                    browser.close()
            # Raise exception to trigger retry logic in caller
            raise e

        duration = time.time() - start_time
        return {
            "success": success,
            "content": content,
            "raw_content": raw_content,
            "error": error,
            "duration": duration,
        }

    def enrich(
        self, url: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:  # noqa: C901
        """
        Renders URL using headless browser, with Proxy Fallback.
        """
        if not self.enabled:
            return {"success": False, "error": "headless_disabled", "content": None}

        if not budget_manager.can_attempt():
            return {
                "success": False,
                "error": "headless_budget_exhausted",
                "content": None,
            }

        # Check Force Proxy
        from news_collector.infrastructure.proxy_manager import proxy_manager

        proxy_settings = None

        # If policy is force, we start with proxy
        if (
            source_config.get("proxy_mode") == "force"
            and proxy_manager.budget_manager.can_afford()
        ):
            proxy_settings = proxy_manager.get_proxy_settings(source_config)

        start_time = time.time()

        try:
            # Attempt 1
            result = self._execute_enrich(url, source_config, proxy_settings)

            # Record usage
            budget_manager.record_usage(result["duration"])
            if proxy_settings:
                # Also record proxy usage
                proxy_manager.record_usage(result["duration"])
                self.logger.info(
                    {
                        "event": "enrichment.headless.proxy.success",
                        "details": {"url": url},
                    }
                )

            return result

        except Exception as e:
            # Handle Failure & Check Retry
            duration_attempt_1 = time.time() - start_time
            budget_manager.record_usage(duration_attempt_1)

            if proxy_settings:
                proxy_manager.record_usage(duration_attempt_1)
                self.logger.warning(f"Headless (Proxy) failed: {e}")
                # Already tried proxy, fail
                return {
                    "success": False,
                    "error": str(e),
                    "content": None,
                    "duration": duration_attempt_1,
                }

            # Check if we should retry with proxy
            if (
                proxy_manager.should_retry_with_proxy(source_config, error=e)
                and budget_manager.can_attempt()
                and proxy_manager.budget_manager.can_afford()
            ):

                proxy_settings = proxy_manager.get_proxy_settings(source_config)
                if proxy_settings:
                    self.logger.info(
                        {
                            "event": "enrichment.headless.proxy.attempt",
                            "details": {"url": url, "reason": str(e)},
                        }
                    )

                    start_retry_time = time.time()
                    try:
                        # Attempt 2 (Proxy)
                        result_2 = self._execute_enrich(
                            url, source_config, proxy_settings
                        )

                        # Record usage
                        budget_manager.record_usage(result_2["duration"])
                        proxy_manager.record_usage(result_2["duration"])

                        self.logger.info(
                            {
                                "event": "enrichment.headless.proxy.success",
                                "details": {"url": url},
                            }
                        )
                        return result_2

                    except Exception as e2:
                        duration_2 = time.time() - start_retry_time
                        # Record usage for failed retry
                        budget_manager.record_usage(duration_2)
                        proxy_manager.record_usage(duration_2)

                        self.logger.warning(f"Headless (Proxy Retry) failed: {e2}")

                        return {
                            "success": False,
                            "error": f"Proxy Retry Failed: {str(e2)}",
                            "content": None,
                            "duration": duration_attempt_1 + duration_2,
                        }

            # If we are here, retries exhausted or failed.
            return {
                "success": False,
                "error": str(e),
                "content": None,
                "duration": duration_attempt_1,
            }

    def _perform_actions(self, page: Any, allowed_actions: list[str]) -> None:
        """Executes limited user interactions."""
        # TODO: Implement scrolling, consent clicking based on allowed_actions
        # For now, minimal implementation
        if "scroll" in allowed_actions:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)  # Wait for lazy load
            except Exception:  # noqa: S110
                pass

        if "consent_click" in allowed_actions:
            # Heuristic for common consent buttons
            try:
                # Try typical selectors
                for selector in [
                    "button[id*='cookie']",
                    "button[class*='cookie']",
                    "button:has-text('Accept')",
                ]:
                    if page.is_visible(selector):
                        page.click(selector)
                        page.wait_for_timeout(500)
                        break
            except Exception:  # noqa: S110
                pass
