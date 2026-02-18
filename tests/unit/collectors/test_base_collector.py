from unittest.mock import MagicMock, patch

from news_collector.collectors.base_collector import BaseCollector


class ConcreteCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {"success": True}

    def _create_session(self):
        pass


def test_base_collector_init():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        logger_mock = MagicMock()
        c = ConcreteCollector(logger_factory=logger_mock)
        assert c.collector_type == "ConcreteCollector"


def test_normalization():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        c = ConcreteCollector(logger_factory=MagicMock())
        # Assuming BaseCollector DOES NOT have simple URL normalization public method
        # If it doesn't, we can skip or test _clean_text which uses normalization
        assert c._clean_text("  foo  ") == "foo"
