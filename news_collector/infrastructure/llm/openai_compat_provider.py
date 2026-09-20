"""Generic OpenAI-compatible chat provider (Groq, Cerebras, OpenRouter, ...).

Thin subclass of :class:`NvidiaProvider`: NIM speaks the standard
``/chat/completions`` protocol, so retries, JSON extraction, rate limiting and
the degradation window are reused unchanged. Only what differs per endpoint
lives here: the log label, extra headers, JSON-mode support and model
resolution (an endpoint always serves its own configured model — callers pass
Ollama-style tags that mean nothing to a remote API).

Keys are never stored in config: endpoints name an environment variable
(``api_key_env``) resolved by the factory.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider


class OpenAICompatProvider(NvidiaProvider):
    """Provider for any OpenAI-compatible ``/chat/completions`` endpoint."""

    # Free-tier endpoints 429 with long Retry-After windows (e.g. per-minute
    # token caps); the chain fails over and cools the provider down instead.
    _fail_fast_on_429 = True

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        extra_headers: Optional[Dict[str, str]] = None,
        json_mode_supported: bool = True,
        extra_body: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self._label = name
        self.extra_headers = dict(extra_headers or {})
        self.json_mode_supported = json_mode_supported
        self.extra_body = dict(extra_body or {})
        super().__init__(api_key=api_key, model=model, base_url=base_url, **kwargs)

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        """Text of the first choice; upstream errors become real exceptions.

        Gateways such as OpenRouter answer HTTP 200 with
        ``{"error": {"code": 503, ...}}`` and no ``choices`` when the upstream
        host fails. Reading that as blank text hid a transient failure behind
        an "empty response"; raising an HTTPError with the embedded status lets
        the normal retry/classification path (5xx, 429, auth) handle it.
        """
        error = data.get("error") if isinstance(data, dict) else None
        if error and not data.get("choices"):
            raw_code = error.get("code") if isinstance(error, dict) else None
            status = int(str(raw_code)) if str(raw_code).isdigit() else 502
            message = error.get("message") if isinstance(error, dict) else error
            response = requests.Response()
            response.status_code = status
            raise requests.HTTPError(
                f"upstream error {status}: {str(message)[:200]}", response=response
            )
        return NvidiaProvider._extract_text(data)

    def _resolve_model(self, model: Optional[str]) -> str:
        return self.model

    def _auth_headers(self) -> Dict[str, str]:
        headers = super()._auth_headers()
        headers.update(self.extra_headers)
        return headers

    def _prepare_payload(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        stream: bool = False,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = super()._prepare_payload(prompt, system, json_mode, stream, model)
        if not self.json_mode_supported:
            # Endpoint rejects ``response_format``; JSON is still extracted
            # from the text by ``_extract_json``.
            payload.pop("response_format", None)
        for key, value in self.extra_body.items():
            # Provider-specific knobs only: the request skeleton stays ours.
            payload.setdefault(key, value)
        return payload
