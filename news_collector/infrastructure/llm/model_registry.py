"""Centralized Ollama model policy, precedence, and stage routing."""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping

import requests
from news_collector.infrastructure.llm.ollama_errors import build_ollama_http_error
from news_collector.utils.logger import get_logger

LOGGER = get_logger().create_module_logger(__name__)

DEFAULT_STAGE = "default"
DEFAULT_BASE_MODEL = "qwen2.5:32b"
DEFAULT_SCORING_MODEL = "qwen2.5:32b"

ALL_STAGES: tuple[str, ...] = (
    DEFAULT_STAGE,
    "translator",
    "editor",
    "headlines",
    "auditor",
    "pre_scorer",
    "classifier",
    "council",
    "scoring",
)
SUPPORTED_STAGES = set(ALL_STAGES)

_STAGE_OVERRIDE_PATH: dict[str, str | None] = {
    "translator": "ollama.translator_model",
    "editor": "ollama.editor_model",
    "headlines": "ollama.headlines_model",
    "auditor": "ollama.model",
    "pre_scorer": "scoring.llm_model",
    "classifier": "ollama.editor_model",
    "council": "ollama.editor_model",
    "scoring": "scoring.llm_model",
}

_MODEL_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}:[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"
_NORMALIZATION_LOGGED: set[tuple[str, str, str]] = set()
_INHERITANCE_LOGGED: set[tuple[str, str]] = set()
_MODEL_MAP_LOGGED: set[str] = set()


class ModelRegistryError(ValueError):
    """Base class for model registry failures."""


class UnknownModelStageError(ModelRegistryError):
    """Raised when requesting a stage that is not mapped."""


class MissingModelConfigurationError(ModelRegistryError):
    """Raised when a required model value is missing."""


class InvalidModelIdError(ModelRegistryError):
    """Raised when a model identifier is malformed."""


class NonCanonicalModelIdError(InvalidModelIdError):
    """Raised in strict mode when an id would require normalization."""


class ModelAvailabilityError(ModelRegistryError):
    """Raised when required models are unavailable in Ollama."""


class NoWarnPolicyViolationError(ModelRegistryError):
    """Raised when NO_WARN mode forbids inherited/normalized resolution."""


class ModelSource(str, Enum):
    ENV = "ENV"
    CONFIG = "CONFIG"
    DEFAULT = "DEFAULT"
    INHERITED = "INHERITED"


@dataclass(frozen=True)
class ModelPolicy:
    normalize_missing_tag: bool
    pinned_mode: bool
    strict_mode: bool
    no_warn_mode: bool


@dataclass(frozen=True)
class ResolvedModel:
    stage: str
    model_id: str
    source: ModelSource
    raw_value: str | None
    normalized: bool
    inherited: bool
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "model_id": self.model_id,
            "source": self.source.value,
            "raw_value": self.raw_value,
            "normalized": self.normalized,
            "inherited": self.inherited,
            "notes": self.notes,
        }


ResolvedModelMap = dict[str, ResolvedModel]


