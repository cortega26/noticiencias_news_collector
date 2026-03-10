from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from news_collector.components.editorial.auditor import EditorialAuditor
from news_collector.editorial.classifier import EditorialClassifier
from news_collector.editorial.council import EditorialCouncil
from news_collector.infrastructure.llm.model_registry import get_all_stages
from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.scoring.pre_scorer import PreScorer


def test_prescorer_uses_registry(monkeypatch):
    calls = []

    def fake_get_model_for_stage(stage, config, logger):
        calls.append(stage)
        return "registry-prescorer:7b"

    class MockProvider:
        def __init__(self, api_url, model):
            self.api_url = api_url
            self.model = model

    def fake_get_provider(config=None, api_url=None, model=None, **kwargs):
        return MockProvider(api_url, model)

    monkeypatch.setattr(
        "news_collector.scoring.pre_scorer.get_model_for_stage",
        fake_get_model_for_stage,
    )
    monkeypatch.setattr(
        "news_collector.scoring.pre_scorer.get_provider", fake_get_provider
    )

    scorer = PreScorer()
    assert scorer.llm.model == "registry-prescorer:7b"
    assert calls == ["pre_scorer"]


def test_cognitive_scorer_uses_registry(monkeypatch):
    calls = []

    def fake_get_model_for_stage(stage, config, logger):
        calls.append(stage)
        return "registry-scoring:32b"

    class MockProvider:
        def __init__(self, api_url, model):
            self.api_url = api_url
            self.model = model

        async def generate_async(self, *args, **kwargs):
            return {"results": []}

    def fake_get_provider(config=None, api_url=None, model=None, **kwargs):
        return MockProvider(api_url, model)

    monkeypatch.setattr(
        "news_collector.scoring.cognitive_scorer.get_model_for_stage",
        fake_get_model_for_stage,
    )
    monkeypatch.setattr(
        "news_collector.scoring.cognitive_scorer.get_provider",
        fake_get_provider,
    )

    scorer = CognitiveScorer()
    assert scorer.llm.model == "registry-scoring:32b"
    assert calls == ["scoring"]


def test_classifier_uses_registry(monkeypatch):
    calls = []

    def fake_get_model_for_stage(stage, config, logger):
        calls.append(stage)
        return "registry-classifier:14b"

    class MockProvider:
        def __init__(self, api_url, model):
            self.api_url = api_url
            self.model = model

    def fake_get_provider(config=None, api_url=None, model=None, **kwargs):
        return MockProvider(api_url, model)

    monkeypatch.setattr(
        "news_collector.editorial.classifier.get_model_for_stage",
        fake_get_model_for_stage,
    )
    monkeypatch.setattr(
        "news_collector.editorial.classifier.get_provider",
        fake_get_provider,
    )

    classifier = EditorialClassifier()
    assert classifier.llm.model == "registry-classifier:14b"
    assert calls == ["classifier"]


def test_council_uses_registry(monkeypatch):
    calls = []

    def fake_get_model_for_stage(stage, config, logger):
        calls.append(stage)
        return "registry-council:14b"

    class MockProvider:
        def __init__(self, api_url, model):
            self.api_url = api_url
            self.model = model

    def fake_get_provider(config=None, api_url=None, model=None, **kwargs):
        return MockProvider(api_url, model)

    monkeypatch.setattr(
        "news_collector.editorial.council.get_model_for_stage",
        fake_get_model_for_stage,
    )
    monkeypatch.setattr(
        "news_collector.editorial.council.get_provider",
        fake_get_provider,
    )

    council = EditorialCouncil()
    assert council.llm.model == "registry-council:14b"
    assert calls == ["council"]


def test_auditor_uses_registry(monkeypatch, tmp_path: Path):
    calls = []

    def fake_get_model_for_stage(stage, config, logger):
        calls.append(stage)
        return "registry-auditor:13b"

    class MockProvider:
        def __init__(self, api_url, model, timeout, max_retries):
            self.api_url = api_url
            self.model = model
            self.timeout = timeout
            self.max_retries = max_retries

    def fake_get_provider(config=None, api_url=None, model=None, timeout=None, max_retries=None, **kwargs):
        return MockProvider(api_url, model, timeout, max_retries)

    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_model_for_stage",
        fake_get_model_for_stage,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_provider",
        fake_get_provider,
    )

    cfg = SimpleNamespace(
        editorial_auditor=SimpleNamespace(
            enabled=True, sampling_rate=0.2, blocking=False
        ),
        paths=SimpleNamespace(data_dir=tmp_path),
        ollama=SimpleNamespace(api_url="http://localhost:11434/api/generate"),
    )

    auditor = EditorialAuditor(cfg)
    assert auditor.model == "registry-auditor:13b"
    assert calls == ["auditor"]


def test_stage_literals_used_with_get_model_for_stage_are_registered():
    """
    Lightweight tripwire: scans literal get_model_for_stage("<stage>") usages.
    Limitation: dynamic/non-literal stage names are intentionally out of scope.
    """
    repo_root = Path(__file__).resolve().parents[4]
    call_pattern = re.compile(r'get_model_for_stage\(\s*["\']([a-zA-Z0-9_]+)["\']')
    used_stages: set[str] = set()

    for root in (repo_root / "news_collector", repo_root / "apps"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts or "docs" in path.parts:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            used_stages.update(call_pattern.findall(content))

    assert used_stages, "No literal get_model_for_stage(...) usages were found."
    registered = set(get_all_stages())
    unknown = sorted(used_stages - registered)
    assert not unknown, (
        "Unregistered stage literal(s) detected in get_model_for_stage calls: "
        f"{unknown}. Register the stage in model_registry.py (ALL_STAGES and "
        "_STAGE_OVERRIDE_PATH)."
    )
