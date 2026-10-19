"""Tests for scripts/editorial_critic_canary.py (plan 154).

The live provider call is manual evidence, not a unit test. These tests cover
the evidence shape, redaction and exit-code mapping with an injected fake
critic, plus the guarantee that importing the script has no app side effects.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import editorial_critic_canary as canary

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fixed_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canary, "_git_sha", lambda: "a" * 40)


def _observation(**overrides: object) -> canary.CriticObservation:
    base = canary.CriticObservation(
        verdict={
            "approved": True,
            "average": 8.0,
            "scores": {
                "hook_score": 8,
                "clarity_score": 8,
                "structure_score": 8,
                "rigor_score": 8,
                "voice_score": 8,
                "shareability_score": 8,
                "closing_score": 8,
            },
            "recoverable": True,
            "feedback": "texto de feedback que no debe salir",
        },
        transport_ok=True,
        json_parsed=True,
        error_kind=None,
        latency_ms=1234,
        model="fake-model:latest",
        provider_chain=("fake",),
    )
    return replace(base, **overrides)


def _run(
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    observation: canary.CriticObservation,
) -> tuple[int, dict, str]:
    code = canary.main(argv, critic_runner=lambda **_: observation)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.out


def test_pass_evidence_shape_and_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict] = []

    def runner(**kwargs: object) -> canary.CriticObservation:
        calls.append(kwargs)
        return _observation()

    code = canary.main(["--provider", "local"], critic_runner=runner)
    emitted = json.loads(capsys.readouterr().out)

    assert code == canary.PASS_EXIT == 0
    assert calls == [{"provider_mode": "local", "timeout": 180, "require_keys": False}]
    assert emitted["status"] == "PASS"
    assert emitted["synthetic"] is True
    assert emitted["git_sha"] == "a" * 40
    assert emitted["provider"] == "local"
    assert emitted["model"] == "fake-model:latest"
    assert emitted["transport_ok"] is True
    assert emitted["json_parsed"] is True
    assert emitted["latency_ms"] == 1234
    assert emitted["error_kind"] is None
    assert emitted["error_class"] is None
    assert emitted["response_chars"] == 0
    assert emitted["verdict_fields"]["approved"] is True
    assert emitted["verdict_fields"]["average"] == 8.0
    assert emitted["verdict_fields"]["scores"]["rigor_score"] == 8
    assert "feedback" not in emitted["verdict_fields"]
    assert "texto de feedback" not in json.dumps(emitted)


def test_valid_rejection_is_fail_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    observation = _observation(verdict={"approved": False, "average": 4.0})
    code, emitted, _ = _run(capsys, ["--provider", "local"], observation)

    assert code == canary.FAIL_EXIT == 1
    assert emitted["status"] == "FAIL"
    assert emitted["verdict_fields"]["approved"] is False


@pytest.mark.parametrize(
    ("observation", "error_kind"),
    [
        (
            _observation(
                verdict=None,
                transport_ok=False,
                json_parsed=False,
                error_kind="transport_error",
            ),
            "transport_error",
        ),
        (
            _observation(
                verdict=None,
                transport_ok=True,
                json_parsed=False,
                error_kind="parse_error",
            ),
            "parse_error",
        ),
        (
            _observation(
                verdict=None,
                transport_ok=True,
                json_parsed=False,
                error_kind="prompt_missing",
            ),
            "prompt_missing",
        ),
    ],
)
def test_failures_are_unverified_not_approval(
    capsys: pytest.CaptureFixture[str],
    observation: canary.CriticObservation,
    error_kind: str,
) -> None:
    code, emitted, raw = _run(capsys, ["--provider", "local"], observation)

    assert code == canary.UNVERIFIED_EXIT == 2
    assert emitted["status"] == "UNVERIFIED"
    assert emitted["error_kind"] == error_kind
    assert emitted["verdict_fields"] is None
    assert "PASS" not in raw


def test_verdict_without_approval_flag_is_unverified(
    capsys: pytest.CaptureFixture[str],
) -> None:
    observation = _observation(
        verdict={"average": 8.0, "scores": {}}, transport_ok=True, json_parsed=True
    )
    code, emitted, _ = _run(capsys, ["--provider", "local"], observation)

    assert code == canary.UNVERIFIED_EXIT
    assert emitted["status"] == "UNVERIFIED"


def test_config_error_exits_3_and_redacts_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def runner(**_: object) -> canary.CriticObservation:
        raise canary.CanaryConfigError(
            "provider rejected sk-live-abcdefgh12345678 " "and Bearer abcdefghijklmnop"
        )

    code = canary.main(["--provider", "configured"], critic_runner=runner)
    raw = capsys.readouterr().out
    emitted = json.loads(raw)

    assert code == canary.CONFIG_ERROR_EXIT == 3
    assert emitted["status"] == "UNVERIFIED"
    assert emitted["error_kind"] == "config_error"
    assert emitted["transport_ok"] is False
    assert "sk-live-abcdefgh12345678" not in raw
    assert "abcdefghijklmnop" not in raw
    assert "[REDACTED]" in raw


def test_require_keys_with_local_provider_is_config_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def runner(**_: object) -> canary.CriticObservation:
        nonlocal called
        called = True
        return _observation()

    code = canary.main(["--provider", "local", "--require-keys"], critic_runner=runner)
    emitted = json.loads(capsys.readouterr().out)

    assert code == canary.CONFIG_ERROR_EXIT
    assert called is False
    assert emitted["status"] == "UNVERIFIED"
    assert emitted["error_kind"] == "config_error"


def test_json_and_human_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = canary.main(
        ["--provider", "local", "--json", "--human"],
        critic_runner=lambda **_: _observation(),
    )
    raw = capsys.readouterr().out

    assert code == canary.CONFIG_ERROR_EXIT
    assert "UNVERIFIED" in raw
    assert "config_error" in raw


def test_unknown_provider_is_config_error_not_unverified_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = canary.main(
        ["--provider", "cloud"], critic_runner=lambda **_: _observation()
    )
    emitted = json.loads(capsys.readouterr().out)

    assert code == canary.CONFIG_ERROR_EXIT
    assert emitted["status"] == "UNVERIFIED"
    assert emitted["error_kind"] == "config_error"


def test_internal_error_is_unverified(capsys: pytest.CaptureFixture[str]) -> None:
    def runner(**_: object) -> canary.CriticObservation:
        raise RuntimeError("boom")

    code = canary.main(["--provider", "local"], critic_runner=runner)
    emitted = json.loads(capsys.readouterr().out)

    assert code == canary.UNVERIFIED_EXIT
    assert emitted["status"] == "UNVERIFIED"
    assert emitted["error_kind"] == "internal_error"
    assert emitted["error_class"] == "RuntimeError"


def test_human_mode_does_not_emit_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = canary.main(
        ["--provider", "local", "--human"],
        critic_runner=lambda **_: _observation(),
    )
    raw = capsys.readouterr().out

    assert code == canary.PASS_EXIT
    assert raw.startswith("Editorial critic canary: PASS")
    assert not raw.lstrip().startswith("{")


def test_safe_verdict_fields_drops_free_text_and_unknown_keys() -> None:
    fields = canary.safe_verdict_fields(
        {
            "approved": True,
            "average": 7.5,
            "scores": {"rigor_score": 7, "not a dimension": 9, "bool_score": True},
            "feedback": "raw model text",
            "raw_response": "full provider response",
            "value_add_assessment": "análisis largo que no debe salir",
        }
    )

    assert fields is not None
    assert fields["scores"] == {"rigor_score": 7}
    assert "feedback" not in fields
    assert "raw_response" not in fields
    assert fields["value_add_assessment_chars"] == len(
        "análisis largo que no debe salir"
    )
    assert "análisis largo" not in json.dumps(fields)


def test_sanitize_redacts_nested_credentials() -> None:
    payload = {
        "model": "nvapi-abcdefgh12345678",
        "url": "https://example.invalid/v1?api_key=supersecretvalue&x=1",
        "chain": ["AIza" + "a" * 30, "ollama"],
    }
    sanitized = canary.sanitize(payload)
    rendered = json.dumps(sanitized)

    assert "nvapi-abcdefgh12345678" not in rendered
    assert "supersecretvalue" not in rendered
    assert "AIza" + "a" * 30 not in rendered
    assert rendered.count("[REDACTED]") >= 3


def test_invoke_critic_discards_progress_prints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _PrintingCritic:
        called = False

        def _critic_editorial_pass(self, *_args: object) -> None:
            self.called = True
            print("Processing (system prompt preview...) [model]")
            print(" Done!")

    critic = _PrintingCritic()
    canary._invoke_critic(critic)

    assert critic.called is True
    assert capsys.readouterr().out == ""


def test_synthetic_inputs_are_clearly_marked() -> None:
    assert "SINTÉTICO" in canary._SYNTHETIC_TITLE
    assert "SINTÉTICO" in canary._SYNTHETIC_DRAFT
    assert "SINTÉTICO" in canary._SYNTHETIC_SOURCE
    assert "canary.invalid" in canary._SYNTHETIC_CONTEXT["source_url"]


def test_importing_script_does_not_import_the_app() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, scripts.editorial_critic_canary; "
                "print('news_collector' in sys.modules)"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
