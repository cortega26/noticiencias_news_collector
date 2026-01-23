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
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.provider")


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
        self, api_url: str = None, model: str = "llama3.2:1b", timeout: int = 120
    ):
        self.api_url = api_url or "http://localhost:11434/api/generate"
        self.model = model
        self.timeout = timeout

        # Async client reused from infrastructure
        self.async_client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self.async_client.aclose()

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
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
        self, prompt: str, system: Optional[str] = None, json_mode: bool = False
    ) -> Union[str, Dict[str, Any]]:
        """
        Async generation. Returns text or dict if json_mode is True.
        """
        payload = self._prepare_payload(
            prompt, system, stream=False, json_mode=json_mode
        )

        try:
            logger.debug(f"Sending async prompt to Ollama ({self.model})...")
            start = time.time()
            response = await self.async_client.post(
                self.api_url, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            text = data.get("response", "")

            logger.debug(f"Async LLM complete in {time.time() - start:.2f}s")

            if json_mode:
                return self._extract_json(text)
            return text

        except httpx.RequestError as e:
            logger.error(f"Async LLM Request Error: {e}")
            raise

    # --- SYNC API (Legacy/Compat) ---

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.RequestException),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def generate_sync(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
    ) -> Union[str, Dict[str, Any], Generator[str, None, None]]:
        """
        Sync generation for legacy components.
        Supports streaming generator if stream=True and json_mode=False.
        """
        payload = self._prepare_payload(
            prompt, system, stream=stream, json_mode=json_mode
        )

        try:
            # We use direct requests for sync to avoid async loop issues in strict sync contexts
            logger.debug(f"Sending sync prompt to Ollama ({self.model})...")
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
                return self._extract_json(text)
            return text

        except requests.RequestException as e:
            logger.error(f"Sync LLM Request Error: {e}")
            raise

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

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Robust JSON extraction from mixed text."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try finding outer braces
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Try bracket counting (from ai_editor.py)
        start_idx = text.find("{")
        if start_idx != -1:
            nesting = 0
            for i, char in enumerate(text[start_idx:], start=start_idx):
                if char == "{":
                    nesting += 1
                elif char == "}":
                    nesting -= 1
                if nesting == 0:
                    try:
                        return json.loads(text[start_idx : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        pass

        logger.warning(f"Failed to extract JSON from: {text[:100]}...")
        return {}
