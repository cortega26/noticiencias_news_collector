import json
import logging
import re
import time
from typing import Any, Dict, Generator, Optional, Union

import httpx
import requests
from news_collector.utils.logger import get_logger
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

logger = get_logger().create_module_logger("infrastructure.llm.gemini_provider")

class GeminiProvider:
    """
    Unified client for Google AI Studio (Gemini) API.
    Provides identical interface to OllamaProvider.
    """

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: int = 300,
        max_retries: int = 5,
    ):
        self.api_key = api_key
        self.model = model or "gemini-2.5-flash"
        self.timeout = timeout
        self.max_retries = max_retries

        self._base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.async_client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self.async_client.aclose()

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        
        contents = []

        if system:
            # System instructions are set differently in Gemini API
            contents.append({
                "role": "user",
                "parts": [{"text": f"System Instruction: {system}\n\nUser: {prompt}"}]
            })
        else:
            contents.append({
                "role": "user",
                "parts": [{"text": prompt}]
            })

        payload = {
            "contents": contents,
            "generationConfig": {}
        }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        return payload

    # --- ASYNC API ---

    async def generate_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[str, Dict[str, Any]]:
        
        use_model = model or self.model
        if "llama" in use_model.lower() or "qwen" in use_model.lower() or "mistral" in use_model.lower():
            use_model = self.model
            
        if ":" in use_model:
            use_model = use_model.split(":")[0]

        use_timeout = timeout or self.timeout

        payload = self._prepare_payload(prompt, system, json_mode)
        url = f"{self._base_url}/models/{use_model}:generateContent?key={self.api_key}"

        from tenacity import AsyncRetrying

        retry_config = AsyncRetrying(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=5, min=10, max=120) + wait_random(1, 5),
            retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        async for attempt in retry_config:
            with attempt:
                try:
                    logger.debug(
                        f"Sending async prompt to Gemini ({use_model}) "
                        f"(timeout={use_timeout}s, attempt={attempt.retry_state.attempt_number}/{self.max_retries + 1})"
                    )
                    start = time.time()
                    response = await self.async_client.post(url, json=payload, timeout=use_timeout)
                    response.raise_for_status()
                    data = response.json()
                    
                    text = ""
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")

                    logger.debug(f"Async LLM complete in {time.time() - start:.2f}s")

                    if json_mode:
                        return self._extract_json(text)
                    return text

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    logger.error(f"Async LLM Request Error (Attempt {attempt.retry_state.attempt_number}): {e}")
                    raise
        raise RuntimeError("Async retry loop exited without producing a response")

    # --- SYNC API ---

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
        
        use_model = model or self.model
        if "llama" in use_model.lower() or "qwen" in use_model.lower() or "mistral" in use_model.lower():
            use_model = self.model
            
        if ":" in use_model:
            use_model = use_model.split(":")[0]

        use_timeout = timeout or self.timeout

        payload = self._prepare_payload(prompt, system, json_mode)
        
        # Stream logic url differ slightly
        endpoint = "streamGenerateContent" if stream else "generateContent"
        url = f"{self._base_url}/models/{use_model}:{endpoint}?key={self.api_key}"
        if stream:
            url += "&alt=sse"

        from news_collector.config import settings

        if not settings.LLM_SYSTEM_AVAILABLE:
            raise ValueError("LLM System is marked as unavailable (Disabled).")

        retry_config = Retrying(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=5, min=10, max=120) + wait_random(1, 5),
            retry=retry_if_exception_type((requests.RequestException, requests.exceptions.HTTPError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        for attempt in retry_config:
            with attempt:
                try:
                    logger.debug(
                        f"Sending sync prompt to Gemini ({use_model}) "
                        f"(timeout={use_timeout}s, attempt={attempt.retry_state.attempt_number}/{self.max_retries + 1})"
                    )
                    response = requests.post(url, json=payload, stream=stream, timeout=use_timeout)
                    response.raise_for_status()

                    if stream:
                        return self._stream_generator(response)

                    data = response.json()
                    text = ""
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")

                    if json_mode:
                        return self._extract_json(text)
                    return text

                except requests.RequestException as e:
                    message = f"Sync LLM Request Error (Attempt {attempt.retry_state.attempt_number}): {e}"
                    if log_errors_as_warning:
                        logger.warning(message)
                    else:
                        logger.error(message)
                    raise
        raise RuntimeError("Retry loop exited without producing a response")

    def check_health(self, timeout_seconds: float = 5.0) -> tuple[bool, str]:
        url = f"{self._base_url}/models/{self.model}?key={self.api_key}"
        try:
            response = requests.get(url, timeout=timeout_seconds)
            if response.status_code == 200:
                return True, "ok"
            return False, f"http_{response.status_code}"
        except requests.RequestException as exc:
            return False, str(exc)

    def _stream_generator(self, response: requests.Response) -> Generator[str, None, None]:
        # Server-Sent Events (SSE) stream parsing
        for line in response.iter_lines():
            line_str = line.decode('utf-8')
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
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
