"""Unit tests for the typed critic gate (plan 060 Phase 7c-2).

Exercises `run_critic_gate` in isolation from `EditorAgent`: every collaborator
is a recording callback, so the tests pin the loop contract (bounded retries,
repair-base selection, cleanup, terminal failure codes) without mocking the
subject.
"""

from __future__ import annotations

import pytest

from news_collector.components.editorial.editorial_critic_gate import (
    EDITORIAL_CRITIC_GATE,
    TECHNICAL_CRITIC_GATE,
    CriticFailureCode,
    CriticGateOutcome,
    CriticGatePolicy,
    CriticVerdict,
    run_critic_gate,
)
from news_collector.components.editorial.editorial_stages import EditorialStage


def _identity(text: str) -> str:
    return text


def test_gate_passes_on_first_verdict() -> None:
    passed: list[bool] = []
    rejections: list[tuple[int, str | None]] = []
    repairs: list[str] = []

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 2),
        content="draft",
        fallback_content="fallback",
        evaluate=lambda content: CriticVerdict(True),
        is_repairable=lambda text: True,
        repair=lambda base, reason: "unused",
        cleanup=_identity,
        on_pass=lambda: passed.append(True),
        on_rejection=lambda attempt, reason: rejections.append((attempt, reason)),
        on_repair=lambda content: repairs.append(content),
    )

    assert result == CriticGateOutcome(
        content="draft", attempts=1, passed=True, failure_code=None, failure_reason=None
    )
    assert passed == [True]
    assert rejections == []
    assert repairs == []


def test_gate_repairs_from_fallback_when_base_not_repairable() -> None:
    verdicts = iter(
        [
            CriticVerdict(False, "No text provided", True),
            CriticVerdict(True),
        ]
    )
    evaluated: list[str] = []
    repairs: list[tuple[str, str | None]] = []
    rejections: list[tuple[int, str | None]] = []
    repaired_contents: list[str] = []
    order: list[str] = []

    def evaluate(content: str) -> CriticVerdict:
        evaluated.append(content)
        return next(verdicts)

    def repair(base: str, reason: str | None) -> str:
        order.append("repair")
        repairs.append((base, reason))
        return "Repaired body"

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 2),
        content="   ",
        fallback_content="Translated text",
        evaluate=evaluate,
        is_repairable=lambda text: bool(text.strip()),
        repair=repair,
        cleanup=lambda text: f"<{text}>",
        on_pass=lambda: None,
        on_rejection=lambda attempt, reason: (
            rejections.append((attempt, reason)),
            order.append("rejection"),
        ),
        on_repair=lambda content: (
            repaired_contents.append(content),
            order.append("cache-write"),
        ),
    )

    assert result.passed is True
    assert result.content == "<Repaired body>"
    assert result.attempts == 2
    assert evaluated == ["   ", "<Repaired body>"]
    assert repairs == [("Translated text", "No text provided")]
    assert rejections == [(1, "No text provided")]
    assert repaired_contents == ["<Repaired body>"]
    assert order == ["rejection", "repair", "cache-write"]


def test_gate_repairs_from_current_content_when_repairable() -> None:
    verdicts = iter(
        [
            CriticVerdict(False, "weak hook", True),
            CriticVerdict(True),
        ]
    )
    repairs: list[tuple[str, str | None]] = []

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.EDITORIAL_CRITIC_OK, 1),
        content="Publishable draft",
        fallback_content="Translated text",
        evaluate=lambda content: next(verdicts),
        is_repairable=lambda text: True,
        repair=lambda base, reason: repairs.append((base, reason)) or "Rewritten draft",
        cleanup=_identity,
        on_pass=lambda: None,
        on_rejection=lambda attempt, reason: None,
        on_repair=lambda content: None,
    )

    assert result.passed is True
    assert result.content == "Rewritten draft"
    assert result.attempts == 2
    assert repairs == [("Publishable draft", "weak hook")]


