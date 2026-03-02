from unittest.mock import MagicMock

from news_collector.logic.workflows.refinery_engine import RefineryEngine


def test_log():
    engine = RefineryEngine(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    invalid_article = {"id": "123"}
    engine.process_single_article(invalid_article, MagicMock(), MagicMock())


test_log()
