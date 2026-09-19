"""HTTP Enricher module for standard HTML fetching and extraction."""

import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from news_collector.infrastructure.requests_client import RobustRequestsClient
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _is_smoke_mode_enabled() -> bool:
    return os.getenv("NOTICIENCIAS_SMOKE", "").strip().lower() in _TRUTHY_VALUES


def is_undecodable(text: str, sample: int = 2000, threshold: float = 0.02) -> bool:
    """True when decoded text is mostly control/replacement chars (a body the
    HTTP layer failed to decompress, e.g. brotli without the codec)."""
    head = text[:sample]
    if not head:
        return False
    bad = sum(1 for ch in head if ord(ch) < 9 or 13 < ord(ch) < 32 or ch == "\ufffd")
    return bad / len(head) > threshold


class HttpEnricher:
    """
    Enriches articles by fetching HTML via standard HTTP and extracting text.
    """

    def __init__(self, request_client: Optional[RobustRequestsClient] = None):
        self.client = request_client or RobustRequestsClient()
        self._blocked_urls: set[str] = set()
        self._warned_block_hosts: set[str] = set()

    def _log_fetch_failure(
        self, url: str, error: Exception, status: Optional[int]
    ) -> None:
        """Warn once per blocking host (403/429); later failures go to DEBUG."""
        host = urlparse(url).netloc
        if status in (403, 429):
            if host in self._warned_block_hosts:
                logger.debug(f"HttpEnricher fetch failed for {url}: {error}")
                return
            self._warned_block_hosts.add(host)
        logger.warning(f"HttpEnricher fetch failed for {url}: {error}")

    @staticmethod
    def _www_fallback_url(url: str, error: Exception) -> Optional[str]:
        """Apex hosts with a broken cert chain (e.g. caltech.edu) work on www."""
        if not isinstance(error, requests.exceptions.SSLError):
            return None
        parts = urlparse(url)
        if not parts.netloc or parts.netloc.startswith("www."):
            return None
        return parts._replace(netloc=f"www.{parts.netloc}").geturl()

    def enrich(  # noqa: C901
        self, url: str, _allow_www_fallback: bool = True
    ) -> Dict[str, Any]:
        """
        Fetches the URL and extracts main content.

        Returns:
            dict: {
                "success": bool,
                "content": str | None,
                "error": str | None,
                "status_code": int | None
            }
        """
        if url in self._blocked_urls:
            return {
                "success": False,
                "content": None,
                "error": "HTTP 403",
                "status_code": 403,
            }

        try:
            response = self.client.get(url, timeout=15)

            if response.status_code == 403:
                self._blocked_urls.add(url)
                return {
                    "success": False,
                    "content": None,
                    "error": "HTTP 403",
                    "status_code": 403,
                }

            if response.status_code >= 400:
                return {
                    "success": False,
                    "content": None,
                    "error": f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                }

            html_content = response.text
            if not html_content:
                return {
                    "success": False,
                    "content": None,
                    "error": "Empty response body",
                    "status_code": response.status_code,
                }

            if is_undecodable(html_content):
                # Fail (instead of storing garbage) so fallback strategies run.
                return {
                    "success": False,
                    "content": None,
                    "raw_content": None,
                    "error": "undecodable_content",
                    "status_code": response.status_code,
                }

            # Text Extraction
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove noise
            for script in soup(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "aside",
                    "noscript",
                    "iframe",
                    "svg",
                ]
            ):
                script.decompose()

            text = soup.get_text(separator=" ", strip=True)

            # Basic cleanup (could be moved to a util if shared)
            text = " ".join(text.split())

            return {
                "success": True,
                "content": text,
                "raw_content": html_content,
                "error": None,
                "status_code": response.status_code,
            }

        except requests.RequestException as e:
            # Response is falsy on 4xx/5xx, so compare against None implicitly.
            fallback_url = self._www_fallback_url(url, e)
            if fallback_url and _allow_www_fallback:
                return self.enrich(fallback_url, _allow_www_fallback=False)
            status = getattr(e.response, "status_code", None)
            self._log_fetch_failure(url, e, status)
            return {
                "success": False,
                "content": None,
                "raw_content": None,
                "error": str(e),
                "status_code": status,
            }
        except ValueError as e:
            # URL safety validation errors (e.g., relative URLs) are expected inputs,
            # not runtime faults.
            if _is_smoke_mode_enabled():
                logger.warning(f"HttpEnricher skipped invalid URL for {url}: {e}")
            else:
                logger.error(f"HttpEnricher invalid URL for {url}: {e}")
            return {
                "success": False,
                "content": None,
                "raw_content": None,
                "error": f"Unexpected: {str(e)}",
                "status_code": None,
            }
        except Exception as e:
            logger.error(f"HttpEnricher unexpected error for {url}: {e}")
            return {
                "success": False,
                "content": None,
                "raw_content": None,
                "error": f"Unexpected: {str(e)}",
                "status_code": None,
            }