def test_gate_irrecoverable_stops_without_repair() -> None:
    passed: list[bool] = []
    rejections: list[tuple[int, str | None]] = []
    repairs: list[tuple[str, str | None]] = []

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 2),
        content="off-topic body",
        fallback_content="fallback",
        evaluate=lambda content: CriticVerdict(False, "wrong topic", False),
        is_repairable=lambda text: True,
        repair=lambda base, reason: repairs.append((base, reason)) or "unused",
        cleanup=_identity,
        on_pass=lambda: passed.append(True),
        on_rejection=lambda attempt, reason: rejections.append((attempt, reason)),
        on_repair=lambda content: None,
    )

    assert result.passed is False
    assert result.content == "off-topic body"
    assert result.attempts == 1
    assert result.failure_code == CriticFailureCode.IRRECOVERABLE
    assert result.failure_reason == "wrong topic"
    assert passed == []
    assert rejections == []
    assert repairs == []


def test_gate_exhausts_retries_with_last_repaired_content() -> None:
    repair_count = 0
    repaired_contents: list[str] = []
    rejections: list[tuple[int, str | None]] = []
    passed: list[bool] = []

    def repair(base: str, reason: str | None) -> str:
        nonlocal repair_count
        repair_count += 1
        return f"repair-{repair_count}"

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 1),
        content="draft-0",
        fallback_content="fallback",
        evaluate=lambda content: CriticVerdict(False, "still bad", True),
        is_repairable=lambda text: True,
        repair=repair,
        cleanup=lambda text: text,
        on_pass=lambda: passed.append(True),
        on_rejection=lambda attempt, reason: rejections.append((attempt, reason)),
        on_repair=lambda content: repaired_contents.append(content),
    )

    assert result.passed is False
    assert result.content == "repair-1"
    assert result.attempts == 2
    assert result.failure_code == CriticFailureCode.RETRIES_EXHAUSTED
    assert result.failure_reason == "still bad"
    assert repair_count == 1
    assert passed == []
    assert rejections == [(1, "still bad")]
    assert repaired_contents == ["repair-1"]


def test_gate_with_zero_retries_returns_first_verdict() -> None:
    repairs: list[tuple[str, str | None]] = []
    rejections: list[tuple[int, str | None]] = []
    passed: list[bool] = []

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.EDITORIAL_CRITIC_OK, 0),
        content="draft",
        fallback_content="fallback",
        evaluate=lambda content: CriticVerdict(False, "not good", True),
        is_repairable=lambda text: True,
        repair=lambda base, reason: repairs.append((base, reason)) or "unused",
        cleanup=_identity,
        on_pass=lambda: passed.append(True),
        on_rejection=lambda attempt, reason: rejections.append((attempt, reason)),
        on_repair=lambda content: None,
    )

    assert result.passed is False
    assert result.content == "draft"
    assert result.attempts == 1
    assert result.failure_code == CriticFailureCode.RETRIES_EXHAUSTED
    assert result.failure_reason == "not good"
    assert repairs == []
    assert rejections == []
    assert passed == []


def test_gate_passes_none_reason_through_to_repair() -> None:
    verdicts = iter(
        [
            CriticVerdict(False, None, True),
            CriticVerdict(True),
        ]
    )
    repairs: list[tuple[str, str | None]] = []

    result = run_critic_gate(
        CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 1),
        content="draft",
        fallback_content="fallback",
        evaluate=lambda content: next(verdicts),
        is_repairable=lambda text: True,
        repair=lambda base, reason: repairs.append((base, reason)) or "Repaired",
        cleanup=_identity,
        on_pass=lambda: None,
        on_rejection=lambda attempt, reason: None,
        on_repair=lambda content: None,
    )

    assert result.passed is True
    assert repairs == [("draft", None)]


def test_gate_rejects_negative_retry_budget() -> None:
    with pytest.raises(ValueError, match="negative retry budget"):
        run_critic_gate(
            CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, -1),
            content="draft",
            fallback_content="fallback",
            evaluate=lambda content: pytest.fail("must not evaluate"),
            is_repairable=lambda text: True,
            repair=lambda base, reason: "unused",
            cleanup=_identity,
            on_pass=lambda: pytest.fail("must not pass"),
            on_rejection=lambda attempt, reason: pytest.fail("must not reject"),
            on_repair=lambda content: pytest.fail("must not repair"),
        )


def test_policy_constants_match_historical_budgets() -> None:
    assert TECHNICAL_CRITIC_GATE.stage == EditorialStage.TECHNICAL_CRITIC_OK
    assert TECHNICAL_CRITIC_GATE.max_retries == 2
    assert EDITORIAL_CRITIC_GATE.stage == EditorialStage.EDITORIAL_CRITIC_OK
    assert EDITORIAL_CRITIC_GATE.max_retries == 1
