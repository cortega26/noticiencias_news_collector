"""Local adversarial review (Codex-quota saver).

Runs the repo's self-review checklist against a git diff using the local
Ollama model — unlimited, offline, zero quota. It is advisory (exit 0
always): a weaker, tireless first pass that catches the mechanical half
of adversarial findings BEFORE spending a Codex review round on them.

By default the review covers the WORKING TREE against `--ref` (committed,
staged and unstaged changes). Use `--staged` to review only the index.

Intended flow (see docs/SELF_REVIEW_CHECKLIST.md §F):
    1. python scripts/adversarial_review.py [--ref origin/main] [--out /tmp/rev.md]
    2. Address everything valid, batch the fixes.
    3. Push ONCE, then let Codex review the remainder.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/adversarial_review.py
    PYTHONPATH=. .venv/bin/python scripts/adversarial_review.py --staged
    PYTHONPATH=. .venv/bin/python scripts/adversarial_review.py --ref main --paths news_collector/ scripts/

NOT in CI: needs local Ollama (50GB model) and several minutes. Manual
`make review-local`. Do not run concurrently with heavy Ollama workloads
(e.g. benchmark judge phases) — both will crawl.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404 - deliberate: fixed git argv, no shell, bounded timeout
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_PATH = REPO_ROOT / "docs" / "SELF_REVIEW_CHECKLIST.md"
DEFAULT_MODEL = "qwen3-next:80b-a3b-instruct-q4_K_M"
DEFAULT_API = "http://localhost:11434"
DEFAULT_MAX_CHARS = 24000
_ALLOWED_API_SCHEMES = frozenset({"http", "https"})
_DIFF_SECTION_RE = re.compile(r"^diff --git a/(?P<a>.+) b/(?P<b>.+)$", re.MULTILINE)


def _git(*args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git executable not found in PATH")
    proc = subprocess.run(  # nosec B603 - fixed argv, no shell, bounded timeout
        [git, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def collect_diff(ref: str, staged: bool, paths: list[str]) -> tuple[str, list[str]]:
    """Return (diff, changed files) for the requested scope.

    Default: working tree against `ref`, so committed, staged and unstaged
    edits are all included. `--staged`: index against HEAD only. The path
    filter applies to both the patch and the changed-file list.
    """
    scope = ["--cached"] if staged else [ref]
    diff = _git("diff", *scope, "--", *paths)
    files = _git("diff", *scope, "--name-only", "--", *paths)
    return diff, [f for f in files.splitlines() if f.strip()]


def truncate_diff(diff: str, max_chars: int) -> tuple[str, bool]:
    """Cut at a hunk boundary so the model never receives a mid-line
    fragment. Returns (excerpt, truncated)."""
    if len(diff) <= max_chars:
        return diff, False
    cut = diff.rfind("\n@@ ", 0, max_chars)
    cut = cut if cut > 0 else diff.rfind("\n", 0, max_chars)
    cut = cut if cut > 0 else max_chars
    excerpt = (
        diff[:cut] + f"\n\n[TRUNCATED by reviewer: {len(diff) - cut} chars omitted]"
    )
    return excerpt, True


def omitted_files(excerpt: str, file_list: list[str]) -> list[str]:
    """Files from `file_list` whose hunks are not in the shown excerpt."""
    shown: set[str] = set()
    for section in re.split(r"^(?=diff --git )", excerpt, flags=re.MULTILINE):
        header = _DIFF_SECTION_RE.match(section)
        if header and "@@" in section:
            shown.add(header.group("b"))
    return [f for f in file_list if f not in shown]


def build_prompt(
    diff: str,
    file_list: list[str],
    checklist: str,
    incomplete: list[str],
) -> str:
    incompleteness = ""
    if incomplete:
        incompleteness = (
            "INCOMPLETE INPUT (hard): the diff was truncated, so these files "
            "are partially shown or absent: "
            + ", ".join(incomplete)
            + ". Do not issue a merge verdict. Start your report with the "
            "line `INCOMPLETE REVIEW`, state what could not be examined, and "
            "review only the shown hunks.\n\n"
        )
    return f"""You are a senior adversarial code reviewer for the Noticiencias
backend repository (Python 3.13, strict contracts, local-first design,
fail-closed behavior). Review ONLY what is in front of you. Flag a finding
ONLY if you can point at the exact lines that support it — no vibes, no
generic advice, no restating the checklist as findings.

