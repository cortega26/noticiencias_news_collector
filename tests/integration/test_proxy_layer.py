import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from news_collector.infrastructure.proxy_manager import ProxyManager
from news_collector.infrastructure.requests_client import RobustRequestsClient


class TestProxyLayer:

    @pytest.fixture
    def mock_env(self):
        with patch.dict(
            os.environ,
            {
                "ENABLE_PROXY": "true",
                "PROXY_URL_DEFAULT": "http://user:pass@proxy.com:8080",
                "PROXY_MAX_TOTAL_REQUESTS_PER_RUN": "10",
            },
        ):
            # Reload config on the EXISTING Singleton
            # Do NOT reset _instance = None, as other modules hold references to the original instance
            pm = ProxyManager.get_instance()
            pm.reload_config()

            # Also reset Budget
            # BudgetManager is also a singleton conceptually but implemented via class variable _instance checks in __new__
            # If we want to verify budget, we should reset it
            pm.budget_manager.reset()

            yield

            # Cleanup - maybe optional if we rely on reload
            # But let's leave it clean
            pm.reload_config()  # Reloads with original env (patched context ends) - wait, patch ends outside yield
            # Actually just yield is enough if patch handles env var restoration,
            # but we need to trigger reload_config after patch exit?
            # Ideally yes, but for tests usually fine.
            # Better:
            # pm.reload_config() called here will see PATCHED env.
            # We want to restore to ORIGINAL env.
            # patch context manager restores os.environ.
            # But ProxyManager still holds PATCHED values until reload_config is called again.

        # After patch context exit:
        ProxyManager.get_instance().reload_config()

    @pytest.fixture
    def proxy_manager(self, mock_env):
        return ProxyManager.get_instance()

    def test_proxy_policy_heuristics(self, proxy_manager):
        """Test intelligent retry logic."""
        # 1. Auto mode + 403 = Retry
        config = {"proxy_mode": "auto", "name": "test_src"}
        response_403 = requests.Response()
        response_403.status_code = 403

        assert (
            proxy_manager.should_retry_with_proxy(config, response=response_403) is True
        )

        # 2. Auto mode + 200 = No Retry
        response_200 = requests.Response()
        response_200.status_code = 200
        assert (
            proxy_manager.should_retry_with_proxy(config, response=response_200)
            is False
        )

        # 3. Off mode + 403 = No Retry
        config_off = {"proxy_mode": "off", "name": "test_src"}
        assert (
            proxy_manager.should_retry_with_proxy(config_off, response=response_403)
            is False
        )

        # 4. Force mode + No Error = Retry
        config_force = {"proxy_mode": "force", "name": "test_src"}
        assert proxy_manager.should_retry_with_proxy(config_force) is True

        # 5. Network Error = Retry
        # Use full namespace to avoid UnboundLocalError with global imports
        err_conn = requests.exceptions.ConnectionError("Connection refused")
        assert proxy_manager.should_retry_with_proxy(config, error=err_conn) is True

    def test_proxy_budget_enforcement(self, proxy_manager):
        """Test budget limits."""
        proxy_manager.budget_manager.max_requests = 1

        config = {"proxy_mode": "force", "name": "test"}

        # First check allowed
        assert proxy_manager.budget_manager.can_afford() is True

        # Record usage
        proxy_manager.record_usage(1.0)

        # Now exhausted
        assert proxy_manager.budget_manager.can_afford() is False
        assert proxy_manager.should_retry_with_proxy(config) is False
        assert proxy_manager.get_proxy_settings(config) is None

    @patch("news_collector.infrastructure.requests_client.validate_url_safety")
    def test_requests_client_integration(self, mock_validate, proxy_manager):
        """Test RobustRequestsClient retries with proxy."""
        with patch("requests.Session.get") as mock_get:
            client = RobustRequestsClient()
            url = "http://blockedsite.com"
            config = {"name": "blocked_source", "proxy_mode": "auto"}

            # Setup:
            # 1. First call -> 403 Forbidden
            # 2. Second call -> 200 OK (Simulated Proxy Success)

            resp_403 = requests.Response()
            resp_403.status_code = 403

            resp_200 = requests.Response()
            resp_200.status_code = 200
            resp_200._content = b"Success"

            # Note: RobustRequestsClient uses tenacity which retries.
            # But get() catches exception and calls _execute_request again with proxy.
            # We need to ensure _execute_request raises for 403 first time.

            mock_get.side_effect = [resp_403, resp_200]

    @patch("news_collector.enrichment.headless_enricher.sync_playwright")
    def test_headless_enricher_integration(self, mock_playwright, proxy_manager):
        """Test HeadlessEnricher uses proxy when appropriate."""
        from news_collector.enrichment.headless_enricher import (
            HeadlessEnricher,
            budget_manager,
        )

        # Setup mocks
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.inner_text.return_value = "Mock Content"
        mock_page.content.return_value = "<html>Mock Content</html>"

        # Configure Enriched
        enricher = HeadlessEnricher()
        enricher.enabled = True

        # Reset budget
        budget_manager.reset()
        proxy_manager.budget_manager.reset()

        # Case 1: Proxy Force Mode -> Should launch with proxy immediately
        url = "http://forceproxy.com"
        config = {
            "name": "force_source",
            "proxy_mode": "force",
            "headless_allowed_actions": [],
        }

        enricher.enrich(url, config)

        # Verify launch called with proxy
        # We expect 1 launch call
        assert mock_p.chromium.launch.call_count >= 1
        args, kwargs = mock_p.chromium.launch.call_args
        assert "proxy" in kwargs
        assert kwargs["proxy"]["server"] == "http://user:pass@proxy.com:8080"

        # Case 2: Auto Mode + Failure -> Retry with Proxy
        # Reset mocks
        mock_p.chromium.launch.reset_mock()

        # First call raises Exception (simulating timeout or block)
        # Second call succeeds

        # We need to simulate the _execute_enrich behavior.
        # Since we are mocking playwright, we need to make the first context/page fail?
        # Or better, we can assume _execute_enrich calls launch.

        # Let's start a fresh enricher/budget to be clean
        budget_manager.reset()
        proxy_manager.budget_manager.reset()

        config_auto = {
            "name": "auto_source",
            "proxy_mode": "auto",
            "headless_allowed_actions": [],
        }

        # We want the FIRST launch to be normal (no proxy), and fail (detected by enrich catching exception)
        # We want the SECOND launch to be with proxy.

        # To simulate failure in _execute_enrich, we can make page.goto raise an exception?
        # But _execute_enrich creates a NEW context/page each time.

        # Side effect for page.goto: First time raise Error, Second time succeed
        mock_page.goto.side_effect = [Exception("Timeout"), None]

        enricher.enrich("http://automode.com", config_auto)

        # Verify calls
        # Expected: 2 launches.
        # 1. No proxy
        # 2. With proxy

        assert mock_p.chromium.launch.call_count == 2

        calls = mock_p.chromium.launch.call_args_list
        call1_kwargs = calls[0].kwargs
        call2_kwargs = calls[1].kwargs

        assert "proxy" not in call1_kwargs  # Attempt 1
        assert "proxy" in call2_kwargs  # Attempt 2
        assert call2_kwargs["proxy"]["server"] == "http://user:pass@proxy.com:8080"
