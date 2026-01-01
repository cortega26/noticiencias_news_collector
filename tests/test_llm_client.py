"""Unit tests for LLM client configuration resolution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news_collector.utils.llm_client import LLMClient


def test_llm_client_prefers_process_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLLAMA_API_URL", "http://env-url/api/generate")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")

    client = LLMClient(dotenv_path=tmp_path / ".env")

    assert client.api_url == "http://env-url/api/generate"
    assert client.model == "env-model"


def test_llm_client_loads_dotenv_when_env_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OLLAMA_API_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "OLLAMA_API_URL=http://dotenv-url/api/generate\n"
        "OLLAMA_MODEL=dotenv-model\n",
        encoding="utf-8",
    )

    client = LLMClient(dotenv_path=env_path)

    assert client.api_url == "http://dotenv-url/api/generate"
    assert client.model == "dotenv-model"
