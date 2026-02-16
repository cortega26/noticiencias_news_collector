
import pytest
from unittest.mock import MagicMock, patch
from news_collector.enrichment.router import EnrichmentStrategyRouter
from news_collector.enrichment.headless_enricher import HeadlessBudgetManager, HeadlessEnricher

@pytest.fixture
def mock_logger():
    logger = MagicMock()
    factory = MagicMock()
    factory.create_module_logger.return_value = logger
    return logger, factory

class TestHeadlessActivation:

    def setup_method(self):
        # Reset singleton budget
        HeadlessBudgetManager._instance = None
        self.budget = HeadlessBudgetManager()
        self.budget.reset()

    def test_budget_enforcement(self, mock_logger):
        logger, factory = mock_logger
        
        # 1. Configure for low budget
        with patch.dict('os.environ', {
            'ENABLE_HEADLESS': 'true', 
            'HEADLESS_MAX_SOURCES_PER_RUN': '2',
            'HEADLESS_MAX_TOTAL_SECONDS_PER_RUN': '10'
        }):
            self.budget.reset()
            enricher = HeadlessEnricher(logger_factory=factory)
            
            # 2. Consume budget
            # Attempt 1 (Allowed)
            assert self.budget.can_attempt() is True
            self.budget.record_usage(5.0) # 5s used
            
            # Attempt 2 (Allowed)
            assert self.budget.can_attempt() is True
            self.budget.record_usage(5.0) # 10s used (limit reached for time)
            
            # Attempt 3 (Blocked by Time)
            assert self.budget.can_attempt() is False
            
            # Reset and test Source Limit
            self.budget.reset()
            self.budget.record_usage(0.1)
            self.budget.record_usage(0.1) # 2 sources used
            assert self.budget.can_attempt() is False # Limit is 2

    def test_logger_propagation(self, mock_logger):
        logger, factory = mock_logger
        
        with patch.dict('os.environ', {'ENABLE_HEADLESS': 'true'}):
            # Init Router with factory
            router = EnrichmentStrategyRouter(logger_factory=factory)
            
            # Verification:
            # 1. Router has logger
            assert router.logger == logger
            # 2. HeadlessEnricher has logger
            assert router.headless.logger == logger
            
            # 3. Trigger log event
            router.route_enrichment("test_source", {}, {"url": ""})
            # Should disable -> log info "skipped" or similar
            # Actually empty URL returns early, let's try valid URL with disabled headless config
            
            router.route_enrichment("test", {"headless_enabled": False, "enrichment_strategy": "headless_fallback"}, {"url": "http://test.com"})
            
            # Check if specific event logged
            # We look for the structured dict
            args, _ = logger.info.call_args
            assert args[0]['event'] == 'enrichment.headless.skipped'

    def test_http_first_contract(self, mock_logger):
        logger, factory = mock_logger
        
        with patch.dict('os.environ', {'ENABLE_HEADLESS': 'true'}):
            router = EnrichmentStrategyRouter(logger_factory=factory)
            router.http = MagicMock()
            router.headless = MagicMock()
            
            # Case 1: HTTP Success (Long content) -> Headless NOT called
            router.http.enrich.return_value = {"success": True, "content": "x" * 1000}
            
            router.route_enrichment(
                "source", 
                {"enrichment_strategy": "headless_fallback", "headless_enabled": True}, 
                {"url": "http://test.com"}
            )
            
            router.http.enrich.assert_called_once()
            router.headless.enrich.assert_not_called()
            
            # Case 2: HTTP Fail -> Headless Called
            router.http.reset_mock()
            router.http.enrich.return_value = {"success": False}
            router.headless.enrich.return_value = {"success": True, "content": "Headless Content"}
            
            router.route_enrichment(
                "source", 
                {"enrichment_strategy": "headless_fallback", "headless_enabled": True}, 
                {"url": "http://test.com"}
            )
            
            router.http.enrich.assert_called_once()
            router.headless.enrich.assert_called_once()

if __name__ == "__main__":
    pytest.main([__file__])
