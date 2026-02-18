"""
Unified HTTP Client for News Collector.
Centralizes configuration, rate limiting, SSRF protection, and retries.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from news_collector.utils.security import validate_url_safety
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class SmartHttpClient:
    """
    Async HTTP Client that enforces:
    1. SSRF Protection (DNS validation)
    2. Rate Limiting (Non-blocking sleeps)
    3. Automatic Retries (Tenacity)
    4. Consistent Timeouts & Headers
    """

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ):
        self._base_headers = {
            "User-Agent": COLLECTION_CONFIG.get("user_agent", "NoticienciasBot/1.0"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if headers:
            self._base_headers.update(headers)

        self.timeout = timeout or COLLECTION_CONFIG.get("request_timeout", 30.0)

        # Configure limits closer to what AsyncRSSCollector used
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=50)

        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers=self._base_headers,
            timeout=self.timeout,
            limits=limits,
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        ignore_ssrf: bool = False,
    ) -> httpx.Response:
        """
        Executes GET request with safety checks and retries.
        """
        if not ignore_ssrf:
            await self._validate_ssrf(url)

        return await self._get_with_retry(url, params, headers)

    @retry(
        stop=stop_after_attempt(RATE_LIMITING_CONFIG.get("max_retries", 3)),
        wait=wait_exponential(
            multiplier=RATE_LIMITING_CONFIG.get("backoff_base", 0.5),
            min=1,
            max=RATE_LIMITING_CONFIG.get("backoff_max", 10.0),
        ),
        retry=retry_if_exception_type(
            (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError)
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        try:
            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            # Don't retry 404s or 403s typically, but retry 5xx
            if e.response.status_code in (404, 403, 400, 422):
                raise  # Let caller handle, don't retry permanent errors
            raise  # Retry 500s via decorator

    async def _validate_ssrf(self, url: str):
        """
        Runs blocking DNS validation in a thread to avoid freezing the loop.
        """
        try:
            await asyncio.to_thread(validate_url_safety, url)
        except ValueError as e:
            logger.error(f"SSRF Blocked: {e}")
            raise httpx.RequestError(f"SSRF Blocked: {e}") from e

    async def safe_fetch_text(self, url: str) -> Optional[str]:
        """
        High-level helper to fetch text content, handling errors gracefully.
        Returns None on failure instead of raising.
        """
        try:
            resp = await self.get(url)
            return resp.text
        except Exception as e:
            logger.warning(f"Fetch failed for {url}: {e}")
            return None
