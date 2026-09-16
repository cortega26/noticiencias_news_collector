#!/usr/bin/env python3
"""Publish cost/SLO snapshot from persisted publication attempts (Plan 107).

Reads ``data/runtime/publication_attempts/*.json`` (skipping
``*.frontend_validation.json``) plus the optional
``data/exports/source_health.json`` export and emits one JSON report:

- publication funnel: attempts, success rate, failure-class histogram,
  per-stage presence/failure rates (pinpoints where publishes die);
- editorial quality signals already persisted: critic average,
  readability word counts;
- LLM-call estimate: attempts files record *stages*, not individual model
  calls, so per-stage calls are estimated with explicit constants
  (``CALL_MODEL``) and the unmetered parts (headline critic loop,
  per-claim fact-check) are reported as a nominal upper bound, never as
  measured data. The ``assumptions`` block in the output states this.
  Closing the metering gap (persisting real call counts) is recorded as
  follow-up work, not done here.
- source-health roll-up: source counts by ``operational_state``.

On-demand, operator-invoked, read-only: writes nothing except the report
itself (``--output``). Same shape as ``scripts/ops/prune_workflow_runs.py``.

Usage:
    python scripts/ops/publish_cost_report.py [--output reports/publish_cost.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)

DEFAULT_ATTEMPTS_DIR = os.path.join("data", "runtime", "publication_attempts")
DEFAULT_SOURCE_HEALTH = os.path.join("data", "exports", "source_health.json")

# Per-stage LLM-call model. Attempts persist stages, not calls, so these
# are documented nominal constants (upper bounds), NOT measurements:
# - editor_refinement: 1 drafter call.
# - editorial_critic: critic runs max_editorial_retries=1 -> up to 2 passes.
# - headlines loop and per-claim fact-check calls are NOT recorded in
#   attempts files (Stage-5 headlines regenerate every publish, uncached;
#   fact-check costs 1 call per claim). They enter the estimate only via
#   HEADLINE_NOMINAL_MAX / FACTCHECK_NOMINAL_MAX below.
CALL_MODEL = {
    "editor_refinement": 1,
    "editorial_critic": 2,
}
# config.toml max_headline_retries=2 -> 3 attempts x (generate + critic).
HEADLINE_NOMINAL_MAX = 6
# No claim counts in attempts files; nominal placeholder for a typical
# fact_check block so the bound stays explicit, not silent.
FACTCHECK_NOMINAL_MAX = 5
# Auditor samples a fraction of publishes (config editorial_auditor).
AUDITOR_SAMPLING_RATE = 0.2


@dataclass
class ArticleCost:
    article_id: str
    success: bool
    failure_class: str | None
    stages_present: list[str] = field(default_factory=list)
    stages_failed: list[str] = field(default_factory=list)
    critic_average: float | None = None
    words: int | None = None
    estimated_calls_metered_part: int = 0


@dataclass
class CostReport:
    attempts_total: int = 0
    attempts_unparseable: int = 0
    succeeded: int = 0
    success_rate: float = 0.0
    failure_classes: dict[str, int] = field(default_factory=dict)
    stage_presence: dict[str, int] = field(default_factory=dict)
    stage_failures: dict[str, int] = field(default_factory=dict)
    critic_average_mean: float | None = None
    words_mean: float | None = None
    estimated_calls_metered_total: int = 0
    estimated_calls_per_article_mean: float = 0.0
    nominal_unmetered_per_article_max: int = 0
    sources_total: int = 0
    sources_by_state: dict[str, int] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)


def _stage_detail(stages: list[dict], name: str) -> dict:
    for stage in stages:
        if stage.get("name") == name:
            details = stage.get("details")
            return details if isinstance(details, dict) else {}
    return {}


def parse_attempt_file(path: Path) -> ArticleCost | None:
    """Parse one attempts file; None when unparseable (counted, not fatal)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        logger.warning(f"Skipping unparseable attempts file {path}: {err}")
        return None
    stages = payload.get("stages") or []
    present = [s.get("name") for s in stages if isinstance(s, dict) and s.get("name")]
    failed = [
        s.get("name")
        for s in stages
        if isinstance(s, dict) and s.get("name") and s.get("success") is False
    ]
    critic_details = _stage_detail(stages, "editorial_critic")
    readability = _stage_detail(stages, "readability")
    critic_avg = critic_details.get("average")
    words = readability.get("words")
    metered = sum(CALL_MODEL.get(name, 0) for name in present)
    return ArticleCost(
        article_id=str(payload.get("article_id", path.stem)),
        success=bool(payload.get("success", False)),
        failure_class=payload.get("failure_class"),
        stages_present=present,
        stages_failed=failed,
        critic_average=(
            float(critic_avg) if isinstance(critic_avg, (int, float)) else None
        ),
        words=int(words) if isinstance(words, int) else None,
        estimated_calls_metered_part=metered,
    )


