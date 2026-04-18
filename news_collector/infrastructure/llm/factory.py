"""Provider Factory for LLM connections."""

import logging
from typing import Any, Optional

from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.infrastructure.llm.rate_limiter import (
    LLMRateLimitConfig,
    LLMRateLimiter,
)
from noticiencias.config_manager import load_config

logger = logging.getLogger("news_collector.infrastructure.llm.factory")


def _ensure_rate_limiter(cfg: Any) -> None:
    """Initialize the process-wide LLMRateLimiter singleton from config (once)."""
    if LLMRateLimiter._instance is not None:
        return

    llm_rl = getattr(cfg, "llm_rate_limiting", None)
    if llm_rl is not None:
        rl_cfg = LLMRateLimitConfig(
            max_concurrent_requests=getattr(llm_rl, "max_concurrent_requests", 2),
            min_delay_between_requests=getattr(
                llm_rl, "min_delay_between_requests", 1.0
            ),
            circuit_breaker_threshold=getattr(llm_rl, "circuit_breaker_threshold", 3),
            circuit_breaker_cooldown=getattr(llm_rl, "circuit_breaker_cooldown", 60.0),
            max_retries=getattr(llm_rl, "max_retries", 3),
            retry_backoff_base=getattr(llm_rl, "retry_backoff_base", 2.0),
            retry_backoff_max=getattr(llm_rl, "retry_backoff_max", 30.0),
            retry_jitter_max=getattr(llm_rl, "retry_jitter_max", 2.0),
        )
    else:
        rl_cfg = LLMRateLimitConfig()

    LLMRateLimiter.get_instance(rl_cfg)


def get_provider(
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 300,
    max_retries: int = 2,
    config: Optional[Any] = None,
) -> Any:
    """
    Returns an appropriate LLM provider (Ollama or Gemini) based on active configuration.
    If Gemini API key is configured, GeminiProvider is returned.
    Otherwise, OllamaProvider is returned.

    Also ensures the process-wide LLM rate limiter is initialized.
    """
    cfg = config or load_config()

    # Initialize rate limiter singleton from config (idempotent)
    _ensure_rate_limiter(cfg)

    gemini_cfg = getattr(cfg, "gemini", None)
    gemini_api_key = getattr(gemini_cfg, "api_key", None) if gemini_cfg else None
    if gemini_api_key:
        use_model = getattr(gemini_cfg, "model", "gemini-2.5-flash")

        # Override with Gemini defaults if the provided model is Ollama-specific
        if model and (
            "llama" in model.lower() or "qwen" in model.lower() or ":" in model
        ):
            model = use_model

        logger.info("Using GeminiProvider with model %s", model or use_model)
        return GeminiProvider(
            api_key=gemini_api_key,
            model=model or use_model,
            timeout=timeout,
            max_retries=max_retries,
        )

    # Fallback to Ollama
    logger.info("Using OllamaProvider with model %s", model)
    return OllamaProvider(
        api_url=api_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )
