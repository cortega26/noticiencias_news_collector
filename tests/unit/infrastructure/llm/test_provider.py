import os
import unittest
from unittest.mock import MagicMock, patch

from news_collector.infrastructure.llm.ollama_errors import OllamaAdmissionError
from news_collector.infrastructure.llm.provider import OllamaProvider


class TestOllamaProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._env_patcher = patch.dict(
            os.environ,
            {
                "NOTICIENCIAS_LLM_STRICT": "0",
                "NOTICIENCIAS_LLM_PINNED": "0",
                "NOTICIENCIAS_LLM_NO_WARN": "0",
            },
            clear=False,
        )
        self._env_patcher.start()
        self.provider = OllamaProvider(timeout=1)

    def tearDown(self):
        self._env_patcher.stop()

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

            result = await self.provider.generate_async("Hi", model="test-model")
            self.assertEqual(result, "Hello World")
            mock_post.assert_called_once()

    def test_extract_json_robust(self):
        # 1. Clean JSON
        self.assertEqual(self.provider._extract_json('{"a": 1}'), {"a": 1})
        # 2. Markdown wrapped
        self.assertEqual(
            self.provider._extract_json('Here is code: ```json\n{"b": 2}\n```'),
            {"b": 2},
        )
        # 3. Nested
        self.assertEqual(
            self.provider._extract_json('Intro {"c": {"d": 3}} Outro'), {"c": {"d": 3}}
        )
        # 4. Fail
        self.assertEqual(self.provider._extract_json("No json here"), {})

    @patch("requests.post")
    @patch("news_collector.config.settings.LLM_SYSTEM_AVAILABLE", True)
    def test_generate_sync(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Sync Hello", "done": True}
        mock_post.return_value = mock_resp

        result = self.provider.generate_sync("Hi", model="test-model")
        self.assertEqual(result, "Sync Hello")

    @patch("news_collector.infrastructure.llm.provider.time.sleep")
    @patch("requests.post")
    @patch("news_collector.config.settings.LLM_SYSTEM_AVAILABLE", True)
    def test_generate_sync_raises_non_retryable_admission_error(
        self, mock_post, _mock_sleep
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {
            "error": "model requires more system memory (19.1 GiB) than is available (1.0 GiB)"
        }
        mock_resp.text = '{"error":"model requires more system memory (19.1 GiB) than is available (1.0 GiB)"}'
        mock_post.return_value = mock_resp

        with self.assertRaises(OllamaAdmissionError) as excinfo:
            self.provider.generate_sync("Hi", model="qwen2.5:32b")

        self.assertIn("requires more system memory", str(excinfo.exception))
        self.assertEqual(mock_post.call_count, 1)

    @patch("news_collector.infrastructure.llm.provider.time.sleep")
    @patch("requests.post")
    @patch("news_collector.config.settings.LLM_SYSTEM_AVAILABLE", True)
    def test_generate_sync_retries_transient_http_500(self, mock_post, _mock_sleep):
        transient_resp = MagicMock()
        transient_resp.status_code = 500
        transient_resp.json.return_value = {"error": "temporary backend failure"}
        transient_resp.text = '{"error":"temporary backend failure"}'

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"response": "Recovered", "done": True}

        mock_post.side_effect = [transient_resp, success_resp]

        result = self.provider.generate_sync("Hi", model="test-model")

        self.assertEqual(result, "Recovered")
        self.assertEqual(mock_post.call_count, 2)

    @patch("requests.get")
    def test_check_health(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        ok, reason = self.provider.check_health(timeout_seconds=1.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


class TestFallbackProvider(unittest.IsolatedAsyncioTestCase):
    def test_extract_json_delegates(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_provider = MagicMock()
        mock_provider._extract_json.return_value = {"key": "value"}

        fallback = FallbackProvider([mock_provider])
        result = fallback._extract_json('{"key": "value"}')

        self.assertEqual(result, {"key": "value"})
        mock_provider._extract_json.assert_called_once_with('{"key": "value"}')

    def test_generate_sync_timeout_delegation(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        captured_timeouts = {}

        mock_p1 = MagicMock()
        mock_p1.timeout = 300

        def side_effect_p1(*args, **kwargs):
            captured_timeouts["p1"] = mock_p1.timeout
            raise Exception("failed")

        mock_p1.generate_sync.side_effect = side_effect_p1

        mock_p2 = MagicMock()
        mock_p2.timeout = 3600

        def side_effect_p2(*args, **kwargs):
            captured_timeouts["p2"] = mock_p2.timeout
            return "success"

        mock_p2.generate_sync.side_effect = side_effect_p2

        fallback = FallbackProvider([mock_p1, mock_p2])
        result = fallback.generate_sync("hello")

        self.assertEqual(result, "success")
        # Check that mock_p1 was called with timeout 60
        self.assertEqual(captured_timeouts.get("p1"), 60)
        # Check that mock_p2 was called with timeout 3600 (not 60!)
        self.assertEqual(captured_timeouts.get("p2"), 3600)
        # Check that timeouts were restored
        self.assertEqual(mock_p1.timeout, 300)
        self.assertEqual(mock_p2.timeout, 3600)

    async def test_generate_async_timeout_delegation(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        captured_timeouts = {}

        mock_p1 = MagicMock()
        mock_p1.timeout = 300

        async def mock_async_fail(*args, **kwargs):
            captured_timeouts["p1"] = mock_p1.timeout
            raise Exception("failed")

        mock_p1.generate_async = mock_async_fail

        mock_p2 = MagicMock()
        mock_p2.timeout = 3600

        async def mock_async_success(*args, **kwargs):
            captured_timeouts["p2"] = mock_p2.timeout
            return "success"

        mock_p2.generate_async = mock_async_success

        fallback = FallbackProvider([mock_p1, mock_p2])
        result = await fallback.generate_async("hello")

        self.assertEqual(result, "success")
        # Check that mock_p1 was called with timeout 60
        self.assertEqual(captured_timeouts.get("p1"), 60)
        # Check that mock_p2 was called with timeout 3600 (not 60!)
        self.assertEqual(captured_timeouts.get("p2"), 3600)
        # Check that timeouts were restored
        self.assertEqual(mock_p1.timeout, 300)
        self.assertEqual(mock_p2.timeout, 3600)


if __name__ == "__main__":
    unittest.main()
