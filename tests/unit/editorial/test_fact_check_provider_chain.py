"""Plan 200: the fact-check verifier runs on its own chain, never the drafter's model."""

from __future__ import annotations

import pytest
from noticiencias.config_schema import Config

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.infrastructure.llm.factory import FallbackProvider, provider_name
from news_collector.infrastructure.llm.provider import OllamaProvider

GROQ = {
    "name": "groq",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "openai/gpt-oss-120b",
    "api_key_env": "GROQ_API_KEY",
}


def _agent(llm: dict | None) -> EditorAgent:
    data: dict = {
        "nvidia": {"api_key": "k", "model": "nvidia/nemotron-3-ultra-550b-a55b"},
        "llm_endpoints": [GROQ],
    }
    if llm is not None:
        data["llm"] = llm
    return EditorAgent(
        "http://localhost:11434/api/generate",
        "qwen2.5:32b",
        config=Config.model_validate(data),
    )


def test_fact_check_chain_excludes_the_drafter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")

    agent = _agent({"purpose_chains": {"fact_check": ["groq"]}})

    assert isinstance(agent.fact_check_provider, FallbackProvider)
    chain = [provider_name(p) for p in agent.fact_check_provider.providers]
    assert chain == ["groq", "ollama"]
    assert "nvidia" in [provider_name(p) for p in agent.provider.providers]
    assert agent.fact_check_provider.providers[-1].model == agent.fact_check_model


def test_without_fact_check_chain_the_verifier_stays_local(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GROQ_API_KEY", "x")

    agent = _agent(None)

    assert isinstance(agent.fact_check_provider, OllamaProvider)
    assert agent.fact_check_provider.model == agent.fact_check_model
