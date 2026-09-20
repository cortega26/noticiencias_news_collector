"""Pure analysis helpers for the test-suite audit (no I/O beyond given paths).

Answers, from data instead of opinion:
- which measured modules are weakly covered, ranked by risk (missing lines);
- which collected tests never execute any measured repo code;
- which test functions assert nothing / lean on mocks more than on assertions.

Consumed by ``scripts/test_suite_audit.py``; kept in the package so it is
unit-tested and reused (`make test-audit`).
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

_ASSERT_CALLS = frozenset(
    {
        "raises",
        "warns",
        "fail",
        "approx",
        "assert_called",
        "assert_called_once",
        "assert_called_with",
        "assert_called_once_with",
        "assert_any_call",
        "assert_has_calls",
        "assert_not_called",
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_with",
        "assertEqual",
        "assertNotEqual",
        "assertTrue",
        "assertFalse",
        "assertIn",
        "assertNotIn",
        "assertIs",
        "assertIsNot",
        "assertIsNone",
        "assertIsNotNone",
        "assertRaises",
        "assertRaisesRegex",
        "assertAlmostEqual",
        "assertGreater",
        "assertGreaterEqual",
        "assertLess",
        "assertLessEqual",
        "assertIsInstance",
        "assertCountEqual",
        "assertDictEqual",
        "assertListEqual",
        "assertRegex",
        "assertLogs",
        "assertWarns",
    }
)
_MOCK_MARKERS = ("MagicMock", "AsyncMock", "patch(", "monkeypatch.setattr", "mocker")


@dataclass(frozen=True)
class FileCoverage:
    path: str
    statements: int
    covered: int
    branches: int
    covered_branches: int

    @property
    def missing(self) -> int:
        return self.statements - self.covered

    @property
    def line_rate(self) -> float:
        return 100.0 * self.covered / self.statements if self.statements else 100.0


@dataclass
class PackageSummary:
    name: str
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0

    @property
    def line_rate(self) -> float:
        return 100.0 * self.covered / self.statements if self.statements else 100.0

    @property
    def branch_rate(self) -> float:
        return 100.0 * self.covered_branches / self.branches if self.branches else 100.0


@dataclass
class TestQuality:
    """Static findings about test functions."""

    __test__ = False  # not a pytest class

    no_assertion: List[str] = field(default_factory=list)
    mock_heavy: List[Dict[str, Any]] = field(default_factory=list)
    total_tests: int = 0


# ------------------------------------------------------------------ coverage


def load_coverage(path: str | Path) -> Dict[str, FileCoverage]:
    """Parse a ``coverage json`` report into per-file counters."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: Dict[str, FileCoverage] = {}
    for name, info in data.get("files", {}).items():
        s = info.get("summary", {})
        out[name] = FileCoverage(
            path=name,
            statements=int(s.get("num_statements", 0)),
            covered=int(s.get("covered_lines", 0)),
            branches=int(s.get("num_branches", 0)),
            covered_branches=int(s.get("covered_branches", 0)),
        )
    return out


def summarize_packages(
    files: Mapping[str, FileCoverage], depth: int = 2
) -> List[PackageSummary]:
    """Aggregate by the first ``depth`` path components, worst line rate first."""
    acc: Dict[str, PackageSummary] = {}
    for f in files.values():
        parts = Path(f.path).parts
        key = "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1])
        s = acc.setdefault(key or ".", PackageSummary(key or "."))
        s.statements += f.statements
        s.covered += f.covered
        s.branches += f.branches
        s.covered_branches += f.covered_branches
    return sorted(acc.values(), key=lambda p: p.line_rate)


def critical_gaps(
    files: Mapping[str, FileCoverage],
    *,
    min_statements: int = 40,
    threshold: float = 85.0,
) -> List[FileCoverage]:
    """Files below ``threshold`` % ranked by absolute missing lines (risk proxy)."""
    gaps = [
        f
        for f in files.values()
        if f.statements >= min_statements and f.line_rate < threshold
    ]
    return sorted(gaps, key=lambda f: f.missing, reverse=True)


def totals(files: Iterable[FileCoverage]) -> PackageSummary:
    t = PackageSummary("total")
    for f in files:
        t.statements += f.statements
        t.covered += f.covered
        t.branches += f.branches
        t.covered_branches += f.covered_branches
    return t


# ------------------------------------------------------- tests that touch code


