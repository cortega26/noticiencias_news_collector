#!/usr/bin/env python3
"""
portability_path_fix.py
=======================

Safely removes hardcoded absolute paths like:
  /home/<user>/<repo>
from a repository and replaces them with robust, portable code patterns.

Designed for cases like migrating from Windows/WSL to Linux where old
absolute paths were accidentally committed (e.g., sys.path.insert calls,
hardcoded DB paths, etc.).

Safety principles:
- Dry-run by default (no modifications).
- Optional apply mode with per-file backups.
- Report all proposed/applied changes to a JSON file.
- Skip risky/irrelevant files by default (logs, generated outputs, docs, systemd).
- Verify replacements by re-scanning after apply.

Usage examples:
  # 1) See what would change (recommended first)
  python tools/portability_path_fix.py --repo . --old-root /home/cortega26/noticiencias_news_collector

  # 2) Apply changes (creates .bak backups)
  python tools/portability_path_fix.py --repo . --old-root /home/cortega26/noticiencias_news_collector --apply

  # 3) Apply including systemd (normally excluded)
  python tools/portability_path_fix.py --repo . --old-root /home/cortega26/noticiencias_news_collector --apply --include-systemd

Exit codes:
  0: success (dry-run or applied), no verification errors
  2: repo dirty and not allowed
  3: verification failed (string still found in files that should have been fixed)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# ----------------------------
# Configuration defaults
# ----------------------------

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-refinery",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".tox",
}

# Files we skip by default because they're typically docs/generated/logs or deployment config.
DEFAULT_EXCLUDE_GLOBS = [
    "*.log",
    "*.txt",
    "run_output*.txt",
    "*.md",  # we skip markdown by default (docs often mention old paths historically)
    "docs/*",
    "reports/*",
    "config/systemd/*",  # deployment config: don't touch unless explicitly included
]

# Binary-ish extensions to skip
BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".xz",
    ".7z",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".sqlite",
    ".db",
}

TEXT_EXT_WHITELIST = {
    ".py",
    ".pyi",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".ini",
    ".cfg",
    ".service",
    ".sh",
    ".bash",
}


@dataclasses.dataclass
class Change:
    file: str
    line_start: int
    line_end: int
    before: str
    after: str
    rule: str


@dataclasses.dataclass
class FileReport:
    file: str
    changed: bool
    skipped_reason: Optional[str]
    changes: List[Change]


def run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    p = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    out, err = p.communicate()
    return p.returncode, out, err


def is_repo_dirty(repo: Path) -> bool:
    code, out, _ = run(["git", "status", "--porcelain"], cwd=repo)
    if code != 0:
        # If not a git repo, we treat it as dirty to be safe.
        return True
    return bool(out.strip())


def matches_any_glob(path: Path, globs: Iterable[str], repo: Path) -> bool:
    rel = path.relative_to(repo).as_posix()
    for g in globs:
        # Path.match matches from beginning; for "docs/*" it's fine.
        # For "*.md" also works with match on name; so try both name + rel.
        if path.match(g) or Path(rel).match(g):
            return True
    return False


def should_consider_file(
    path: Path, repo: Path, include_systemd: bool
) -> Tuple[bool, Optional[str]]:
    if not path.is_file():
        return False, "not a file"

    # Exclude directories
    for part in path.relative_to(repo).parts:
        if part in DEFAULT_EXCLUDE_DIRS:
            return False, f"excluded dir: {part}"

    # Exclude by extension if clearly binary
    if path.suffix.lower() in BINARY_EXTS:
        return False, f"binary extension: {path.suffix}"

    # Exclude by glob rules unless overridden
    if not include_systemd:
        if matches_any_glob(path, DEFAULT_EXCLUDE_GLOBS, repo):
            return False, "excluded glob (default)"
    else:
        # If include_systemd, we still skip docs/logs by default but not systemd
        globs = [
            g for g in DEFAULT_EXCLUDE_GLOBS if not g.startswith("config/systemd/")
        ]
        if matches_any_glob(path, globs, repo):
            return False, "excluded glob (default)"

    # Only text-ish known extensions or files without extension (rare scripts)
    if path.suffix and path.suffix.lower() not in TEXT_EXT_WHITELIST:
        # allow e.g. Makefile (no extension)
        return False, f"unhandled extension: {path.suffix}"

    # Quick binary sniff: if file contains NUL byte, skip
    try:
        data = path.read_bytes()
    except Exception as e:
        return False, f"cannot read bytes: {e}"

    if b"\x00" in data:
        return False, "contains NUL byte (likely binary)"

    return True, None


def ensure_imports_block(lines: List[str], imports: List[str]) -> List[str]:
    """
    Ensure required imports exist. Conservative approach:
    - If 'from pathlib import Path' missing, add it near other imports.
    - If 'import os' missing, add it.
    """
    text = "\n".join(lines)

    # Determine insertion point after shebang + docstring + initial imports.
    # We'll insert after the last import line in the first import block.
    import_block_end = 0
    in_docstring = False
    docstring_delim = None

    for i, line in enumerate(lines):
        if i == 0 and line.startswith("#!"):
            continue

        # Detect module docstring start/end (triple quotes)
        if not in_docstring and (
            line.strip().startswith('"""') or line.strip().startswith("'''")
        ):
            in_docstring = True
            docstring_delim = line.strip()[:3]
            # single-line docstring
            if line.strip().count(docstring_delim) >= 2 and len(line.strip()) > 3:
                in_docstring = False
                docstring_delim = None
            continue
        elif in_docstring:
            if docstring_delim and docstring_delim in line:
                # end docstring
                in_docstring = False
                docstring_delim = None
            continue

        # Track import block end
        if line.startswith("import ") or line.startswith("from "):
            import_block_end = i + 1
            continue

        # Stop scanning once we hit code after import block
        if (
            import_block_end
            and line.strip()
            and not (line.startswith("import ") or line.startswith("from "))
        ):
            break

    # Insert missing imports
    missing: List[str] = []
    for imp in imports:
        # naive check
        if imp.startswith("import "):
            mod = imp.split()[1]
            if re.search(rf"^\s*import\s+{re.escape(mod)}(\s|$)", text, flags=re.M):
                continue
        elif imp.startswith("from "):
            # e.g. "from pathlib import Path"
            if re.search(r"^\s*from\s+pathlib\s+import\s+Path(\s|$)", text, flags=re.M):
                continue
        missing.append(imp)

    if not missing:
        return lines

    insertion = [m + "\n" for m in missing]
    # Keep a blank line after inserted imports if needed
    if import_block_end == 0:
        # No imports found; insert after shebang (if present)
        idx = 1 if (lines and lines[0].startswith("#!")) else 0
        new_lines = lines[:idx] + insertion + ["\n"] + lines[idx:]
        return new_lines

    new_lines = lines[:import_block_end] + insertion + lines[import_block_end:]
    return new_lines


