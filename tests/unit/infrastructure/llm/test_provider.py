import unittest
from unittest.mock import MagicMock, patch
import json
import httpx
from news_collector.infrastructure.llm.provider import OllamaProvider

import asyncio

class TestOllamaProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = OllamaProvider(timeout=1)

    async def asyncTearDown(self):
        await self.provider.close()

    async def test_generate_async_text(self):
        with patch("httpx.AsyncClient.post") as mock_post:
            # Mock response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "Hello World", "done": True}
            mock_resp.raise_for_status.return_value = None
            
            # Proper async mock
            async def get_response(*args, **kwargs):
                return mock_resp
            mock_post.side_effect = get_response

            result = await self.provider.generate_async("Hi")
            self.assertEqual(result, "Hello World")
            mock_post.assert_called_once()

    def test_extract_json_robust(self):
        # 1. Clean JSON
        self.assertEqual(self.provider._extract_json('{"a": 1}'), {"a": 1})
        # 2. Markdown wrapped
        self.assertEqual(self.provider._extract_json('Here is code: ```json\n{"b": 2}\n```'), {"b": 2})
        # 3. Nested
        self.assertEqual(self.provider._extract_json('Intro {"c": {"d": 3}} Outro'), {"c": {"d": 3}})
        # 4. Fail
        self.assertEqual(self.provider._extract_json('No json here'), {})

    @patch("requests.post")
    def test_generate_sync(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Sync Hello", "done": True}
        mock_post.return_value = mock_resp
        
        result = self.provider.generate_sync("Hi")
        self.assertEqual(result, "Sync Hello")

if __name__ == "__main__":
    unittest.main()
