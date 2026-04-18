"""Shared Ollama HTTP error parsing and classification helpers."""

from __future__ import annotations

import json
import re
from typing import Any

_ADMISSION_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"requires more system memory", flags=re.IGNORECASE),
    re.compile(r"insufficient .*memory|not enough .*memory", flags=re.IGNORECASE),
    re.compile(r"out of memory", flags=re.IGNORECASE),
    re.compile(r"failed to load model", flags=re.IGNORECASE),
    re.compile(r"model .* not found", flags=re.IGNORECASE),
    re.compile(r"pull .* first", flags=re.IGNORECASE),
)


class OllamaProviderError(RuntimeError):
    """Structured Ollama error surfaced to callers."""

    def __init__(
        self,
        *,
        model: str | None,
        status_code: int | None,
        error_message: str,
        retryable: bool = False,
    ) -> None:
        self.model = model
        self.status_code = status_code
        self.error_message = error_message
        self.retryable = retryable

        prefix = "Ollama request failed"
        if model:
            prefix += f" for model '{model}'"
        if status_code is not None:
            prefix += f" (status {status_code})"

        detail = error_message.strip() or "Unknown Ollama error"
        super().__init__(f"{prefix}: {detail}")


class OllamaAdmissionError(OllamaProviderError):
    """Deterministic Ollama admission/model-load failure."""


def extract_ollama_error_message(response: Any) -> str:
    """Return the most specific error text available from an Ollama response."""
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if payload:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    text = getattr(response, "text", "")
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    normalized = " ".join(str(text).split()).strip()
    if normalized:
        return normalized

    status_code = getattr(response, "status_code", None)
    return f"HTTP {status_code}" if status_code is not None else "Unknown Ollama error"


def is_ollama_admission_error(message: str) -> bool:
    """Return True when the Ollama error is deterministic and not retryable."""
    normalized = message.strip()
    return any(pattern.search(normalized) for pattern in _ADMISSION_ERROR_PATTERNS)


def build_ollama_http_error(response: Any, *, model: str | None) -> OllamaProviderError:
    """Create a structured error from an Ollama HTTP response."""
    status_code = getattr(response, "status_code", None)
    error_message = extract_ollama_error_message(response)

    if is_ollama_admission_error(error_message):
        return OllamaAdmissionError(
            model=model,
            status_code=status_code,
            error_message=error_message,
            retryable=False,
        )

    retryable = bool(status_code is not None and status_code >= 500)
    return OllamaProviderError(
        model=model,
        status_code=status_code,
        error_message=error_message,
        retryable=retryable,
    )
