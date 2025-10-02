#!/usr/bin/env python3
"""Repository-wide placeholder scanner."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - exercised in tests
    yaml = None  # type: ignore[assignment]

DEFAULT_EXTENSIONS = {
    ".py",
    ".md",
    ".rst",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".env",
    ".json",
    ".cfg",
    ".sh",
    ".bash",
    ".xml",
    ".html",
}

DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "reports",
    ".coverage",
    ".coverage.py",
}

EXCLUDE_PATTERNS = [".coverage"]

SEVERITY_BY_EXT = {
    "high": {".py"},
    "medium": {
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".env",
        ".json",
        ".cfg",
        ".xml",
        ".html",
        ".sh",
        ".bash",
    },
    "low": {".md", ".rst", ".txt"},
}

GIT_BLAME_CACHE: Dict[Tuple[Path, int, int], Tuple[str, str]] = {}


@dataclass
class Pattern:
    tag: str
    kind: str
    regex: str
    description: str
    suggested_fix: str
    flags: Sequence[str]
    compiled: re.Pattern


@dataclass
class Finding:
    tag: str
    kind: str
    file: str
    line_start: int
    line_end: int
    snippet: str
    description: str
    severity: str
    suggested_fix: str
    author: str = ""
    author_time: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "tag": self.tag,
            "kind": self.kind,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "snippet": self.snippet,
            "description": self.description,
            "severity": self.severity,
            "suggested_fix": self.suggested_fix,
            "author": self.author,
            "author_time": self.author_time,
        }


def parse_flags(flag_names: Sequence[str]) -> int:
    flag_value = 0
    for name in flag_names:
        if not name:
            continue
        upper = name.upper()
        if upper == "IGNORECASE":
            flag_value |= re.IGNORECASE
        elif upper == "MULTILINE":
            flag_value |= re.MULTILINE
        elif upper == "DOTALL":
            flag_value |= re.DOTALL
        else:
            raise ValueError(f"Unsupported regex flag: {name}")
    return flag_value


def _parse_inline_list(value: str) -> List[Any]:
    if value == "[]":
        return []
    items: List[str] = []
    buffer = ""
    in_quote = False
    quote_char = ""
    for char in value:
        if char in {'"', "'"}:
            if not in_quote:
                in_quote = True
                quote_char = char
                continue
            if quote_char == char:
                in_quote = False
                continue
        if char == "," and not in_quote:
            if buffer.strip():
                items.append(_coerce_scalar(buffer.strip()))
            buffer = ""
        else:
            buffer += char
    if buffer.strip():
        items.append(_coerce_scalar(buffer.strip()))
    return items


def _coerce_scalar(value: str) -> Any:
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        return _parse_inline_list(value[1:-1].strip())
    if value[0] in {'"', "'"} and value[-1] == value[0]:
        raw = value[1:-1]
        return bytes(raw, "utf-8").decode("unicode_escape")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _fallback_yaml_load(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_list: List[Dict[str, Any]] | None = None
    current_item: Dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            if ":" not in line:
                continue
            key, remainder = line.split(":", 1)
            key = key.strip()
            value = remainder.strip()
            if value:
                data[key] = _coerce_scalar(value)
                current_list = None
                current_item = None
            else:
                current_list = []
                data[key] = current_list
                current_item = None
        elif indent >= 2:
            if line.startswith("- "):
                if current_list is None:
                    continue
                entry_line = line[2:]
                if ":" not in entry_line:
                    continue
                key, value = entry_line.split(":", 1)
                current_item = {key.strip(): _coerce_scalar(value.strip())}
                current_list.append(current_item)
            else:
                if current_item is None:
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                current_item[key.strip()] = _coerce_scalar(value.strip())
    return data


def _load_patterns_data(pattern_path: Path) -> Dict[str, Any]:
    text = pattern_path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _fallback_yaml_load(text)


def load_patterns(pattern_path: Path) -> List[Pattern]:
    data = _load_patterns_data(pattern_path)
    patterns = []
    for entry in data.get("patterns", []):
        flags = entry.get("flags", [])
        compiled = re.compile(entry["regex"], parse_flags(flags))
        patterns.append(
            Pattern(
                tag=entry["tag"],
                kind=entry["kind"],
                regex=entry["regex"],
                description=entry.get("description", ""),
                suggested_fix=entry.get("suggested_fix", ""),
                flags=flags,
                compiled=compiled,
            )
        )
    return patterns


def is_excluded_dir(dirname: str, extra_excludes: Sequence[str]) -> bool:
    if dirname in DEFAULT_EXCLUDES:
        return True
    if dirname in extra_excludes:
        return True
    for pattern in EXCLUDE_PATTERNS:
        if dirname.startswith(pattern):
            return True
    return False


def infer_severity(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in SEVERITY_BY_EXT["high"]:
        return "high"
    if ext in SEVERITY_BY_EXT["medium"]:
        return "medium"
    if ext in SEVERITY_BY_EXT["low"]:
        return "low"
    return "medium"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def gather_context(lines: List[str], start: int, end: int, context: int) -> str:
    start_idx = max(0, start - 1 - context)
    end_idx = min(len(lines), end + context)
    snippet_lines = lines[start_idx:end_idx]
    return "\n".join(snippet_lines).rstrip()


def detect_patterns(
    path: Path,
    display_path: str,
    text: str,
    patterns: Sequence[Pattern],
    context: int,
) -> List[Finding]:
    findings: List[Finding] = []
    lines = text.splitlines()
    for pattern in patterns:
        for match in pattern.compiled.finditer(text):
            start_line = text.count("\n", 0, match.start()) + 1
            end_line = start_line + match.group(0).count("\n")
            snippet = gather_context(lines, start_line, end_line, context)
            findings.append(
                Finding(
                    tag=pattern.tag,
                    kind=pattern.kind,
                    file=display_path,
                    line_start=start_line,
                    line_end=end_line,
                    snippet=snippet,
                    description=pattern.description,
                    severity=infer_severity(path),
                    suggested_fix=pattern.suggested_fix,
                )
            )
    return findings


def detect_python_stubs(
    path: Path, display_path: str, text: str, context: int
) -> List[Finding]:
    lines = text.splitlines()
    findings: List[Finding] = []
    stack: List[int] = []
    for idx, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        while stack and indent <= stack[-1]:
            stack.pop()
        if re.match(r"^\s*(def|async\s+def|class)\b", line):
            stack.append(indent)
            continue
        if stripped == "pass" and stack:
            start_line = idx + 1
            snippet = gather_context(lines, start_line, start_line, context)
            findings.append(
                Finding(
                    tag="PASS_STUB",
                    kind="placeholder",
                    file=display_path,
                    line_start=start_line,
                    line_end=start_line,
                    snippet=snippet,
                    description="Function or class stub uses pass.",
                    severity="high",
                    suggested_fix="Implement the code path or document intentional pass.",
                )
            )
        elif stripped == "..." and stack:
            start_line = idx + 1
            snippet = gather_context(lines, start_line, start_line, context)
            findings.append(
                Finding(
                    tag="ELLIPSIS_STUB",
                    kind="placeholder",
                    file=display_path,
                    line_start=start_line,
                    line_end=start_line,
                    snippet=snippet,
                    description="Function or class stub uses ellipsis.",
                    severity="high",
                    suggested_fix="Replace the ellipsis with real implementation code.",
                )
            )
    return findings


def looks_like_code(line: str) -> bool:
    patterns = [r"\bdef\b", r"\bclass\b", r"\bimport\b", r"\breturn\b", r"=", r"\(.*\)"]
    return any(re.search(p, line) for p in patterns)


def detect_commented_code(
    path: Path, display_path: str, text: str, context: int
) -> List[Finding]:
    findings: List[Finding] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.lstrip()
        prefix = None
        if stripped.startswith("#"):
            prefix = "#"
        elif stripped.startswith("//"):
            prefix = "//"
        elif stripped.startswith("<!--") and "-->" not in stripped:
            # handle multiline HTML comments
            start_idx = idx
            comment_block = [lines[idx]]
            idx += 1
            while idx < len(lines) and "-->" not in lines[idx]:
                comment_block.append(lines[idx])
                idx += 1
            if idx < len(lines):
                comment_block.append(lines[idx])
            if len(comment_block) >= 5:
                content = "\n".join(comment_block)
                if looks_like_code(content):
                    start_line = start_idx + 1
                    end_line = idx + 1 if idx < len(lines) else len(lines)
                    snippet = gather_context(lines, start_line, end_line, context)
                    findings.append(
                        Finding(
                            tag="COMMENTED_CODE",
                            kind="commented_code",
                            file=display_path,
                            line_start=start_line,
                            line_end=end_line,
                            snippet=snippet,
                            description="Large block of commented-out code detected.",
                            severity=infer_severity(path),
                            suggested_fix="Remove the commented code or explain why it must remain.",
                        )
                    )
            idx += 1
            continue
        if not prefix:
            idx += 1
            continue
        start_idx = idx
        block_lines = []
        while idx < len(lines):
            current = lines[idx].lstrip()
            if current.startswith(prefix):
                block_lines.append(lines[idx])
                idx += 1
            else:
                break
        if len(block_lines) >= 5:
            content = "\n".join(block_lines)
            if looks_like_code(content):
                start_line = start_idx + 1
                end_line = start_idx + len(block_lines)
                snippet = gather_context(lines, start_line, end_line, context)
                findings.append(
                    Finding(
                        tag="COMMENTED_CODE",
                        kind="commented_code",
                        file=display_path,
                        line_start=start_line,
                        line_end=end_line,
                        snippet=snippet,
                        description="Large block of commented-out code detected.",
                        severity=infer_severity(path),
                        suggested_fix="Remove the commented code or explain why it must remain.",
                    )
                )
    return findings


def unique_findings(findings: Iterable[Finding]) -> List[Finding]:
    seen = set()
    unique: List[Finding] = []
    for finding in findings:
        key = (
            finding.tag,
            finding.kind,
            finding.file,
            finding.line_start,
            finding.line_end,
            finding.snippet,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def scan_repository(
    root: Path,
    patterns: Sequence[Pattern],
    include_ext: Sequence[str],
    exclude_dirs: Sequence[str],
    context: int,
) -> List[Finding]:
    findings: List[Finding] = []
    include_ext_lower = {ext.lower() for ext in include_ext}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d, exclude_dirs)]
        for filename in filenames:
            path = Path(dirpath) / filename
            ext = path.suffix.lower()
            if ext not in include_ext_lower:
                continue
            text = read_text(path)
            try:
                rel_path = path.relative_to(root)
            except ValueError:
                rel_path = path
            display_path = rel_path.as_posix()
            file_findings = []
            file_findings.extend(
                detect_patterns(path, display_path, text, patterns, context)
            )
            if ext == ".py":
                file_findings.extend(
                    detect_python_stubs(path, display_path, text, context)
                )
            file_findings.extend(
                detect_commented_code(path, display_path, text, context)
            )
            findings.extend(file_findings)
    findings = unique_findings(findings)
    findings.sort(key=lambda f: (f.file, f.line_start, f.tag))
    return findings


def apply_git_blame(root: Path, findings: List[Finding]) -> None:
    for finding in findings:
        key = (Path(finding.file), finding.line_start, finding.line_end)
        if key in GIT_BLAME_CACHE:
            author, author_time = GIT_BLAME_CACHE[key]
            finding.author = author
            finding.author_time = author_time
            continue
        rel_path = Path(finding.file)
        blame_args = [
            "git",
            "blame",
            "-L",
            f"{finding.line_start},{finding.line_end}",
            "--",
            str(rel_path),
        ]
        try:
            result = subprocess.run(
                blame_args,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
            )
        except OSError:
            continue
        if result.returncode != 0:
            continue
        lines = result.stdout.splitlines()
        if not lines:
            continue
        first_line = lines[0]
        match = re.search(
            r"\((?P<author>.+?)\s+(?P<date>\d{4}-\d{2}-\d{2})", first_line
        )
        if match:
            author = match.group("author").strip()
            author_time = match.group("date")
        else:
            author = ""
            author_time = ""
        finding.author = author
        finding.author_time = author_time
        GIT_BLAME_CACHE[key] = (author, author_time)


def write_csv(path: Path, findings: Sequence[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tag",
                "kind",
                "file",
                "line_start",
                "line_end",
                "snippet",
                "description",
                "severity",
                "suggested_fix",
                "author",
                "author_time",
            ]
        )
        for finding in findings:
            writer.writerow(
                [
                    finding.tag,
                    finding.kind,
                    finding.file,
                    finding.line_start,
                    finding.line_end,
                    finding.snippet,
                    finding.description,
                    finding.severity,
                    finding.suggested_fix,
                    finding.author,
                    finding.author_time,
                ]
            )


def write_json(path: Path, findings: Sequence[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump([f.to_dict() for f in findings], handle, indent=2, ensure_ascii=False)


def summarize(findings: Sequence[Finding]) -> Dict[str, Counter]:
    tag_counter = Counter(f.tag for f in findings)
    dir_counter = Counter(Path(f.file).parent.as_posix() or "." for f in findings)
    file_counter = Counter(f.file for f in findings)
    return {
        "tags": tag_counter,
        "dirs": dir_counter,
        "files": file_counter,
    }


def load_baseline(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def _fingerprint_key(tag: str, kind: str, file_path: str, snippet: str) -> str:
    snippet_hash = sha256(snippet.encode("utf-8")).hexdigest()
    return "|".join([tag, kind, file_path, snippet_hash])


def findings_to_fingerprint(findings: Sequence[Finding]) -> Dict[str, Finding]:
    mapping: Dict[str, Finding] = {}
    for finding in findings:
        fingerprint = _fingerprint_key(
            finding.tag,
            finding.kind,
            finding.file,
            finding.snippet,
        )
        mapping[fingerprint] = finding
    return mapping


def baseline_fingerprint(
    entries: Sequence[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        fingerprint = _fingerprint_key(
            entry.get("tag", ""),
            entry.get("kind", ""),
            entry.get("file", ""),
            entry.get("snippet", ""),
        )
        mapping[fingerprint] = entry
    return mapping


def compare_to_baseline(
    findings: Sequence[Finding],
    baseline_entries: Sequence[Dict[str, str]],
) -> Tuple[List[Finding], List[Dict[str, str]]]:
    current_fp = findings_to_fingerprint(findings)
    baseline_fp = baseline_fingerprint(baseline_entries)
    new = [current_fp[key] for key in current_fp.keys() - baseline_fp.keys()]
    resolved = [baseline_fp[key] for key in baseline_fp.keys() - current_fp.keys()]
    return new, resolved


def write_markdown(
    path: Path,
    findings: Sequence[Finding],
    baseline_entries: Sequence[Dict[str, str]],
    new: Sequence[Finding],
    resolved: Sequence[Dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(findings)
    lines = ["# Placeholder Audit", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append("### Counts by tag")
    lines.append("")
    lines.append("| Tag | Count |")
    lines.append("| --- | ---: |")
    for tag, count in summary["tags"].most_common():
        lines.append(f"| {tag} | {count} |")
    if not summary["tags"]:
        lines.append("| *(none)* | 0 |")
    lines.append("")
    lines.append("### Counts by directory")
    lines.append("")
    lines.append("| Directory | Count |")
    lines.append("| --- | ---: |")
    for directory, count in summary["dirs"].most_common():
        lines.append(f"| {directory} | {count} |")
    if not summary["dirs"]:
        lines.append("| *(none)* | 0 |")
    lines.append("")
    lines.append("### Top files")
    lines.append("")
    lines.append("| File | Count |")
    lines.append("| --- | ---: |")
    for file, count in summary["files"].most_common(10):
        lines.append(f"| {file} | {count} |")
    if not summary["files"]:
        lines.append("| *(none)* | 0 |")
    lines.append("")
    lines.append("## New vs Baseline")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("| --- | ---: |")
    lines.append(f"| New | {len(new)} |")
    lines.append(f"| Resolved | {len(resolved)} |")
    unchanged = max(len(findings) - len(new), 0)
    lines.append(f"| Remaining | {unchanged} |")
    lines.append("")
    if new:
        lines.append("### New findings")
        lines.append("")
        for finding in new:
            lines.append(
                f"- `{finding.file}:{finding.line_start}` **{finding.tag}** – {finding.description or finding.snippet.splitlines()[0]}"
            )
        lines.append("")
    if resolved:
        lines.append("### Resolved findings")
        lines.append("")
        for entry in resolved:
            file = entry.get("file", "")
            line = entry.get("line_start", "")
            tag = entry.get("tag", "")
            description = entry.get("description", entry.get("snippet", ""))
            lines.append(f"- `{file}:{line}` **{tag}** – {description}")
        lines.append("")
    lines.append("## Appendix")
    lines.append("")
    files_group: Dict[str, List[Finding]] = defaultdict(list)
    for finding in findings:
        files_group[finding.file].append(finding)
    for file in sorted(files_group.keys()):
        lines.append(f"### {file}")
        lines.append("")
        lines.append(
            "| Line(s) | Tag | Kind | Severity | Description | Suggested fix | Snippet |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for finding in files_group[file]:
            snippet = finding.snippet.replace("\n", "<br />")
            lines.append(
                f"| {finding.line_start}-{finding.line_end} | {finding.tag} | {finding.kind} | {finding.severity} | {finding.description} | {finding.suggested_fix} | {snippet} |"
            )
        lines.append("")
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def save_baseline(path: Path, findings: Sequence[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, findings)


def run_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    include_ext = args.include_ext or sorted(DEFAULT_EXTENSIONS)
    patterns = load_patterns(Path(args.patterns))
    findings = scan_repository(
        root=root,
        patterns=patterns,
        include_ext=include_ext,
        exclude_dirs=args.exclude_dir or [],
        context=args.context,
    )
    if args.blame:
        apply_git_blame(root, findings)

    baseline_path = Path(args.baseline)
    baseline_entries = load_baseline(baseline_path)
    new_findings, resolved_findings = compare_to_baseline(findings, baseline_entries)

    if args.output_csv:
        write_csv(Path(args.output_csv), findings)
    if args.output_json:
        write_json(Path(args.output_json), findings)
    if args.output_md:
        write_markdown(
            Path(args.output_md),
            findings,
            baseline_entries,
            new_findings,
            resolved_findings,
        )

    if args.save_baseline:
        save_baseline(baseline_path, findings)

    if args.compare_baseline:
        max_new = args.max_new
        if max_new is None:
            max_new = int(os.getenv("AUDIT_TODOS_MAX_NEW", "0"))
        if len(new_findings) > max_new:
            print("New placeholder findings exceed allowed threshold:", file=sys.stderr)
            for finding in new_findings:
                print(
                    f"NEW {finding.file}:{finding.line_start} {finding.tag} {finding.description}",
                    file=sys.stderr,
                )
            for entry in resolved_findings:
                print(
                    f"RESOLVED {entry.get('file')}:{entry.get('line_start')} {entry.get('tag')} {entry.get('description', '')}",
                    file=sys.stderr,
                )
            return 2
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan repository for TODOs and placeholders."
    )
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument(
        "--include-ext", nargs="*", help="File extensions to include (with dot)"
    )
    parser.add_argument(
        "--exclude-dir", nargs="*", default=[], help="Additional directories to exclude"
    )
    parser.add_argument(
        "--context", type=int, default=2, help="Context lines to include in snippets"
    )
    parser.add_argument(
        "--patterns", required=True, help="Path to YAML pattern configuration"
    )
    parser.add_argument("--output-csv", help="Path to write CSV report")
    parser.add_argument("--output-json", help="Path to write JSON report")
    parser.add_argument("--output-md", help="Path to write Markdown report")
    parser.add_argument(
        "--baseline",
        default="reports/placeholders.baseline.json",
        help="Baseline JSON path",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Persist the current findings as the baseline",
    )
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare current findings with the baseline",
    )
    parser.add_argument(
        "--blame", action="store_true", help="Include git blame metadata"
    )
    parser.add_argument(
        "--max-new", type=int, help="Maximum allowed new findings before failing"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return run_scan(args)
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"scan_placeholders failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
