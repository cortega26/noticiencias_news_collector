"""Local adversarial review (Codex-quota saver).

Runs the repo's self-review checklist against a git diff using the local
Ollama model — unlimited, offline, zero quota. It is advisory (exit 0
always): a weaker, tireless first pass that catches the mechanical half
of adversarial findings BEFORE spending a Codex review round on them.

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
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_PATH = REPO_ROOT / "docs" / "SELF_REVIEW_CHECKLIST.md"
DEFAULT_MODEL = "qwen3-next:80b-a3b-instruct-q4_K_M"
DEFAULT_API = "http://localhost:11434"
DEFAULT_MAX_CHARS = 24000


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def collect_diff(ref: str, staged: bool, paths: list[str]) -> tuple[str, list[str]]:
    if staged:
        diff = _git("diff", "--cached", "--", *paths)
    else:
        diff = _git("diff", f"{ref}...HEAD", "--", *paths)
    files = _git("diff", "--name-only", (f"{ref}...HEAD" if not staged else "--cached"))
    file_list = [f for f in files.splitlines() if f.strip()]
    return diff, file_list


def build_prompt(diff: str, file_list: list[str], checklist: str) -> str:
    return f"""You are a senior adversarial code reviewer for the Noticiencias
backend repository (Python 3.13, strict contracts, local-first design,
fail-closed behavior). Review ONLY what is in front of you. Flag a finding
ONLY if you can point at the exact lines that support it — no vibes, no
generic advice, no restating the checklist as findings.

CLOSED-WORLD RULE (hard): the diff is a partial view of the repository.
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


def query_ollama(prompt: str, model: str, api: str, ctx: int, timeout: int) -> str:
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:
        raise SystemExit(
            f"ollama request failed ({type(exc).__name__}: {exc}). "
            f"Is Ollama serving {model} at {api}? "
            "Check `curl localhost:11434/api/tags`."
        )
    return payload.get("response", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--ctx", type=int, default=16384)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--out", default=None)
    parser.add_argument("--print-prompt", action="store_true")
    args = parser.parse_args(argv)

    if not CHECKLIST_PATH.exists():
        raise SystemExit(f"checklist not found: {CHECKLIST_PATH}")
    checklist = CHECKLIST_PATH.read_text(encoding="utf-8")
    if not checklist.strip() or "## " not in checklist:
        raise SystemExit(
            f"checklist at {CHECKLIST_PATH} is empty or has no sections — "
            "refusing to review with a degraded lens."
        )
    diff, file_list = collect_diff(args.ref, args.staged, args.paths)
    if not diff.strip():
        print("empty diff — nothing to review.")
        return 0
    if len(diff) > args.max_chars:
        # Cut at the last hunk boundary (else last newline) so the model
        # never receives a mid-line fragment it cannot judge.
        cut = diff.rfind("\n@@ ", 0, args.max_chars)
        cut = cut if cut > 0 else diff.rfind("\n", 0, args.max_chars)
        cut = cut if cut > 0 else args.max_chars
        diff = (
            diff[:cut] + f"\n\n[TRUNCATED by reviewer: {len(diff) - cut} chars omitted]"
        )
    prompt = build_prompt(diff, file_list, checklist)
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
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print()
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
