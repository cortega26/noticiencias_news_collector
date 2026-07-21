"""
Diagnostics module for tracking source health and collection statistics.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from news_collector.config.sources import ALL_SOURCES
from news_collector.observability.enrichment_metrics_store import enrichment_metrics
from news_collector.system.source_health import build_source_health_record

FailureStage = Literal[
    "collector.fetch",
    "collector.parse",
    "collector.validate_payload",
    "collector.apply_filters",
    "storage.upsert",
    "unknown",
]


@dataclass
class SourceHealth:
    source_id: str
    attempted: int = 0
    fetch_ok: int = 0
    parsed_ok: int = 0
    validation_ok: int = 0
    filter_passed: int = 0
    saved: int = 0

    # Filter stats
    skipped_short_content: int = 0
    skipped_short_title: int = 0
    skipped_already_published: int = 0
    skipped_top_n_cutoff: int = 0

    # Failure diagnostics
    primary_failure_stage: Optional[FailureStage] = None
    primary_failure_reason: Optional[str] = None
    http_status: Optional[int] = None
    last_error_details: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    status: Literal["WORKING", "FAILING", "UNKNOWN"] = "UNKNOWN"

    def mark_stage_success(self, stage: str, count: int = 1):
        if stage == "fetch":
            self.fetch_ok += count
        elif stage == "parse":
            self.parsed_ok += count
        elif stage == "validate":
            self.validation_ok += count
        elif stage == "filter":
            self.filter_passed += count
        elif stage == "save":
            self.saved += count

    def record_failure(
        self, stage: FailureStage, reason: str, details: Dict[str, Any] | None = None
    ):
        if self.primary_failure_stage is None:  # Keep first/most significant failure
            self.primary_failure_stage = stage
            self.primary_failure_reason = reason
            if details:
                self.last_error_details = details
                self.http_status = details.get("status_code")


@dataclass
class SourceHealthTracker:
    sources: Dict[str, SourceHealth] = field(default_factory=dict)

    def get_source(self, source_id: str) -> SourceHealth:
        if source_id not in self.sources:
            self.sources[source_id] = SourceHealth(source_id=source_id)
        return self.sources[source_id]

    def record_attempt(self, source_id: str):
        self.get_source(source_id).attempted += 1

    def record_success(self, source_id: str, stage: str, count: int = 1):
        self.get_source(source_id).mark_stage_success(stage, count)

    def record_failure(
        self,
        source_id: str,
        stage: FailureStage,
        reason: str,
        details: Dict[str, Any] | None = None,
    ):
        self.get_source(source_id).record_failure(stage, reason, details)

    def record_filter_rejection(self, source_id: str, filter_type: str, count: int = 1):
        src = self.get_source(source_id)
        if filter_type in ("min_length", "content_too_short"):
            src.skipped_short_content += count
        elif filter_type == "title_too_short":
            src.skipped_short_title += count
        elif filter_type == "duplicate":
            src.skipped_already_published += count
        elif filter_type == "top_n":
            src.skipped_top_n_cutoff += count

    def finalize_status(self):
        for src in self.sources.values():
            if src.saved > 0:
                src.status = "WORKING"
            else:
                src.status = "FAILING"

    def export_json(self, path: str):
        self.finalize_status()
        output: Dict[str, Dict[str, Any]] = {}
        now = datetime.now().isoformat()
        metrics_by_source = enrichment_metrics.get_all_metrics()

        source_ids = sorted(set(ALL_SOURCES) | set(self.sources))

        for sid in source_ids:
            data = self.sources.get(sid)
            observed = {
                "last_run": now,
                "feed_ok": bool(data and data.fetch_ok > 0),
                "pipeline_ok": bool(
                    data
                    and (
                        data.parsed_ok > 0
                        or data.validation_ok > 0
                        or data.filter_passed > 0
                        or data.saved > 0
                    )
                ),
                "content_ok": bool(data and data.saved > 0),
                "content_mode": ALL_SOURCES.get(sid, {}).get("content_mode", "unknown"),
                "enrichment_strategy": ALL_SOURCES.get(sid, {}).get(
                    "enrichment_strategy", "http"
                ),
                "articles_found": data.parsed_ok if data else 0,
                "articles_saved": data.saved if data else 0,
                "latency": 0.0,
                "last_error_message": data.primary_failure_reason if data else None,
            }
            record = build_source_health_record(
                sid,
                source_config=ALL_SOURCES.get(sid, {}),
                observed=observed,
                metrics=metrics_by_source.get(sid, {}),
                failure_stage=data.primary_failure_stage if data else None,
                failure_reason=data.primary_failure_reason if data else None,
                last_run=now,
            )
            output[sid] = record.model_dump(mode="python")

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, Any] = {"sources": output}

        # Emit blacklist suggestions for sources that failed completely
        suggested_blacklist: list[Dict[str, Any]] = []
        for sid in sorted(self.sources):
            data = self.sources[sid]
            if data.saved > 0:
                continue
            if data.attempted == 0:
                continue
            if ALL_SOURCES.get(sid, {}).get("blacklisted"):
                continue

            suggested_blacklist.append(
                {
                    "source_id": sid,
                    "reason": (
                        data.primary_failure_reason
                        or f"No articles saved ({data.parsed_ok} found, {data.saved} saved)"
                    ),
                    "failure_stage": data.primary_failure_stage,
                    "run_attempted": data.attempted,
                }
            )

        if suggested_blacklist:
            payload["suggested_blacklist"] = suggested_blacklist

        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def print_summary_table(self):
        self.finalize_status()
        print("\n🏥 REPORTE DE SALUD DE FUENTES")
        print("=" * 100)
        print(
            f"{'FUENTE':<20} | {'ESTADO':<8} | {'FOUND':<5} | {'SAVED':<5} | {'FILT:LEN':<8} | {'FILT:DEDUP':<10} | {'DIAGNOSIS'}"
        )
        print("-" * 100)

        for sid, data in self.sources.items():
            status_icon = "✅" if data.status == "WORKING" else "❌"
            diagnosis = ""
            if data.status == "FAILING":
                diagnosis = (
                    f"{data.primary_failure_stage}: {data.primary_failure_reason}"[:35]
                )

            print(
                f"{sid[:20]:<20} | {status_icon} {data.status[:7]:<6} | {data.parsed_ok:<5} | {data.saved:<5} | {data.skipped_short_content:<8} | {data.skipped_already_published:<10} | {diagnosis}"
            )
        print("=" * 100)
