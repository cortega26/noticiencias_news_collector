#!/usr/bin/env python3
"""
Audit Sources CLI — Blacklist management and source health diagnostics.

Usage:
    python scripts/audit_sources.py list-failing          # sources with failures
    python scripts/audit_sources.py suggest-blacklist      # candidates for blacklist
    python scripts/audit_sources.py blacklist <id> --reason "..."  # blacklist a source
    python scripts/audit_sources.py unblacklist <id>       # re-enable a source
    python scripts/audit_sources.py report                 # full audit markdown report
    python scripts/audit_sources.py list-blacklisted       # show blacklisted sources
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from news_collector.config.sources import ALL_SOURCES, load_sources, save_sources


def _get_db() -> "Any":
    """Lazy-import DB manager to avoid circular imports."""
    from news_collector.storage.database import DatabaseManager

    db = DatabaseManager()
    return db


# ── Commands ────────────────────────────────────────────────────────────────


def cmd_list_failing(args: argparse.Namespace) -> int:
    """Show sources with DB failures."""
    db = _get_db()
    with db.get_session() as session:
        from sqlalchemy import or_

        from news_collector.storage.models import Source

        failing = (
            session.query(Source)
            .filter(
                or_(
                    Source.status != "ACTIVE",
                    Source.consecutive_failures > 0,
                )
            )
            .all()
        )

    if not failing:
        print("✅ No failing sources found.")
        return 0

    print(f"\n{'ID':<22} {'Status':<12} {'Failures':<9} {'Error':<50}")
    print("-" * 95)
    for s in sorted(failing, key=lambda x: x.id):
        err = (s.error_message or "")[:48]
        print(f"{s.id:<22} {s.status:<12} {s.consecutive_failures:<9} {err}")
    print(f"\nTotal: {len(failing)} failing sources")
    return 1


def cmd_suggest_blacklist(args: argparse.Namespace) -> int:
    """Identify sources that should be considered for blacklisting."""
    db = _get_db()
    min_failures = getattr(args, "min_failures", 3)

    with db.get_session() as session:
        from sqlalchemy import and_

        from news_collector.storage.models import Source

        candidates = (
            session.query(Source)
            .filter(
                and_(
                    Source.blacklisted.isnot(True),
                    Source.consecutive_failures >= min_failures,
                )
            )
            .all()
        )

    if not candidates:
        print(f"✅ No blacklist candidates found (min_failures={min_failures}).")
        return 0

    print(f"\nBlacklist candidates (≥{min_failures} consecutive failures):")
    print(f"{'ID':<22} {'Failures':<9} {'Status':<12} {'Error':<50}")
    print("-" * 95)
    for s in sorted(candidates, key=lambda x: x.consecutive_failures, reverse=True):
        err = (s.error_message or "")[:48]
        print(f"{s.id:<22} {s.consecutive_failures:<9} {s.status:<12} {err}")

    print(
        f"\nTo blacklist: python scripts/audit_sources.py blacklist <id> --reason '...'"
    )
    return 1


def cmd_blacklist(args: argparse.Namespace) -> int:
    """Mark a source as blacklisted in sources.yaml."""
    source_id = args.source_id
    reason = args.reason or "Manually blacklisted via audit CLI"

    if source_id not in ALL_SOURCES:
        print(f"❌ Source '{source_id}' not found in sources.yaml")
        return 1

    # Reload fresh
    load_sources()

    if source_id not in ALL_SOURCES:
        print(f"❌ Source '{source_id}' not found after reload")
        return 1

    # Update in-memory
    ALL_SOURCES[source_id]["blacklisted"] = True
    ALL_SOURCES[source_id]["blacklist_reason"] = reason
    ALL_SOURCES[source_id]["blacklisted_date"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d"
    )

    # Persist to YAML
    from news_collector.config.sources import ALL_SOURCES as sources_dict
    from news_collector.config.sources import save_sources

    sources_dict[source_id]["blacklisted"] = True
    sources_dict[source_id]["blacklist_reason"] = reason
    sources_dict[source_id]["blacklisted_date"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d"
    )

    # Persist to YAML (mirror cmd_unblacklist ordering: write before success message)
    save_sources(sources_dict)

    print(f"✅ Blacklisted '{source_id}': {reason}")
    return 0


def cmd_unblacklist(args: argparse.Namespace) -> int:
    """Remove blacklist status from a source."""
    source_id = args.source_id

    load_sources()

    if source_id not in ALL_SOURCES:
        print(f"❌ Source '{source_id}' not found.")
        return 1

    config = ALL_SOURCES[source_id]
    if not config.get("blacklisted"):
        print(f"Source '{source_id}' is not blacklisted.")
        return 0

    # Remove blacklist fields
    for key in ["blacklisted", "blacklist_reason", "blacklisted_date"]:
        config.pop(key, None)

    from news_collector.config.sources import ALL_SOURCES as sources_dict

    source_dict = sources_dict.get(source_id, {})
    for key in ["blacklisted", "blacklist_reason", "blacklisted_date"]:
        source_dict.pop(key, None)

    # Persist
    from news_collector.config.sources import save_sources

    save_sources(sources_dict)

    print(
        f"✅ Unblacklisted '{source_id}'. It will be included in future collection cycles."
    )
    return 0


def cmd_list_blacklisted(args: argparse.Namespace) -> int:
    """Show all blacklisted sources."""
    load_sources()

    blacklisted = {
        sid: cfg for sid, cfg in ALL_SOURCES.items() if cfg.get("blacklisted")
    }

    if not blacklisted:
        print("No blacklisted sources.")
        return 0

    print(f"\n{'ID':<22} {'Name':<30} {'Date':<14} Reason")
    print("-" * 100)
    for sid in sorted(blacklisted):
        cfg = blacklisted[sid]
        name = cfg.get("name", "")[:28]
        date = cfg.get("blacklisted_date", "?")[:12]
        reason = cfg.get("blacklist_reason", "")[:40]
        print(f"{sid:<22} {name:<30} {date:<14} {reason}")
    print(f"\nTotal: {len(blacklisted)} blacklisted sources")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a full audit markdown report."""
    load_sources()
    db = _get_db()

    with db.get_session() as session:
        from sqlalchemy import func

        from news_collector.storage.models import Source

        total = session.query(Source).count()
        active = session.query(Source).filter(Source.status == "ACTIVE").count()
        cooldown = session.query(Source).filter(Source.status == "COOLDOWN").count()
        dead = session.query(Source).filter(Source.status == "DEAD").count()
        blacklisted_db = (
            session.query(Source).filter(Source.blacklisted.is_(True)).count()
        )
        failing = session.query(Source).filter(Source.consecutive_failures > 0).count()

    # Sources.yaml stats
    bl_yaml = sum(1 for c in ALL_SOURCES.values() if c.get("blacklisted"))
    manual = sum(1 for c in ALL_SOURCES.values() if c.get("manual_only"))

    # Build report
    lines = []
    lines.append("# Source Audit Report")
    lines.append(
        f"\nGenerated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    lines.append("")

    lines.append("## Overview")
    lines.append(f"- Sources in YAML config: {len(ALL_SOURCES)}")
    lines.append(f"- Sources in DB: {total}")
    lines.append(f"- Active in DB: {active}")
    lines.append(f"- Cooldown in DB: {cooldown}")
    lines.append(f"- Dead in DB: {dead}")
    lines.append(f"- Blacklisted in YAML: {bl_yaml}")
    lines.append(f"- Blacklisted in DB: {blacklisted_db}")
    lines.append(f"- Manual-only: {manual}")
    lines.append(f"- With consecutive failures: {failing}")

    lines.append("\n## Non-Working Sources (from latest reliability sweep)")
    sweep_dir = Path("data/audit")
    if sweep_dir.exists():
        sweeps = sorted(sweep_dir.glob("source_reliability_*.json"), reverse=True)
        if sweeps:
            latest = sweeps[0]
            data = json.loads(latest.read_text())
            non_working = [r for r in data["results"] if r["status"] != "WORKING"]
            lines.append(f"\nLast sweep: {latest.name}")
            lines.append(f"Total sources tested: {data['source_count']}")
            lines.append(f"Working: {data['source_count'] - len(non_working)}")
            lines.append(f"Non-working: {len(non_working)}")
            lines.append("\n| Source | Status | HTTP | Error |")
            lines.append("|--------|--------|------|-------|")
            for r in non_working:
                lines.append(
                    f"| {r['source_id']} | {r['status']} | {r['http_status']} | {r['error_hint']} |"
                )

    lines.append("\n## Known Issues")
    lines.append(
        "- Reddit collector needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env"
    )
    lines.append("- Scrapling enrichment disabled (set ENABLE_HEADLESS=true to enable)")
    lines.append(
        "- PreScorer LLM fallback triggers frequently when NVIDIA provider has parsing issues"
    )

    report = "\n".join(lines) + "\n"

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to: {args.output}")
    else:
        print(report)

    return 0


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Sources CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # list-failing
    p = sub.add_parser("list-failing", help="Show sources with DB failures")
    p.set_defaults(func=cmd_list_failing)

    # suggest-blacklist
    p = sub.add_parser("suggest-blacklist", help="Identify blacklist candidates")
    p.add_argument(
        "--min-failures",
        type=int,
        default=3,
        help="Min consecutive failures (default: 3)",
    )
    p.set_defaults(func=cmd_suggest_blacklist)

    # blacklist
    p = sub.add_parser("blacklist", help="Blacklist a source")
    p.add_argument("source_id", help="Source ID to blacklist")
    p.add_argument("--reason", "-r", help="Blacklist reason", default="")
    p.set_defaults(func=cmd_blacklist)

    # unblacklist
    p = sub.add_parser("unblacklist", help="Remove blacklist from a source")
    p.add_argument("source_id", help="Source ID to unblacklist")
    p.set_defaults(func=cmd_unblacklist)

    # list-blacklisted
    p = sub.add_parser("list-blacklisted", help="Show blacklisted sources")
    p.set_defaults(func=cmd_list_blacklisted)

    # report
    p = sub.add_parser("report", help="Generate full audit report")
    p.add_argument("--output", "-o", help="Output markdown file path")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
