import unittest
from unittest.mock import MagicMock

from news_collector.editorial.classifier import EditorialClassifier


class TestEditorialClassifier(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.classifier = EditorialClassifier(llm_client=self.mock_llm)

    def test_classify_returns_valid_category(self):
        self.mock_llm.generate_sync.return_value = "SALUD"
        result = self.classifier.classify_article("Title", "Summary about health")
        self.assertEqual(result, "SALUD")

    def test_classify_cleans_output(self):
        self.mock_llm.generate_sync.return_value = "  tecnología. "
        result = self.classifier.classify_article("Title", "Tech stuff")
        self.assertEqual(result, "TECNOLOGÍA")

    def test_classify_fallback_on_invalid(self):
        self.mock_llm.generate_sync.return_value = "FOOBAR"
        result = self.classifier.classify_article("Title", "Summary")
        self.assertEqual(result, "CIENCIA")

    def test_classify_fallback_on_none(self):
        self.mock_llm.generate_sync.return_value = None
        result = self.classifier.classify_article("Title", "Summary")
        self.assertEqual(result, "CIENCIA")

    def test_classify_fallback_on_error(self):
        self.mock_llm.generate_sync.side_effect = Exception("Boom")
        result = self.classifier.classify_article("Title", "Summary")
        self.assertEqual(result, "CIENCIA")


if __name__ == "__main__":
    unittest.main()
