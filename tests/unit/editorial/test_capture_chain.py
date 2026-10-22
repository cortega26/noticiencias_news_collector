"""The live capture tool's budgets and failure accounting; no providers called."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.editorial_eval import capture_chain


@pytest.mark.parametrize(
    "max_calls,expected_exit,expected_total", [(1, 1, 2), (2, 0, 4)]
)
def test_capture_allocates_each_label_its_own_budget_and_retains_failures(
    tmp_path, monkeypatch, max_calls, expected_exit, expected_total
):
    source = tmp_path / "source.txt"
    source.write_text("Already retrieved source")
    prompts = tmp_path / "prompts.yaml"
    prompts.write_text("editor:\n  system: Evidence review\n")
    output = tmp_path / "capture"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_chain",
            "--source",
            str(source),
            "--source-url",
            "https://example.org/source",
            "--title",
            "Question",
            "--publication-date",
            "2024-06-05",
            "--baseline-prompts",
            str(prompts),
            "--output-dir",
            str(output),
            "--max-calls",
            str(max_calls),
            "--max-seconds",
            "60",
        ],
    )
    monkeypatch.setattr(capture_chain.signal, "signal", lambda *args: None)
    monkeypatch.setattr(capture_chain.signal, "alarm", lambda *args: None)
    monkeypatch.setattr(
        "noticiencias.config_manager.load_config",
        lambda: SimpleNamespace(
            paths=SimpleNamespace(data_dir=""),
            ollama=SimpleNamespace(api_url="local", model="model"),
        ),
    )

    class CaptureEditor:
        def __init__(self, *args, **kwargs):
            self.provider = SimpleNamespace(providers=[])
            self.fact_check_provider = SimpleNamespace(timeout=60)
            self.editor_model = "model"
            self.last_critic_verdict = {
                "approved": False,
                "verification_status": "unverified",
                "support_issues": ["Concrete source support issue"],
            }

        def _send_prompt(self, *args, **kwargs):
            return "boundary response"

        def _send_fact_check_prompt(self, *args, **kwargs):
            return {"status": "uncertain"}

        def prepare_article(self, article, override_date=None):
            assert override_date == "2024-06-05"
            assert article["content_mode"] == "summary_only"
            self._send_prompt("source", system="Evidence review")
            self._send_prompt("source", system="Evidence review")
            return SimpleNamespace(
                preview_markdown="Prepared captured work",
                grounding_notes="Human review pending",
            )

    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent", CaptureEditor
    )
    assert capture_chain.main() == expected_exit
    report = json.loads((output / "chain-report.json").read_text())
    assert report["calls"] == expected_total
    assert len(report["records"]) == 2
    assert report["human_semantic_acceptance"] == "pending"
    for record in report["records"]:
        assert record["calls"] == max_calls
        assert record["human_review"]["reviewer"] is None
        if expected_exit:
            assert "budget exhausted" in record["error"]
            assert " at " in record["error"]
            packet = (output / f"{record['label']}-review-packet.md").read_text()
            assert "Concrete source support issue" in packet
            assert "human review pending" in packet
            assert "budget exhausted" in packet
        else:
            assert record["output_chars"] > 0
            assert record["error"] is None
