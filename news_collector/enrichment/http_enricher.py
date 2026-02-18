"""HTTP Enricher module for standard HTML fetching and extraction."""

import logging
from typing import Dict, Any, Optional

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from news_collector.infrastructure.requests_client import RobustRequestsClient

logger = logging.getLogger(__name__)

class HttpEnricher:
    """
    Enriches articles by fetching HTML via standard HTTP and extracting text.
    """

    def __init__(self, request_client: Optional[RobustRequestsClient] = None):
        self.client = request_client or RobustRequestsClient()

    def enrich(self, url: str) -> Dict[str, Any]:
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
        try:
            response = self.client.get(url, timeout=15)
            
            if response.status_code >= 400:
                return {
                    "success": False,
                    "content": None,
                    "error": f"HTTP {response.status_code}",
                    "status_code": response.status_code
                }

            html_content = response.text
            if not html_content:
                 return {
                    "success": False,
                    "content": None,
                    "error": "Empty response body",
                    "status_code": response.status_code
                }

            # Text Extraction
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Remove noise
            for script in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe", "svg"]):
                script.decompose()

            text = soup.get_text(separator=" ", strip=True)
            
            # Basic cleanup (could be moved to a util if shared)
            text = " ".join(text.split())

            return {
                "success": True,
                "content": text,
                "raw_content": html_content,
                "error": None,
                "status_code": response.status_code
            }

        except requests.RequestException as e:
            logger.warning(f"HttpEnricher fetch failed for {url}: {e}")
            return {
                "success": False,
                "content": None,
                "raw_content": None,
                "error": str(e),
                "status_code": getattr(e.response, "status_code", None) if e.response else None
            }
        except Exception as e:
            logger.error(f"HttpEnricher unexpected error for {url}: {e}")
            return {
                "success": False,
                "content": None,
                "raw_content": None,
                "error": f"Unexpected: {str(e)}",
                "status_code": None
            }
