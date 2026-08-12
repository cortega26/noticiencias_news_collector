"""Strategy pattern for LLM provider health checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthResult:
    """Outcome of an LLM provider health check."""

    healthy: bool
    disable_llm: bool = False
    error: str | None = None
    warning: str | None = None


class LLMHealthChecker(ABC):
    """Check reachability of a specific LLM provider."""

    @abstractmethod
    def check(self, config: Any, logger: Any) -> HealthResult:
        """Return health status. Raises RuntimeError for strict-mode abort."""


class NvidiaHealthChecker(LLMHealthChecker):
    def check(self, config: Any, logger: Any) -> HealthResult:
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        nvidia_cfg = config.nvidia
        nvidia_model = getattr(nvidia_cfg, "model", "qwen/qwen3-next-80b-a3b-instruct")
        provider = NvidiaProvider(
            api_key=nvidia_cfg.api_key,
            model=nvidia_model,
            base_url=getattr(
                nvidia_cfg, "base_url", "https://integrate.api.nvidia.com/v1"
            ),
        )
        try:
            healthy, reason = provider.check_health(timeout_seconds=5)
        except RuntimeError:
            raise
        except Exception as err:
            warning = f"NVIDIA NIM health check error: {err}"
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False, disable_llm=True, error=warning, warning=warning
            )

        if healthy:
            if logger:
                logger.info(f"NVIDIA NIM health check passed (model={nvidia_model}).")
            return HealthResult(healthy=True)
        warning = f"NVIDIA NIM health check failed: {reason}"
        if logger:
            logger.warning(warning)
        return HealthResult(
            healthy=False, disable_llm=True, error=warning, warning=warning
        )


class GeminiHealthChecker(LLMHealthChecker):
    def check(self, config: Any, logger: Any) -> HealthResult:
        from news_collector.infrastructure.llm.gemini_provider import GeminiProvider

        gemini_model = getattr(config.gemini, "model", "gemini-2.5-flash")
        gemini_provider = GeminiProvider(
            api_key=config.gemini.api_key, model=gemini_model
        )
        try:
            healthy, reason = gemini_provider.check_health(timeout_seconds=5)
        except RuntimeError:
            raise
        except Exception as err:
            warning = f"Gemini health check error: {err}"
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False, disable_llm=True, error=warning, warning=warning
            )

        if healthy:
            if logger:
                logger.info(f"Gemini health check passed (model={gemini_model}).")
            return HealthResult(healthy=True)
        warning = f"Gemini health check failed: {reason}"
        if logger:
            logger.warning(warning)
        return HealthResult(
            healthy=False, disable_llm=True, error=warning, warning=warning
        )


class OllamaHealthChecker(LLMHealthChecker):
    def check(self, config: Any, logger: Any) -> HealthResult:
        try:
            import requests

            from news_collector.infrastructure.llm.model_registry import (
                ModelAvailabilityError,
                ModelRegistryError,
                preflight_ollama_models,
            )

            auditor_cfg = getattr(config, "editorial_auditor", None)
            health_timeout_seconds = int(
                getattr(auditor_cfg, "health_timeout_seconds", 5)
            )
            preflight_ollama_models(
                config,
                check_availability=True,
                check_generation=True,
                timeout_seconds=health_timeout_seconds,
                logger=logger,
            )
        except ModelAvailabilityError as availability_err:
            warning = str(availability_err)
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False, disable_llm=True, error=warning, warning=warning
            )
        except ModelRegistryError as cfg_error:
            warning = f"Ollama model configuration error: {cfg_error}"
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False,
                disable_llm=True,
                error=warning,
                warning=warning,
            )
        except requests.RequestException as conn_err:
            warning = f"LLM Provider unreachable: {conn_err}"
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False, disable_llm=True, error=warning, warning=warning
            )
        except RuntimeError:
            raise
        except Exception as unexpected_err:
            warning = f"Ollama health check error: {unexpected_err}"
            if logger:
                logger.warning(warning)
            return HealthResult(
                healthy=False, disable_llm=True, error=warning, warning=warning
            )

        return HealthResult(healthy=True)


def resolve_health_checker(config: Any) -> LLMHealthChecker | None:
    """Return the appropriate checker for the active provider configuration."""
    nvidia_api_key = getattr(getattr(config, "nvidia", None), "api_key", None)
    if nvidia_api_key:
        return NvidiaHealthChecker()

    gemini_api_key = getattr(getattr(config, "gemini", None), "api_key", None)
    if gemini_api_key:
        return GeminiHealthChecker()

    return OllamaHealthChecker()
