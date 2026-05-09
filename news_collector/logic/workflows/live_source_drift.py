"""Helpers for nightly/manual live source drift reporting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from news_collector.config.sources import ALL_SOURCES
from news_collector.contracts.source_health import SourceHealthRecord

CRITICAL_SOURCE_COHORT = [
    "phys_org",
    "deepmind_blog",
    "harvard_gazette",
    "uw_news",
    "uw_madison_news",
    "medicalxpress",
    "techxplore",
    "openai_blog",
    "reddit_science",
    "sciencedaily_top",
    "michigan_news",
    "microsoft_research",
]


def _load_health_records(payload: Mapping[str, Any] | None) -> dict[str, SourceHealthRecord]:
    records: dict[str, SourceHealthRecord] = {}
    for source_id, raw in (payload or {}).items():
        if not isinstance(raw, Mapping):
            continue
        normalized = {"source_id": source_id, **dict(raw)}
        records[source_id] = SourceHealthRecord.model_validate(normalized)
    return records


def load_source_health_file(path: Path | None) -> dict[str, SourceHealthRecord]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        return {}
    return _load_health_records(payload)


def _strategy_recommendation(record: SourceHealthRecord) -> str | None:
    configured = str(
        ALL_SOURCES.get(record.source_id, {}).get("enrichment_strategy")
        or record.enrichment_strategy
    )

    if (
        configured == "scrapling_stealth"
        and record.scrapling_http_attempts > 0
        and record.scrapling_http_success_rate >= record.scrapling_stealth_success_rate
    ):
        return "prefer_scrapling_http"

    if (
        configured in {"http", "plain_http"}
        and record.failure_taxonomy in {"js_render_required", "anti_bot_block"}
    ):
        return "upgrade_from_plain_http"

    if (
        record.content_mode in {"summary_only", "rss_only", "summary_fallback"}
        and record.headless_seconds_used > 0
        and record.articles_saved == 0
    ):
        return "remove_headless_budget"

    return None


def build_live_source_drift_report(
    *,
    current_records: Mapping[str, SourceHealthRecord],
    baseline_records: Mapping[str, SourceHealthRecord] | None = None,
    monitored_sources: Iterable[str] | None = None,
    save_ratio_drop_threshold: float = 0.3,
    publishable_drop_threshold: float = 0.3,
) -> dict[str, Any]:
    baseline = dict(baseline_records or {})
    sources = list(monitored_sources or CRITICAL_SOURCE_COHORT)

    newly_broken: list[dict[str, Any]] = []
    save_ratio_collapse: list[dict[str, Any]] = []
    publishability_collapse: list[dict[str, Any]] = []
    strategy_mismatch: list[dict[str, Any]] = []
    handoff_regressions: list[dict[str, Any]] = []

    for source_id in sources:
        current = current_records.get(source_id)
        if current is None:
            continue
        previous = baseline.get(source_id)

        if previous is not None:
            became_broken = previous.articles_saved > 0 and current.articles_saved == 0
            new_failure = previous.failure_taxonomy is None and current.failure_taxonomy is not None
            if became_broken or new_failure:
                newly_broken.append(
                    {
                        "source_id": source_id,
                        "baseline_articles_saved": previous.articles_saved,
                        "current_articles_saved": current.articles_saved,
                        "baseline_failure_taxonomy": previous.failure_taxonomy,
                        "current_failure_taxonomy": current.failure_taxonomy,
                        "current_operational_state": current.operational_state,
                    }
                )

            save_ratio_drop = previous.save_ratio - current.save_ratio
            if save_ratio_drop >= save_ratio_drop_threshold:
                save_ratio_collapse.append(
                    {
                        "source_id": source_id,
                        "baseline_save_ratio": previous.save_ratio,
                        "current_save_ratio": current.save_ratio,
                        "delta": round(save_ratio_drop, 3),
                    }
                )

            publishable_drop = previous.publishable_ratio - current.publishable_ratio
            if publishable_drop >= publishable_drop_threshold:
                publishability_collapse.append(
                    {
                        "source_id": source_id,
                        "baseline_publishable_ratio": previous.publishable_ratio,
                        "current_publishable_ratio": current.publishable_ratio,
                        "delta": round(publishable_drop, 3),
                    }
                )

        recommendation = _strategy_recommendation(current)
        if recommendation:
            strategy_mismatch.append(
                {
                    "source_id": source_id,
                    "configured_strategy": ALL_SOURCES.get(source_id, {}).get(
                        "enrichment_strategy",
                        current.enrichment_strategy,
                    ),
                    "observed_strategy": current.enrichment_strategy,
                    "recommendation": recommendation,
                    "plain_http_success_rate": current.plain_http_success_rate,
                    "scrapling_http_success_rate": current.scrapling_http_success_rate,
                    "scrapling_stealth_success_rate": current.scrapling_stealth_success_rate,
                    "headless_seconds_used": current.headless_seconds_used,
                }
            )

        if current.failure_taxonomy == "publication_contract_failure":
            handoff_regressions.append(
                {
                    "source_id": source_id,
                    "failure_taxonomy": current.failure_taxonomy,
                    "last_error_message": current.last_error_message,
                }
            )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "monitored_sources": sources,
        "summary": {
            "sources_evaluated": len(sources),
            "newly_broken_count": len(newly_broken),
            "save_ratio_collapse_count": len(save_ratio_collapse),
            "publishability_collapse_count": len(publishability_collapse),
            "strategy_mismatch_count": len(strategy_mismatch),
            "handoff_regression_count": len(handoff_regressions),
        },
        "newly_broken": newly_broken,
        "save_ratio_collapse": save_ratio_collapse,
        "publishability_collapse": publishability_collapse,
        "strategy_mismatch": strategy_mismatch,
        "handoff_regressions": handoff_regressions,
    }


def render_live_source_drift_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Live Source Drift Report",
        "",
        f"- Sources evaluated: {report['summary']['sources_evaluated']}",
        f"- Newly broken: {report['summary']['newly_broken_count']}",
        f"- Save ratio collapse: {report['summary']['save_ratio_collapse_count']}",
        f"- Publishability collapse: {report['summary']['publishability_collapse_count']}",
        f"- Strategy mismatch: {report['summary']['strategy_mismatch_count']}",
        f"- Frontend handoff regressions: {report['summary']['handoff_regression_count']}",
        "",
    ]

    for section in (
        ("newly_broken", "Newly Broken"),
        ("save_ratio_collapse", "Save Ratio Collapse"),
        ("publishability_collapse", "Publishability Collapse"),
        ("strategy_mismatch", "Strategy Mismatch"),
        ("handoff_regressions", "Frontend Handoff Regressions"),
    ):
        key, title = section
        entries = report.get(key, [])
        lines.append(f"## {title}")
        if not entries:
            lines.extend(["- None", ""])
            continue
        for entry in entries:
            source_id = entry.get("source_id", "unknown")
            lines.append(f"- `{source_id}`: {json.dumps(entry, ensure_ascii=False, sort_keys=True)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
