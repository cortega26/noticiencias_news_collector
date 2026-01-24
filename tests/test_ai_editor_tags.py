import os
import sys
import unittest
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath("/home/cortega26/noticiencias_news_collector"))

# Now import
try:
    from news_collector.components.editorial.ai_editor import EditorAgent
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)


class TestEditorAgentTags(unittest.TestCase):
    def setUp(self):
        self.agent = EditorAgent(api_url="http://mock", model="mock")
        self.agent.provider = MagicMock()
        self.agent._send_prompt = MagicMock(return_value="Dummy content")
        self.agent._extract_json = MagicMock(return_value={"direct": "Title"})
        # Mock min_content_length to avoid validation error
        self.agent.min_content_length = 0

    def test_other_category_filtered(self):
        raw_text = {
            "title": "Test Article",
            "content": "Some content",
            "id": "123",
            "metadata": {"category": "other"},
        }

        # Mock file operations to avoid writing to disk
        self.agent._get_cache_path = MagicMock()
        self.agent._get_cache_path.return_value.exists.return_value = False
        self.agent._get_cache_path.return_value.write_text = MagicMock()

        result = self.agent.process_article(raw_text)

        # Check that tags list is empty
        self.assertIn("tags: []", result)
        self.assertNotIn('tags: ["other"]', result)

    def test_valid_category_kept(self):
        raw_text = {
            "title": "Test Article",
            "content": "Some content",
            "id": "123",
            "metadata": {"category": "AI"},
        }

        self.agent._get_cache_path = MagicMock()
        self.agent._get_cache_path.return_value.exists.return_value = False

        result = self.agent.process_article(raw_text)

        # Check that AI tag is present
        self.assertIn('tags: ["AI"]', result)


if __name__ == "__main__":
    unittest.main()
