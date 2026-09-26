"""
Module role: Typed critic-gate policy for the EditorAgent repair loops
(plan 060 Phase 7c-2).

Owns:
- CriticVerdict: normalized (is_valid, reason, recoverable) decision
- CriticFailureCode / CriticGateOutcome: terminal outcome vocabulary
- CriticGatePolicy + the stage policies of the technical and editorial gates
- CriticGateHooks: the typed host-callback bundle the gate drives
- run_critic_gate: the bounded evaluate -> repair -> re-evaluate loop shared
  by Stage 3 (technical critic) and Stage 4 (editorial critic)

Does NOT own:
- Prompts, LLM calls or repair prompts (EditorAgent)
- Cache paths, checkpoint writes or stage-2 cache updates (caller callbacks)
- Raise/caveat decisions and their log text (caller callbacks)
- Provider/model provenance (future Phase 7c stages)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from news_collector.components.editorial.editorial_stages import EditorialStage


@dataclass(frozen=True)
class CriticVerdict:
    """One critic decision, normalized from the legacy tuple shapes."""

    is_valid: bool
    reason: str | None = None
    recoverable: bool = True


class CriticFailureCode(StrEnum):
    """Terminal gate outcomes; the gate returns them, callers act on them."""

    IRRECOVERABLE = "critic_irrecoverable"
    RETRIES_EXHAUSTED = "critic_retries_exhausted"


@dataclass(frozen=True)
class CriticGatePolicy:
    """Declared cache identity and bounded retry policy of one critic gate."""

    stage: EditorialStage
    max_retries: int


TECHNICAL_CRITIC_GATE = CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 2)
EDITORIAL_CRITIC_GATE = CriticGatePolicy(EditorialStage.EDITORIAL_CRITIC_OK, 1)


@dataclass(frozen=True)
class CriticGateOutcome:
    """Result of a gate run; `content` is always the latest candidate."""

    content: str
    attempts: int
    passed: bool
    failure_code: CriticFailureCode | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class CriticGateHooks:
    """Host callbacks the gate drives; supplied by `EditorAgent`."""

    evaluate: Callable[[str], CriticVerdict]
    is_repairable: Callable[[str], bool]
    repair: Callable[[str, str | None], str]
    cleanup: Callable[[str], str]
    on_pass: Callable[[], None]
    on_rejection: Callable[[int, str | None], None]
    on_repair: Callable[[str], None]


def run_critic_gate(
    policy: CriticGatePolicy,
    hooks: CriticGateHooks,
    *,
    content: str,
    fallback_content: str,
) -> CriticGateOutcome:
    """Run the bounded evaluate -> repair -> re-evaluate loop of one gate.

    Verbatim control-flow extraction of the Stage 3 and Stage 4 critic loops
    previously inlined in `EditorAgent.process_article` (plan 060 Phase
    7c-2): same attempt counts, repair-base selection and cleanup. The
    terminal outcome is returned instead of raised so each caller keeps its
    own raise/caveat policy, logging and cache writes.
    """
    for attempt in range(policy.max_retries + 1):
        verdict = hooks.evaluate(content)
        if verdict.is_valid:
            hooks.on_pass()
            return CriticGateOutcome(content, attempt + 1, True)

        if not verdict.recoverable:
            return CriticGateOutcome(
                content,
                attempt + 1,
                False,
                CriticFailureCode.IRRECOVERABLE,
                verdict.reason,
            )

        if attempt < policy.max_retries:
            hooks.on_rejection(attempt + 1, verdict.reason)
            repair_base = content if hooks.is_repairable(content) else fallback_content
            content = hooks.cleanup(hooks.repair(repair_base, verdict.reason))
            hooks.on_repair(content)
        else:
            return CriticGateOutcome(
                content,
                attempt + 1,
                False,
                CriticFailureCode.RETRIES_EXHAUSTED,
                verdict.reason,
            )

    raise ValueError(
        f"critic gate policy for {policy.stage} has a negative retry budget"
    )
