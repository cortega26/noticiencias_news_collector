#!/usr/bin/env python3
"""Bounded, sanitized canary for the source-aware Stage-4 editorial critic.

Runs one synthetic article through the *real* ``EditorAgent._critic_editorial_pass``
(including its real prompt construction, JSON extraction and verdict parser)
and prints a single sanitized evidence record. It exists because deterministic
tests cannot prove that the configured provider returns a parseable
``editor_critic`` verdict in production (issue #366).

Design constraints (plan 154):

- No paid call by default: ``--provider local`` talks to the local Ollama
  endpoint only. ``--provider configured`` uses the app's provider chain and is
  never run automatically.
- No prompt/token/key/raw-response output. Only booleans, counts, model ids and
  the seven safe criterion scores can reach stdout.
- ``UNVERIFIED`` (transport or parse failure) is distinct from ``PASS``/``FAIL``
  and can never be read as approval. The critic fails open internally, so this
  script explicitly inspects whether a verdict was actually parsed.
- No article database, publication or artifact writes. The production
  ``EditorAgent.__init__`` creates a cache directory, so the script binds the
  real critic method to an uninitalized instance instead of constructing it.

Usage::

    .venv/bin/python scripts/editorial_critic_canary.py --provider local
    .venv/bin/python scripts/editorial_critic_canary.py --provider configured --require-keys

Exit codes: 0 = PASS, 1 = FAIL (valid verdict that rejects the article),
2 = UNVERIFIED (transport/parse/internal failure), 3 = configuration error.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - deliberate: fixed git argv, no shell, bounded timeout
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # support `python scripts/...` execution

PASS_EXIT = 0
FAIL_EXIT = 1
UNVERIFIED_EXIT = 2
CONFIG_ERROR_EXIT = 3

_SYNTHETIC_TITLE = "[CANARY SINTÉTICO 154] Agua líquida bajo la corteza de Marte"

_SYNTHETIC_SOURCE = """MATERIAL SINTÉTICO DE PRUEBA (no es una noticia real).

Un equipo de investigación publicó un estudio simulado sobre señales de radar
que podrían indicar agua líquida en una zona profunda de la corteza marciana.
El texto describe la muestra de datos, el método de análisis y sus límites: no
se trata de una observación directa, sino de una interpretación compatible con
varias explicaciones alternativas. La fuente sintética insiste en que el
resultado es preliminar y requiere verificación independiente.
"""

_SYNTHETIC_DRAFT = """---
title: "Agua líquida bajo la corteza de Marte: una pista preliminar"
category: "ciencia"
---

# Agua líquida bajo la corteza de Marte: una pista preliminar

Un equipo de investigación presentó un análisis de datos de radar que podría
ser compatible con agua líquida bajo una capa profunda de la corteza marciana.
El hallazgo es preliminar y no equivale a una observación directa del líquido.

## Qué encontraron

Las señales analizadas muestran un patrón que, según el equipo, encaja con la
presencia de un material muy reflectante a varios kilómetros de profundidad.
Los autores compararon ese patrón con respuestas conocidas de hielo, rocas y
salmuera en condiciones de laboratorio.

## Por qué importa

Si se confirma, el resultado ampliaría los ambientes que podrían albergar agua
en Marte. También ayudaría a elegir futuros sitios de exploración con mayor
precisión.

## Qué falta

La interpretación depende de un modelo geológico y de datos de calibración
limitados. Los propios autores advierten que otras combinaciones de materiales
pueden producir señales parecidas, por lo que el resultado necesita nuevas
mediciones independientes antes de considerarse una confirmación.

