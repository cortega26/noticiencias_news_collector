"""Pure helpers for building stable source-health records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from news_collector.contracts.source_health import (
    SourceFailureTaxonomy,
    SourceHealthRecord,
    SourceOperationalState,
)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_last_run(last_run: Any) -> Optional[str]:
    if isinstance(last_run, datetime):
        return last_run.astimezone(timezone.utc).isoformat()
    if isinstance(last_run, str) and last_run.strip():
        return last_run.strip()
    return None


def classify_failure_taxonomy(
    *,
    feed_ok: bool,
    pipeline_ok: bool,
    articles_saved: int,
    last_error_message: str | None,
    failure_reason: str | None = None,
    failure_stage: str | None = None,
) -> SourceFailureTaxonomy | None:
    error_blob = " ".join(
        part.strip().lower()
        for part in (
            last_error_message or "",
            failure_reason or "",
            failure_stage or "",
        )
        if isinstance(part, str) and part.strip()
    )

    if articles_saved > 0 and not error_blob:
        return None

    if (
        "permalink" in error_blob
        or "frontmatter" in error_blob
        or "validate:content" in error_blob
    ):
        return "publication_contract_failure"

    if (
        "relevance" in error_blob
        or "editorial" in error_blob
        or "auditor" in error_blob
        or "critic" in error_blob
    ):
        return "editorial_relevance_rejection"

    if (
        "cloudflare" in error_blob
        or "captcha" in error_blob
        or "anti-bot" in error_blob
    ):
        return "anti_bot_block"

    if (
        "js" in error_blob
        or "javascript" in error_blob
        or "render" in error_blob
        or "hydration" in error_blob
        or "headless_disabled" in error_blob
    ):
        return "js_render_required"

    if (
        "403" in error_blob
        or "401" in error_blob
        or "429" in error_blob
        or "forbidden" in error_blob
        or "blocked" in error_blob
    ):
        return "article_fetch_blocked"

    if (
        "content_too_short" in error_blob
        or "min_length" in error_blob
        or "too short" in error_blob
    ):
        return "content_too_short"

    if "parse" in error_blob or "extract" in error_blob or "selector" in error_blob:
        return "extraction_parser_mismatch"

    if not feed_ok and not pipeline_ok:
        return "feed_fetch_failure"

    if error_blob:
        return "unknown_failure"

    return None


def classify_operational_state(
    *,
    content_mode: str,
    articles_found: int,
    articles_saved: int,
    save_ratio: float,
) -> SourceOperationalState:
    if articles_saved > 0 and content_mode == "full_text" and save_ratio >= 0.8:
        return "healthy_full_text"

    if (
        articles_saved > 0
        and content_mode in {"summary_only", "summary_fallback"}
        and save_ratio >= 0.5
    ):
        return "healthy_summary_only"

    if articles_found > 0 or articles_saved > 0:
        return "partial_yield_flaky"

    return "failing_suppressed_candidate"


def build_source_health_record(
    source_id: str,
    *,
    source_config: Mapping[str, Any] | None = None,
    observed: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    last_run: Any = None,
) -> SourceHealthRecord:
    config = source_config or {}
    data = observed or {}
    metrics_data = metrics or {}

    articles_found = _to_int(data.get("articles_found"))
    articles_saved = _to_int(data.get("articles_saved"))
    save_ratio = (
        round(articles_saved / max(articles_found, 1), 3) if articles_found else 0.0
    )
    total_attempts = _to_int(metrics_data.get("total_enrichment_attempted"))
    total_publishable = _to_int(metrics_data.get("total_publishable"))
    plain_http_attempts = _to_int(metrics_data.get("plain_http_attempts"))
    plain_http_success = _to_int(metrics_data.get("plain_http_success"))
    scrapling_http_attempts = _to_int(metrics_data.get("scrapling_http_attempts"))
    scrapling_http_success = _to_int(metrics_data.get("scrapling_http_success"))
    scrapling_stealth_attempts = _to_int(metrics_data.get("scrapling_stealth_attempts"))
    scrapling_stealth_success = _to_int(metrics_data.get("scrapling_stealth_success"))
    publishable_ratio = (
        round(total_publishable / max(total_attempts, 1), 3) if total_attempts else 0.0
    )

    last_error_message = data.get("last_error_message")
    if not isinstance(last_error_message, str) or not last_error_message.strip():
        last_error_message = data.get("error_message")
    if not isinstance(last_error_message, str) or not last_error_message.strip():
        last_error_message = failure_reason
    if not isinstance(last_error_message, str) or not last_error_message.strip():
        last_error_message = None

    content_mode = str(
        data.get("content_mode") or config.get("content_mode") or "unknown"
    )
    record = SourceHealthRecord(
        source_id=source_id,
        source_name=str(config.get("name")) if config.get("name") else None,
        language=str(config.get("language")) if config.get("language") else None,
        content_mode=content_mode,
        enrichment_strategy=str(
            data.get("enrichment_strategy")
            or config.get("enrichment_strategy")
            or "http"
        ),
        fetch_mode=(
            str(data.get("fetch_mode") or config.get("fetch_mode"))
            if (data.get("fetch_mode") or config.get("fetch_mode"))
            else None
        ),
        feed_ok=bool(data.get("feed_ok", data.get("success", False))),
        pipeline_ok=bool(data.get("pipeline_ok", True)),
        content_ok=bool(data.get("content_ok", articles_saved > 0)),
        articles_found=articles_found,
        articles_saved=articles_saved,
        save_ratio=save_ratio,
        total_enrichment_attempted=total_attempts,
        total_publishable=total_publishable,
        publishable_ratio=publishable_ratio,
        avg_enrichment_time=_to_float(metrics_data.get("avg_enrichment_time")),
        avg_content_length=_to_float(metrics_data.get("avg_content_length")),
        http_attempts=_to_int(metrics_data.get("http_attempts")),
        plain_http_attempts=plain_http_attempts,
        plain_http_success=plain_http_success,
        plain_http_success_rate=(
            round(plain_http_success / plain_http_attempts, 3)
            if plain_http_attempts
            else 0.0
        ),
        scrapling_http_attempts=scrapling_http_attempts,
        scrapling_http_success=scrapling_http_success,
        scrapling_http_success_rate=(
            round(scrapling_http_success / scrapling_http_attempts, 3)
            if scrapling_http_attempts
            else 0.0
        ),
        headless_attempts=_to_int(metrics_data.get("headless_attempts")),
        scrapling_stealth_attempts=scrapling_stealth_attempts,
        scrapling_stealth_success=scrapling_stealth_success,
        scrapling_stealth_success_rate=(
            round(scrapling_stealth_success / scrapling_stealth_attempts, 3)
            if scrapling_stealth_attempts
            else 0.0
        ),
        proxy_attempts=_to_int(metrics_data.get("proxy_attempts")),
        scholarly_attempts=_to_int(metrics_data.get("scholarly_attempts")),
        proxy_requests_used=_to_int(metrics_data.get("proxy_requests_used")),
        headless_seconds_used=_to_float(metrics_data.get("headless_seconds_used")),
        last_run=_normalize_last_run(last_run)
        or _normalize_last_run(data.get("last_run")),
        latency=_to_float(data.get("latency", data.get("processing_time"))),
        last_error_message=last_error_message,
        failure_taxonomy=classify_failure_taxonomy(
            feed_ok=bool(data.get("feed_ok", data.get("success", False))),
            pipeline_ok=bool(data.get("pipeline_ok", True)),
            articles_saved=articles_saved,
            last_error_message=last_error_message,
            failure_reason=failure_reason,
            failure_stage=failure_stage,
        ),
        operational_state=classify_operational_state(
            content_mode=content_mode,
            articles_found=articles_found,
            articles_saved=articles_saved,
            save_ratio=save_ratio,
        ),
    )
    return record


def serialize_source_health_report(
    source_details: Mapping[str, Mapping[str, Any]],
    *,
    source_configs: Mapping[str, Mapping[str, Any]],
    metrics_by_source: Mapping[str, Mapping[str, Any]] | None = None,
    last_run: Any = None,
) -> Dict[str, Dict[str, Any]]:
    metrics_lookup = metrics_by_source or {}
    serialized: Dict[str, Dict[str, Any]] = {}

    source_ids = sorted(set(source_configs) | set(source_details))

    for source_id in source_ids:
        record = build_source_health_record(
            source_id,
            source_config=source_configs.get(source_id, {}),
            observed=source_details.get(source_id, {}),
            metrics=metrics_lookup.get(source_id, {}),
            last_run=last_run,
        )
        serialized[source_id] = record.model_dump(mode="python")

    return serialized
