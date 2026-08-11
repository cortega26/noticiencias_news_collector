#!/usr/bin/env python3
"""Fail-closed validation for the plans/README.md decision ledger.

Checks (all enforced in plans/README.md):
  1. A "Last verified" stamp with a resolvable git commit exists.
  2. Every ledger table row uses a known status value.
  3. DONE plans must not sit in plans/ root unless their row carries "KEEP:".
  4. Every backtick-quoted hex token (>= 7 chars) resolves as a git commit.
  5. Every plan file in plans/ root has a ledger row, and every row has a file.

Exit code 0 on clean ledger, 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LEDGER = "plans/README.md"
VALID_STATUSES = {"TODO", "IN_PROGRESS", "PARTIAL", "DONE", "BLOCKED", "REJECTED"}
HEX_RE = re.compile(r"`([0-9a-f]{7,40})`")
STAMP_RE = re.compile(
    r"\*\*Last verified:\*\* `([0-9a-f]{7,40})` \(\d{4}-\d{2}-\d{2}\)"
)
ROW_RE = re.compile(r"^\|\s*(\d{3})\s*\|(.*)\|(.*)\|$")


def git_ok(root: Path, *args: str) -> bool:
    """True when the git subcommand succeeds in root."""
    try:
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def commit_resolves(root: Path, token: str) -> bool:
    return git_ok(root, "cat-file", "-e", f"{token}^{{commit}}")


def row_status(cells: list[str]) -> str:
    status = cells[-1].strip()
    return status.split()[0].split("(")[0].strip("—–- ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: derived from script location).",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    ledger = root / LEDGER
    plans_dir = root / "plans"

    findings: list[str] = []

    if not ledger.is_file():
        print(f"validate_plans_ledger: {LEDGER} not found under {root}")
        return 1
    if not git_ok(root, "rev-parse", "--git-dir"):
        print(f"validate_plans_ledger: {root} is not a git repository")
        return 1

    text = ledger.read_text(encoding="utf-8")

    # 1. Last-verified stamp.
    stamp = STAMP_RE.search(text)
    if stamp is None:
        findings.append(
            f"{LEDGER}: missing '**Last verified:** `<commit>` (YYYY-MM-DD)' stamp"
        )
    elif not commit_resolves(root, stamp.group(1)):
        findings.append(
            f"{LEDGER}: last-verified commit `{stamp.group(1)}` does not resolve"
        )

    # 2 + 3. Table rows: status enum + DONE-in-root rule.
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if match is None:
            continue
        number, _, raw_status = match.groups()
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        status = row_status(cells)
        rows[number] = status
        if status not in VALID_STATUSES:
            findings.append(f"{LEDGER}: plan {number} has unknown status {status!r}")
            continue
        if status == "DONE" and not _kept_with_reason(line):
            plan_file = plans_dir / f"{number}-*.md"
            plan_dir = plans_dir / number
            in_root = any(plans_dir.glob(f"{number}-*.md")) or plan_dir.is_dir()
            if in_root:
                findings.append(
                    f"{LEDGER}: plan {number} is DONE but still in plans/ root; "
                    "archive it or mark the row with 'KEEP: <reason>'"
                )

    # 4. Commit tokens resolve.
    for token in sorted(set(HEX_RE.findall(text))):
        if not commit_resolves(root, token):
            findings.append(f"{LEDGER}: cited commit `{token}` does not resolve")

    # 5. Rows <-> files drift.
    for plan_file in sorted(plans_dir.glob("[0-9][0-9][0-9]-*.md")):
        if plan_file.name not in ("README.md",) and plan_file.stem[:3] not in rows:
            findings.append(
                f"{LEDGER}: plan {plan_file.stem[:3]} file exists but has no row"
            )
    for number in sorted(rows):
        if (
            not any(plans_dir.glob(f"{number}-*.md"))
            and not (plans_dir / number).is_dir()
        ):
            findings.append(
                f"{LEDGER}: plan {number} row exists but no plan file/folder is present"
            )

    if findings:
        for finding in findings:
            print(f"validate_plans_ledger: {finding}")
        print(f"validate_plans_ledger: {len(findings)} issue(s) found")
        return 1
    print("validate_plans_ledger: OK")
    return 0


def _kept_with_reason(line: str) -> bool:
    return "KEEP:" in line


if __name__ == "__main__":
    sys.exit(main())
