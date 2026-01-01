"""End-to-end smoke test for cognitive scoring using mocked LLM."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news_collector.scoring import create_scorer
from news_collector.storage.models import Article
from news_collector.utils import llm_client


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_cognitive_scoring_uses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}
    jsonlib = json

    def fake_post(url: str, json: Dict[str, Any], timeout: int) -> _FakeResponse:
        captured["url"] = url
        captured["payload"] = json
        response_body = jsonlib.dumps(
            {
                "scores": {
                    "contraintuitivo": 4,
                    "impacto_humano": 5,
                    "conflicto_ideas": 3,
                    "incertidumbre": 2,
                    "utilidad_practica": 4,
                },
                "reasoning": "Mock reasoning: strong cognitive impact.",
            }
        )
        return _FakeResponse({"response": response_body})

    monkeypatch.setenv("OLLAMA_API_URL", "http://fake-ollama/api/generate")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)

    scorer = create_scorer(mode="cognitive")
    article = Article(
        id=1,
        url="http://example.com",
        title="Breakthrough in Fusion Research",
        summary="Scientists achieved a net energy gain in a fusion experiment.",
        content="Detailed content about the experiment and its implications.",
        source_id="test_source",
        source_name="Test Source",
        published_date=datetime.now(timezone.utc),
        collected_date=datetime.now(timezone.utc),
    )

    result = scorer.score_article(article)

    assert captured["url"] == "http://fake-ollama/api/generate"
    assert captured["payload"]["model"] == "llama3.2"
    assert result["components"]["cognitive_engagement_raw"] == pytest.approx(
        3.6, abs=1e-6
    )
    assert result["components"]["cognitive_engagement_norm"] == pytest.approx(
        0.72, abs=1e-6
    )