def contexts_by_test(coverage_json: str | Path) -> Dict[str, Set[str]]:
    """``test id -> measured files it executed`` from a report made with
    ``--cov-context=test`` (contexts look like ``tests/x.py::test_a|run``)."""
    data = json.loads(Path(coverage_json).read_text(encoding="utf-8"))
    seen: Dict[str, Set[str]] = {}
    for name, info in data.get("files", {}).items():
        for contexts in (info.get("contexts") or {}).values():
            for ctx in contexts:
                test_id = ctx.split("|", 1)[0]
                if test_id:
                    seen.setdefault(test_id, set()).add(name)
    return seen


def tests_touching_no_code(
    collected: Sequence[str], seen: Mapping[str, Set[str]]
) -> List[str]:
    """Collected test ids that never executed a measured line."""
    executed = {t.split("[", 1)[0] for t in seen}
    return [t for t in collected if t.split("[", 1)[0] not in executed]


# ------------------------------------------------------------- static quality


def _has_assertion(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", "")
            if name in _ASSERT_CALLS:
                return True
    return False


def analyze_test_quality(
    tests_dir: str | Path, *, mock_ratio: float = 6.0
) -> TestQuality:
    """Static scan: tests without any assertion; files with many mock operations
    per test (risk of asserting on the fakes instead of the code)."""
    quality = TestQuality()
    for path in sorted(Path(tests_dir).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        funcs = [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
            and not _is_fixture(n)
        ]
        quality.total_tests += len(funcs)
        for fn in funcs:
            if not _has_assertion(fn):
                quality.no_assertion.append(f"{path}::{fn.name}")
        mocks = sum(source.count(m) for m in _MOCK_MARKERS)
        if funcs and mocks / len(funcs) >= mock_ratio:
            quality.mock_heavy.append(
                {"file": str(path), "tests": len(funcs), "mock_ops": mocks}
            )
    quality.mock_heavy.sort(key=lambda d: d["mock_ops"] / d["tests"], reverse=True)
    return quality


def _is_fixture(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if getattr(target, "attr", getattr(target, "id", "")) == "fixture":
            return True
    return False


# ----------------------------------------------------------------- rendering


def render_markdown(
    files: Mapping[str, FileCoverage],
    quality: TestQuality,
    no_code_tests: Sequence[str],
    *,
    threshold: float = 85.0,
    top: int = 20,
) -> str:
    tot = totals(files.values())
    lines = [
        "# Auditoría de la suite de tests",
        "",
        f"- Cobertura líneas: **{tot.line_rate:.1f} %** ({tot.covered}/{tot.statements}); "
        f"branch: **{tot.branch_rate:.1f} %**",
        f"- Tests: {quality.total_tests}; sin aserción: {len(quality.no_assertion)}; "
        f"archivos con muchos mocks: {len(quality.mock_heavy)}; "
        f"tests que no ejecutan código medido: {len(no_code_tests)}",
        "",
        "## Cobertura por paquete (peor primero)",
        "| paquete | líneas % | branch % | líneas |",
        "|---|---:|---:|---:|",
    ]
    for p in summarize_packages(files)[:top]:
        lines.append(
            f"| {p.name} | {p.line_rate:.1f} | {p.branch_rate:.1f} | {p.statements} |"
        )
    lines += [
        "",
        f"## Brechas críticas (<{threshold:.0f} %, por líneas sin cubrir)",
        "| archivo | líneas % | sin cubrir |",
        "|---|---:|---:|",
    ]
    for f in critical_gaps(files, threshold=threshold)[:top]:
        lines.append(f"| {f.path} | {f.line_rate:.1f} | {f.missing} |")
    lines += ["", "## Tests sin aserción (revisar)"]
    lines += [f"- {t}" for t in quality.no_assertion[:top]] or ["- ninguno"]
    lines += ["", "## Archivos con más mocks por test (revisar)"]
    lines += [
        f"- {d['file']}: {d['mock_ops']} ops / {d['tests']} tests"
        for d in quality.mock_heavy[:top]
    ] or ["- ninguno"]
    lines += [
        "",
        "## Tests que no ejecutan ningún código medido",
        "_Heurística: no cuentan los tests que prueban scripts/CLI por subproceso "
        "(no se mide ese proceso) ni el código ejecutado en tiempo de importación; "
        "confirmar a mano antes de borrar._",
    ]
    lines += [f"- {t}" for t in no_code_tests[:top]] or ["- ninguno"]
    return "\n".join(lines) + "\n"
