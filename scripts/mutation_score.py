#!/usr/bin/env python3
"""Per-module mutation score from a finished ``mutmut run`` (reads ``mutants/**/*.meta``).

Usage:
    python scripts/mutation_score.py [--mutants mutants] [--check]

``--check`` fails (exit 1) when a module is below its floor in ``[tool.mutation.floors]``
of ``pyproject.toml`` (a floor is only ever raised: it is the score already achieved).
Score = detected / (detected + survived + untested + suspicious); detected = killed +
timeout + segfault + caught-by-type-check. Survivors are behavior changes no test notices;
"no tests" mutants (code no selected test reaches) also count against the score so that
losing coverage of part of a module cannot keep the gate green. Skipped/unchecked are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Dict, List, Mapping

# mutmut's exit-code -> verdict table (mutmut.stats.status_by_exit_code).
_DETECTED = {1, 3, 36, -24, 24, 152, 255, -11, -9, 37}
_SURVIVED = {0}
_UNTESTED = {5, 33}  # no test reaches the mutated code: counts AGAINST the score
_IGNORED = {34, None}  # skipped / not checked


def module_scores(mutants_dir: Path) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for meta in sorted(mutants_dir.rglob("*.meta")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        counts: Counter[str] = Counter()
        for code in (data.get("exit_code_by_key") or {}).values():
            if code in _SURVIVED:
                counts["survived"] += 1
            elif code in _DETECTED:
                counts["detected"] += 1
            elif code in _UNTESTED:
                counts["untested"] += 1
            elif code in _IGNORED:
                counts["ignored"] += 1
            else:
                counts["suspicious"] += 1  # counted as not detected
        name = str(meta.relative_to(mutants_dir)).removesuffix(".meta")
        out[name] = dict(counts)
    return out


def score(counts: Mapping[str, int]) -> float | None:
    judged = (
        counts.get("detected", 0)
        + counts.get("survived", 0)
        + counts.get("untested", 0)
        + counts.get("suspicious", 0)
    )
    return 100.0 * counts.get("detected", 0) / judged if judged else None


def load_floors(pyproject: Path) -> Dict[str, float]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return {
        str(k): float(v)
        for k, v in data.get("tool", {}).get("mutation", {}).get("floors", {}).items()
    }


def check(
    scores: Mapping[str, Mapping[str, int]], floors: Mapping[str, float]
) -> List[str]:
    """Human-readable violations: below-floor modules and floors without results."""
    problems = []
    for module, floor in floors.items():
        counts = scores.get(module)
        value = score(counts) if counts else None
        if value is None:
            problems.append(f"{module}: no mutation results (floor {floor:.0f} %)")
        elif value + 1e-9 < floor:
            problems.append(f"{module}: {value:.1f} % < floor {floor:.0f} %")
    return problems


def render(scores: Mapping[str, Mapping[str, int]]) -> str:
    lines = [
        "| module | detected | survived | untested | score |",
        "|---|---:|---:|---:|---:|",
    ]
    total: Counter[str] = Counter()
    for module, counts in scores.items():
        total.update(counts)
        value = score(counts)
        lines.append(
            f"| {module} | {counts.get('detected', 0)} | {counts.get('survived', 0)} "
            f"| {counts.get('untested', 0)} "
            f"| {'n/a' if value is None else f'{value:.1f} %'} |"
        )
    value = score(total)
    lines.append(
        f"| **total** | {total['detected']} | {total['survived']} "
        f"| {total['untested']} | {'n/a' if value is None else f'{value:.1f} %'} |"
    )
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mutants", type=Path, default=Path("mutants"))
    ap.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    scores = module_scores(args.mutants)
    print(render(scores))
    if args.check:
        problems = check(scores, load_floors(args.pyproject))
        for line in problems:
            print(f"FAIL {line}", file=sys.stderr)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