ARTÍCULO SINTÉTICO DE PRUEBA (CANARY 154): no describe un hallazgo real.
"""

_SYNTHETIC_CONTEXT = {
    "title": _SYNTHETIC_TITLE,
    "summary": "Estudio simulado sobre una posible señal de agua líquida en Marte.",
    "source_name": "Fuente sintética de canary (no real)",
    "source_url": "https://canary.invalid/plan-154",
    "category": "ciencia",
    "article_type": "noticia",
    "content_mode": "full_text",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token|auth)=)[^&\s\"']+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"\b(?:"
        r"sk-[A-Za-z0-9_-]{8,}"
        r"|nvapi-[A-Za-z0-9_-]{8,}"
        r"|AIza[0-9A-Za-z_-]{20,}"
        r"|gh[pousr]_[A-Za-z0-9]{20,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}"
        r")\b"
    ),
)


class CanaryConfigError(RuntimeError):
    """Configuration problem: exit 3, never evidence of approval."""


@dataclass(frozen=True)
class CriticObservation:
    """Side-effect-free summary of one real critic invocation."""

    verdict: dict[str, Any] | None
    transport_ok: bool
    json_parsed: bool
    error_kind: str | None
    latency_ms: int
    model: str
    provider_chain: tuple[str, ...] = ()
    error_class: str | None = None
    response_chars: int = 0


class _ArgumentParser(argparse.ArgumentParser):
    """Turn argparse usage errors into exit-3 configuration errors."""

    def error(self, message: str) -> NoReturn:
        raise CanaryConfigError(message)


def redact_text(text: str) -> str:
    """Mask anything that looks like a credential before it reaches stdout."""

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1) if match.groups() else ""
        return f"{prefix}[REDACTED]"

    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_replace, redacted)
    return redacted


def sanitize(value: Any) -> Any:
    """Recursively redact string values; evidence is data-only by design."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def safe_verdict_fields(verdict: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project a verdict onto non-sensitive fields (never feedback/prompt text)."""
    if not isinstance(verdict, dict):
        return None

    fields: dict[str, Any] = {}
    approved = verdict.get("approved")
    if type(approved) is bool:
        fields["approved"] = approved

    average = verdict.get("average")
    if isinstance(average, (int, float)) and not isinstance(average, bool):
        fields["average"] = round(float(average), 2)

    scores = verdict.get("scores")
    if isinstance(scores, dict):
        safe_scores = {
            str(key): value
            for key, value in scores.items()
            if re.fullmatch(r"[a-z_]{1,40}", str(key))
            and type(value) is int
            and 0 <= value <= 10
        }
        if safe_scores:
            fields["scores"] = safe_scores

    # PR #373 may add a structured value-add field; expose only its shape.
    value_add = verdict.get("value_add_assessment")
    if type(value_add) is bool:
        fields["value_add_assessment"] = value_add
    elif isinstance(value_add, (int, float)) and not isinstance(value_add, bool):
        fields["value_add_assessment"] = value_add
    elif isinstance(value_add, str):
        fields["value_add_assessment_chars"] = len(value_add)

    return fields or None


def classify(observation: CriticObservation) -> tuple[str, int]:
    """Map an observation to (status, exit code); UNVERIFIED is never PASS."""
    if observation.error_kind is not None:
        return "UNVERIFIED", UNVERIFIED_EXIT
    if not observation.transport_ok or not observation.json_parsed:
        return "UNVERIFIED", UNVERIFIED_EXIT
    if not isinstance(observation.verdict, dict):
        return "UNVERIFIED", UNVERIFIED_EXIT

    approved = observation.verdict.get("approved")
    if approved is True:
        return "PASS", PASS_EXIT
    if approved is False:
        return "FAIL", FAIL_EXIT
    return "UNVERIFIED", UNVERIFIED_EXIT


def build_evidence(
    observation: CriticObservation,
    *,
    provider: str,
    git_sha: str,
) -> dict[str, Any]:
    """Build the sanitized, issue #366-shaped evidence record."""
    status, _ = classify(observation)
    return sanitize(
        {
            "status": status,
            "synthetic": True,
            "git_sha": git_sha,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "environment": {
                "python": platform.python_version(),
                "platform": sys.platform,
            },
            "provider": provider,
            "model": observation.model,
            "provider_chain": list(observation.provider_chain),
            "transport_ok": observation.transport_ok,
            "json_parsed": observation.json_parsed,
            "verdict_fields": safe_verdict_fields(observation.verdict),
            "latency_ms": observation.latency_ms,
            "response_chars": observation.response_chars,
            "error_kind": observation.error_kind,
            "error_class": observation.error_class,
        }
    )


