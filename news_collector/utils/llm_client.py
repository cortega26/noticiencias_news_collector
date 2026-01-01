import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests

try:
    from dotenv import dotenv_values
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    dotenv_values = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _default_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv_values(dotenv_path: Optional[Path]) -> Dict[str, str]:
    if dotenv_values is None:
        return {}
    env_path = dotenv_path or _default_env_path()
    if not env_path.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(env_path, verbose=False).items()
        if value is not None
    }


class LLMClient:
    """
    Simple client to interact with Ollama (or compatible APIs).
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        dotenv_path: Optional[Path | str] = None,
    ):
        if dotenv_path is not None and not isinstance(dotenv_path, Path):
            dotenv_path = Path(dotenv_path)
        env_values = _load_dotenv_values(dotenv_path)
        self.api_url = (
            api_url
            or os.getenv("OLLAMA_API_URL")
            or os.getenv("OLLAMA_URL")
            or env_values.get("OLLAMA_API_URL")
            or env_values.get("OLLAMA_URL")
            or "http://localhost:11434/api/generate"
        )
        self.model = (
            model
            or os.getenv("OLLAMA_MODEL")
            or env_values.get("OLLAMA_MODEL")
            or "llama3.2:1b"
        )

    def generate(self, prompt: str, system: Optional[str] = None, format: str = "json") -> Union[str, Dict[str, Any]]:
        """
        Generate text from the LLM.
        
        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            format: "json" or "text". If "json", attempts to parse response as JSON.
            
        Returns:
            String response or Dictionary if format is json.
        """
        full_prompt = prompt
        
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        if system:
            payload["system"] = system
            
        if format == "json":
            payload["format"] = "json"

        try:
            logger.debug(f"Sending prompt to LLM ({self.model})...")
            start_time = time.time()
            response = requests.post(self.api_url, json=payload, timeout=300)
            response.raise_for_status()
            
            data = response.json()
            response_text = data.get("response", "")
            
            duration = time.time() - start_time
            logger.debug(f"LLM processing complete in {duration:.2f} seconds.")

            if format == "json":
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    logger.warning("LLM response was not valid JSON, returning text.")
                    # Try to find JSON blob in text
                    import re
                    match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(0))
                        except:
                            pass
                    return {"error": "Invalid JSON", "raw": response_text}
            
            return response_text

        except requests.exceptions.RequestException as e:
            logger.error(f"Error communicating with LLM: {e}")
            if format == "json":
                return {"error": str(e)}
            return ""
