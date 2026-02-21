import os
import sys
import unittest

# Add project root to path
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(
    os.environ.get("NEWS_COLLECTOR_PATH", Path(__file__).resolve().parents[1])
).resolve()
sys.path.insert(0, str(BASE_DIR))

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
        self.agent._critic_pass = MagicMock(return_value=(True, None))
        self.agent._generate_headlines = MagicMock(
            return_value={
                "direct": "Direct Headline",
                "question": "Question Headline?",
                "benefit": "Benefit Headline",
                "excerpt": "This is a short excerpt for SEO purposes that is long enough.",
            }
        )

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

        # Parse YAML
        import re

        import yaml

        match = re.search(r"^---\n(.*?)\n---", result, re.DOTALL)
        assert match, "Frontmatter not found"
        fm = yaml.safe_load(match.group(1))

        # Check tags list is empty
        self.assertEqual(fm.get("tags"), [])

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

        # Parse YAML
        import re

        import yaml

        match = re.search(r"^---\n(.*?)\n---", result, re.DOTALL)
        assert match, "Frontmatter not found"
        fm = yaml.safe_load(match.group(1))

        # Check tag matches semantic term "inteligencia artificial" OR "AI" depending on normalizer
        # Since we can't easily mock normalizer unless we mock import,
        # we check if ONE of expected values is present.
        # Actually, if normalizer is not mocked, it uses real logic?
        # The test does not mock normalizer import.
        # So it uses real TagNormalizer.
        # Assuming "AI" -> "inteligencia artificial".

        tags = fm.get("tags", [])
        assert len(tags) > 0
        # Check loosely
        assert "inteligencia artificial" in tags or "AI" in tags


if __name__ == "__main__":
    unittest.main()
