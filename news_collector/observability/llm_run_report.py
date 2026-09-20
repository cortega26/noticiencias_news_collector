"""End-of-run LLM health report.

Answers, without opening the log: how much of this run's LLM-dependent work
(prescoring, scoring) was really done by an LLM, which providers failed, and
whether the run is *degraded* enough to deserve attention.

Pure aggregation over two already-existing sources — the persisted attempt
metrics (``LLMMetricsStore``) and the in-memory stage counters
(``llm_run_stats``). No network, no provider calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from news_collector.observability.llm_metrics_store import (
    ProviderSummary,
    format_report,
)

STAGES = ("prescoring", "scoring", "rescoring")
# Stages that can raise a degraded alert. Re-scoring is informational: it is
# served by the cache/heuristics by policy, so its heuristic share is expected.
ALERTING_STAGES = ("prescoring", "scoring")


@dataclass
class StageOutcome:
    """Items a stage handled, split by who actually did the work."""

    stage: str
    llm: int = 0
    cached: int = 0
    heuristic: int = 0
    heuristic_reasons: Dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.llm + self.cached + self.heuristic

    @property
    def heuristic_ratio(self) -> Optional[float]:
        """Share of items that fell back to heuristics (cache excluded)."""
        worked = self.llm + self.heuristic
        return self.heuristic / worked if worked else None


@dataclass
class LLMRunReport:
    run_id: Optional[str]
    stages: List[StageOutcome]
    providers: List[ProviderSummary]
    degraded: bool
    reasons: List[str]
    llm_activity: bool  # False => LLM not configured/used (e.g. CI): never alert

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["providers"] = [p.as_dict() for p in self.providers]
        for stage, raw in zip(data["stages"], self.stages, strict=True):
            stage["total"] = raw.total
            stage["heuristic_ratio"] = raw.heuristic_ratio
        return data


def _stage_outcomes(counts: Mapping[str, int]) -> List[StageOutcome]:
    outcomes: List[StageOutcome] = []
    for stage in STAGES:
        outcome = StageOutcome(stage)
        for key, n in counts.items():
            head, _, tail = key.partition(".")
            if head != stage:
                continue
            if tail == "llm":
                outcome.llm += n
            elif tail == "cached":
                outcome.cached += n
            elif tail.startswith("heuristic."):
                outcome.heuristic += n
                reason = tail.split(".", 1)[1]
                outcome.heuristic_reasons[reason] = (
                    outcome.heuristic_reasons.get(reason, 0) + n
                )
        outcomes.append(outcome)
    return outcomes


def build_run_report(
    counts: Mapping[str, int],
    providers: Sequence[ProviderSummary],
    *,
    run_id: Optional[str] = None,
    warn_heuristic_ratio: float = 0.5,
) -> LLMRunReport:
    """Aggregate a run. ``degraded`` never fires when the LLM was not in use."""
    stages = _stage_outcomes(counts)
    real_calls = sum(p.calls for p in providers)
    skips = sum(p.skips for p in providers)
    # Skips count as activity: with every provider circuit-open/degraded there
    # are zero calls but that is exactly the outage this report must surface.
    activity = real_calls > 0 or skips > 0 or any(s.llm for s in stages)

    reasons: List[str] = []
    if activity:
        for s in stages:
            if s.stage not in ALERTING_STAGES:
                continue
            ratio = s.heuristic_ratio
            if ratio is not None and ratio > warn_heuristic_ratio:
                top = max(s.heuristic_reasons, key=s.heuristic_reasons.get)  # type: ignore[arg-type]
                reasons.append(
                    f"{s.stage}: {ratio:.0%} of items fell back to heuristics "
                    f"(main reason: {top})"
                )
        if real_calls == 0 and skips > 0:
            reasons.append(
                "all providers unavailable (every attempt was skipped: "
                "circuit open, cooling down or disabled)"
            )
        by_purpose: Dict[str, List[ProviderSummary]] = {}
        for p in providers:
            by_purpose.setdefault(p.purpose or "all", []).append(p)
        for purpose, rows in by_purpose.items():
            if sum(r.calls for r in rows) and sum(r.ok for r in rows) == 0:
                reasons.append(f"{purpose}: every provider attempt failed")
    return LLMRunReport(
        run_id=run_id,
        stages=stages,
        providers=list(providers),
        degraded=bool(reasons),
        reasons=reasons,
        llm_activity=activity,
    )


def format_run_report(report: LLMRunReport) -> str:
    """Plain-text block for the end of a run."""
    lines = ["", "🤖 LLM DE ESTA CORRIDA:", "-" * 40]
    if not report.llm_activity:
        lines.append("Sin actividad de LLM (¿no configurado? scoring heurístico).")
        return "\n".join(lines)
    for s in report.stages:
        if not s.total:
            continue
        ratio = s.heuristic_ratio
        why = (
            ", ".join(f"{k}={v}" for k, v in sorted(s.heuristic_reasons.items())) or "-"
        )
        lines.append(
            f"{s.stage:<11} LLM {s.llm:>4} | caché {s.cached:>4} | heurístico "
            f"{s.heuristic:>4}"
            + (f" ({ratio:.0%})" if ratio is not None else "")
            + f"  [{why}]"
        )
    if report.providers:
        lines += ["", format_report(list(report.providers))]
    lines.append("")
    lines.append(
        "⚠️  DEGRADADO: " + "; ".join(report.reasons)
        if report.degraded
        else "✅ LLM saludable en esta corrida."
    )
    return "\n".join(lines)


def write_run_report(report: LLMRunReport, path: str | Path) -> Optional[Path]:
    """Persist the report as JSON. Fail-open: returns ``None`` on I/O error."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report.as_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target
    except OSError:
        return None


