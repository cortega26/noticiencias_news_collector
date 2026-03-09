"""
Synchronous HTTP Client for News Collector.
Wraps requests.Session with retries, timeouts, and fail-fast logic for 403s.
"""

import logging
import secrets
import time
from typing import Any, Dict, Optional

import requests
from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from news_collector.utils.security import validate_url_safety
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def _is_retryable_error(exception: BaseException) -> bool:
    """
    Determines if an exception should trigger a retry.
    Returns True for transient errors (5xx, timeouts).
    Returns False for permanent errors (403 Forbidden, 404 Not Found, SSRF).
    """
    if not isinstance(exception, requests.RequestException):
        return False

    # Check for HTTP Status Codes
    response = getattr(exception, "response", None)
    if response is not None:
        status = response.status_code
        # Fail fast on 403 (Forbidden) and 404 (Not Found)
        if status in (403, 404, 401, 410):
            return False
        # Retry on Server Errors (5xx)
        if 500 <= status < 600:
            return True
        # Retry on Rate Limit (429) - though we usually handle this with sleeps,
        # tenacity can help if we miss the header.
        if status == 429:
            return True

    # Retry on specific Request errors (Connection, Timeout)
    # Retry on specific Request errors (Connection, Timeout)
    return isinstance(
        exception, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    )


def _redact_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safely copies and denies-lists sensitive headers for logging.
    """
    if not headers:
        return {}
    safe = headers.copy()
    sensitive_keys = {"authorization", "cookie", "x-api-key", "token"}
    for key in headers:
        if key.lower() in sensitive_keys:
            safe[key] = "[REDACTED]"
    return safe


def _safe_retry_log(retry_state):
    """
    Custom before_sleep callback that avoids logging sensitive headers.
    """
    if retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        verb = "Retrying"

        # Extract URL and Status if possible, but keep headers out
        details = ""
        if isinstance(exc, requests.RequestException):
            request = getattr(exc, "request", None)
            response = getattr(exc, "response", None)
            if request:
                details += f" {request.method} {request.url}"
            if response is not None:
                details += f" (Status: {response.status_code})"

        logger.warning(
            f"{verb} {retry_state.fn.__name__} in {retry_state.next_action.sleep}s "
            f"due to: {exc!r}.{details}"
        )


class SSRFSafeSession(requests.Session):
    """
    Hardened requests.Session that intercepts adapter selection
    to validate SSRF constraints on every physical connection attempt,
    including implicit cross-host redirects.
    """
    def __init__(self):
        super().__init__()
        import threading
        self._local = threading.local()

    def set_ignore_ssrf(self, ignore: bool):
        self._local.ignore_ssrf = ignore

    def get_adapter(self, url):
        # We hook here because it is guaranteed to execute right before every HTTP request,
        # perfectly catching any down-chain 3xx redirects to a new host.
        ignore = getattr(self._local, "ignore_ssrf", False)
        if not ignore:
            validate_url_safety(url)
        return super().get_adapter(url)


class RobustRequestsClient:
    """
    Synchronous HTTP Client that enforces:
    1. Browser-like Headers (User-Agent rotation)
    2. Fail-Fast on 403/404
    3. Automatic Retries for transient errors
    4. SSRF Protection validation
    """

    def __init__(self, timeout: float = 30.0):
        self.session = SSRFSafeSession()
        self.timeout = timeout
        self._configure_session()

    def _configure_session(self):
        """Sets up headers and adapters."""
        # Rotation (simple selection at init)
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        base_ua = secrets.choice(user_agents)
        bot_identifier = f"NoticienciasBot/1.0 (+{COLLECTION_CONFIG.get('contact_email', 'admin@noticiencias.com')})"
        final_ua = f"{base_ua} {bot_identifier}"

        self.session.headers.update(
            {
                "User-Agent": final_ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )

        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            # We handle retries via tenacity, but requests adapter can handle some connection resets
            max_retries=0,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @retry(
        stop=stop_after_attempt(RATE_LIMITING_CONFIG.get("max_retries", 3)),
        wait=wait_exponential(
            multiplier=RATE_LIMITING_CONFIG.get("backoff_base", 0.5),
            min=1,
            max=RATE_LIMITING_CONFIG.get("backoff_max", 10.0),
        ),
        retry=retry_if_exception(_is_retryable_error),
        # re-raise exception after retries exhaustion
        reraise=True,
        before_sleep=_safe_retry_log,
    )
    def _execute_request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        proxies: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """
        Internal method that executes the request with strict retry logic.
        """
        req_timeout = timeout or self.timeout

        # Merge local headers if provided without overwriting defaults completely
        request_headers = dict(self.session.headers)
        if headers:
            request_headers.update(headers)

        response = self.session.get(
            url,
            params=params,
            headers=request_headers,
            timeout=req_timeout,
            allow_redirects=True,
            proxies=proxies,
        )

        # Raise for status to trigger retry logic or fail-fast logic
        response.raise_for_status()

        return response

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        ignore_ssrf: bool = False,
        source_config: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """
        Executes GET request with safety checks, retries, and Proxy Fallback.
        """
        self.session.set_ignore_ssrf(ignore_ssrf)
        try:
            # 1. Try Direct Connection
            try:
                return self._execute_request(url, params, headers, timeout)
            except Exception as e:
                # 2. Check Proxy Eligibility
                if not source_config:
                    raise e

            from news_collector.infrastructure.proxy_manager import proxy_manager

            response = getattr(e, "response", None)

            if proxy_manager.should_retry_with_proxy(
                source_config, error=e, response=response
            ):
                proxy_settings = proxy_manager.get_proxy_settings(source_config)

                if proxy_settings:
                    logger.info(
                        {
                            "event": "proxy.attempt",
                            "details": {
                                "url": url,
                                "source_id": source_config.get("name", "unknown"),
                                "reason": str(e),
                            },
                        }
                    )

                    start_time = time.time()
                    try:
                        # Retry with proxy
                        # We use _execute_request again, but tenacity might retry *proxied* requests too, which is desired.
                        resp = self._execute_request(
                            url, params, headers, timeout, proxies=proxy_settings
                        )

                        duration = time.time() - start_time
                        source_id = source_config.get("name") if source_config else None
                        proxy_manager.record_usage(duration, source_id=source_id)

                        logger.info(
                            {
                                "event": "proxy.success",
                                "details": {"url": url, "duration": duration},
                            }
                        )
                        return resp

                    except Exception as proxy_err:
                        duration = time.time() - start_time
                        source_id = source_config.get("name") if source_config else None
                        proxy_manager.record_usage(
                            duration, source_id=source_id
                        )  # Record usage even on failure

                        logger.warning(
                            {
                                "event": "proxy.failed",
                                "details": {
                                    "url": url,
                                    "error": str(proxy_err),
                                    "duration": duration,
                                },
                            }
                        )
                        # Fall through to re-raise original error or proxy error?
                        # Usually better to raise the proxy error if that was the last attempt,
                        # OR raise the original if proxy was just a fallback that didn't work.
                        # Given strict requirements, let's raise the proxy error as it's the most recent state.
                        raise proxy_err

            # If not eligible or proxy failed logic, re-raise original
            raise e
        finally:
            self.session.set_ignore_ssrf(False)

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
