"""Provider Factory for LLM connections."""

import logging
from typing import Any, Optional

from noticiencias.config_manager import load_config
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.infrastructure.llm.gemini_provider import GeminiProvider

logger = logging.getLogger("news_collector.infrastructure.llm.factory")

def get_provider(
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 300,
    max_retries: int = 2,
    config: Optional[Any] = None
) -> Any:
    """
    Returns an appropriate LLM provider (Ollama or Gemini) based on active configuration.
    If Gemini API key is configured, GeminiProvider is returned.
    Otherwise, OllamaProvider is returned.
    """
    cfg = config or load_config()

    gemini_api_key = getattr(cfg.gemini, "api_key", None)
    if gemini_api_key:
        use_model = getattr(cfg.gemini, "model", "gemini-2.5-flash")
        
        # Override with Gemini defaults if the provided model is Ollama-specific
        if model and ("llama" in model.lower() or "qwen" in model.lower() or ":" in model):
            model = use_model

        logger.info(f"Using GeminiProvider with model {model or use_model}")
        return GeminiProvider(
            api_key=gemini_api_key,
            model=model or use_model,
            timeout=timeout,
            max_retries=max_retries,
        )
    
    # Fallback to Ollama
    logger.info(f"Using OllamaProvider with model {model}")
    return OllamaProvider(
        api_url=api_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )
