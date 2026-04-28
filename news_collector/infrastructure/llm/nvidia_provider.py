"""
NVIDIA NIM Provider — OpenAI-compatible API.

Provides the same interface as OllamaProvider and GeminiProvider so the
factory can swap providers transparently.

Rate-limit aware:
- Integrates with LLMRateLimiter for concurrency control.
- Distinguishes 429 from other errors; feeds circuit breaker.
- Never logs the API key.
"""

import json
import random
import re
import time
from typing import Any, Dict, Generator, Optional, Union

import httpx
import requests
from news_collector.infrastructure.llm.rate_limiter import (
    LLMRateLimiter,
    parse_retry_after,
    redact_message,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.nvidia_provider")

_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_CHAT_COMPLETIONS_PATH = "/chat/completions"

# Model names that belong to Ollama (local) and must be replaced by the
# configured NVIDIA model when the NVIDIA provider is active.
_OLLAMA_MODEL_INDICATORS = ("llama", "qwen", "mistral", "phi", "gemma", "deepseek")


class RateLimitError(Exception):
    """Raised when the provider returns 429 and the circuit breaker is open."""

    def __init__(
        self,
        message: str = "LLM rate limit exceeded",
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after


class NvidiaProvider:
    """
    Unified client for the NVIDIA NIM API (OpenAI-compatible).

    Features:
    - Sync & Async methods (same interface as GeminiProvider / OllamaProvider)
    - Robust JSON extraction
    - Streaming support (SSE)
    - Configurable timeouts & retries
    - Rate-limiter integration (concurrency + circuit breaker)
    - API key is never emitted to logs
    """

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        base_url: str = _NVIDIA_BASE_URL,
        timeout: int = 300,
        max_retries: int = 3,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.model = model or "nvidia/qwen3-next-80b-a3b-thinking"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens

        self._endpoint_url = f"{self.base_url}{_CHAT_COMPLETIONS_PATH}"
        self.async_client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.async_client.aclose()

    # ---- Model helpers ----

    def _resolve_model(self, model: Optional[str]) -> str:
        """
        Return the NVIDIA model to use.

        If the caller passes an Ollama-style model (e.g. ``qwen2.5:32b``) or
        any model that clearly targets a local backend, fall back to
        ``self.model`` so the NVIDIA endpoint always receives a valid model ID.
        """
        if model:
            lower = model.lower()
            is_ollama_local = any(ind in lower for ind in _OLLAMA_MODEL_INDICATORS)
            has_ollama_tag = ":" in model  # e.g. "qwen2.5:32b"
            if is_ollama_local or has_ollama_tag:
                return self.model
            return model
        return self.model

    # ---- Request helpers ----

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self._resolve_model(model),
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    # ---- Retry helpers ----

    @staticmethod
    def _backoff_delay(
        attempt: int, base: float = 2.0, cap: float = 30.0, jitter: float = 2.0
    ) -> float:
        delay = min(cap, base * (2.0**attempt))
        return delay + random.uniform(0, jitter)  # noqa: S311

    @staticmethod
    def _is_429(exc: BaseException) -> bool:
        return (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
        ) or (
            isinstance(exc, requests.HTTPError)
            and exc.response is not None
            and exc.response.status_code == 429
        )

    @staticmethod
    def _get_retry_after_from_exc(exc: BaseException) -> Optional[float]:
        resp = getattr(exc, "response", None)
        if resp is None:
            return None
        header = None
        if isinstance(resp, httpx.Response):
            header = resp.headers.get("retry-after")
        elif isinstance(resp, requests.Response):
            header = resp.headers.get("Retry-After")
        return parse_retry_after(header)

    # ---- Response helpers ----

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return message.get("content", "") or ""

    @staticmethod
    def _try_parse_json_dict(candidate: str) -> tuple[bool, Dict[str, Any]]:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return False, {}
        if isinstance(parsed, dict):
            return True, {str(k): v for k, v in parsed.items()}
        return True, {}

    @staticmethod
    def _extract_braced_segment(text: str) -> Optional[str]:
        start_idx = text.find("{")
        if start_idx == -1:
            return None
        nesting = 0
        for i, char in enumerate(text[start_idx:], start=start_idx):
            if char == "{":
                nesting += 1
            elif char == "}":
                nesting -= 1
            if nesting == 0:
                return text[start_idx : i + 1]
        return None

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Robust JSON extraction from mixed text."""
        text = text.strip()
        ok, parsed = self._try_parse_json_dict(text)
        if ok:
            return parsed
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            ok, parsed = self._try_parse_json_dict(match.group(0))
            if ok:
                return parsed
        segment = self._extract_braced_segment(text)
        if segment:
            ok, parsed = self._try_parse_json_dict(segment)
            if ok:
                return parsed
        logger.warning("Failed to extract JSON from NVIDIA response: {}...", text[:100])
        return {}

    # ---- ASYNC API ----

    async def generate_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[str, Dict[str, Any]]:
        use_timeout = timeout or self.timeout
        payload = self._prepare_payload(prompt, system, json_mode, stream=False, model=model)
        use_model = payload["model"]

        limiter = LLMRateLimiter.get_instance()

        for attempt_num in range(1, self.max_retries + 1):
            acquired = await limiter.acquire_async()
            if not acquired:
                raise RateLimitError("LLM circuit breaker is open — skipping request")

            try:
                logger.debug(
                    "Sending async prompt to NVIDIA NIM ({}) (timeout={}s, attempt={}/{})",
                    use_model,
                    use_timeout,
                    attempt_num,
                    self.max_retries,
                )
                start = time.time()
                async_client = httpx.AsyncClient(timeout=use_timeout)
                try:
                    response = await async_client.post(
                        self._endpoint_url,
                        headers=self._auth_headers(),
                        json=payload,
                        timeout=use_timeout,
                    )
                    response.raise_for_status()
                finally:
                    await async_client.aclose()

                data = response.json()
                text = self._extract_text(data)

                logger.debug(
                    "Async NVIDIA NIM complete in {:.2f}s", time.time() - start
                )
                limiter.circuit_breaker.record_success()

                if json_mode:
                    return self._extract_json(text)
                return text

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                safe_msg = redact_message(str(e))
                is_rate_limit = self._is_429(e)

                if is_rate_limit:
                    retry_after = self._get_retry_after_from_exc(e)
                    limiter.circuit_breaker.record_rate_limit(retry_after)
                    logger.warning(
                        "NVIDIA NIM 429 (attempt {}/{}): {}",
                        attempt_num,
                        self.max_retries,
                        safe_msg,
                    )
                    if (
                        attempt_num < self.max_retries
                        and not limiter.circuit_breaker.is_open
                    ):
                        delay = retry_after or self._backoff_delay(attempt_num)
                        await __import__("asyncio").sleep(delay)
                        continue
                    raise RateLimitError(safe_msg, retry_after=retry_after) from e
                else:
                    limiter.circuit_breaker.record_error()
                    logger.error(
                        "Async NVIDIA NIM error (attempt {}/{}): {}",
                        attempt_num,
                        self.max_retries,
                        safe_msg,
                    )
                    if attempt_num < self.max_retries:
                        delay = self._backoff_delay(attempt_num)
                        await __import__("asyncio").sleep(delay)
                        continue
                    raise
            finally:
                limiter.release_async()

        raise RuntimeError("Async retry loop exited without producing a response")

    # ---- SYNC API ----

    def generate_sync(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        log_errors_as_warning: bool = False,
    ) -> Union[str, Dict[str, Any], Generator[str, None, None]]:
        use_timeout = timeout or self.timeout
        payload = self._prepare_payload(
            prompt, system, json_mode, stream=stream, model=model
        )
        use_model = payload["model"]

        from news_collector.config import settings

        if not settings.LLM_SYSTEM_AVAILABLE:
            raise ValueError("LLM System is marked as unavailable (Disabled).")

        limiter = LLMRateLimiter.get_instance()

        for attempt_num in range(1, self.max_retries + 1):
            acquired = limiter.acquire_sync()
            if not acquired:
                raise RateLimitError("LLM circuit breaker is open — skipping request")

            try:
                logger.debug(
                    "Sending sync prompt to NVIDIA NIM ({}) (timeout={}s, attempt={}/{})",
                    use_model,
                    use_timeout,
                    attempt_num,
                    self.max_retries,
                )
                response = requests.post(
                    self._endpoint_url,
                    headers=self._auth_headers(),
                    json=payload,
                    stream=stream,
                    timeout=use_timeout,
                )
                response.raise_for_status()

                if stream:
                    return self._stream_generator(response)

                data = response.json()
                text = self._extract_text(data)

                limiter.circuit_breaker.record_success()

                if json_mode:
                    return self._extract_json(text)
                return text

            except requests.RequestException as e:
                safe_msg = redact_message(str(e))
                is_rate_limit = self._is_429(e)

                if is_rate_limit:
                    retry_after = self._get_retry_after_from_exc(e)
                    limiter.circuit_breaker.record_rate_limit(retry_after)
                    log_fn = logger.warning
                else:
                    limiter.circuit_breaker.record_error()
                    log_fn = logger.warning if log_errors_as_warning else logger.error

                log_fn(
                    "Sync NVIDIA NIM {} (attempt {}/{}): {}",
                    "429" if is_rate_limit else "error",
                    attempt_num,
                    self.max_retries,
                    safe_msg,
                )

                if is_rate_limit and limiter.circuit_breaker.is_open:
                    raise RateLimitError(safe_msg, retry_after=retry_after) from e

                if attempt_num < self.max_retries:
                    delay = (
                        retry_after or self._backoff_delay(attempt_num)
                        if is_rate_limit
                        else self._backoff_delay(attempt_num)
                    )
                    time.sleep(delay)
                    continue
                raise
            finally:
                limiter.release_sync()

        raise RuntimeError("Retry loop exited without producing a response")

    def check_health(self, timeout_seconds: float = 5.0) -> tuple[bool, str]:
        """
        Lightweight health probe: list available models.
        Returns (ok, status_string).
        """
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._auth_headers(),
                timeout=timeout_seconds,
            )
            if response.status_code == 200:
                return True, "ok"
            return False, f"http_{response.status_code}"
        except requests.RequestException as exc:
            return False, redact_message(str(exc))

    def _stream_generator(
        self, response: requests.Response
    ) -> Generator[str, None, None]:
        """Parse an SSE stream from NVIDIA NIM (OpenAI-style)."""
        for line in response.iter_lines():
            if isinstance(line, bytes):
                line_str = line.decode("utf-8")
            else:
                line_str = line
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue
