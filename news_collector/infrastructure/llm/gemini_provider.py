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

logger = get_logger().create_module_logger("infrastructure.llm.gemini_provider")


class RateLimitError(Exception):
    """Raised when the provider returns 429 and the circuit breaker is open."""

    def __init__(
        self,
        message: str = "LLM rate limit exceeded",
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after


class GeminiProvider:
    """
    Unified client for Google AI Studio (Gemini) API.
    Provides identical interface to OllamaProvider.

    Rate-limit aware:
    - Integrates with LLMRateLimiter for concurrency control.
    - Distinguishes 429 from other errors; feeds circuit breaker.
    - Never logs the API key.
    """

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: int = 300,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.model = model or "gemini-2.5-flash"
        self.timeout = timeout
        self.max_retries = max_retries

        self._base_api_url = "https://generativelanguage.googleapis.com/v1beta"
        self.async_client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self.async_client.aclose()

    # ---- URL helpers (key never touches logs) ----

    def _endpoint_url(self, model: str, endpoint: str = "generateContent") -> str:
        return f"{self._base_api_url}/models/{model}:{endpoint}?key={self.api_key}"

    @staticmethod
    def _safe_model_name(model: str) -> str | None:
        """Strip Ollama-style tags and local model names before hitting Gemini."""
        if (
            "llama" in model.lower()
            or "qwen" in model.lower()
            or "mistral" in model.lower()
        ):
            return None  # caller should fall back to self.model
        if ":" in model:
            return model.split(":")[0]
        return model

    def _resolve_model(self, model: Optional[str]) -> str:
        if model:
            safe = self._safe_model_name(model)
            if safe:
                return safe
        safe = self._safe_model_name(self.model)
        return safe or self.model

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:

        contents = []
        if system:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {"text": f"System Instruction: {system}\n\nUser: {prompt}"}
                    ],
                }
            )
        else:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload: Dict[str, Any] = {"contents": contents, "generationConfig": {}}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
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

    # ---- ASYNC API ----

    async def generate_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[str, Dict[str, Any]]:

        use_model = self._resolve_model(model)
        use_timeout = timeout or self.timeout
        payload = self._prepare_payload(prompt, system, json_mode)
        url = self._endpoint_url(use_model)

        limiter = LLMRateLimiter.get_instance()

        for attempt_num in range(1, self.max_retries + 1):
            acquired = await limiter.acquire_async()
            if not acquired:
                raise RateLimitError("LLM circuit breaker is open — skipping request")

            try:
                logger.debug(
                    "Sending async prompt to Gemini ({}) (timeout={}s, attempt={}/{})",
                    use_model,
                    use_timeout,
                    attempt_num,
                    self.max_retries,
                )
                start = time.time()
                response = await self.async_client.post(
                    url, json=payload, timeout=use_timeout
                )
                response.raise_for_status()

                data = response.json()
                text = ""
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")

                logger.debug("Async Gemini complete in {:.2f}s", time.time() - start)

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
                        "Gemini 429 (attempt {}/{}): {}",
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
                        "Async Gemini error (attempt {}/{}): {}",
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

    def generate_sync(  # noqa: C901
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        log_errors_as_warning: bool = False,
    ) -> Union[str, Dict[str, Any], Generator[str, None, None]]:

        use_model = self._resolve_model(model)
        use_timeout = timeout or self.timeout
        payload = self._prepare_payload(prompt, system, json_mode)

        endpoint = "streamGenerateContent" if stream else "generateContent"
        url = self._endpoint_url(use_model, endpoint)
        if stream:
            url += "&alt=sse"

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
                    "Sending sync prompt to Gemini ({}) (timeout={}s, attempt={}/{})",
                    use_model,
                    use_timeout,
                    attempt_num,
                    self.max_retries,
                )
                response = requests.post(
                    url, json=payload, stream=stream, timeout=use_timeout
                )
                response.raise_for_status()

                if stream:
                    return self._stream_generator(response)

                data = response.json()
                text = ""
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")

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
                    "Sync Gemini {} (attempt {}/{}): {}",
                    "429" if is_rate_limit else "error",
                    attempt_num,
                    self.max_retries,
                    safe_msg,
                )

                if is_rate_limit and limiter.circuit_breaker.is_open:
                    raise RateLimitError(safe_msg, retry_after=retry_after) from e

                if attempt_num < self.max_retries:
                    if is_rate_limit:
                        delay = retry_after or self._backoff_delay(attempt_num)
                    else:
                        delay = self._backoff_delay(attempt_num)
                    time.sleep(delay)
                    continue
                raise
            finally:
                limiter.release_sync()

        raise RuntimeError("Retry loop exited without producing a response")

    def check_health(self, timeout_seconds: float = 5.0) -> tuple[bool, str]:
        url = f"{self._base_api_url}/models/{self.model}?key={self.api_key}"
        try:
            response = requests.get(url, timeout=timeout_seconds)
            if response.status_code == 200:
                return True, "ok"
            return False, f"http_{response.status_code}"
        except requests.RequestException as exc:
            return False, redact_message(str(exc))

    def _stream_generator(
        self, response: requests.Response
    ) -> Generator[str, None, None]:
        for line in response.iter_lines():
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = (
                            data["candidates"][0].get("content", {}).get("parts", [])
                        )
                        if parts:
                            yield parts[0].get("text", "")
                except json.JSONDecodeError:
                    continue

    # --- HELPERS ---

    @staticmethod
    def _try_parse_json_dict(candidate: str) -> tuple[bool, Dict[str, Any]]:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return False, {}
        if isinstance(parsed, dict):
            return True, {str(key): value for key, value in parsed.items()}
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
        parsed_ok, parsed_json = self._try_parse_json_dict(text)
        if parsed_ok:
            return parsed_json
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed_ok, parsed_json = self._try_parse_json_dict(match.group(0))
            if parsed_ok:
                return parsed_json
        bracket_segment = self._extract_braced_segment(text)
        if bracket_segment:
            parsed_ok, parsed_json = self._try_parse_json_dict(bracket_segment)
            if parsed_ok:
                return parsed_json
        logger.warning("Failed to extract JSON from: {}...", text[:100])
        return {}