def apply_rule_sys_path_hardcode(
    content: str, old_root: str
) -> Tuple[str, List[Change]]:
    """
    Replace:
      sys.path.insert(0, "/home/.../repo")
      sys.path.append("/home/.../repo")
    with a robust BASE_DIR insertion.

    We only target exact occurrences with old_root (string match),
    to avoid accidental changes.
    """
    changes: List[Change] = []
    lines = content.splitlines(keepends=True)

    pattern = re.compile(
        r"""
        ^(?P<indent>\s*)
        sys\.path\.(?P<method>insert|append)\(
            (?P<args>.*?)
        \)\s*$
        """,
        re.VERBOSE,
    )

    new_lines = lines[:]
    for idx, line in enumerate(lines):
        m = pattern.match(line.strip("\n"))
        if not m:
            continue
        if old_root not in line:
            continue

        # Replace the entire sys.path.* line with robust snippet.
        indent = m.group("indent")
        snippet = (
            f"{indent}from pathlib import Path\n"
            f"{indent}import os\n"
            f"{indent}import sys\n"
            f"{indent}\n"
            f"{indent}BASE_DIR = Path(os.environ.get('NEWS_COLLECTOR_PATH', Path(__file__).resolve().parents[1])).resolve()\n"
            f"{indent}sys.path.insert(0, str(BASE_DIR))\n"
        )

        before = line
        after = snippet

        # We'll mark replacement later; to avoid shifting indices, store then apply.
        new_lines[idx] = after

        changes.append(
            Change(
                file="",
                line_start=idx + 1,
                line_end=idx + 1,
                before=before.rstrip("\n"),
                after=after.rstrip("\n"),
                rule="sys.path hardcoded -> BASE_DIR from env/__file__",
            )
        )

    return "".join(new_lines), changes


