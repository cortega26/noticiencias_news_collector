"""Scrapling-based enrichers for hard-to-scrape sources.

Two strategies:
- ScraplingHttpEnricher  → uses Fetcher (curl_cffi, TLS fingerprinting, no browser)
  Suitable for sites that block plain httpx but not real-browser TLS stacks.
- ScraplingEnricher      → uses StealthyFetcher (Patchright browser, anti-bot full suite)
  Suitable for sites with Cloudflare, heavy JS, or aggressive bot detection.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Mapping, Optional

try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
except ImportError:
    Fetcher = None  # type: ignore[assignment,misc]
    StealthyFetcher = None  # type: ignore[assignment,misc]

from news_collector.enrichment.headless_enricher import budget_manager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class ScraplingEnricher:
    """
    Enriches articles using Scrapling's StealthyFetcher (Patchright/anti-bot).

    Shares the HeadlessBudgetManager with HeadlessEnricher so both paths
    count against the same per-run headless budget.
    """

    def __init__(self, logger_factory=None):
        self.enabled = os.getenv("ENABLE_HEADLESS", "false").lower() == "true"
        self.logger = (
            logger_factory.create_module_logger("enrichment.scrapling")
            if logger_factory
            else get_logger().create_module_logger(__name__)
        )

        if self.enabled and StealthyFetcher is None:
            self.logger.error(
                "Scrapling enabled but scrapling[fetchers] not installed."
            )
            self.enabled = False

    def _execute_enrich(
        self,
        url: str,
        source_config: Dict[str, Any],
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        max_duration = source_config.get("headless_max_seconds", 30)

        if StealthyFetcher is None:
            raise RuntimeError("scrapling[fetchers] is not installed")

        start_time = time.time()
        content = None
        raw_content = None

        fetch_kwargs: Dict[str, Any] = {
            "headless": True,
            "solve_cloudflare": True,
            "block_webrtc": True,
            "hide_canvas": True,
            "network_idle": True,
            "timeout": max_duration * 1000,  # milliseconds
            "disable_resources": True,  # skip images/fonts for speed
        }
        if proxy:
            fetch_kwargs["proxy"] = proxy

        page = StealthyFetcher.fetch(url, **fetch_kwargs)

        raw_content = (
            page.body
            if isinstance(page.body, str)
            else page.body.decode("utf-8", errors="replace")
        )

        text = page.get_all_text(separator=" ", strip=True)
        content = " ".join(text.split())  # normalize whitespace

        duration = time.time() - start_time
        return {
            "success": True,
            "content": content,
            "raw_content": raw_content,
            "error": None,
            "duration": duration,
        }

    def enrich(  # noqa: C901
        self, url: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "scrapling_disabled", "content": None}

        if not budget_manager.can_attempt():
            return {
                "success": False,
                "error": "headless_budget_exhausted",
                "content": None,
            }

        from news_collector.infrastructure.proxy_manager import proxy_manager

        proxy: Optional[str] = None
        if (
            source_config.get("proxy_mode") == "force"
            and proxy_manager.budget_manager.can_afford()
        ):
            proxy_settings: Optional[Mapping[str, str]] = (
                proxy_manager.get_proxy_settings(source_config)
            )
            if proxy_settings:
                proxy = proxy_settings.get("http")

        start_time = time.time()

        try:
            result = self._execute_enrich(url, source_config, proxy)
            budget_manager.record_usage(result["duration"])
            if proxy:
                proxy_manager.record_usage(result["duration"])
                self.logger.info(
                    {
                        "event": "enrichment.scrapling.proxy.success",
                        "details": {"url": url},
                    }
                )
            return result

        except Exception as e:
            duration_attempt_1 = time.time() - start_time
            budget_manager.record_usage(duration_attempt_1)

            if proxy:
                proxy_manager.record_usage(duration_attempt_1)
                self.logger.warning(f"Scrapling (proxy) failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "content": None,
                    "duration": duration_attempt_1,
                }

            if (
                proxy_manager.should_retry_with_proxy(source_config, error=e)
                and budget_manager.can_attempt()
                and proxy_manager.budget_manager.can_afford()
            ):
                proxy_settings = proxy_manager.get_proxy_settings(source_config)
                if proxy_settings:
                    retry_proxy = proxy_settings.get("http")
                    self.logger.info(
                        {
                            "event": "enrichment.scrapling.proxy.attempt",
                            "details": {"url": url, "reason": str(e)},
                        }
                    )
                    start_retry = time.time()
                    try:
                        result2 = self._execute_enrich(url, source_config, retry_proxy)
                        budget_manager.record_usage(result2["duration"])
                        proxy_manager.record_usage(result2["duration"])
                        return result2
                    except Exception as e2:
                        dur2 = time.time() - start_retry
                        budget_manager.record_usage(dur2)
                        proxy_manager.record_usage(dur2)
                        self.logger.warning(f"Scrapling (proxy retry) failed: {e2}")
                        return {
                            "success": False,
                            "error": f"Proxy retry failed: {e2}",
                            "content": None,
                            "duration": duration_attempt_1 + dur2,
                        }

            self.logger.error(
                {
                    "event": "enrichment.scrapling.failed",
                    "details": {"url": url, "error": str(e)},
                }
            )
            return {
                "success": False,
                "error": str(e),
                "content": None,
                "duration": duration_attempt_1,
            }


class ScraplingHttpEnricher:
    """
    Lightweight HTTP enricher using Scrapling's Fetcher (curl_cffi + TLS fingerprinting).

    No browser — just an HTTP client that presents a real-browser TLS fingerprint.
    Fixes sources blocked by TLS fingerprint checks (e.g. openai.com) without the
    overhead of launching Patchright. Does NOT count against the headless budget.
    """

    def __init__(self, logger_factory=None):
        self.enabled = Fetcher is not None
        self.logger = (
            logger_factory.create_module_logger("enrichment.scrapling_http")
            if logger_factory
            else get_logger().create_module_logger(__name__)
        )
        if not self.enabled:
            self.logger.error(
                "ScraplingHttpEnricher: scrapling[fetchers] not installed."
            )

    def enrich(self, url: str, source_config: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "success": False,
                "error": "scrapling_not_installed",
                "content": None,
            }

        timeout = source_config.get("headless_max_seconds", 30)
        start = time.time()
        try:
            page = Fetcher.get(url, timeout=timeout, follow_redirects=True)
            text = str(page.get_all_text(separator=" ", strip=True))
            content = " ".join(text.split())
            duration = time.time() - start
            return {
                "success": page.status < 400,
                "content": content,
                "raw_content": (
                    page.body
                    if isinstance(page.body, str)
                    else page.body.decode("utf-8", errors="replace")
                ),
                "error": None if page.status < 400 else f"http_{page.status}",
                "duration": duration,
            }
        except Exception as e:
            self.logger.error(
                {
                    "event": "enrichment.scrapling_http.failed",
                    "details": {"url": url, "error": str(e)},
                }
            )
            return {
                "success": False,
                "error": str(e),
                "content": None,
                "duration": time.time() - start,
            }
