import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_init_empty_providers_raises(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        with self.assertRaises(ValueError):
            FallbackProvider([])

    def test_generate_sync_stream_buffers_chunks(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        def stream_side_effect(*args, **kwargs):
            yield "chunk1"
            yield "chunk2"

        mock_p1 = MagicMock()
        mock_p1.timeout = 300
        mock_p1.generate_sync.side_effect = stream_side_effect

        fallback = FallbackProvider([mock_p1])
        result = fallback.generate_sync("hello", stream=True)

        self.assertEqual(list(result), ["chunk1", "chunk2"])
        self.assertEqual(mock_p1.timeout, 300)

    def test_generate_sync_stream_error_restores_timeout_and_raises(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        def broken_stream(*args, **kwargs):
            yield "chunk1"
            raise RuntimeError("mid-stream failure")

        mock_p1 = MagicMock()
        mock_p1.timeout = 300
        mock_p1.generate_sync.side_effect = broken_stream

        fallback = FallbackProvider([mock_p1])
        with self.assertRaises(RuntimeError):
            fallback.generate_sync("hello", stream=True)

        self.assertEqual(mock_p1.timeout, 300)

    def test_generate_sync_all_fail_raises_last_error(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_p1 = MagicMock()
        mock_p1.timeout = 300
        mock_p1.generate_sync.side_effect = RuntimeError("p1 failed")

        mock_p2 = MagicMock()
        mock_p2.timeout = 300
        mock_p2.generate_sync.side_effect = RuntimeError("p2 failed")

        fallback = FallbackProvider([mock_p1, mock_p2])
        with self.assertRaisesRegex(RuntimeError, "p2 failed"):
            fallback.generate_sync("hello")

        self.assertEqual(mock_p1.timeout, 300)

    def test_generate_sync_no_usable_providers_raises_runtime_error(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        class DegradedProvider:
            def is_degraded(self) -> bool:
                return True

            def generate_sync(self, *args, **kwargs):
                raise AssertionError("should not be called")

        fallback = FallbackProvider([DegradedProvider(), DegradedProvider()])
        with self.assertRaisesRegex(RuntimeError, "no active providers"):
            fallback.generate_sync("hello")

    async def test_generate_async_all_fail_raises_last_error(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        async def async_fail(*args, **kwargs):
            raise TimeoutError("p1 timed out")

        mock_p1 = MagicMock()
        mock_p1.timeout = 300
        mock_p1.generate_async = async_fail

        mock_p2 = MagicMock()
        mock_p2.timeout = 300
        mock_p2.generate_async = async_fail

        fallback = FallbackProvider([mock_p1, mock_p2])
        with self.assertRaises(TimeoutError):
            await fallback.generate_async("hello")

        self.assertEqual(mock_p1.timeout, 300)

    async def test_generate_async_no_usable_providers_raises_runtime_error(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        class DegradedAsyncProvider:
            def is_degraded(self) -> bool:
                return True

            async def generate_async(self, *args, **kwargs):
                raise AssertionError("should not be called")

        fallback = FallbackProvider([DegradedAsyncProvider(), DegradedAsyncProvider()])
        with self.assertRaisesRegex(RuntimeError, "no active providers"):
            await fallback.generate_async("hello")

    def test_check_health_delegates(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_provider = MagicMock()
        mock_provider.check_health.return_value = (True, "ok")

        fallback = FallbackProvider([mock_provider])
        self.assertEqual(fallback.check_health(), (True, "ok"))
        mock_provider.check_health.assert_called_once_with(2.0)

    def test_list_models_delegates(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_provider = MagicMock()
        mock_provider.list_models.return_value = ["model-a", "model-b"]

        fallback = FallbackProvider([mock_provider])
        self.assertEqual(fallback.list_models(), ["model-a", "model-b"])

    def test_check_model_exists_delegates_when_supported(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_provider = MagicMock()
        mock_provider.check_model_exists.return_value = True

        fallback = FallbackProvider([mock_provider])
        self.assertTrue(fallback.check_model_exists("some-model"))
        mock_provider.check_model_exists.assert_called_once_with("some-model")

    def test_check_model_exists_defaults_true_when_unsupported(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        class MinimalProvider:
            model = "test-model"

        fallback = FallbackProvider([MinimalProvider()])
        self.assertTrue(fallback.check_model_exists("some-model"))

    async def test_close_closes_providers_with_close(self):
        from news_collector.infrastructure.llm.factory import FallbackProvider

        mock_p1 = AsyncMock()
        mock_p1.timeout = 300

        class MinimalProvider:
            model = "test-model"

        fallback = FallbackProvider([mock_p1, MinimalProvider()])
        await fallback.close()
        mock_p1.close.assert_awaited_once()


class TestGetProvider(unittest.TestCase):
    def setUp(self):
        self._rate_limiter_patcher = patch(
            "news_collector.infrastructure.llm.rate_limiter.LLMRateLimiter"
        )
        self._mock_limiter_cls = self._rate_limiter_patcher.start()
        self._mock_limiter_cls._instance = None
        self._mock_limiter_cls.get_instance.side_effect = lambda cfg: None

    def tearDown(self):
        self._rate_limiter_patcher.stop()

    def test_get_provider_cloud_model_falls_back_to_ollama_default(self):
        from news_collector.infrastructure.llm import factory as factory_module

        cfg = SimpleNamespace(
            nvidia=SimpleNamespace(api_key=None),
            gemini=SimpleNamespace(api_key=None),
            ollama=SimpleNamespace(
                model="qwen2.5:32b", api_url="http://localhost:11434"
            ),
            llm_rate_limiting=None,
        )

        with patch.object(factory_module, "OllamaProvider") as mock_ollama_cls:
            mock_ollama_instance = MagicMock()
            mock_ollama_cls.return_value = mock_ollama_instance

            provider = factory_module.get_provider(model="gemini-2.5-flash", config=cfg)

            mock_ollama_cls.assert_called_once()
            _, kwargs = mock_ollama_cls.call_args
            self.assertEqual(kwargs["model"], "qwen2.5:32b")
            self.assertIs(provider, mock_ollama_instance)

    def test_get_provider_returns_ollama_when_single_provider(self):
        from news_collector.infrastructure.llm import factory as factory_module

        cfg = SimpleNamespace(
            n=SimpleNamespace(api_key=None),
            gemini=SimpleNamespace(api_key=None),
            ollama=SimpleNamespace(
                model="qwen2.5:32b", api_url="http://localhost:11434"
            ),
        )

        with patch.object(factory_module, "load_config") as mock_load_config:
            mock_load_config.return_value = MagicMock()
            with patch.object(factory_module, "OllamaProvider") as mock_ollama_cls:
                mock_ollama_instance = MagicMock()
                mock_ollama_cls.return_value = mock_ollama_instance
                provider = factory_module.get_provider(config=cfg)
            self.assertIs(provider, mock_ollama_instance)

    def test_ensure_rate_limiter_uses_default_config_when_rate_limiting_absent(self):
        from news_collector.infrastructure.llm import factory as factory_module
        from news_collector.infrastructure.llm.rate_limiter import LLMRateLimitConfig

        cfg = SimpleNamespace(
            nvidia=SimpleNamespace(api_key=None),
            gemini=SimpleNamespace(api_key=None),
            ollama=SimpleNamespace(
                model="qwen2.5:32b", api_url="http://localhost:11434"
            ),
        )

        with patch.object(
            factory_module.LLMRateLimiter, "get_instance"
        ) as mock_get_instance:
            with patch.object(
                factory_module.LLMRateLimiter, "_instance", None, create=True
            ):
                factory_module._ensure_rate_limiter(cfg)

            mock_get_instance.assert_called_once()
            created_cfg = mock_get_instance.call_args[0][0]
            self.assertIsInstance(created_cfg, LLMRateLimitConfig)


if __name__ == "__main__":

    unittest.main()