def apply_rule_db_path_hardcode(
    content: str, old_root: str
) -> Tuple[str, List[Change]]:
    """
    Replace:
      Path("/home/.../repo/data/news.db")
    with:
      ROOT = Path(os.environ.get("NEWS_COLLECTOR_PATH", Path.cwd())).resolve()
      DB_PATH_ABS = ROOT / "data" / "news.db"

    Only applies when the literal old_root appears in the Path string.
    """
    changes: List[Change] = []
    lines = content.splitlines(keepends=True)

    # Very targeted: Path(".../data/news.db") or Path('.../data/news.db')
    pat = re.compile(r"""Path\((?P<q>["'])(?P<path>[^"']+)(?P=q)\)""")

    new_lines = lines[:]
    for idx, line in enumerate(lines):
        if old_root not in line:
            continue
        m = pat.search(line)
        if not m:
            continue
        full_path = m.group("path")
        # Only target DB under old root
        if not full_path.startswith(old_root):
            continue
        if "/data/" not in full_path or not full_path.endswith(".db"):
            continue

        indent = re.match(r"^\s*", line).group(0)
        # Identify file name
        db_name = Path(full_path).name  # e.g. news.db

        replacement = (
            f"{indent}ROOT = Path(os.environ.get('NEWS_COLLECTOR_PATH', Path.cwd())).resolve()\n"
            f"{indent}DB_PATH_ABS = ROOT / 'data' / '{db_name}'\n"
        )

        before = line
        after = replacement
        new_lines[idx] = after

        changes.append(
            Change(
                file="",
                line_start=idx + 1,
                line_end=idx + 1,
                before=before.rstrip("\n"),
                after=after.rstrip("\n"),
                rule="Path('/home/.../data/*.db') -> ROOT / 'data' / db",
            )
        )

    return "".join(new_lines), changes


def apply_rule_systemd_workdir(
    content: str, old_root: str, repo_hint_name: str
) -> Tuple[str, List[Change]]:
    """
    For systemd unit files, replace:
      WorkingDirectory=/home/.../repo
      EnvironmentFile=/home/.../repo/config/...
    with:
      WorkingDirectory=%h/<repo_hint_name>
      EnvironmentFile=%h/<repo_hint_name>/config/...
    This is only applied when include_systemd is enabled.
    """
    changes: List[Change] = []
    lines = content.splitlines(keepends=True)
    new_lines = lines[:]

    for idx, line in enumerate(lines):
        if old_root not in line:
            continue

        if line.startswith("WorkingDirectory=") and old_root in line:
            before = line.rstrip("\n")
            after = f"WorkingDirectory=%h/{repo_hint_name}\n".rstrip("\n")
            new_lines[idx] = after + "\n"
            changes.append(
                Change(
                    file="",
                    line_start=idx + 1,
                    line_end=idx + 1,
                    before=before,
                    after=after,
                    rule="systemd WorkingDirectory -> %h/repo",
                )
            )

        if line.startswith("EnvironmentFile=") and old_root in line:
            # preserve trailing relative portion
            rel = line.split("=", 1)[1].strip()
            suffix = rel[len(old_root) :].lstrip("/")
            before = line.rstrip("\n")
            after = f"EnvironmentFile=%h/{repo_hint_name}/{suffix}".rstrip("\n")
            new_lines[idx] = after + "\n"
            changes.append(
                Change(
                    file="",
                    line_start=idx + 1,
                    line_end=idx + 1,
                    before=before,
                    after=after,
                    rule="systemd EnvironmentFile -> %h/repo/...",
                )
            )

    return "".join(new_lines), changes


