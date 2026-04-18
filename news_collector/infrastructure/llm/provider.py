"""
Unified Ollama Provider.
Replaces legacy llm_client.py and ai_editor.py logic.
Supports both Sync (legacy) and Async (pipeline) operations.

Rate-limit aware:
- Integrates with LLMRateLimiter for concurrency control.
- Distinguishes 429 from other errors; feeds circuit breaker.
"""

import json
import random
import re
import time
from typing import Any, Dict, Generator, Optional, Union

import httpx
import requests
from news_collector.infrastructure.llm.model_registry import (
    NonCanonicalModelIdError,
    canonicalize_model_id,
    is_no_warn_mode_enabled,
    is_strict_mode_enabled,
)
from news_collector.infrastructure.llm.ollama_errors import (
    OllamaProviderError,
    build_ollama_http_error,
)
from news_collector.infrastructure.llm.rate_limiter import (
    LLMRateLimiter,
    redact_message,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.provider")
_NON_CANONICAL_WARNED: set[tuple[str, str, str]] = set()


class RateLimitError(Exception):
    """Raised when the provider returns 429 and the circuit breaker is open."""

    def __init__(
        self,
        message: str = "LLM rate limit exceeded",
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after


class OllamaProvider:
    """
    Unified client for Ollama API.
    Features:
    - Sync & Async methods
    - Robust JSON extraction
    - Streaming support
    - Configurable timeouts & retries
    - Rate-limiter integration (concurrency + circuit breaker)
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 3600,
        max_retries: int = 2,  # Default 2 retries (3 attempts total)
    ):
        self.api_url = api_url or "http://127.0.0.1:11434/api/generate"
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

        if self.model is not None:
            raw_model = str(self.model)
            self.model = canonicalize_model_id(
                raw_model, stage="provider_default", logger=logger
            )
            self._warn_non_canonical(
                stage="provider_default",
                raw_value=raw_model,
                canonical_value=self.model,
            )

        # 2. API URL: Handle base vs endpoint mismatch
        clean_url = self.api_url.rstrip("/")
        if clean_url.endswith("/api/generate"):
            self.api_url = clean_url
        else:
            self.api_url = f"{clean_url}/api/generate"

        # Async client reused from infrastructure
        self.async_client = httpx.AsyncClient(timeout=timeout)

    def _base_url(self) -> str:
        return self.api_url.replace("/api/generate", "")

    async def close(self):
        await self.async_client.aclose()

    @staticmethod
    def _warn_non_canonical(
        *,
        stage: str,
        raw_value: str,
        canonical_value: str,
    ) -> None:
        if raw_value == canonical_value:
            return
        if is_no_warn_mode_enabled():
            raise NonCanonicalModelIdError(
                "NO_WARN mode forbids provider canonicalization for "
                f"{stage}: {raw_value!r} -> {canonical_value!r}. "
                "Pass a canonical '<model>:<tag>' from the registry."
            )
        if is_strict_mode_enabled():
            return
        key = (stage, raw_value, canonical_value)
        if key in _NON_CANONICAL_WARNED:
            return
        logger.warning(
            "Non-canonical Ollama model id in {}: '{}' -> '{}' (registry normalized).",
            stage,
            raw_value,
            canonical_value,
        )
        _NON_CANONICAL_WARNED.add(key)

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        stream: bool = False,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        use_model = model or self.model
        if use_model is None:
            raise ValueError(
                "Ollama model is not configured. Provide a model in config or pass model=..."
            )

        raw_model = str(use_model)
        use_model = canonicalize_model_id(
            raw_model, stage="provider_runtime_override", logger=logger
        )
        self._warn_non_canonical(
            stage="provider_runtime_override",
            raw_value=raw_model,
            canonical_value=use_model,
        )

        payload = {
            "model": use_model,
            "prompt": prompt,
            "stream": stream,
            # Increase context window so long editorial prompts don't get truncated.
            # 8192 comfortably fits ~2500 tokens of input + ~3000 tokens of article output.
            "options": {
                "num_ctx": 8192,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        return payload

    # ---- Retry helpers ----

    @staticmethod
    def _backoff_delay(
        attempt: int, base: float = 2.0, cap: float = 15.0, jitter: float = 1.5
    ) -> float:
        delay = min(cap, base * (2.0**attempt))
        return delay + random.uniform(0, jitter)  # noqa: S311

    @staticmethod
    def _is_429_response(response: requests.Response) -> bool:
        return OllamaProvider._response_status_code(response) == 429

    @staticmethod
    def _is_429_httpx(response: httpx.Response) -> bool:
        return OllamaProvider._response_status_code(response) == 429

    @staticmethod
    def _response_status_code(response: Any) -> int:
        raw_status = getattr(response, "status_code", 200)
        return raw_status if isinstance(raw_status, int) else 200

    # --- ASYNC API (Recommended) ---

    async def generate_async(  # noqa: C901
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """
        Async generation. Returns text or dict if json_mode is True.
        """
        payload = self._prepare_payload(
            prompt, system, stream=False, json_mode=json_mode, model=model
        )

        limiter = LLMRateLimiter.get_instance()

        for attempt_num in range(
            1, self.max_retries + 2
        ):  # max_retries + 1 total attempts
            acquired = await limiter.acquire_async()
            if not acquired:
                raise RateLimitError("LLM circuit breaker is open — skipping request")

            try:
                logger.debug(
                    "Sending async prompt to Ollama ({}) (attempt={}/{})",
                    payload["model"],
                    attempt_num,
                    self.max_retries + 1,
                )
                start = time.time()
                response = await self.async_client.post(
                    self.api_url, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("response", "")

                logger.debug("Async LLM complete in {:.2f}s", time.time() - start)

                limiter.circuit_breaker.record_success()

                if json_mode:
                    return self._extract_json(str(text))
                return str(text)

            except httpx.HTTPStatusError as e:
                if self._is_429_httpx(e.response):
                    safe_msg = redact_message(str(e))
                    limiter.circuit_breaker.record_rate_limit()
                    logger.warning("Ollama 429 (attempt {}): {}", attempt_num, safe_msg)
                    if (
                        attempt_num <= self.max_retries
                        and not limiter.circuit_breaker.is_open
                    ):
                        await __import__("asyncio").sleep(
                            self._backoff_delay(attempt_num)
                        )
                        continue
                    raise RateLimitError(safe_msg) from e

                provider_error = build_ollama_http_error(
                    e.response, model=str(payload["model"])
                )
                safe_msg = redact_message(str(provider_error))
                limiter.circuit_breaker.record_error()
                if not provider_error.retryable:
                    logger.error(
                        "Async Ollama non-retryable failure (attempt {}): {}",
                        attempt_num,
                        safe_msg,
                    )
                    raise provider_error from e

                logger.error("Async LLM error (attempt {}): {}", attempt_num, safe_msg)
                if attempt_num <= self.max_retries:
                    await __import__("asyncio").sleep(self._backoff_delay(attempt_num))
                    continue
                raise provider_error from e
            except httpx.RequestError as e:
                limiter.circuit_breaker.record_error()
                logger.error("Async LLM Request Error (attempt {}): {}", attempt_num, e)
                if attempt_num <= self.max_retries:
                    await __import__("asyncio").sleep(self._backoff_delay(attempt_num))
                    continue
                raise
            finally:
                limiter.release_async()

        raise RuntimeError("Async retry loop exited without producing a response")

    # --- SYNC API (Legacy/Compat) ---

    def generate_sync(  # noqa: C901
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
        log_errors_as_warning: bool = False,
    ) -> Union[str, Dict[str, Any], Generator[str, None, None]]:
        """
        Sync generation with configurable retries and rate-limiter integration.
        """
        payload = self._prepare_payload(
            prompt, system, stream=stream, json_mode=json_mode, model=model
        )

        # Fail fast if system marked LLM as unavailable (boot check)
        from news_collector.config import settings

        if not settings.LLM_SYSTEM_AVAILABLE:
            raise ValueError("LLM System is marked as unavailable (Disabled).")

        limiter = LLMRateLimiter.get_instance()

        for attempt_num in range(
            1, self.max_retries + 2
        ):  # max_retries + 1 total attempts
            acquired = limiter.acquire_sync()
            if not acquired:
                raise RateLimitError("LLM circuit breaker is open — skipping request")

            try:
                logger.debug(
                    "Sending sync prompt to Ollama ({}) at {} "
                    "(timeout={}s, attempt={}/{})",
                    payload["model"],
                    self.api_url,
                    self.timeout,
                    attempt_num,
                    self.max_retries + 1,
                )
                response = requests.post(
                    self.api_url, json=payload, stream=stream, timeout=self.timeout
                )

                # Check for 429 BEFORE raise_for_status so we can handle it specially
                if self._is_429_response(response):
                    limiter.circuit_breaker.record_rate_limit()
                    logger.warning(
                        "Ollama 429 (attempt {}/{})",
                        attempt_num,
                        self.max_retries + 1,
                    )
                    if (
                        attempt_num <= self.max_retries
                        and not limiter.circuit_breaker.is_open
                    ):
                        time.sleep(self._backoff_delay(attempt_num))
                        continue
                    raise RateLimitError(
                        f"Ollama returned 429 after {attempt_num} attempts"
                    )

                if self._response_status_code(response) >= 400:
                    provider_error = build_ollama_http_error(
                        response, model=str(payload["model"])
                    )
                    if not provider_error.retryable:
                        limiter.circuit_breaker.record_error()
                        safe_msg = redact_message(str(provider_error))
                        logger.error(
                            "Sync LLM Request Error (Attempt {}/{}): {}",
                            attempt_num,
                            self.max_retries + 1,
                            safe_msg,
                        )
                        raise provider_error
                    raise requests.HTTPError(str(provider_error), response=response)

                response.raise_for_status()

                if stream:
                    return self._stream_generator(response)

                # Non-streaming
                data = response.json()
                text = data.get("response", "")

                limiter.circuit_breaker.record_success()

                if json_mode:
                    return self._extract_json(str(text))
                return str(text)

            except RateLimitError:
                raise  # already handled above
            except requests.RequestException as e:
                limiter.circuit_breaker.record_error()
                response_error: OllamaProviderError | None = None
                error_response = getattr(e, "response", None)
                if error_response is not None:
                    response_error = build_ollama_http_error(
                        error_response, model=str(payload["model"])
                    )
                    if not response_error.retryable:
                        safe_msg = redact_message(str(response_error))
                        logger.error(
                            "Sync LLM Request Error (Attempt {}/{}): {}",
                            attempt_num,
                            self.max_retries + 1,
                            safe_msg,
                        )
                        raise response_error from e

                safe_msg = redact_message(
                    str(response_error) if response_error is not None else str(e)
                )
                message = f"Sync LLM Request Error (Attempt {attempt_num}/{self.max_retries + 1}): {safe_msg}"
                if log_errors_as_warning:
                    logger.warning(message)
                else:
                    logger.error(message)

                if attempt_num <= self.max_retries:
                    time.sleep(self._backoff_delay(attempt_num))
                    continue
                if response_error is not None:
                    raise response_error from e
                raise
            finally:
                limiter.release_sync()

        raise RuntimeError("Retry loop exited without producing a response")

    def check_health(self, timeout_seconds: float = 2.0) -> tuple[bool, str]:
        """
        Lightweight readiness check against Ollama tags endpoint.
        """
        tags_url = f"{self._base_url()}/api/tags"
        try:
            response = requests.get(tags_url, timeout=timeout_seconds)
            if response.status_code == 200:
                return True, "ok"
            return False, f"http_{response.status_code}"
        except requests.RequestException as exc:
            return False, str(exc)

    def _stream_generator(
        self, response: requests.Response
    ) -> Generator[str, None, None]:
        for line in response.iter_lines():
            if line:
                try:
                    json_resp = json.loads(line)
                    chunk = json_resp.get("response", "")
                    if chunk:
                        yield chunk
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

        # Try finding outer braces
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed_ok, parsed_json = self._try_parse_json_dict(match.group(0))
            if parsed_ok:
                return parsed_json

        # Try bracket counting fallback (from ai_editor.py)
        bracket_segment = self._extract_braced_segment(text)
        if bracket_segment:
            parsed_ok, parsed_json = self._try_parse_json_dict(bracket_segment)
            if parsed_ok:
                return parsed_json

        logger.warning("Failed to extract JSON from: {}...", text[:100])
        return {}

    def list_models(self) -> list[str]:
        """
        Fetches available models from Ollama /api/tags.
        Returns a list of model names (e.g. ['llama3:latest', ...]).
        """
        tags_url = f"{self._base_url()}/api/tags"

        try:
            resp = requests.get(tags_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                return models
            else:
                logger.warning("Failed to list models: {}", resp.status_code)
                return []
        except Exception as e:
            logger.warning("Error listing models: {}", e)
            return []

    def check_model_exists(self, model_name: str) -> bool:
        """
        Checks if a specific model exists in local Ollama instance.
        """
        available = self.list_models()
        raw_model = str(model_name)
        target = canonicalize_model_id(
            raw_model, stage="provider_existence_check", logger=logger
        )
        self._warn_non_canonical(
            stage="provider_existence_check",
            raw_value=raw_model,
            canonical_value=target,
        )
        return target in available
