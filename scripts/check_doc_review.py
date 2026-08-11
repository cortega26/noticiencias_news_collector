#!/usr/bin/env python3
"""
check_doc_review.py — changed-file gate: code changes that touch contract,
config, or workflow paths must come with an active-doc review in the same PR.

Protected path classes (any change to these triggers the requirement):
  - contracts/ (boundary shapes and adapters)
  - config.toml, noticiencias/config_schema.py (runtime config schema)
  - .github/workflows/ (CI behavior)
  - serving/ and storage/ (public API surface and persistence contracts)

When a protected path changes, at least one ACTIVE doc (README.md or
docs/*.md outside historical scopes) must change in the same set. Edits that
only touch historical scopes (docs/audits/, docs/archive/, docs/reports/,
docs/CHANGELOG.md, plans/) never trigger the requirement.

Usage:
  scripts/check_doc_review.py [--changed file1 file2 ...]
  scripts/check_doc_review.py                  # reads git diff origin/main...HEAD

Exit codes:
  0 — no protected path changed, or an active doc changed alongside
  1 — protected path changed without an active-doc review
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Path classes that own facts repeated in active docs.
PROTECTED_PREFIXES = (
    "news_collector/contracts/",
    "noticiencias/config_schema.py",
    "config.toml",
    ".github/workflows/",
    "news_collector/serving/",
    "news_collector/storage/",
)

# Active docs that carry the facts those paths own. A change to ANY of them
# satisfies the review requirement.
ACTIVE_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/INDEX.md",
    "docs/PIPELINE_CONTRACTS.md",
    "docs/PRODUCT_FLOW.md",
    "docs/SOURCE_OF_TRUTH.md",
    "docs/ci.md",
    "docs/security.md",
    "docs/RUNBOOK_LOCAL_DEV.md",
    "docs/database_deployment.md",
    "docs/testing.md",
)

# Historical scopes: edits here are evidence, not active documentation.
HISTORICAL_PREFIXES = (
    "docs/audits/",
    "docs/archive/",
    "docs/reports/",
    "docs/CHANGELOG.md",
    "docs/adr/",
    "archive/",
    "plans/",
    "audit/",
)

_PROTECTED_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in PROTECTED_PREFIXES) + ")"
)
_HISTORICAL_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in HISTORICAL_PREFIXES) + ")"
)
_ACTIVE_DOC_RE = re.compile(r"^(" + "|".join(re.escape(d) for d in ACTIVE_DOCS) + ")$")


def git_changed_files() -> list[str]:
    """Changed files vs origin/main...HEAD, falling back to local diff."""
    for args in (
        ["git", "diff", "--name-only", "--diff-filter=d", "origin/main...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=d", "HEAD"],
        ["git", "diff", "--name-only", "--cached", "--diff-filter=d"],
        ["git", "diff", "--name-only", "--diff-filter=d"],
    ):
        try:
            proc = subprocess.run(
                args,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        files = [f for f in proc.stdout.splitlines() if f.strip()]
        if files:
            return files
    return []


def classify(files: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (protected, active_docs, historical) changed paths."""
    protected: list[str] = []
    active_docs: list[str] = []
    historical: list[str] = []
    for f in files:
        if _HISTORICAL_RE.match(f):
            historical.append(f)
        elif _ACTIVE_DOC_RE.match(f):
            active_docs.append(f)
        elif _PROTECTED_RE.match(f):
            protected.append(f)
    return protected, active_docs, historical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changed",
        nargs="*",
        default=None,
        help="Explicit changed-file list (testable; default: git diff origin/main...HEAD)",
    )
    args = parser.parse_args(argv)

    files = args.changed if args.changed is not None else git_changed_files()
    protected, active_docs, historical = classify(files)

    if not protected:
        print(
            "[check:doc-review] OK - no contract/config/workflow paths changed"
            f" ({len(historical)} historical-only edit(s) exempt)."
        )
        return 0

    if active_docs:
        print(
            "[check:doc-review] OK - protected paths changed WITH active-doc review: "
            + ", ".join(sorted(active_docs))
        )
        return 0

    print(
        "[check:doc-review] FAIL - protected path(s) changed without an active-doc "
        "review in the same PR:"
    )
    for f in sorted(protected):
        print(f"  - {f}")
    print(
        "\nUpdate at least one of these active docs in the same PR "
        "(docs/AGENTS.md section 9):"
    )
    for d in ACTIVE_DOCS:
        print(f"  - {d}")
    print("\nHistorical-only edits (audits/archive/reports/plans) never require this.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