def _git_sha() -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    try:
        result = subprocess.run(
            [git, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"


def _contain_import_side_effects() -> None:
    """Keep app imports from writing logs or LLM attempt metrics.

    Importing ``news_collector`` configures loguru with a stdout sink and a
    rotating file sink, and installs an LLM metrics sink. The canary must emit
    only JSON on stdout and must not write evidence/operational files, so the
    log file is sent to the null device and metrics persistence is disabled for
    this process. The caller removes the remaining loguru handlers afterwards.
    """
    os.environ["NOTICIENCIAS__LOGGING__FILE_PATH"] = os.devnull
    os.environ["LOG_LEVEL"] = "CRITICAL"
    os.environ["NOTICIENCIAS_LLM_METRICS"] = "0"


class _RecordingProvider:
    """Delegate to the real provider while recording transport outcome."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0
        self.response_chars = 0
        self.error_class: str | None = None

    def generate_sync(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        try:
            result = self._inner.generate_sync(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self.error_class = type(exc).__name__
            raise
        if isinstance(result, str):
            self.response_chars = len(result)
            return result
        if isinstance(result, dict):
            return result
        return self._recording_stream(result)

    def _recording_stream(self, stream: Any) -> Any:
        try:
            for chunk in stream:
                self.response_chars += len(chunk)
                yield chunk
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self.error_class = type(exc).__name__
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _load_runtime() -> Any:
    """Load app config without touching article storage or the cache dir."""
    from noticiencias.config_manager import load_config

    return load_config()


def _provider_chain(provider: Any) -> list[Any]:
    return list(getattr(provider, "providers", [provider]))


def _build_provider(
    cfg: Any, provider_mode: str, timeout: int
) -> tuple[Any, str, tuple[str, ...]]:
    """Build a real provider and the editor model id, without a cache dir."""
    from news_collector.infrastructure.llm.attempts import provider_name
    from news_collector.infrastructure.llm.factory import FallbackProvider, get_provider
    from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
    from news_collector.infrastructure.llm.model_registry import (
        resolve_ollama_stage_models,
    )
    from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider
    from news_collector.infrastructure.llm.provider import OllamaProvider

    try:
        resolved = resolve_ollama_stage_models(cfg)
    except Exception as exc:  # noqa: BLE001 - config problem, not transport
        raise CanaryConfigError(
            f"Ollama model resolution failed: {type(exc).__name__}"
        ) from exc

    if provider_mode == "local":
        provider: Any = OllamaProvider(
            api_url=getattr(cfg.ollama, "api_url", None),
            model=resolved["editor"],
            timeout=timeout,
        )
        chain = _provider_chain(provider)
        return provider, resolved["editor"], tuple(provider_name(p) for p in chain)

    provider = get_provider(
        purpose="editing",
        config=cfg,
        api_url=getattr(cfg.ollama, "api_url", None),
        model=resolved["default"],
        timeout=timeout,
        max_tokens=32768,
    )
    chain = _provider_chain(provider)
    primary = chain[0] if chain else provider
    is_cloud = isinstance(primary, (NvidiaProvider, GeminiProvider))
    if isinstance(provider, FallbackProvider) and chain:
        is_cloud = isinstance(chain[0], (NvidiaProvider, GeminiProvider))
    editor_model = getattr(provider, "model", None) if is_cloud else resolved["editor"]
    return (
        provider,
        editor_model or resolved["editor"],
        tuple(provider_name(p) for p in chain),
    )


def _raise_on_missing_keys(provider: Any) -> None:
    from news_collector.infrastructure.llm.attempts import provider_name

    names = [provider_name(p) for p in _provider_chain(provider)]
    if not any(name != "ollama" for name in names):
        raise CanaryConfigError(
            "--require-keys: configured provider chain has no credentialed "
            "(non-Ollama) provider"
        )


def _no_call_error_kind(agent: Any, body: str) -> str:
    if os.getenv("ENABLE_EDITORIAL_CRITIC", "true").lower() == "false":
        return "critic_disabled"
    if not agent.prompts.get("editor_critic", {}).get("system"):
        return "prompt_missing"
    if not body:
        return "empty_body"
    return "no_request"


def _invoke_critic(agent: Any) -> None:
    """Call the real critic, discarding its progress ``print`` chatter.

    ``EditorAgent._send_prompt`` prints to stdout; the evidence record is the
    only thing this CLI may emit, so the call runs under a redirected stdout
    whose buffer is discarded (never read, logged or printed).
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        agent._critic_editorial_pass(  # noqa: SLF001 - real seam under test
            _SYNTHETIC_DRAFT,
            _SYNTHETIC_CONTEXT,
            _SYNTHETIC_SOURCE,
        )


def _run_real(
    *,
    provider_mode: str,
    timeout: int,
    require_keys: bool,
) -> CriticObservation:
    """Invoke the real critic once and return a sanitized observation."""
    _contain_import_side_effects()
    from loguru import logger as loguru_logger

    try:
        cfg = _load_runtime()

        from news_collector.components.editorial.ai_editor import (
            EditorAgent,
            _extract_publishable_body,
        )

        provider, editor_model, chain_names = _build_provider(
            cfg, provider_mode, timeout
        )
    finally:
        # Importing ``news_collector`` configures loguru (stdout + file). Drop
        # every sink so no log line, including the critic's debug response
        # preview, can escape the process.
        loguru_logger.remove()

    if require_keys:
        _raise_on_missing_keys(provider)

    recorder = _RecordingProvider(provider)

    # Bind the real critic to an *uninitialized* EditorAgent: __init__ creates
    # data/cache/editor, and the canary must not write files. Only the
    # attributes read by _critic_editorial_pass are set.
    agent = object.__new__(EditorAgent)
    agent.prompts = EditorAgent._load_prompts(agent)
    agent.editor_model = editor_model
    agent.provider = recorder
    agent.last_critic_verdict = None

    started = time.monotonic()
    _invoke_critic(agent)
    latency_ms = int(round((time.monotonic() - started) * 1000))

    verdict = agent.last_critic_verdict
    if isinstance(verdict, dict):
        error_kind = None
    elif recorder.calls == 0:
        error_kind = _no_call_error_kind(
            agent, _extract_publishable_body(_SYNTHETIC_DRAFT)
        )
    elif recorder.error_class is not None:
        error_kind = "transport_error"
    else:
        error_kind = "parse_error"

    return CriticObservation(
        verdict=verdict if isinstance(verdict, dict) else None,
        transport_ok=recorder.error_class is None and recorder.calls > 0,
        json_parsed=isinstance(verdict, dict),
        error_kind=error_kind,
        latency_ms=latency_ms,
        model=editor_model,
        provider_chain=chain_names,
        error_class=recorder.error_class,
        response_chars=recorder.response_chars,
    )


def _format_human(evidence: dict[str, Any]) -> str:
    verdict_fields = evidence.get("verdict_fields")
    lines = [
        f"Editorial critic canary: {evidence['status']}",
        (
            f"provider={evidence['provider']} model={evidence['model']} "
            f"chain={','.join(evidence['provider_chain']) or 'unknown'}"
        ),
        (
            f"transport_ok={evidence['transport_ok']} "
            f"json_parsed={evidence['json_parsed']} "
            f"latency_ms={evidence['latency_ms']}"
        ),
        f"verdict_fields={json.dumps(verdict_fields, ensure_ascii=False)}",
        (
            f"response_chars={evidence['response_chars']} "
            f"error_kind={evidence['error_kind']} "
            f"error_class={evidence['error_class']}"
        ),
        f"git_sha={evidence['git_sha']}",
    ]
    return "\n".join(lines)


def _emit(evidence: dict[str, Any], *, human: bool) -> None:
    if human:
        print(_format_human(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def _config_error_evidence(error: CanaryConfigError) -> dict[str, Any]:
    observation = CriticObservation(
        verdict=None,
        transport_ok=False,
        json_parsed=False,
        error_kind="config_error",
        latency_ms=0,
        model="unknown",
        provider_chain=(),
    )
    evidence = build_evidence(observation, provider="unknown", git_sha=_git_sha())
    evidence["error"] = redact_text(str(error))[:300]
    return sanitize(evidence)


def _internal_error_evidence(exc: Exception) -> dict[str, Any]:
    observation = CriticObservation(
        verdict=None,
        transport_ok=False,
        json_parsed=False,
        error_kind="internal_error",
        latency_ms=0,
        model="unknown",
        provider_chain=(),
    )
    evidence = build_evidence(observation, provider="unknown", git_sha=_git_sha())
    evidence["error_class"] = type(exc).__name__
    return sanitize(evidence)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Bounded Stage-4 editorial critic canary (plan 154)."
    )
    parser.add_argument(
        "--provider",
        choices=("local", "configured"),
        default="local",
        help=(
            "local = local Ollama only (default, free); configured = the app's "
            "real provider chain (can cost money)."
        ),
    )
    parser.add_argument(
        "--require-keys",
        action="store_true",
        help="exit 3 when --provider configured has no credentialed provider.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="provider timeout in seconds (default: 180).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one sanitized JSON object (default).",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="emit a short human-readable summary instead of JSON.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    critic_runner: Callable[..., CriticObservation] | None = None,
) -> int:
    """CLI entry point; ``critic_runner`` is an injection seam for tests."""
    try:
        args = _build_parser().parse_args(argv)
        if args.json and args.human:
            raise CanaryConfigError("--json and --human are mutually exclusive")
        if args.require_keys and args.provider == "local":
            raise CanaryConfigError(
                "--require-keys only applies to --provider configured"
            )
        if args.timeout <= 0:
            raise CanaryConfigError("--timeout must be a positive number of seconds")

        runner = critic_runner or _run_real
        observation = runner(
            provider_mode=args.provider,
            timeout=args.timeout,
            require_keys=args.require_keys,
        )
    except CanaryConfigError as exc:
        evidence = _config_error_evidence(exc)
        _emit(evidence, human=bool(argv and "--human" in argv))
        return CONFIG_ERROR_EXIT
    except Exception as exc:  # noqa: BLE001 - CLI must never crash without evidence
        evidence = _internal_error_evidence(exc)
        _emit(evidence, human=bool(argv and "--human" in argv))
        return UNVERIFIED_EXIT

    evidence = build_evidence(observation, provider=args.provider, git_sha=_git_sha())
    _, exit_code = classify(observation)
    _emit(evidence, human=args.human)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
