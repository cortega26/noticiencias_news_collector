"""Plan 101: EditorialCouncil/EditorialClassifier take collaborators explicitly.

- Construction with a fake llm_client must work with zero ambient
  config/env (load_config rigged to raise).
- Construction with neither llm_client nor config raises ValueError.
- An explicit config is the object used for provider wiring.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from news_collector.editorial.classifier import EditorialClassifier
from news_collector.editorial.council import EditorialCouncil


def _raise_ambient(*args, **kwargs):
    raise AssertionError("ambient config must not be consulted")


@pytest.fixture()
def no_ambient_config(monkeypatch):
    monkeypatch.setattr("noticiencias.config_manager.load_config", _raise_ambient)
    monkeypatch.setattr(
        "news_collector.config.settings.get_runtime_config", _raise_ambient
    )


@pytest.mark.parametrize("cls", [EditorialCouncil, EditorialClassifier])
def test_constructs_with_fake_client_and_no_ambient_state(cls, no_ambient_config):
    client = object()
    instance = cls(llm_client=client)
    assert instance.llm is client


@pytest.mark.parametrize("cls", [EditorialCouncil, EditorialClassifier])
def test_bare_construction_raises_valueerror(cls):
    with pytest.raises(ValueError, match="explicitly"):
        cls()


@pytest.mark.parametrize(
    ("cls", "module", "stage"),
    [
        (EditorialCouncil, "news_collector.editorial.council", "council"),
        (
            EditorialClassifier,
            "news_collector.editorial.classifier",
            "classifier",
        ),
    ],
)
def test_explicit_config_is_used_for_provider_wiring(
    cls, module, stage, monkeypatch
):
    seen = {}

    def fake_get_model_for_stage(stage_name, config=None, logger=None, **kwargs):
        seen["model_stage"] = stage_name
        seen["model_config"] = config
        return "explicit-model:1b"

    def fake_get_provider(config=None, api_url=None, model=None, **kwargs):
        seen["provider_config"] = config
        return SimpleNamespace(model=model, api_url=api_url)

    monkeypatch.setattr(f"{module}.get_model_for_stage", fake_get_model_for_stage)
    monkeypatch.setattr(f"{module}.get_provider", fake_get_provider)

    cfg = SimpleNamespace(ollama=SimpleNamespace(api_url="http://explicit.invalid"))
    instance = cls(config=cfg)

    assert seen["model_stage"] == stage
    assert seen["model_config"] is cfg
    assert seen["provider_config"] is cfg
    assert instance.llm.model == "explicit-model:1b"