def process_file(
    path: Path,
    repo: Path,
    old_root: str,
    apply: bool,
    backups: bool,
    include_systemd: bool,
) -> FileReport:
    consider, reason = should_consider_file(path, repo, include_systemd=include_systemd)
    if not consider:
        return FileReport(
            file=str(path.relative_to(repo)),
            changed=False,
            skipped_reason=reason,
            changes=[],
        )

    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return FileReport(
            file=str(path.relative_to(repo)),
            changed=False,
            skipped_reason="non-utf8 text",
            changes=[],
        )
    except Exception as e:
        return FileReport(
            file=str(path.relative_to(repo)),
            changed=False,
            skipped_reason=f"read error: {e}",
            changes=[],
        )

    if old_root not in original:
        return FileReport(
            file=str(path.relative_to(repo)),
            changed=False,
            skipped_reason=None,
            changes=[],
        )

    updated = original
    all_changes: List[Change] = []

    # Rule 1: sys.path hardcodes (python files)
    if path.suffix.lower() == ".py":
        updated, changes1 = apply_rule_sys_path_hardcode(updated, old_root=old_root)
        all_changes.extend(changes1)

        updated, changes2 = apply_rule_db_path_hardcode(updated, old_root=old_root)
        all_changes.extend(changes2)

        # Ensure imports if we injected Path/os/sys lines
        if any("BASE_DIR" in c.after or "ROOT = Path(" in c.after for c in all_changes):
            lines = updated.splitlines(keepends=True)
            lines = ensure_imports_block(
                lines, imports=["import os", "import sys", "from pathlib import Path"]
            )
            updated = "".join(lines)

    # Rule 2: systemd (only if enabled)
    if include_systemd and path.suffix.lower() == ".service":
        repo_hint_name = repo.name
        updated, changes3 = apply_rule_systemd_workdir(
            updated, old_root=old_root, repo_hint_name=repo_hint_name
        )
        all_changes.extend(changes3)

    # If no changes actually created, report as not changed (but found old_root)
    if updated == original or not all_changes:
        return FileReport(
            file=str(path.relative_to(repo)),
            changed=False,
            skipped_reason="matched old_root but no safe rule applied (manual review needed)",
            changes=[],
        )

    # Fill file field in each Change
    rel = str(path.relative_to(repo))
    for c in all_changes:
        c.file = rel

    # Apply
    if apply:
        if backups:
            bak = path.with_suffix(path.suffix + ".bak")
            # Avoid overwriting existing backups: keep last backup
            if not bak.exists():
                shutil.copy2(path, bak)
        path.write_text(updated, encoding="utf-8")

    return FileReport(
        file=rel,
        changed=(apply and updated != original),
        skipped_reason=None,
        changes=all_changes,
    )


def scan_repo(repo: Path) -> List[Path]:
    files: List[Path] = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        # exclude dirs quickly
        try:
            rel_parts = p.relative_to(repo).parts
        except Exception:
            continue
        if any(part in DEFAULT_EXCLUDE_DIRS for part in rel_parts):
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=str, default=".", help="Repository root path")
    ap.add_argument(
        "--old-root",
        type=str,
        required=True,
        help="Old absolute repo root to eliminate",
    )
    ap.add_argument(
        "--apply", action="store_true", help="Apply changes (otherwise dry-run)"
    )
    ap.add_argument(
        "--report", type=str, default="path_fix_report.json", help="JSON report output"
    )
    ap.add_argument(
        "--no-backups", action="store_true", help="Disable .bak backups when applying"
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running even if git status is dirty",
    )
    ap.add_argument(
        "--include-systemd",
        action="store_true",
        help="Allow modifications in config/systemd/*.service",
    )
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    old_root = args.old_root.rstrip("/")

    if not repo.exists():
        print(f"ERROR: repo does not exist: {repo}", file=sys.stderr)
        return 1

    if not args.allow_dirty and is_repo_dirty(repo):
        print(
            "ERROR: repo has uncommitted changes. Commit/stash first, or use --allow-dirty.",
            file=sys.stderr,
        )
        return 2

    files = scan_repo(repo)
    results: List[FileReport] = []

    for f in files:
        rep = process_file(
            path=f,
            repo=repo,
            old_root=old_root,
            apply=args.apply,
            backups=(not args.no_backups),
            include_systemd=args.include_systemd,
        )
        # Only keep files where old_root appeared OR changes were applied OR skip reason exists
        # (reduces noise)
        if rep.changes or rep.skipped_reason:
            results.append(rep)

    # Write report
    report_path = repo / args.report
    report_data = {
        "repo": str(repo),
        "old_root": old_root,
        "apply": bool(args.apply),
        "include_systemd": bool(args.include_systemd),
        "backups": (not args.no_backups),
        "files": [
            {
                "file": r.file,
                "changed": r.changed,
                "skipped_reason": r.skipped_reason,
                "changes": [dataclasses.asdict(c) for c in r.changes],
            }
            for r in results
        ],
        "summary": {
            "files_touched_or_flagged": len(results),
            "files_with_changes": sum(1 for r in results if r.changes),
        },
    }
    report_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Report written to: {report_path}")
    if not args.apply:
        print("Dry-run mode (no files modified). Re-run with --apply to write changes.")
        return 0

    # Verification: rescan only relevant files and check old_root not present
    # (excluding docs/logs by default already)
    leftovers: List[str] = []
    for r in results:
        if not r.changes:
            continue
        p = repo / r.file
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if old_root in txt:
            leftovers.append(r.file)

    if leftovers:
        print(
            "ERROR: Verification failed. old_root still present in files:",
            file=sys.stderr,
        )
        for lf in leftovers:
            print(f"  - {lf}", file=sys.stderr)
        print("Check report JSON and review those files manually.", file=sys.stderr)
        return 3

    print("Apply complete and verified: old_root no longer present in modified files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
