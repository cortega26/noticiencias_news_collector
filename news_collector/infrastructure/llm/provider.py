"""
Unified Ollama Provider.
Replaces legacy llm_client.py and ai_editor.py logic.
Supports both Sync (legacy) and Async (pipeline) operations.
"""

import json
import logging
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
from news_collector.utils.logger import get_logger
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

logger = get_logger().create_module_logger("infrastructure.llm.provider")
_NON_CANONICAL_WARNED: set[tuple[str, str, str]] = set()


class OllamaProvider:
    """
    Unified client for Ollama API.
    Features:
    - Sync & Async methods
    - Robust JSON extraction
    - Streaming support
    - Configurable timeouts & retries
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
            "Non-canonical Ollama model id in %s: '%s' -> '%s' (registry normalized).",
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
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        return payload

    # --- ASYNC API (Recommended) ---

    async def generate_async(
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

        try:
            logger.debug(f"Sending async prompt to Ollama ({payload['model']})...")
            start = time.time()
            response = await self.async_client.post(
                self.api_url, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            text = data.get("response", "")

            logger.debug(f"Async LLM complete in {time.time() - start:.2f}s")

            if json_mode:
                return self._extract_json(str(text))
            return str(text)

        except httpx.RequestError as e:
            logger.error(f"Async LLM Request Error: {e}")
            raise

    # --- SYNC API (Legacy/Compat) ---

    # --- SYNC API (Legacy/Compat) ---

    def generate_sync(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
        log_errors_as_warning: bool = False,
    ) -> Union[str, Dict[str, Any], Generator[str, None, None]]:
        """
        Sync generation with configurable retries.
        """
        payload = self._prepare_payload(
            prompt, system, stream=stream, json_mode=json_mode, model=model
        )

        # Fail fast if system marked LLM as unavailable (boot check)
        from news_collector.config import settings

        if not settings.LLM_SYSTEM_AVAILABLE:
            raise ValueError("LLM System is marked as unavailable (Disabled).")

        # Configure Retry logic dynamically
        retry_config = Retrying(
            stop=stop_after_attempt(
                self.max_retries + 1
            ),  # +1 because 0 retries = 1 attempt
            wait=wait_exponential(multiplier=1, min=2, max=10) + wait_random(0, 1),
            retry=retry_if_exception_type(requests.RequestException),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        # Execute with retries
        for attempt in retry_config:
            with attempt:
                try:
                    logger.debug(
                        f"Sending sync prompt to Ollama ({payload['model']}) at {self.api_url} "
                        f"(timeout={self.timeout}s, attempt={attempt.retry_state.attempt_number}/{self.max_retries + 1})"
                    )
                    response = requests.post(
                        self.api_url, json=payload, stream=stream, timeout=self.timeout
                    )
                    response.raise_for_status()

                    if stream:
                        return self._stream_generator(response)

                    # Non-streaming
                    data = response.json()
                    text = data.get("response", "")

                    if json_mode:
                        return self._extract_json(str(text))
                    return str(text)

                except requests.RequestException as e:
                    message = (
                        "Sync LLM Request Error "
                        f"(Attempt {attempt.retry_state.attempt_number}): {e}"
                    )
                    if log_errors_as_warning:
                        logger.warning(message)
                    else:
                        logger.error(message)
                    raise
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

        logger.warning(f"Failed to extract JSON from: {text[:100]}...")
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
                logger.warning(f"Failed to list models: {resp.status_code}")
                return []
        except Exception as e:
            logger.warning(f"Error listing models: {e}")
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
