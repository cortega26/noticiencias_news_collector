#!/usr/bin/env python3
"""Deterministic one-cycle smoke runner for Docker CI."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from news_collector.config import ALL_SOURCES
from news_collector.perf import CollectorReplaySession, ReplayEvent, load_replay_fixture
from news_collector.system import create_system

SMOKE_SOURCE_ID = "smoke_replay_source"
SMOKE_FIXTURE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "replay" / "docker_smoke.jsonl"
)


def _shift_fixture_dates(events: List[ReplayEvent]) -> List[ReplayEvent]:
    """Shift fixture publish dates to land within the recency window.

    Smoke fixtures use absolute publish dates (e.g. 2024-01-01) for
    determinism, but ``recent_days_threshold`` in config.toml (365) would
    age them out of collection. Mirror pipeline_e2e._relative_fixture_dates:
    shift every article so the newest one lands ~2h before now, preserving
    relative gaps.
    """
    newest: datetime | None = None
    for event in events:
        for article in event.articles:
            published = article.published or ""
            # Only a trailing "Z" is UTC; replace it anchored so an embedded
            # "Z" elsewhere in the string cannot corrupt the offset.
            if published.endswith("Z"):
                normalized = published[:-1] + "+00:00"
            else:
                normalized = published
            if not normalized:
                continue
            try:
                dt = datetime.fromisoformat(normalized)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if newest is None or dt > newest:
                newest = dt

    if newest is None:
        return events

    offset = datetime.now(timezone.utc) - timedelta(hours=2) - newest

    shifted: List[ReplayEvent] = []
    for event in events:
        articles = []
        for article in event.articles:
            published = article.published
            if published and published.endswith("Z"):
                published = published[:-1] + "+00:00"
            if published:
                try:
                    dt = datetime.fromisoformat(published)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published = (dt + offset).astimezone(timezone.utc).isoformat()
                except ValueError:
                    pass
            articles.append(dataclasses.replace(article, published=published))
        shifted.append(dataclasses.replace(event, articles=tuple(articles)))
    return shifted


def _load_smoke_source() -> Tuple[CollectorReplaySession, Dict[str, Any]]:
    if not SMOKE_FIXTURE_PATH.exists():
        raise FileNotFoundError(f"Missing smoke fixture: {SMOKE_FIXTURE_PATH}")

    events = load_replay_fixture(SMOKE_FIXTURE_PATH)
    replay_session = CollectorReplaySession(_shift_fixture_dates(events))
    source_config_map = replay_session.build_source_config()

    if SMOKE_SOURCE_ID not in source_config_map:
        raise RuntimeError(
            f"Fixture must include source_id='{SMOKE_SOURCE_ID}' for smoke mode."
        )

    source_config = dict(source_config_map[SMOKE_SOURCE_ID])
    source_config.setdefault("collector_type", "rss")
    source_config.setdefault("enrichment_strategy", "none")
    source_config.setdefault("content_mode", "summary_only")
    source_config.setdefault("headless_enabled", False)
    return replay_session, source_config


def _smoke_contract_satisfied(payload: Dict[str, Any]) -> bool:
    return (
        payload.get("sources_processed", 0) == 1
        and payload.get("articles_found", 0) >= 1
    )


async def _run_smoke_cycle() -> int:
    # Enforce deterministic simulation behavior in dry-run scoring.
    random.seed(0)
    os.environ.setdefault("NOTICIENCIAS_SMOKE", "1")

    replay_session, smoke_source_config = _load_smoke_source()
    system = create_system()
    if not system.initialize():
        print("❌ Smoke mode failed: system initialization returned False.")
        return 1

    dispatcher = getattr(system, "collector", None)
    collectors = getattr(dispatcher, "collectors", {})
    rss_collector = collectors.get("rss") if isinstance(collectors, dict) else None
    if rss_collector is None:
        print("❌ Smoke mode failed: RSS collector is unavailable.")
        await system.shutdown()
        return 1

    ALL_SOURCES[SMOKE_SOURCE_ID] = smoke_source_config
    try:
        with replay_session.patch_collector(rss_collector, asynchronous=False):
            result = await system.run_collection_cycle(
                sources_filter=[SMOKE_SOURCE_ID],
                dry_run=True,
                trace_id=f"smoke-{uuid.uuid4()}",
            )
    finally:
        ALL_SOURCES.pop(SMOKE_SOURCE_ID, None)
        await system.shutdown()

    summary = result.get("summary", {})
    payload = {
        "mode": "smoke",
        "sources_processed": summary.get("sources_processed", 0),
        "articles_found": summary.get("articles_found", 0),
        "articles_saved": summary.get("articles_saved", 0),
    }
    print(json.dumps(payload, ensure_ascii=False))

    return 0 if _smoke_contract_satisfied(payload) else 1


def main() -> int:
    try:
        return asyncio.run(_run_smoke_cycle())
    except Exception as exc:
        print(f"❌ Smoke mode failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