{incompleteness}CLOSED-WORLD RULE (hard): the diff is a partial view of the repository.
NEVER assert that something does not exist elsewhere (a make target, a
file, a doc, a config key). Absence from the shown diff proves nothing
about the repo. If your finding depends on repo-wide absence, verify it
first by asking for the file — or drop the finding.

Use this checklist as your review lens (it distills real past findings):

---
{checklist}
---

Changed files:
{chr(10).join(f'- {f}' for f in file_list)}

Diff under review:
```diff
{diff}
```

Report in Markdown, highest severity first, with exactly these severities:
- P1: blocks the change (bug, contract violation, ungrounded claim that gates a decision, security issue).
- P2: should fix (correctness risk under realistic conditions, dead code paths, untested resume/retry logic, docs-code drift).
- P3: nit (style, naming, minor clarity).

Each finding: `### [P1/P2/P3] short title`, then: file:line evidence
(quote ≤3 lines), why it matters concretely for THIS diff, and the
cheapest verification or fix. End with a one-paragraph verdict: mergeable
as-is, mergeable after P1s, or needs rework. If a checklist area does not
apply, say so in one line instead of inventing findings. Maximum 12 findings.
"""


def validate_api(api: str) -> str:
    """Only http(s) Ollama endpoints are accepted (no file:/custom schemes)."""
    parsed = urllib.parse.urlparse(api)
    if parsed.scheme not in _ALLOWED_API_SCHEMES or not parsed.netloc:
        raise SystemExit(
            f"refusing non-http(s) Ollama API {api!r}: only http/https endpoints "
            "are allowed."
        )
    return api.rstrip("/")


def query_ollama(prompt: str, model: str, api: str, ctx: int, timeout: int) -> str:
    api = validate_api(api)
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": ctx},
        }
    ).encode()
    req = urllib.request.Request(
        f"{api}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(
            req, timeout=timeout
        ) as resp:  # nosec B310 - http(s) validated above
            payload = json.loads(resp.read())
    except Exception as exc:
        raise SystemExit(
            f"ollama request failed ({type(exc).__name__}: {exc}). "
            f"Is Ollama serving {model} at {api}? "
            "Check `curl localhost:11434/api/tags`."
        ) from exc
    return payload.get("response", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ref",
        default="origin/main",
        help="Base ref compared against the working tree (default: origin/main)",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Review only the staged index (git diff --cached)",
    )
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--ctx", type=int, default=16384)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--out", default=None)
    parser.add_argument("--print-prompt", action="store_true")
    return parser


def load_checklist(path: Path = CHECKLIST_PATH) -> str:
    if not path.exists():
        raise SystemExit(f"checklist not found: {path}")
    checklist = path.read_text(encoding="utf-8")
    if not checklist.strip() or "## " not in checklist:
        raise SystemExit(
            f"checklist at {path} is empty or has no sections — "
            "refusing to review with a degraded lens."
        )
    return checklist


def emit_report(report: str, out: str | None) -> None:
    if out:
        Path(out).write_text(report, encoding="utf-8")
        print(f"report written to {out}")
    else:
        print()
        print(report)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checklist = load_checklist()
    diff, file_list = collect_diff(args.ref, args.staged, args.paths)
    if not diff.strip():
        print("empty diff — nothing to review.")
        return 0

    diff, truncated = truncate_diff(diff, args.max_chars)
    incomplete = omitted_files(diff, file_list) if truncated else []
    if truncated:
        listed = ", ".join(incomplete[:5]) + ("…" if len(incomplete) > 5 else "")
        print(
            f"WARNING: diff truncated at {args.max_chars} chars; review is "
            f"INCOMPLETE for {len(incomplete)} file(s): {listed}",
            file=sys.stderr,
        )

    prompt = build_prompt(diff, file_list, checklist, incomplete)
    if args.print_prompt:
        print(prompt)
        return 0
    print(
        f"reviewing {len(file_list)} files "
        f"({len(diff)} diff chars) with {args.model} ...",
        flush=True,
    )
    report = query_ollama(prompt, args.model, args.api, args.ctx, args.timeout)
    if not report.strip():
        print("review completed: model returned no findings.")
        report = "_No findings reported._\n"
    if incomplete:
        report = (
            f"> INCOMPLETE REVIEW — the diff was truncated at {args.max_chars} "
            f"chars; not fully examined: {', '.join(incomplete)}\n\n{report}"
        )
    emit_report(report, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
