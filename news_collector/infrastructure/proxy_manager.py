"""
Proxy Manager Module.

Handles proxy configuration, pool selection (Residential/Datacenter),
budget enforcement, and retry eligibility heuristics.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class ProxyBudgetManager:
    """Tracks global usage of proxy resources per process execution."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProxyBudgetManager, cls).__new__(cls)
            cls._instance.reset()
        return cls._instance

    def reset(self):
        self.requests_attempted = 0
        self.total_seconds_used = 0.0
        # Default limits: 0 (disabled) or specific values
        self.max_requests = int(os.getenv("PROXY_MAX_TOTAL_REQUESTS_PER_RUN", "50"))
        # Using a high default for time if not set, as requests count is primary cost driver
        self.max_total_seconds = float(
            os.getenv("PROXY_MAX_TOTAL_SECONDS_PER_RUN", "600")
        )

    def can_afford(self) -> bool:
        """Checks if budget allows for another proxy request."""
        if self.requests_attempted >= self.max_requests:
            return False
        return not self.total_seconds_used >= self.max_total_seconds

    def record_usage(self, duration: float):
        """Records a completed proxy request."""
        self.requests_attempted += 1
        self.total_seconds_used += duration


class ProxyManager:
    """
    Manages proxy usage policies and provider selection.
    """

    _instance = None

    def __init__(self):
        self.budget_manager = ProxyBudgetManager()
        self.reload_config()

    def reload_config(self):
        """Reloads configuration from environment variables."""
        self._enabled = os.getenv("ENABLE_PROXY", "false").lower() == "true"
        self.provider = os.getenv("PROXY_PROVIDER", "generic")
        self.fail_open = os.getenv("PROXY_FAIL_OPEN", "false").lower() == "true"

        # Load Pool URLs
        self.proxies = {}
        self.proxies["default"] = os.getenv("PROXY_URL_DEFAULT")
        self.proxies["residential"] = os.getenv("PROXY_URL_RESIDENTIAL")
        self.proxies["datacenter"] = os.getenv("PROXY_URL_DATACENTER")

        # Fallback
        if self.proxies["default"] and not self.proxies["residential"]:
            self.proxies["residential"] = self.proxies["default"]
        if self.proxies["default"] and not self.proxies["datacenter"]:
            self.proxies["datacenter"] = self.proxies["default"]

        self.budget_manager.reset()

    @property
    def enabled(self):
        # Always re-check for testing overrides, but mainly rely on init state
        return self._enabled

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ProxyManager()
        return cls._instance

    def should_retry_with_proxy(
        self,
        source_config: Dict[str, Any],
        error: Optional[Exception] = None,
        response: Optional[Any] = None,
    ) -> bool:
        """
        Determines if a request should be retried via proxy.

        Args:
            source_config: Source configuration dict (from sources.yaml)
            error: The exception caught (Response/ConnectionError)
            response: The requests.Response object (if available)

        Returns:
            bool: True if proxy retry is recommended and allowed.
        """
        if not self.enabled:
            return False

        # 1. Check Source Policy
        proxy_mode = source_config.get("proxy_mode", "auto").lower()
        if proxy_mode == "off":
            return False

        # 2. Check Budget
        if not self.budget_manager.can_afford():
            return False

        # 3. Analyze Error/Response (Heuristics)
        # Force mode overrides heuristics
        if proxy_mode == "force":
            return True

        should_retry = False
        reason = "unknown"

        # Check StatusCode (403, 429, 503 often mean blocking/throttling)
        if response is not None and response.status_code in [403, 429, 503]:
            should_retry = True
            reason = f"status_{response.status_code}"

        # Check Exception (Connection Refused, Timeout, Reset)
        if error:
            # Converting to string to check simple patterns if specific types aren't available
            err_str = str(error).lower()
            if (
                "connect" in err_str
                or "timeout" in err_str
                or "refused" in err_str
                or "reset" in err_str
            ):
                should_retry = True
                reason = "network_error"

        if should_retry:
            logger.info(f"Proxy retry triggered: {reason}")
            return True

        return False

    def get_proxy_settings(
        self, source_config: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """
        Returns the requests-compatible proxy dictionary for a given source.

        Returns:
            dict: {"http": url, "https": url} or None
        """
        if not self.enabled:
            return None

        if not self.budget_manager.can_afford():
            logger.warning("Proxy request blocked: Budget Exhausted")
            return None

        pool_name = source_config.get("proxy_pool", "default")
        proxy_url = self.proxies.get(pool_name) or self.proxies.get("default")

        if not proxy_url:
            if self.fail_open:
                logger.warning(
                    f"Proxy enabled but no URL found for pool '{pool_name}'. Failing open."
                )
                return None
            else:
                logger.error(
                    f"Proxy required but missing configuration for pool '{pool_name}'"
                )
                return None

        return {"http": proxy_url, "https": proxy_url}

    def record_usage(self, duration: float, source_id: Optional[str] = None):
        """Records usage (success or failure) to decrement budget."""
        self.budget_manager.record_usage(duration)
        if source_id:
            from news_collector.observability.enrichment_metrics_store import (
                enrichment_metrics,
            )

            enrichment_metrics.record_cost(source_id, proxy_requests=1)


# Global Accessor
proxy_manager = ProxyManager.get_instance()