def load_attempts(attempts_dir: Path) -> tuple[list[ArticleCost], int]:
    costs: list[ArticleCost] = []
    unparseable = 0
    if not attempts_dir.is_dir():
        raise FileNotFoundError(f"attempts dir not found: {attempts_dir}")
    for path in sorted(attempts_dir.glob("*.json")):
        if path.name.endswith(".frontend_validation.json"):
            continue
        parsed = parse_attempt_file(path)
        if parsed is None:
            unparseable += 1
        else:
            costs.append(parsed)
    return costs, unparseable


def load_source_states(source_health_path: Path) -> Counter:
    states: Counter = Counter()
    if not source_health_path.is_file():
        logger.warning(f"source health export not found: {source_health_path}")
        return states
    try:
        payload = json.loads(source_health_path.read_text(encoding="utf-8"))
    except ValueError as err:
        logger.warning(
            f"Skipping unparseable source health {source_health_path}: {err}"
        )
        return states
    sources = payload.get("sources") or {}
    for record in sources.values():
        if isinstance(record, dict):
            states[str(record.get("operational_state", "unknown"))] += 1
    return states


def build_report(
    costs: list[ArticleCost],
    unparseable: int,
    source_states: Counter,
) -> CostReport:
    report = CostReport()
    report.attempts_total = len(costs)
    report.attempts_unparseable = unparseable
    report.succeeded = sum(1 for c in costs if c.success)
    if costs:
        report.success_rate = round(report.succeeded / len(costs), 4)
    report.failure_classes = dict(
        Counter(c.failure_class or "unknown" for c in costs if not c.success)
    )
    presence: Counter = Counter()
    failures: Counter = Counter()
    for cost in costs:
        presence.update(cost.stages_present)
        failures.update(cost.stages_failed)
    report.stage_presence = dict(sorted(presence.items()))
    report.stage_failures = dict(sorted(failures.items()))
    critic_vals = [c.critic_average for c in costs if c.critic_average is not None]
    if critic_vals:
        report.critic_average_mean = round(sum(critic_vals) / len(critic_vals), 3)
    word_vals = [c.words for c in costs if c.words is not None]
    if word_vals:
        report.words_mean = round(sum(word_vals) / len(word_vals), 1)
    report.estimated_calls_metered_total = sum(
        c.estimated_calls_metered_part for c in costs
    )
    if costs:
        report.estimated_calls_per_article_mean = round(
            report.estimated_calls_metered_total / len(costs), 2
        )
    report.nominal_unmetered_per_article_max = (
        HEADLINE_NOMINAL_MAX + FACTCHECK_NOMINAL_MAX
    )
    report.sources_total = sum(source_states.values())
    report.sources_by_state = dict(sorted(source_states.items()))
    report.assumptions = [
        "Attempts files record stages, not model calls: metered estimate uses "
        f"CALL_MODEL {CALL_MODEL}; headline loop and per-claim fact-check are "
        "unmetered and bounded nominally at "
        f"{HEADLINE_NOMINAL_MAX}+{FACTCHECK_NOMINAL_MAX} calls/article.",
        f"Auditor cost applies to ~{AUDITOR_SAMPLING_RATE:.0%} of publishes "
        "(sampling_rate) and is advisory-only; not in the per-article sum.",
        "Lead time is not reported: attempts files carry completion time only.",
        "Follow-up (not this plan): persist real per-stage call counts so the "
        "estimate can be replaced by measurement.",
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts-dir", default=DEFAULT_ATTEMPTS_DIR)
    parser.add_argument("--source-health", default=DEFAULT_SOURCE_HEALTH)
    parser.add_argument("--output", default=None)
    parser.add_argument("--pretty", action="store_true", default=True)
    args = parser.parse_args(argv)

    try:
        costs, unparseable = load_attempts(Path(args.attempts_dir))
    except FileNotFoundError as err:
        logger.error(str(err))
        return 2
    states = load_source_states(Path(args.source_health))
    report = build_report(costs, unparseable, states)
    text = json.dumps(
        asdict(report), indent=2 if args.pretty else None, ensure_ascii=False
    )
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    logger.info(
        f"cost report: {report.attempts_total} attempts, "
        f"success_rate={report.success_rate}, "
        f"est_calls/article~{report.estimated_calls_per_article_mean} "
        f"(+<={report.nominal_unmetered_per_article_max} nominal)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
