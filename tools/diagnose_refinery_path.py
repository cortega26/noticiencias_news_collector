#!/usr/bin/env python3
"""
Diagnose why Refinery/Streamlit still resolves an old NEWS_COLLECTOR_PATH.

What it does (deterministic):
- Prints the env vars seen by THIS process (NEWS_COLLECTOR_PATH, etc.).
- Searches for a target old path string in:
  - repo
  - ~/.streamlit and ./.streamlit
  - ~/.config, ~/.local/share, ~/.cache
- Skips big/binary files, skips logs by default.
- Writes a JSON report with matches + suggested next steps.

Usage:
  python tools/diagnose_refinery_path.py \
    --repo . \
    --old "/home/cortega26/noticiencias_news_collector" \
    --out diagnose_refinery_path_report.json

Tip: run with the same interpreter that launches Streamlit:
  .venv-refinery/bin/python tools/diagnose_refinery_path.py --repo . --old "...";
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

DEFAULT_SKIP_GLOBS = [
    "*.log",
    "*.sqlite*",
    "*.db",
    "*.bin",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.webp",
    "*.gif",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.xz",
    "*.7z",
    "*.whl",
    "*.so",
    "*.a",
    "*.o",
    "*.pyc",
    "__pycache__",
    ".git",
    ".venv",
    ".venv-refinery",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
]

MAX_BYTES_DEFAULT = 2_000_000  # 2MB per file to avoid expensive scans


@dataclass
class Match:
    file: str
    line: int
    excerpt: str


@dataclass
class ScanResult:
    root: str
    scanned_files: int
    skipped_files: int
    matches: List[Match]


def _is_binary(data: bytes) -> bool:
    # Heuristic: if NUL byte exists, treat as binary
    return b"\x00" in data


def _should_skip(path: Path, skip_globs: List[str]) -> bool:
    p = str(path)
    for g in skip_globs:
        # directory-like glob entries
        if g in {"__pycache__", ".git", ".venv", ".venv-refinery", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"}:
            if f"/{g}/" in p or p.endswith(f"/{g}"):
                return True
        if path.match(g):
            return True
    return False


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def scan_root(
    root: Path,
    needle: str,
    *,
    skip_globs: List[str],
    max_bytes: int,
) -> ScanResult:
    scanned = 0
    skipped = 0
    matches: List[Match] = []

    for fp in _iter_files(root):
        try:
            if _should_skip(fp, skip_globs):
                skipped += 1
                continue
            st = fp.stat()
            if st.st_size > max_bytes:
                skipped += 1
                continue

            data = fp.read_bytes()
            if _is_binary(data):
                skipped += 1
                continue

            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                skipped += 1
                continue

            scanned += 1
            if needle not in text:
                continue

            # collect line-level matches (bounded)
            for i, line in enumerate(text.splitlines(), start=1):
                if needle in line:
                    excerpt = line.strip()
                    if len(excerpt) > 220:
                        excerpt = excerpt[:217] + "..."
                    matches.append(Match(file=str(fp), line=i, excerpt=excerpt))

        except (PermissionError, FileNotFoundError):
            skipped += 1
            continue

    return ScanResult(root=str(root), scanned_files=scanned, skipped_files=skipped, matches=matches)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Repo root to scan")
    ap.add_argument("--old", required=True, help="Old root path string to find")
    ap.add_argument("--out", default="diagnose_refinery_path_report.json", help="Report JSON path")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES_DEFAULT, help="Max file size to scan")
    ap.add_argument("--include-logs", action="store_true", help="Also scan *.log files")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    needle = args.old

    # 1) Env seen by this process
    env_snapshot = {
        "PWD": os.getcwd(),
        "NEWS_COLLECTOR_PATH": os.getenv("NEWS_COLLECTOR_PATH"),
        "STREAMLIT_SERVER_HEADLESS": os.getenv("STREAMLIT_SERVER_HEADLESS"),
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": os.getenv("STREAMLIT_BROWSER_GATHER_USAGE_STATS"),
        "HOME": os.getenv("HOME"),
        "XDG_CONFIG_HOME": os.getenv("XDG_CONFIG_HOME"),
        "XDG_CACHE_HOME": os.getenv("XDG_CACHE_HOME"),
        "XDG_DATA_HOME": os.getenv("XDG_DATA_HOME"),
        "USER": os.getenv("USER"),
        "SHELL": os.getenv("SHELL"),
        "PYTHON": os.getenv("PYTHON"),
        "VIRTUAL_ENV": os.getenv("VIRTUAL_ENV"),
    }

    home = Path(os.path.expanduser("~"))
    xdg_config = Path(os.getenv("XDG_CONFIG_HOME") or (home / ".config"))
    xdg_cache = Path(os.getenv("XDG_CACHE_HOME") or (home / ".cache"))
    xdg_data = Path(os.getenv("XDG_DATA_HOME") or (home / ".local" / "share"))

    # Typical Streamlit secrets locations
    streamlit_user = home / ".streamlit"
    streamlit_repo = repo / ".streamlit"

    # Build scan roots in priority order (most likely first)
    scan_roots: List[Path] = [
        streamlit_repo,
        streamlit_user,
        repo,
        xdg_config,
        xdg_data,
        xdg_cache,
    ]

    skip_globs = list(DEFAULT_SKIP_GLOBS)
    if args.include_logs:
        skip_globs = [g for g in skip_globs if g != "*.log"]

    results: List[ScanResult] = []
    for r in scan_roots:
        results.append(scan_root(r, needle, skip_globs=skip_globs, max_bytes=args.max_bytes))

    # Summaries
    total_matches = sum(len(r.matches) for r in results)
    likely_sources: List[str] = []
    for r in results:
        if not r.matches:
            continue
        # rank likely cause sources
        if ".streamlit" in r.root:
            likely_sources.append(f"streamlit_secrets_or_config_in:{r.root}")
        if r.root == str(xdg_config):
            likely_sources.append("user_config_in_~/.config")
        if r.root == str(repo):
            likely_sources.append("repo_source_or_generated_files")
        if r.root == str(xdg_cache):
            likely_sources.append("cache_in_~/.cache")

    report = {
        "env_snapshot_seen_by_this_process": env_snapshot,
        "repo": str(repo),
        "needle_old_root": needle,
        "total_matches": total_matches,
        "likely_sources": sorted(set(likely_sources)),
        "results": [asdict(r) for r in results],
        "next_steps_if_env_is_missing": [
            "If NEWS_COLLECTOR_PATH is null/empty here, then Streamlit is being launched without it.",
            "Kill any existing Streamlit process and re-run `make refinery` from the same shell.",
            "If launching from VS Code, ensure the integrated terminal inherits env or use Makefile inline env prefix.",
        ],
        "next_steps_if_matches_found_in_streamlit": [
            "If matches appear under ~/.streamlit or ./.streamlit, remove or update those secrets/config files.",
            "Common files: ~/.streamlit/secrets.toml, ./.streamlit/secrets.toml, ~/.streamlit/config.toml",
        ],
        "next_steps_if_matches_only_in_cache": [
            "If matches only appear in ~/.cache, you can delete the specific cache subtree related to the app safely.",
        ],
    }

    out = Path(args.out).resolve()
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== Diagnose Refinery Path ===")
    print(f"Report: {out}")
    print(f"PWD: {env_snapshot['PWD']}")
    print(f"NEWS_COLLECTOR_PATH (seen here): {env_snapshot['NEWS_COLLECTOR_PATH']!r}")
    print(f"Total matches of old root: {total_matches}")
    if likely_sources:
        print("Likely sources:", ", ".join(sorted(set(likely_sources))))
    print("Top matches (first 20):")
    shown = 0
    for r in results:
        for m in r.matches:
            print(f"- {m.file}:{m.line}  {m.excerpt}")
            shown += 1
            if shown >= 20:
                break
        if shown >= 20:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