def emit_run_report(
    config: Any = None,
    *,
    emit: Any = print,
    export_path: str | Path | None = "data/exports/llm_run_report.json",
    store: Any = None,
    scope: Any = None,
) -> Optional[LLMRunReport]:
    """Build, show, log and export the current run's LLM health report.

    Fail-open by design: an observability failure must never fail a run, so any
    error is logged and swallowed. ``scope`` (``llm_run_stats.begin_scope()``)
    limits the report to one workflow inside a long-lived process (e.g. one
    publication among many in the serving process). Returns the report
    (``None`` if disabled or on failure). ``emit`` receives the text block (``print`` by default; pass a
    logger method for non-interactive callers).
    """
    from news_collector.infrastructure.run_context import run_context
    from news_collector.observability import llm_run_stats
    from news_collector.observability.llm_metrics_store import LLMMetricsStore
    from news_collector.utils.logger import get_logger

    logger = get_logger().create_module_logger(__name__)
    try:
        if config is None:
            from noticiencias.config_manager import load_config

            config = load_config()
        health = config.llm_health
        if not health.enabled:
            return None
        run_id = run_context.get_context().get("run_id")
        providers = (store or LLMMetricsStore()).summary(
            by_purpose=True,
            run_id=run_id,
            since_ts=scope.started_at if scope is not None else None,
        )
        counts = (
            llm_run_stats.delta_since(scope)
            if scope is not None
            else llm_run_stats.snapshot()
        )
        report = build_run_report(
            counts,
            providers,
            run_id=run_id,
            warn_heuristic_ratio=health.warn_heuristic_ratio,
        )
        emit(format_run_report(report))
        if report.degraded:
            logger.warning(
                {
                    "event": "llm.run.degraded",
                    "run_id": run_id,
                    "reasons": report.reasons,
                }
            )
        if export_path:
            write_run_report(report, export_path)
        return report
    except Exception as err:  # noqa: BLE001 - never fail a run over reporting
        logger.warning("LLM run report unavailable: {}", err)
        return None