_PROVENANCE_SOURCE_MAP = {
    "env": ModelSource.ENV,
    "env-file": ModelSource.ENV,
    "legacy_env_file": ModelSource.ENV,
    "legacy_env": ModelSource.ENV,
    "file": ModelSource.CONFIG,
    "defaults": ModelSource.DEFAULT,
}


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_policy(
    *,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> ModelPolicy:
    env_pinned = _is_truthy(os.getenv("NOTICIENCIAS_LLM_PINNED"))
    env_strict = _is_truthy(os.getenv("NOTICIENCIAS_LLM_STRICT"))
    env_no_warn = _is_truthy(os.getenv("NOTICIENCIAS_LLM_NO_WARN"))

    pinned = env_pinned if pinned_mode is None else pinned_mode
    strict = env_strict if strict_mode is None else strict_mode
    no_warn = env_no_warn if no_warn_mode is None else no_warn_mode
    strict = strict or pinned

    return ModelPolicy(
        normalize_missing_tag=not pinned,
        pinned_mode=pinned,
        strict_mode=strict,
        no_warn_mode=no_warn,
    )


def is_pinned_mode_enabled() -> bool:
    return resolve_policy().pinned_mode


def is_strict_mode_enabled() -> bool:
    return resolve_policy().strict_mode


def is_no_warn_mode_enabled() -> bool:
    return resolve_policy().no_warn_mode


def get_all_stages() -> tuple[str, ...]:
    return ALL_STAGES


def _get_value(container: Any, key: str, default: Any = None) -> Any:
    if container is None:
        return default
    if isinstance(container, Mapping):
        return container.get(key, default)
    return getattr(container, key, default)


def _get_nested_value(container: Any, dotted_path: str, default: Any = None) -> Any:
    current = container
    for segment in dotted_path.split("."):
        current = _get_value(current, segment, default)
        if current is default:
            return default
    return current


def _get_provenance_layers(config: Any) -> dict[str, str]:
    metadata = getattr(config, "_metadata", None)
    provenance = getattr(metadata, "provenance", None)
    if not isinstance(provenance, Mapping):
        return {}
    result: dict[str, str] = {}
    for path, origin in provenance.items():
        layer = getattr(origin, "layer", None)
        if isinstance(path, str) and isinstance(layer, str):
            result[path] = layer
    return result


def _source_for_path(
    path: str,
    *,
    has_explicit_value: bool,
    provenance_layers: Mapping[str, str],
) -> ModelSource:
    layer = provenance_layers.get(path)
    if layer is not None:
        return _PROVENANCE_SOURCE_MAP.get(layer, ModelSource.CONFIG)
    if has_explicit_value:
        return ModelSource.CONFIG
    return ModelSource.DEFAULT


def _canonicalize_model_id_with_meta(
    model_id: str | None,
    *,
    stage: str,
    policy: ModelPolicy,
) -> tuple[str, bool]:
    if model_id is None:
        raise MissingModelConfigurationError(
            f"Missing Ollama model for stage '{stage}'. Configure it in config.toml "
            f"or via env (NOTICIENCIAS__OLLAMA__MODEL / stage override)."
        )

    value = str(model_id)
    if value == "":
        raise MissingModelConfigurationError(
            f"Empty Ollama model for stage '{stage}'. Set a value like "
            "'qwen2.5:32b'."
        )
    if value != value.strip() or any(char.isspace() for char in value):
        raise InvalidModelIdError(
            f"Invalid Ollama model for stage '{stage}': {value!r}. "
            "Whitespace is not allowed. Use '<model>:<tag>' "
            "(example: 'qwen2.5:32b')."
        )

    normalized = False
    canonical = value
    if ":" not in canonical:
        if policy.pinned_mode:
            raise InvalidModelIdError(
                f"Pinned mode forbids untagged model for stage '{stage}': {value!r}. "
                "Use a pinned tag like 'qwen2.5:32b' or 'llama3.3:70b'."
            )
        if policy.strict_mode:
            raise NonCanonicalModelIdError(
                f"Strict mode forbids implicit ':latest' normalization for stage '{stage}' "
                f"(received {value!r}). Use '<model>:<tag>'."
            )
        canonical = f"{canonical}:latest"
        normalized = True

    if canonical.count(":") != 1:
        raise InvalidModelIdError(
            f"Invalid Ollama model for stage '{stage}': {value!r}. "
            "Expected exactly one ':' separator in '<model>:<tag>'."
        )

    if policy.pinned_mode and canonical.endswith(":latest"):
        raise InvalidModelIdError(
            f"Pinned mode forbids ':latest' for stage '{stage}' (received {value!r}). "
            "Pin an immutable tag like ':32b' or ':70b'."
        )

    import re

    if not re.match(_MODEL_PATTERN, canonical):
        raise InvalidModelIdError(
            f"Invalid Ollama model for stage '{stage}': {value!r}. "
            "Allowed characters are letters, numbers, '.', '_', '-', '/', and one ':'. "
            "Example: 'qwen2.5:32b'."
        )
    return canonical, normalized


def canonicalize_model_id(
    model_id: str | None,
    *,
    stage: str,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> str:
    policy = resolve_policy(
        pinned_mode=pinned_mode,
        strict_mode=strict_mode,
        no_warn_mode=no_warn_mode,
    )
    canonical, normalized = _canonicalize_model_id_with_meta(
        model_id,
        stage=stage,
        policy=policy,
    )
    if normalized:
        resolved_logger = logger or LOGGER
        raw = str(model_id)
        log_key = (stage, raw, canonical)
        if log_key not in _NORMALIZATION_LOGGED:
            resolved_logger.info(
                f"Normalized Ollama model for stage '{stage}': '{raw}' -> '{canonical}'"
            )
            _NORMALIZATION_LOGGED.add(log_key)
    return canonical


def _serialize_map_for_logging(
    resolved_map: ResolvedModelMap,
) -> dict[str, dict[str, Any]]:
    return {
        stage: resolved_map[stage].to_dict() for stage in sorted(resolved_map.keys())
    }


def resolve_ollama_model_map(  # noqa: C901
    config: Any,
    *,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> ResolvedModelMap:
    """
    Resolve canonical model ids with explicit policy and provenance metadata.

    Allowed:
    - Stage unset -> inherit base model, but only with `source=INHERITED` and explicit notes.
    - Missing tag -> normalize to `:latest` only in default mode (never in strict/pinned).

    Forbidden:
    - Any implicit stage fallback not represented in the returned map.
    - Any normalization bypassing this resolver.
    """

    policy = resolve_policy(
        pinned_mode=pinned_mode,
        strict_mode=strict_mode,
        no_warn_mode=no_warn_mode,
    )
    provenance_layers = _get_provenance_layers(config)

    base_raw = _get_nested_value(config, "ollama.model", default=None)
    has_base = base_raw is not None
    effective_base_raw = base_raw if has_base else DEFAULT_BASE_MODEL
    base_source = _source_for_path(
        "ollama.model",
        has_explicit_value=has_base,
        provenance_layers=provenance_layers,
    )
    base_model, base_normalized = _canonicalize_model_id_with_meta(
        effective_base_raw,
        stage=DEFAULT_STAGE,
        policy=policy,
    )
    resolved_map: ResolvedModelMap = {
        DEFAULT_STAGE: ResolvedModel(
            stage=DEFAULT_STAGE,
            model_id=base_model,
            source=base_source,
            raw_value=None if not has_base else str(base_raw),
            normalized=base_normalized,
            inherited=False,
            notes=None,
        )
    }

    if base_normalized:
        raw = str(effective_base_raw)
        log_key = (DEFAULT_STAGE, raw, base_model)
        resolved_logger = logger or LOGGER
        if log_key not in _NORMALIZATION_LOGGED:
            resolved_logger.info(
                f"Normalized Ollama model for stage '{DEFAULT_STAGE}': '{raw}' -> '{base_model}'"
            )
            _NORMALIZATION_LOGGED.add(log_key)

    for stage in (s for s in ALL_STAGES if s != DEFAULT_STAGE):
        override_path = _STAGE_OVERRIDE_PATH.get(stage)
        if override_path is None:
            inherited_model = base_model
            resolved_map[stage] = ResolvedModel(
                stage=stage,
                model_id=inherited_model,
                source=ModelSource.INHERITED,
                raw_value=None,
                normalized=False,
                inherited=True,
                notes=f"inherited from '{DEFAULT_STAGE}'",
            )
        else:
            override_raw = _get_nested_value(config, override_path, default=None)
            has_override = override_raw is not None
            if not has_override and stage in {"scoring", "pre_scorer"}:
                override_raw = DEFAULT_SCORING_MODEL
                has_override = False
            if has_override:
                source = _source_for_path(
                    override_path,
                    has_explicit_value=True,
                    provenance_layers=provenance_layers,
                )
                canonical, normalized = _canonicalize_model_id_with_meta(
                    override_raw,
                    stage=stage,
                    policy=policy,
                )
                resolved_map[stage] = ResolvedModel(
                    stage=stage,
                    model_id=canonical,
                    source=source,
                    raw_value=str(override_raw),
                    normalized=normalized,
                    inherited=False,
                    notes=None,
                )
                if normalized:
                    raw = str(override_raw)
                    log_key = (stage, raw, canonical)
                    resolved_logger = logger or LOGGER
                    if log_key not in _NORMALIZATION_LOGGED:
                        resolved_logger.info(
                            f"Normalized Ollama model for stage '{stage}': '{raw}' -> '{canonical}'"
                        )
                        _NORMALIZATION_LOGGED.add(log_key)
            else:
                inherited_model = base_model
                resolved_map[stage] = ResolvedModel(
                    stage=stage,
                    model_id=inherited_model,
                    source=ModelSource.INHERITED,
                    raw_value=None,
                    normalized=False,
                    inherited=True,
                    notes=f"inherited from '{DEFAULT_STAGE}'",
                )

        if resolved_map[stage].inherited:
            inheritance_log_key = (stage, resolved_map[stage].model_id)
            resolved_logger = logger or LOGGER
            if inheritance_log_key not in _INHERITANCE_LOGGED:
                resolved_logger.info(
                    f"Inherited Ollama model for stage '{stage}' from '{DEFAULT_STAGE}': '{resolved_map[stage].model_id}'"
                )
                _INHERITANCE_LOGGED.add(inheritance_log_key)

    missing_stages = [stage for stage in ALL_STAGES if stage not in resolved_map]
    if missing_stages:
        raise ModelRegistryError(
            "Model registry stage coverage failure. Missing resolved stage(s): "
            f"{missing_stages}. Ensure ALL_STAGES and _STAGE_OVERRIDE_PATH stay in sync."
        )

    if policy.no_warn_mode:
        violations: list[str] = []
        for stage in ALL_STAGES:
            item = resolved_map[stage]
            if item.normalized:
                raw = item.raw_value if item.raw_value is not None else item.model_id
                violations.append(f"- {stage}: normalized {raw!r} -> {item.model_id!r}")
            if item.inherited:
                violations.append(
                    f"- {stage}: inherited from '{DEFAULT_STAGE}' -> {item.model_id!r}"
                )
        if violations:
            details = "\n".join(violations)
            raise NoWarnPolicyViolationError(
                "NO_WARN mode forbids model normalization/inheritance.\n"
                f"Violations:\n{details}\n"
                "Remediation: define explicit canonical '<model>:<tag>' values for all "
                "stages (directly or via mapped override paths), or disable "
                "NOTICIENCIAS_LLM_NO_WARN."
            )

    resolved_logger = logger or LOGGER
    serialized_map = _serialize_map_for_logging(resolved_map)
    signature = json.dumps(serialized_map, sort_keys=True, separators=(",", ":"))
    if signature not in _MODEL_MAP_LOGGED:
        resolved_logger.info(f"Resolved Ollama model map: {signature}")
        _MODEL_MAP_LOGGED.add(signature)

    return resolved_map


def get_resolved_model_map_data(
    config: Any,
    *,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> dict[str, dict[str, Any]]:
    return _serialize_map_for_logging(
        resolve_ollama_model_map(
            config,
            logger=logger,
            pinned_mode=pinned_mode,
            strict_mode=strict_mode,
            no_warn_mode=no_warn_mode,
        )
    )


def resolve_ollama_stage_models(
    config: Any,
    *,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> Dict[str, str]:
    resolved_map = resolve_ollama_model_map(
        config,
        logger=logger,
        pinned_mode=pinned_mode,
        strict_mode=strict_mode,
        no_warn_mode=no_warn_mode,
    )
    return {stage: item.model_id for stage, item in resolved_map.items()}


def get_model_for_stage(
    stage: str,
    *,
    config: Any,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> str:
    if stage not in SUPPORTED_STAGES:
        supported = ", ".join(ALL_STAGES)
        raise UnknownModelStageError(
            f"Unknown Ollama stage '{stage}'. Register this stage in model_registry.py "
            "ALL_STAGES and _STAGE_OVERRIDE_PATH, then configure its model source. "
            f"Supported stages: {supported}."
        )
    resolved = resolve_ollama_stage_models(
        config,
        logger=logger,
        pinned_mode=pinned_mode,
        strict_mode=strict_mode,
        no_warn_mode=no_warn_mode,
    )
    return resolved[stage]


def preflight_ollama_models(
    config: Any,
    *,
    check_availability: bool = False,
    check_generation: bool = False,
    timeout_seconds: int = 5,
    probe_timeout_seconds: int | None = None,
    logger: logging.Logger | None = None,
    pinned_mode: bool | None = None,
    strict_mode: bool | None = None,
    no_warn_mode: bool | None = None,
) -> Dict[str, str]:
    resolved = resolve_ollama_stage_models(
        config,
        logger=logger,
        pinned_mode=pinned_mode,
        strict_mode=strict_mode,
        no_warn_mode=no_warn_mode,
    )
    if not check_availability and not check_generation:
        return resolved

    ollama_cfg = _get_value(config, "ollama")
    api_url = str(_get_value(ollama_cfg, "api_url", "http://localhost:11434"))
    clean = api_url.rstrip("/")
    if clean.endswith("/api/generate"):
        base_url = clean[: -len("/api/generate")]
    else:
        base_url = clean.split("/api/")[0]

    required = set(resolved.values())
    if check_availability:
        tags_url = f"{base_url}/api/tags"
        try:
            response = requests.get(tags_url, timeout=timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ModelAvailabilityError(
                f"Ollama preflight failed to reach {tags_url}: {exc}"
            ) from exc

        models = response.json().get("models", [])
        available = {m.get("name") for m in models if m.get("name")}
        missing = sorted(model for model in required if model not in available)
        if missing:
            raise ModelAvailabilityError(
                "Ollama preflight missing required model(s): "
                f"{missing}. Pull them first (example: `ollama pull <model>:<tag>`)."
            )

    if check_generation:
        generate_url = f"{base_url}/api/generate"
        effective_probe_timeout = probe_timeout_seconds or max(timeout_seconds, 30)
        for model_name in sorted(required):
            payload = {
                "model": model_name,
                "prompt": "ping",
                "stream": False,
                "options": {"num_ctx": 1, "num_predict": 1},
            }
            try:
                response = requests.post(
                    generate_url, json=payload, timeout=effective_probe_timeout
                )
            except requests.RequestException as exc:
                raise ModelAvailabilityError(
                    f"Ollama generate probe failed for model '{model_name}' at "
                    f"{generate_url}: {exc}"
                ) from exc

            if response.status_code >= 400:
                provider_error = build_ollama_http_error(
                    response, model=str(model_name)
                )
                raise ModelAvailabilityError(
                    f"Ollama generate probe failed: {provider_error}"
                ) from provider_error

    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Noticiencias Ollama model identifiers."
    )
    parser.add_argument(
        "--check-availability",
        action="store_true",
        help="Also query Ollama /api/tags and verify model availability.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Timeout in seconds for availability check.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit resolved mapping as JSON.",
    )
    args = parser.parse_args(argv)

    from noticiencias.config_manager import load_config

    config = load_config()
    env_enabled = _is_truthy(os.getenv("NOTICIENCIAS_OLLAMA_PREFLIGHT"))
    check_availability = args.check_availability or env_enabled

    try:
        if check_availability:
            preflight_ollama_models(
                config,
                check_availability=True,
                timeout_seconds=args.timeout,
                logger=LOGGER,
            )
        resolved_data = get_resolved_model_map_data(config, logger=LOGGER)
    except ModelRegistryError as exc:
        print(f"OLLAMA_PREFLIGHT_FAILED: {exc}")
        return 1

    if args.json:
        print(json.dumps(resolved_data, indent=2, sort_keys=True))
    else:
        model_ids = {k: v["model_id"] for k, v in resolved_data.items()}
        print(
            "OLLAMA_PREFLIGHT_OK: "
            + ", ".join(f"{k}={v}" for k, v in sorted(model_ids.items()))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
