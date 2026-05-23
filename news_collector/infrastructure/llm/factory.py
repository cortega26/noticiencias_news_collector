"""Provider Factory for LLM connections."""

import logging
from typing import Any, Dict, Generator, Optional, Union, cast

from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider
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


class FallbackProvider:
    """A wrapper provider that implements the LLM provider interface and executes
    calls sequentially through a list of providers when timeouts or errors occur.
    """

    def __init__(self, providers: list[Any]):
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider.")
        self.providers = providers
        # Expose self.model from the first/primary provider
        self.model = getattr(providers[0], "model", None)

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
        last_error = None
        for i, provider in enumerate(self.providers):
            try:
                # First ones get a fast timeout of 60s to trigger failover quickly
                current_timeout = 60 if i < len(self.providers) - 1 else (timeout or 60)

                kwargs: Dict[str, Any] = {
                    "prompt": prompt,
                    "system": system,
                    "json_mode": json_mode,
                    "model": model,
                    "log_errors_as_warning": log_errors_as_warning,
                }

                old_timeout = getattr(provider, "timeout", None)
                if old_timeout is not None:
                    provider.timeout = current_timeout

                # OllamaProvider does not accept timeout in generate_sync
                if provider.__class__.__name__ != "OllamaProvider":
                    kwargs["timeout"] = current_timeout

                logger.info(
                    "FallbackProvider attempting generate_sync with %s (timeout=%s)...",
                    provider.__class__.__name__,
                    current_timeout,
                )

                if stream:
                    # Buffer stream chunks to allow fallback on mid-stream failure
                    chunks = []
                    generator = provider.generate_sync(stream=True, **kwargs)
                    try:
                        for chunk in generator:
                            chunks.append(chunk)
                    except Exception as e:
                        if old_timeout is not None:
                            provider.timeout = old_timeout
                        raise e

                    if old_timeout is not None:
                        provider.timeout = old_timeout

                    def chunk_generator(
                        chunks_list: list[str] = chunks,
                    ) -> Generator[str, None, None]:
                        for chunk in chunks_list:
                            yield chunk

                    return chunk_generator()
                else:
                    res = cast(
                        Union[str, Dict[str, Any], Generator[str, None, None]],
                        provider.generate_sync(stream=False, **kwargs),
                    )
                    if old_timeout is not None:
                        provider.timeout = old_timeout
                    return res
            except Exception as e:
                logger.warning(
                    "Provider %s failed during generate_sync: %s. Proceeding to fallback...",
                    provider.__class__.__name__,
                    e,
                )
                last_error = e

        if last_error:
            raise last_error
        raise RuntimeError("FallbackProvider failed with no active providers.")

    async def generate_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[str, Dict[str, Any]]:
        last_error = None
        for i, provider in enumerate(self.providers):
            try:
                current_timeout = 60 if i < len(self.providers) - 1 else (timeout or 60)
                kwargs: Dict[str, Any] = {
                    "prompt": prompt,
                    "system": system,
                    "json_mode": json_mode,
                    "model": model,
                }

                old_timeout = getattr(provider, "timeout", None)
                if old_timeout is not None:
                    provider.timeout = current_timeout

                # OllamaProvider generate_async does not take timeout argument
                if provider.__class__.__name__ != "OllamaProvider":
                    kwargs["timeout"] = current_timeout

                logger.info(
                    "FallbackProvider attempting generate_async with %s (timeout=%s)...",
                    provider.__class__.__name__,
                    current_timeout,
                )

                res = cast(
                    Union[str, Dict[str, Any]], await provider.generate_async(**kwargs)
                )
                if old_timeout is not None:
                    provider.timeout = old_timeout
                return res
            except Exception as e:
                logger.warning(
                    "Provider %s failed during generate_async: %s. Proceeding to fallback...",
                    provider.__class__.__name__,
                    e,
                )
                last_error = e

        if last_error:
            raise last_error
        raise RuntimeError("FallbackProvider failed with no active providers.")

    def check_health(self, timeout_seconds: float = 2.0) -> tuple[bool, str]:
        return cast(tuple[bool, str], self.providers[0].check_health(timeout_seconds))

    def list_models(self) -> list[str]:
        return cast(list[str], self.providers[0].list_models())

    def check_model_exists(self, model_name: str) -> bool:
        if hasattr(self.providers[0], "check_model_exists"):
            return cast(bool, self.providers[0].check_model_exists(model_name))
        return True

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Robust JSON extraction from mixed text."""
        return cast(Dict[str, Any], self.providers[0]._extract_json(text))

    async def close(self) -> None:
        for provider in self.providers:
            if hasattr(provider, "close"):
                await provider.close()


def get_provider(
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 300,
    max_retries: int = 2,
    max_tokens: Optional[int] = None,
    config: Optional[Any] = None,
) -> Any:
    """
    Returns an appropriate LLM provider (Ollama, NVIDIA, or Gemini) based on active configuration
    wrapped in a FallbackProvider for resilient multi-tiered fallback:
    NVIDIA NIM -> Google Gemini API -> Local Ollama.

    Also ensures the process-wide LLM rate limiter is initialized.
    """
    cfg = config or load_config()

    # Initialize rate limiter singleton from config (idempotent)
    _ensure_rate_limiter(cfg)

    providers: list[Any] = []

    # Priority 1: NVIDIA NIM (when an NVIDIA API key is configured)
    nvidia_cfg = getattr(cfg, "nvidia", None)
    nvidia_api_key = getattr(nvidia_cfg, "api_key", None) if nvidia_cfg else None
    if nvidia_api_key:
        use_model = getattr(nvidia_cfg, "model", "qwen/qwen3-next-80b-a3b-instruct")
        use_base_url = getattr(
            nvidia_cfg, "base_url", "https://integrate.api.nvidia.com/v1"
        )
        use_max_tokens = max_tokens or getattr(nvidia_cfg, "max_tokens", 4096)
        logger.info(
            "Configuring NvidiaProvider with model %s (max_tokens=%s)",
            use_model,
            use_max_tokens,
        )
        providers.append(
            NvidiaProvider(
                api_key=nvidia_api_key,
                model=use_model,
                base_url=use_base_url,
                timeout=timeout,
                max_retries=max_retries,
                max_tokens=use_max_tokens,  # type: ignore[arg-type]
            )
        )

    # Priority 2: Gemini (when a Google AI Studio API key is configured)
    gemini_cfg = getattr(cfg, "gemini", None)
    gemini_api_key = getattr(gemini_cfg, "api_key", None) if gemini_cfg else None
    if gemini_api_key:
        use_model = getattr(gemini_cfg, "model", "gemini-2.5-flash")

        # Override with Gemini defaults if the provided model is Ollama-specific
        use_gemini_model = model or use_model
        if use_gemini_model and (
            "llama" in use_gemini_model.lower()
            or "qwen" in use_gemini_model.lower()
            or ":" in use_gemini_model
        ):
            use_gemini_model = use_model

        logger.info("Configuring GeminiProvider with model %s", use_gemini_model)
        providers.append(
            GeminiProvider(
                api_key=gemini_api_key,
                model=use_gemini_model,
                timeout=timeout,
                max_retries=max_retries,
            )
        )

    # Priority 3: Ollama (local)
    # Always include Ollama as the final fallback
    ollama_cfg = getattr(cfg, "ollama", None)
    default_ollama_model = getattr(ollama_cfg, "model", "qwen2.5:32b")
    use_ollama_model = model or default_ollama_model
    # If the requested model is a cloud model, fallback to the local default model
    if use_ollama_model and (
        "/" in str(use_ollama_model) or "gemini" in str(use_ollama_model).lower()
    ):
        use_ollama_model = default_ollama_model

    logger.info("Configuring OllamaProvider with model %s", use_ollama_model)
    providers.append(
        OllamaProvider(
            api_url=api_url or getattr(ollama_cfg, "api_url", None),
            model=use_ollama_model,
            timeout=timeout,
            max_retries=max_retries,
        )
    )

    # Return FallbackProvider if there are multiple providers configured
    if len(providers) > 1:
        logger.info(
            "Returning FallbackProvider with chain: %s",
            [p.__class__.__name__ for p in providers],
        )
        return FallbackProvider(providers)

    return providers[0]
