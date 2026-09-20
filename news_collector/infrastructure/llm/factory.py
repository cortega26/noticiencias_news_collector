"""Provider Factory for LLM connections."""

import asyncio
import os
import re
import time
from typing import Any, Dict, Generator, NoReturn, Optional, Union, cast

from noticiencias.config_manager import load_config, load_env_overrides

from news_collector.infrastructure.llm.attempts import (
    blocked_reason,
    cool_down_provider,
    disable_provider,
    emit_attempt,
    provider_name,
)
from news_collector.infrastructure.llm.failure_kinds import (
    EmptyResponseError,
    FailureKind,
    classify_exception,
    retry_after_seconds,
)
from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider
from news_collector.infrastructure.llm.openai_compat_provider import (
    OpenAICompatProvider,
)
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.infrastructure.llm.rate_limiter import (
    LLMRateLimitConfig,
    LLMRateLimiter,
    reset_queue_wait,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.factory")


def _is_empty_response(res: Any) -> bool:
    """A 200 with no usable content (blank text or ``{}``) is a provider failure."""
    if isinstance(res, str):
        return not res.strip()
    if isinstance(res, dict):
        # {} or a degenerate parse such as {"": ""} carries no content.
        return not any(k or v for k, v in res.items())
    return False


def _is_degraded(provider: Any) -> bool:
    """
    Return True when a provider is degraded.

    Uses the method defined on the concrete class type so duck-typed mocks
    (MagicMock returns a truthy stub for any attribute) are not skipped.
    """
    if getattr(type(provider), "is_degraded", None) is None:
        return False
    return bool(provider.is_degraded())


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

    Every attempt is classified (:mod:`failure_kinds`), logged as a structured
    ``llm.attempt`` event and offered to registered sinks (:mod:`attempts`).
    The last provider keeps the historical semantics: its result is returned
    as-is and its error propagates.
    """

    # Non-final providers get a short leash so failover happens quickly.
    FAILOVER_TIMEOUT_S = 60
    # With a call budget: hard cap for a non-final attempt (a fixed cap, not a
    # share of what is left: geometric shares starved every fallback), and the
    # smallest slice worth starting another attempt for.
    MAX_ATTEMPT_S = 25.0
    # Longest Retry-After worth waiting out (then retrying once) instead of
    # failing over, when the call has a budget.
    SHORT_RATE_LIMIT_WAIT_S = 30.0
    MIN_ATTEMPT_S = 2.0

    def __init__(self, providers: list[Any], purpose: str = "unspecified"):
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider.")
        self.providers = providers
        self.purpose = purpose
        # Expose self.model from the first/primary provider
        self.model = getattr(providers[0], "model", None)

    # ---- shared per-attempt logic (sync and async paths) ----

    def _skip_reason(self, provider: Any, op: str) -> Optional[str]:
        """Reason to skip this provider without calling it, else ``None``."""
        name = provider_name(provider)
        if _is_degraded(provider):
            logger.info("Skipping degraded provider {} during {}", name, op)
            return "degraded"
        reason = blocked_reason(provider)
        if reason:
            logger.info("Skipping provider {} during {}: {}", name, op, reason)
        return reason

    def _timeout_for(self, index: int, timeout: Optional[int], provider: Any) -> int:
        if index < len(self.providers) - 1:
            own = getattr(provider, "timeout", None)
            if isinstance(own, (int, float)) and 0 < own < self.FAILOVER_TIMEOUT_S:
                return int(own)
            return self.FAILOVER_TIMEOUT_S
        return timeout or getattr(provider, "timeout", None) or self.FAILOVER_TIMEOUT_S

    def _call_kwargs(
        self, provider: Any, current_timeout: int, base: Dict[str, Any]
    ) -> Dict[str, Any]:
        kwargs = dict(base)
        # OllamaProvider does not accept timeout in its generate_* methods
        if provider.__class__.__name__ != "OllamaProvider":
            kwargs["timeout"] = current_timeout
        return kwargs

    def _check_result(self, res: Any, index: int) -> None:
        """Fail over on a blank 200 unless this is the last provider."""
        if index < len(self.providers) - 1 and _is_empty_response(res):
            kind = (
                FailureKind.INVALID_JSON
                if isinstance(res, dict)
                else FailureKind.EMPTY_RESPONSE
            )
            raise EmptyResponseError(kind)

    def _record_skip(self, provider: Any, index: int, reason: str) -> str:
        """Emit a zero-latency DEGRADED_SKIP attempt so skips are measurable."""
        emit_attempt(
            provider,
            purpose=self.purpose,
            ok=False,
            kind=FailureKind.DEGRADED_SKIP,
            started=time.monotonic(),
            failover_index=index,
            error=RuntimeError(reason),
        )
        return f"{provider_name(provider)}=skipped({reason})"

    def _record_success(
        self, provider: Any, index: int, started: float, empty: bool = False
    ) -> None:
        emit_attempt(
            provider,
            purpose=self.purpose,
            ok=not empty,
            kind=FailureKind.EMPTY_RESPONSE if empty else None,
            started=started,
            failover_index=index,
        )
        if index > 0 and not empty:
            logger.warning(
                "LLM failover: served by {} (purpose={}) after {} failed attempt(s)",
                provider_name(provider),
                self.purpose,
                index,
            )

    def _short_rate_limit_wait(
        self, exc: BaseException, deadline: Optional[float]
    ) -> Optional[float]:
        """Seconds to wait before retrying the same provider, or ``None``.

        Only for a rate limit whose ``Retry-After`` is short and still leaves
        room in the caller's budget for the retry: e.g. Groq refills its
        per-minute token cap in ~25 s, far quicker than falling over to a
        provider that needs 50 s+ for the same batch.
        """
        if deadline is None or classify_exception(exc) is not FailureKind.RATE_LIMITED:
            return None
        wait = retry_after_seconds(exc)
        if wait is None or wait <= 0 or wait > self.SHORT_RATE_LIMIT_WAIT_S:
            return None
        if deadline - time.monotonic() < wait + self.MIN_ATTEMPT_S * 2:
            return None
        return wait

    def _record_failure(
        self,
        provider: Any,
        index: int,
        started: float,
        exc: BaseException,
        cooldown: bool = True,
    ) -> FailureKind:
        kind = classify_exception(exc)
        emit_attempt(
            provider,
            purpose=self.purpose,
            ok=False,
            kind=kind,
            started=started,
            failover_index=index,
            error=exc,
        )
        name = provider_name(provider)
        if kind is FailureKind.AUTH and disable_provider(provider, str(exc)[:120]):
            logger.error(
                "LLM provider {} rejected our credentials ({}); disabling it for "
                "1h (retried afterwards). Check its API key.",
                name,
                exc.__class__.__name__,
            )
        elif kind is FailureKind.RATE_LIMITED and not cooldown:
            pass  # caller waits Retry-After and retries this provider itself
        elif kind is FailureKind.RATE_LIMITED:
            delay = cool_down_provider(provider, retry_after_seconds(exc))
            logger.warning(
                "LLM provider {} rate-limited; cooling down {:.0f}s", name, delay
            )
        else:
            logger.warning(
                "Provider {} failed during {} ({}): {}. Proceeding to fallback...",
                name,
                self.purpose,
                kind.value,
                exc,
            )
        return kind

    def _exhausted(
        self, last_error: Optional[BaseException], kinds: list[str]
    ) -> NoReturn:
        logger.error(
            "LLM chain exhausted (purpose={}): {}",
            self.purpose,
            ", ".join(kinds) or "no active providers",
        )
        if last_error:
            raise last_error
        raise RuntimeError("FallbackProvider failed with no active providers.")

    # ---- public API ----

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
        last_error: Optional[BaseException] = None
        kinds: list[str] = []
        base = {
            "prompt": prompt,
            "system": system,
            "json_mode": json_mode,
            "model": model,
            "log_errors_as_warning": log_errors_as_warning,
        }
        for i, provider in enumerate(self.providers):
            skipped = self._skip_reason(provider, "generate_sync")
            if skipped:
                kinds.append(self._record_skip(provider, i, skipped))
                continue
            old_timeout = getattr(provider, "timeout", None)
            current_timeout = self._timeout_for(i, timeout, provider)
            reset_queue_wait()
            started = time.monotonic()
            try:
                if old_timeout is not None:
                    provider.timeout = current_timeout
                kwargs = self._call_kwargs(provider, current_timeout, base)
                logger.info(
                    "FallbackProvider attempting generate_sync with {} (timeout={})...",
                    provider.__class__.__name__,
                    current_timeout,
                )
                if stream:
                    # Buffer stream chunks to allow fallback on mid-stream failure
                    chunks = list(provider.generate_sync(stream=True, **kwargs))
                    self._check_result("".join(chunks), i)
                    self._record_success(provider, i, started, empty=not chunks)

                    def chunk_generator(
                        chunks_list: list[str] = chunks,
                    ) -> Generator[str, None, None]:
                        yield from chunks_list

                    return chunk_generator()
                res = cast(
                    Union[str, Dict[str, Any], Generator[str, None, None]],
                    provider.generate_sync(stream=False, **kwargs),
                )
                self._check_result(res, i)
                self._record_success(provider, i, started, _is_empty_response(res))
                return res
            except Exception as e:
                kinds.append(
                    f"{provider_name(provider)}={self._record_failure(provider, i, started, e).value}"
                )
                last_error = e
            finally:
                if old_timeout is not None:
                    provider.timeout = old_timeout
        return self._exhausted(last_error, kinds)

    async def generate_async(  # noqa: C901
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        budget: Optional[float] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Run the chain; ``budget`` bounds the *whole* call in seconds.

        Without a budget each attempt only has its own timeout. With one, a
        slow provider can no longer starve the rest of the chain: every
        non-final attempt is capped at ``MAX_ATTEMPT_S`` (and cancelled for
        real), so failover still fits inside the caller's
        deadline. The final provider gets whatever remains.
        """
        last_error: Optional[BaseException] = None
        kinds: list[str] = []
        base = {
            "prompt": prompt,
            "system": system,
            "json_mode": json_mode,
            "model": model,
        }
        deadline = None if budget is None else time.monotonic() + budget
        out_of_budget = False
        for i, provider in enumerate(self.providers):
            skipped = self._skip_reason(provider, "generate_async")
            if skipped:
                kinds.append(self._record_skip(provider, i, skipped))
                continue
            # A rate-limited provider is retried once when the wait is short
            # (see _short_rate_limit_wait); otherwise the chain moves on.
            for try_no in range(2):
                old_timeout = getattr(provider, "timeout", None)
                current_timeout = self._timeout_for(i, timeout, provider)
                attempt_cap: Optional[float] = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining < self.MIN_ATTEMPT_S:
                        kinds.append(f"{provider_name(provider)}=skipped(budget)")
                        out_of_budget = True
                        break
                    is_last = i >= len(self.providers) - 1
                    attempt_cap = (
                        remaining if is_last else min(remaining, self.MAX_ATTEMPT_S)
                    )
                    current_timeout = max(1, int(min(current_timeout, attempt_cap)))
                reset_queue_wait()
                started = time.monotonic()
                try:
                    if old_timeout is not None:
                        provider.timeout = current_timeout
                    kwargs = self._call_kwargs(provider, current_timeout, base)
                    logger.info(
                        "FallbackProvider attempting generate_async with {} (timeout={})...",
                        provider.__class__.__name__,
                        current_timeout,
                    )
                    call = provider.generate_async(**kwargs)
                    if attempt_cap is not None:
                        call = asyncio.wait_for(call, timeout=attempt_cap)
                    res = cast(Union[str, Dict[str, Any]], await call)
                    self._check_result(res, i)
                    self._record_success(provider, i, started, _is_empty_response(res))
                    return res
                except Exception as e:
                    wait = (
                        self._short_rate_limit_wait(e, deadline)
                        if try_no == 0
                        else None
                    )
                    kind = self._record_failure(
                        provider, i, started, e, cooldown=wait is None
                    )
                    if wait is not None:
                        logger.info(
                            "LLM provider {} rate-limited; waiting {:.0f}s and retrying "
                            "once (faster than failing over)",
                            provider_name(provider),
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    kinds.append(f"{provider_name(provider)}={kind.value}")
                    last_error = e
                    break
                finally:
                    if old_timeout is not None:
                        provider.timeout = old_timeout
            if out_of_budget:
                break
        return self._exhausted(last_error, kinds)

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


def resolve_secret(name: str) -> str:
    """Secret from the process environment, else the canonical repo ``.env``.

    ``config_manager`` reads ``.env`` without exporting it, so keys for
    ``[[llm_endpoints]]`` would otherwise only work when exported by the shell.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        return str(load_env_overrides().get(name, "")).strip()
    except Exception as err:  # noqa: BLE001 - a broken .env must not break the chain
        logger.debug("Could not read .env for {}: {}", name, err)
        return ""


_WARNED_MISSING_KEYS: set[str] = set()


def _install_metrics_sink() -> None:
    """Persist attempt metrics (fail-open; see llm_metrics_store)."""
    try:
        from news_collector.observability.llm_metrics_store import (
            install_default_metrics_sink,
        )

        install_default_metrics_sink()
    except Exception as err:  # noqa: BLE001 - observability must never break calls
        logger.debug("LLM metrics sink not installed: {}", err)


_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def _expand_placeholders(text: str) -> Optional[str]:
    """Replace ``${VAR}`` with ``resolve_secret(VAR)``; ``None`` if any is unset.

    Lets an endpoint URL carry an identifier that must not live in the
    committed config (e.g. Cloudflare's account id in the Workers AI path).
    """
    missing = False

    def _sub(match: "re.Match[str]") -> str:
        nonlocal missing
        value = resolve_secret(match.group(1))
        missing = missing or not value
        return value

    expanded = _PLACEHOLDER_RE.sub(_sub, text)
    return None if missing else expanded


def _build_endpoint_providers(cfg: Any, nvidia_cfg: Any) -> list[Any]:
    """Build OpenAI-compatible providers from ``[[llm_endpoints]]``.

    Misconfiguration (unset key variable) skips that endpoint with a warning:
    a broken optional fallback must never take the whole chain down.
    """
    endpoints = getattr(cfg, "llm_endpoints", None)
    if not isinstance(endpoints, list):
        return []
    providers: list[Any] = []
    for ep in endpoints:
        if not ep.enabled:
            continue
        api_key = resolve_secret(ep.api_key_env)
        if not api_key:
            # Warn once per process: get_provider() runs once per pipeline stage.
            if ep.name not in _WARNED_MISSING_KEYS:
                _WARNED_MISSING_KEYS.add(ep.name)
                logger.warning(
                    "LLM endpoint '{}' skipped: environment variable {} is not set",
                    ep.name,
                    ep.api_key_env,
                )
            continue
        base_url = _expand_placeholders(ep.base_url)
        if base_url is None:
            if ep.name not in _WARNED_MISSING_KEYS:
                _WARNED_MISSING_KEYS.add(ep.name)
                logger.warning(
                    "LLM endpoint '{}' skipped: unresolved ${{VAR}} in base_url",
                    ep.name,
                )
            continue
        threshold = ep.degraded_failure_threshold or getattr(
            nvidia_cfg, "degraded_failure_threshold", 2
        )
        cooldown = ep.degraded_cooldown_seconds or getattr(
            nvidia_cfg, "degraded_cooldown_seconds", 300.0
        )
        logger.info("Configuring endpoint '{}' with model {}", ep.name, ep.model)
        providers.append(
            OpenAICompatProvider(
                name=ep.name,
                api_key=api_key,
                base_url=base_url,
                model=ep.model,
                extra_headers=ep.extra_headers,
                json_mode_supported=ep.json_mode_supported,
                timeout=ep.timeout,
                max_tokens=ep.max_tokens,
                max_retries=ep.max_retries,
                degraded_failure_threshold=threshold,
                degraded_cooldown_seconds=cooldown,
            )
        )
    return providers


def _apply_chain_order(providers: list[Any], chain: Any) -> list[Any]:
    """Order remote providers by ``[llm] chain`` (default: as built).

    Unknown names are ignored with a warning; providers not listed are
    dropped, so the list is an explicit allow-list.
    """
    if not isinstance(chain, list) or not chain:
        return providers
    by_name = {provider_name(p): p for p in providers}
    ordered: list[Any] = []
    for name in chain:
        if name == "ollama":
            continue  # always appended last by get_provider
        if name in by_name:
            ordered.append(by_name[name])
        else:
            logger.warning(
                "[llm] chain lists '{}' but no such provider is configured", name
            )
    return ordered


def get_provider(
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 300,
    max_retries: int = 2,
    max_tokens: Optional[int] = None,
    config: Optional[Any] = None,
    purpose: str = "unspecified",
) -> Any:
    """
    Returns an appropriate LLM provider (Ollama, NVIDIA, or Gemini) based on active configuration
    wrapped in a FallbackProvider for resilient multi-tiered fallback:
    NVIDIA NIM -> Google Gemini API -> [[llm_endpoints]] -> Local Ollama
    (order overridable with ``[llm] chain``; Ollama is always last).

    ``purpose`` labels the caller ("headline", "scoring", ...) in attempt logs.

    Also ensures the process-wide LLM rate limiter is initialized.
    """
    cfg = config or load_config()

    # Initialize rate limiter singleton from config (idempotent)
    _ensure_rate_limiter(cfg)
    _install_metrics_sink()

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
        use_degraded_threshold = getattr(nvidia_cfg, "degraded_failure_threshold", 2)
        use_degraded_cooldown = getattr(nvidia_cfg, "degraded_cooldown_seconds", 300.0)
        use_degraded_probe_timeout = getattr(
            nvidia_cfg, "degraded_probe_timeout_seconds", 5.0
        )
        use_degraded_window = getattr(nvidia_cfg, "degraded_window_size", 5)
        use_slow_response_seconds = getattr(nvidia_cfg, "slow_response_seconds", None)
        logger.info(
            "Configuring NvidiaProvider with model {} (max_tokens={})",
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
                degraded_failure_threshold=use_degraded_threshold,
                degraded_cooldown_seconds=use_degraded_cooldown,
                degraded_probe_timeout_seconds=use_degraded_probe_timeout,
                degraded_window_size=use_degraded_window,
                slow_response_seconds=use_slow_response_seconds,
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

        logger.info("Configuring GeminiProvider with model {}", use_gemini_model)
        providers.append(
            GeminiProvider(
                api_key=gemini_api_key,
                model=use_gemini_model,
                timeout=timeout,
                max_retries=max_retries,
            )
        )

    # Priority 3: extra OpenAI-compatible endpoints, then optional reordering
    providers.extend(_build_endpoint_providers(cfg, nvidia_cfg))
    llm_cfg = getattr(cfg, "llm", None)
    purpose_chains = getattr(llm_cfg, "purpose_chains", None)
    chain_order = getattr(llm_cfg, "chain", None)
    if isinstance(purpose_chains, dict) and purpose_chains.get(purpose):
        chain_order = purpose_chains[purpose]
    providers = _apply_chain_order(providers, chain_order)

    # Priority 4: Ollama (local)
    # Always include Ollama as the final fallback
    ollama_cfg = getattr(cfg, "ollama", None)
    default_ollama_model = getattr(ollama_cfg, "model", "qwen2.5:32b")
    use_ollama_model = model or default_ollama_model
    # If the requested model is a cloud model, fallback to the local default model
    if use_ollama_model and (
        "/" in str(use_ollama_model) or "gemini" in str(use_ollama_model).lower()
    ):
        use_ollama_model = default_ollama_model

    logger.info("Configuring OllamaProvider with model {}", use_ollama_model)
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
            "Returning FallbackProvider with chain: {}",
            [p.__class__.__name__ for p in providers],
        )
        return FallbackProvider(providers, purpose=purpose)

    return providers[0]
