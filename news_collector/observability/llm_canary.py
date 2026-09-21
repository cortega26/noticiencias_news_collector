"""Pure evaluation of an LLM canary run (no network, no I/O).

The canary scores a small synthetic batch through the *real* provider chain and
answers one question: "would the LLM do the work today?". This module only turns
the counters of that run into a verdict, so the rules are unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping

STAGE = "scoring"


@dataclass(frozen=True)
class CanaryThresholds:
    min_llm_ratio: float = 0.8
    max_seconds: float = 120.0


@dataclass
class CanaryVerdict:
    ok: bool
    total: int
    llm: int
    heuristic: int
    llm_ratio: float
    elapsed_s: float
    reasons: List[str] = field(default_factory=list)
    heuristic_reasons: Dict[str, int] = field(default_factory=dict)


def evaluate(
    counts: Mapping[str, int],
    elapsed_s: float,
    thresholds: CanaryThresholds | None = None,
) -> CanaryVerdict:
    """Judge the ``llm_run_stats`` snapshot of a canary run.

    ``cached`` items are excluded from the denominator: a cache hit says nothing
    about the provider chain (the canary uses a fresh cache, so it is normally 0).
    """
    th = thresholds or CanaryThresholds()
    llm = int(counts.get(f"{STAGE}.llm", 0))
    prefix = f"{STAGE}.heuristic."
    why = {k[len(prefix) :]: int(v) for k, v in counts.items() if k.startswith(prefix)}
    heuristic = sum(why.values())
    total = llm + heuristic
    ratio = llm / total if total else 0.0

    reasons: List[str] = []
    if total == 0:
        reasons.append("no items were scored")
    elif ratio < th.min_llm_ratio:
        main = max(why, key=lambda k: why[k]) if why else "unknown"
        reasons.append(
            f"only {ratio:.0%} of items scored by the LLM "
            f"(min {th.min_llm_ratio:.0%}; main fallback reason: {main})"
        )
    if elapsed_s > th.max_seconds:
        reasons.append(f"took {elapsed_s:.0f}s (max {th.max_seconds:.0f}s)")
    return CanaryVerdict(
        ok=not reasons,
        total=total,
        llm=llm,
        heuristic=heuristic,
        llm_ratio=ratio,
        elapsed_s=elapsed_s,
        reasons=reasons,
        heuristic_reasons=why,
    )


def format_verdict(v: CanaryVerdict) -> str:
    head = "CANARY OK" if v.ok else "CANARY FAILED"
    lines = [
        f"{head}: {v.llm}/{v.total} items by LLM ({v.llm_ratio:.0%}) in "
        f"{v.elapsed_s:.1f}s"
    ]
    if v.heuristic_reasons:
        lines.append(
            "  heuristic: "
            + ", ".join(f"{k}={n}" for k, n in sorted(v.heuristic_reasons.items()))
        )
    lines += [f"  - {r}" for r in v.reasons]
    return "\n".join(lines)
