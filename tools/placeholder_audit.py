"""Structured placeholder audit CLI."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:  # pragma: no cover - optional dependency
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover - executed in tests
    _pyyaml = None
try:  # pragma: no cover - optional dependency
    from ruamel.yaml import YAML as _RuamelYAML
except ModuleNotFoundError:  # pragma: no cover - executed in tests
    _RuamelYAML = None

PLACEHOLDER_PATTERN = re.compile(
    r"\b(TODO|FIXME|TBD)\s*\[(?P<attrs>[^\]]+)\]\s*:\s*(?P<text>.+)"
)

CONFIG_PATH = Path(".placeholder-audit.yaml")

CONTEXT_WEIGHTS: Dict[str, float] = {
    "prod_code": 1.0,
    "tests": 0.5,
    "docs": 0.25,
    "generated": 0.0,
}

SARIF_SEVERITIES = {
    "HIGH": "error",
    "MED": "warning",
    "LOW": "note",
}

_ALLOWED_DOC_TBD_CONTEXTS = {"docs"}


class PlaceholderAuditError(RuntimeError):
    """Raised when the audit cannot be executed."""


@dataclass
class AgeThresholds:
    warn: int
    high: int


@dataclass
class AuditConfig:
    include: Sequence[str]
    exclude: Sequence[str]
    contexts: Dict[str, Sequence[str]]
    required_fields: Sequence[str]
    due_format: str
    warn_window_days: int
    age_threshold_days: AgeThresholds
    block_severities: Sequence[str]
    delta_mode: bool
    pr_halo_lines: int

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "AuditConfig":
        if not path.exists():
            raise PlaceholderAuditError(f"Configuration file not found: {path}")
        raw = load_yaml_config(path)
        try:
            thresholds = raw.get("age_threshold_days", {})
            return cls(
                include=tuple(raw["include"]),
                exclude=tuple(raw.get("exclude", ())),
                contexts={k: tuple(v) for k, v in raw.get("contexts", {}).items()},
                required_fields=tuple(raw.get("required_fields", ())),
                due_format=str(raw.get("due_format", "YYYY-MM-DD")),
                warn_window_days=int(raw.get("warn_window_days", 7)),
                age_threshold_days=AgeThresholds(
                    warn=int(thresholds.get("warn", 30)),
                    high=int(thresholds.get("high", 90)),
                ),
                block_severities=tuple(raw.get("block_severities", ("HIGH",))),
                delta_mode=bool(raw.get("delta_mode", False)),
                pr_halo_lines=int(raw.get("pr_halo_lines", 10)),
            )
        except KeyError as error:
            raise PlaceholderAuditError(
                f"Missing configuration key: {error.args[0]}"
            ) from error


@dataclass
class DiffLine:
    old_number: Optional[int]
    new_number: Optional[int]
    symbol: str


@dataclass
class DiffFile:
    path: Path
    lines: List[DiffLine] = field(default_factory=list)
    is_binary: bool = False

    def new_line_numbers(self) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for line in self.lines:
            if line.new_number is not None:
                mapping[line.new_number] = line.symbol
        return mapping

    def old_line_numbers(self) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for line in self.lines:
            if line.old_number is not None:
                mapping[line.old_number] = line.symbol
        return mapping


@dataclass
class PlaceholderRecord:
    marker: str
    attributes: Dict[str, str]
    text: str
    file_path: Path
    line_number: int
    context: str
    inside_fence: bool
    severity: str
    score: float
    reasons: List[str]
    suggested_fix: str
    expired: bool
    is_added_or_modified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker": self.marker,
            "attributes": self.attributes,
            "text": self.text,
            "file_path": self.file_path.as_posix(),
            "line_number": self.line_number,
            "context": self.context,
            "inside_fence": self.inside_fence,
            "severity": self.severity,
            "score": self.score,
            "reasons": self.reasons,
            "suggested_fix": self.suggested_fix,
            "expired": self.expired,
            "is_added_or_modified": self.is_added_or_modified,
        }


@dataclass
class AuditReport:
    findings: List[PlaceholderRecord]
    base_high_count: int
    head_high_count: int
    net_new_high: int
    expired_blockers: int


def run_git(args: Sequence[str], cwd: Optional[Path] = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def load_yaml_config(path: Path) -> Dict[str, Any]:
    if _pyyaml is not None:
        with path.open("r", encoding="utf-8") as handle:
            return _pyyaml.safe_load(handle)
    if _RuamelYAML is not None:
        parser = _RuamelYAML(typ="safe")
        with path.open("r", encoding="utf-8") as handle:
            return parser.load(handle)
    raise PlaceholderAuditError(
        "Install PyYAML or ruamel.yaml to load the audit configuration."
    )


def list_tracked_files() -> List[Path]:
    output = run_git(["ls-files"])
    return [Path(line) for line in output.splitlines() if line]


def parse_diff(base: str, halo: int) -> List[DiffFile]:
    diff_text = run_git(["diff", f"--unified={halo}", f"{base}...HEAD"])
    files: List[DiffFile] = []
    current: Optional[DiffFile] = None
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git"):
            if current:
                files.append(current)
            current = None
            continue
        if raw_line.startswith("Binary files"):
            if current:
                current.is_binary = True
            continue
        if raw_line.startswith("--- "):
            continue
        if raw_line.startswith("+++ "):
            path_text = raw_line[4:]
            if path_text == "/dev/null":
                current = DiffFile(path=Path(""))
                continue
            if path_text.startswith("b/"):
                path_text = path_text[2:]
            file_path = Path(path_text)
            current = DiffFile(path=file_path)
            old_line = None
            new_line = None
            continue
        if current is None:
            continue
        if raw_line.startswith("@@"):
            header = raw_line.split("@@")[1].strip()
            parts = header.split(" ")
            minus = parts[0]
            plus = parts[1]
            minus_start, *_ = minus[1:].split(",")
            plus_start, *_ = plus[1:].split(",")
            old_line = int(minus_start)
            new_line = int(plus_start)
            current.lines.append(DiffLine(old_number=None, new_number=None, symbol="@"))
            continue
        if raw_line.startswith("+"):
            symbol = "+"
            current.lines.append(DiffLine(old_number=None, new_number=new_line, symbol=symbol))
            new_line = (new_line or 0) + 1
            continue
        if raw_line.startswith("-"):
            symbol = "-"
            current.lines.append(DiffLine(old_number=old_line, new_number=None, symbol=symbol))
            old_line = (old_line or 0) + 1
            continue
        symbol = " "
        current.lines.append(
            DiffLine(old_number=old_line, new_number=new_line, symbol=symbol)
        )
        old_line = (old_line or 0) + 1
        new_line = (new_line or 0) + 1
    if current:
        files.append(current)
    return files


def build_full_scan_targets(config: AuditConfig) -> List[DiffFile]:
    files: List[DiffFile] = []
    for path in list_tracked_files():
        if match_any(path, config.exclude):
            continue
        if config.include and not match_any(path, config.include):
            continue
        if not path.exists():
            continue
        try:
            line_count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            continue
        diff_lines = [
            DiffLine(old_number=None, new_number=index, symbol="+")
            for index in range(1, line_count + 1)
        ]
        files.append(DiffFile(path=path, lines=diff_lines))
    return files


def match_any(path: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    posix = path.as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
        if pattern.startswith("**/") and (
            fnmatch.fnmatch(posix, pattern[3:])
            or fnmatch.fnmatch(path.name, pattern[3:])
        ):
            return True
    return False


def classify_context(path: Path, config: AuditConfig) -> str:
    posix = path.as_posix()
    preferred = ("tests", "docs")
    for name in preferred:
        for pattern in config.contexts.get(name, ()):  # type: ignore[arg-type]
            if fnmatch.fnmatch(posix, pattern):
                return name
    for name, patterns in config.contexts.items():
        if name in preferred:
            continue
        for pattern in patterns:
            if fnmatch.fnmatch(posix, pattern):
                return name
    return "prod_code"


def parse_attributes(raw: str) -> Dict[str, str]:
    attributes: Dict[str, str] = {}
    for chunk in raw.split(";"):
        key, _, value = chunk.partition("=")
        attributes[key.strip()] = value.strip()
    return attributes


def read_base_file(path: Path, base_ref: str) -> Optional[str]:
    git_path = path.as_posix()
    try:
        return run_git(["show", f"{base_ref}:{git_path}"])
    except subprocess.CalledProcessError:
        return None


def compute_age_days(path: Path, line_number: int) -> Optional[int]:
    try:
        blame_output = run_git(
            [
                "blame",
                "--line-porcelain",
                f"-L{line_number},{line_number}",
                "HEAD",
                path.as_posix(),
            ]
        )
    except subprocess.CalledProcessError:
        return None
    for line in blame_output.splitlines():
        if line.startswith("author-time "):
            timestamp = int(line.split()[1])
            authored = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
            delta = dt.datetime.now(tz=dt.timezone.utc) - authored
            return delta.days
    return None


def validate_issue(value: Optional[str]) -> bool:
    if value is None:
        return False
    if value.startswith("#") and value[1:].isdigit():
        return True
    return bool(re.match(r"https?://", value))


def evaluate_placeholder(
    marker: str,
    attributes: Dict[str, str],
    text: str,
    context: str,
    config: AuditConfig,
    age_days: Optional[int],
    inside_fence: bool,
) -> Tuple[str, float, List[str], str, bool]:
    reasons: List[str] = []
    expired = False
    due_within_window = False
    due_str = attributes.get("due")
    if due_str:
        try:
            due_date = dt.datetime.strptime(due_str, "%Y-%m-%d").date()
            if due_date < dt.date.today():
                expired = True
                reasons.append("due date expired")
            elif (due_date - dt.date.today()).days <= config.warn_window_days:
                due_within_window = True
                reasons.append("due within warn window")
        except ValueError:
            reasons.append("invalid due format")
    completeness_weight = 0.0
    missing_fields = [field for field in config.required_fields if field not in attributes]
    if marker == "TBD" and context in _ALLOWED_DOC_TBD_CONTEXTS:
        if not validate_issue(attributes.get("issue")):
            reasons.append("docs TBD requires linked issue")
            completeness_weight = 1.0
        else:
            completeness_weight = 0.0
    else:
        missing = len(missing_fields)
        if missing == 1:
            completeness_weight = 0.5
            reasons.append(f"missing {missing_fields[0]}")
        elif missing >= 2:
            completeness_weight = 1.0
            reasons.append(f"missing fields: {', '.join(missing_fields)}")
    if "issue" in attributes and not validate_issue(attributes.get("issue")):
        reasons.append("issue must be #id or URL")
        completeness_weight = max(completeness_weight, 0.5)
    context_weight = CONTEXT_WEIGHTS.get(context, CONTEXT_WEIGHTS["prod_code"])
    age_factor = 1.0
    if age_days is not None:
        if age_days > config.age_threshold_days.high:
            age_factor += 0.5
            reasons.append("age > 90d")
        elif age_days > config.age_threshold_days.warn:
            age_factor += 0.25
            reasons.append("age > 30d")
    if completeness_weight == 0.0 and marker != "TBD":
        age_factor = 0.0
    score = context_weight * completeness_weight * age_factor
    severity = "LOW"
    if expired:
        severity = "HIGH"
    else:
        if score >= 1.25:
            severity = "HIGH"
        elif score >= 0.75:
            severity = "MED"
        if due_within_window and severity == "LOW":
            severity = "MED"
        if completeness_weight > 0.0:
            if context == "prod_code":
                severity = "HIGH"
            elif context == "tests":
                severity = "MED"
            elif context == "docs":
                severity = "MED"
    if marker == "TBD" and context in _ALLOWED_DOC_TBD_CONTEXTS and validate_issue(attributes.get("issue")):
        severity = "LOW"
    suggested_fix = "Ensure owner/due/issue metadata is complete"
    if marker == "TBD" and context in _ALLOWED_DOC_TBD_CONTEXTS:
        suggested_fix = "Keep TBD entries inside fenced blocks with linked issue"
    return severity, score, reasons, suggested_fix, expired


def detect_placeholders(
    path: Path,
    content: str,
    new_lines: Dict[int, str],
    context: str,
    config: AuditConfig,
    inside_fence_lines: Set[int],
) -> List[PlaceholderRecord]:
    findings: List[PlaceholderRecord] = []
    for idx, line in enumerate(content.splitlines(), start=1):
        symbol = new_lines.get(idx)
        if symbol is None:
            continue
        match = PLACEHOLDER_PATTERN.search(line)
        if not match:
            continue
        marker = match.group(1)
        attrs = parse_attributes(match.group("attrs"))
        text = match.group("text").strip()
        if path.suffix.lower() == ".md" and idx in inside_fence_lines:
            if validate_issue(attrs.get("issue")):
                continue
        age_days = compute_age_days(path, idx)
        severity, score, reasons, suggested_fix, expired = evaluate_placeholder(
            marker=marker,
            attributes=attrs,
            text=text,
            context=context,
            config=config,
            age_days=age_days,
            inside_fence=idx in inside_fence_lines,
        )
        findings.append(
            PlaceholderRecord(
                marker=marker,
                attributes=attrs,
                text=text,
                file_path=path,
                line_number=idx,
                context=context,
                inside_fence=idx in inside_fence_lines,
                severity=severity,
                score=score,
                reasons=reasons,
                suggested_fix=suggested_fix,
                expired=expired,
                is_added_or_modified=symbol == "+",
            )
        )
    return findings


def track_fences(content: str) -> Set[int]:
    inside = False
    fence_lines: Set[int] = set()
    fence_delimiter: Optional[str] = None
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            delimiter = stripped[:3]
            if inside and fence_delimiter == delimiter:
                inside = False
                fence_delimiter = None
            else:
                inside = True
                fence_delimiter = delimiter
            continue
        if inside:
            fence_lines.add(idx)
    return fence_lines


def summarize(findings: Sequence[PlaceholderRecord]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total": len(findings),
        "by_severity": {"HIGH": 0, "MED": 0, "LOW": 0},
        "high_legacy": [],
    }
    for finding in findings:
        summary["by_severity"][finding.severity] += 1
        if finding.severity == "HIGH" and not finding.is_added_or_modified:
            summary["high_legacy"].append(finding)
    return summary


def build_sarif(findings: Sequence[PlaceholderRecord]) -> Dict[str, Any]:
    results = []
    for finding in findings:
        rule_id = finding.marker
        results.append(
            {
                "ruleId": rule_id,
                "level": SARIF_SEVERITIES.get(finding.severity, "note"),
                "message": {"text": "; ".join(finding.reasons) or finding.text},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": finding.file_path.as_posix()
                            },
                            "region": {
                                "startLine": finding.line_number,
                                "startColumn": 1,
                            },
                        }
                    }
                ],
            }
        )
    return {
        "version": "2.1.0",
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "placeholder-audit",
                        "rules": [
                            {
                                "id": marker,
                                "name": marker,
                                "shortDescription": {"text": f"{marker} placeholder"},
                            }
                            for marker in {f.marker for f in findings}
                        ],
                    }
                },
                "results": results,
            }
        ],
    }


def format_table(findings: Sequence[PlaceholderRecord]) -> str:
    headers = ["File", "Line", "Marker", "Severity", "Reason"]
    rows: List[List[str]] = [headers]
    for finding in findings:
        reason = "; ".join(finding.reasons) or ""
        rows.append(
            [
                finding.file_path.as_posix(),
                str(finding.line_number),
                finding.marker,
                finding.severity,
                reason,
            ]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    lines: List[str] = []
    for idx, row in enumerate(rows):
        formatted = " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))
        lines.append(formatted)
        if idx == 0:
            separator = "-+-".join("-" * width for width in widths)
            lines.append(separator)
    return "\n".join(lines)


def build_pr_comment(findings: Sequence[PlaceholderRecord]) -> str:
    header = "| File:Line | Marker | Severity | Reason | Fix |"
    separator = "| --- | --- | --- | --- | --- |"
    rows = [header, separator]
    for finding in findings[:25]:
        reason = "; ".join(finding.reasons) or "Review placeholder"
        cell = (
            f"| `{finding.file_path.as_posix()}:{finding.line_number}` | {finding.marker} | "
            f"{finding.severity} | {reason} | {finding.suggested_fix} |"
        )
        rows.append(cell)
    return "\n".join(rows)


def count_high(findings: Sequence[PlaceholderRecord]) -> int:
    return sum(1 for finding in findings if finding.severity == "HIGH")


def compute_delta(
    head_findings: Sequence[PlaceholderRecord],
    base_findings: Sequence[PlaceholderRecord],
) -> Tuple[int, int, int]:
    head_high = count_high(head_findings)
    base_high = count_high(base_findings)
    net_new = max(head_high - base_high, 0)
    return base_high, head_high, net_new


def scan_files(
    diff_files: Sequence[DiffFile],
    config: AuditConfig,
    base_ref: str,
) -> AuditReport:
    head_findings: List[PlaceholderRecord] = []
    base_findings: List[PlaceholderRecord] = []
    for diff_file in diff_files:
        if diff_file.is_binary or not diff_file.path:
            continue
        path = diff_file.path
        if match_any(path, config.exclude):
            continue
        if config.include and not match_any(path, config.include):
            continue
        context = classify_context(path, config)
        new_lines = diff_file.new_line_numbers()
        if not new_lines:
            continue
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        fence_lines = track_fences(content)
        head_findings.extend(
            detect_placeholders(
                path=path,
                content=content,
                new_lines=new_lines,
                context=context,
                config=config,
                inside_fence_lines=fence_lines,
            )
        )
        old_lines = diff_file.old_line_numbers()
        if old_lines:
            base_content = read_base_file(path, base_ref)
            if base_content:
                fence_old = track_fences(base_content)
                base_findings.extend(
                    detect_placeholders(
                        path=path,
                        content=base_content,
                        new_lines=old_lines,
                        context=context,
                        config=config,
                        inside_fence_lines=fence_old,
                    )
                )
    base_high, head_high, net_new = compute_delta(head_findings, base_findings)
    expired_blockers = sum(
        1
        for finding in head_findings
        if finding.expired and finding.is_added_or_modified
    )
    return AuditReport(
        findings=head_findings,
        base_high_count=base_high,
        head_high_count=head_high,
        net_new_high=net_new,
        expired_blockers=expired_blockers,
    )


def should_fail(
    report: AuditReport,
    config: AuditConfig,
    *,
    strict: bool,
    pr_diff_only: bool,
) -> bool:
    if strict:
        return report.head_high_count > 0 or report.expired_blockers > 0
    if not pr_diff_only:
        return False
    if not config.delta_mode:
        return report.head_high_count > 0 or report.expired_blockers > 0
    if report.expired_blockers > 0:
        return True
    return report.net_new_high > 0


def run_audit(args: argparse.Namespace) -> int:
    config = AuditConfig.load()
    if args.halo is None:
        args.halo = config.pr_halo_lines
    if args.pr_diff_only:
        diff_files = parse_diff(args.base, args.halo)
        if not diff_files:
            print("No diff to analyze.")
            if args.comment:
                Path(args.comment).write_text(
                    "No placeholder changes detected.",
                    encoding="utf-8",
                )
            if args.sarif:
                empty = build_sarif([])
                Path(args.sarif).write_text(
                    json.dumps(empty, indent=2),
                    encoding="utf-8",
                )
            return 0
    else:
        diff_files = build_full_scan_targets(config)
    report = scan_files(diff_files, config, args.base)
    if args.format == "table":
        print(format_table(report.findings))
    else:
        print(json.dumps([f.to_dict() for f in report.findings], indent=2))
    summary = summarize(report.findings)
    totals = summary["by_severity"]
    print(
        f"Summary: total={summary['total']} high={totals['HIGH']} "
        f"med={totals['MED']} low={totals['LOW']}"
    )
    if summary["high_legacy"]:
        print(
            "Legacy HIGH (no fail): "
            + ", ".join(
                f"{item.file_path.as_posix()}:{item.line_number}" for item in summary["high_legacy"]
            )
        )
    if args.sarif:
        sarif_doc = build_sarif(report.findings)
        Path(args.sarif).write_text(json.dumps(sarif_doc, indent=2), encoding="utf-8")
    if args.comment:
        Path(args.comment).write_text(build_pr_comment(report.findings), encoding="utf-8")
    if should_fail(
        report,
        config,
        strict=args.strict,
        pr_diff_only=args.pr_diff_only,
    ):
        return 1
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Structured placeholder audit")
    parser.add_argument("--base", default="main", help="Base branch for diff")
    parser.add_argument(
        "--pr-diff-only",
        action="store_true",
        help="Limit scan to PR diff and halo",
    )
    parser.add_argument("--halo", type=int, default=None, help="Halo lines around diff")
    parser.add_argument("--sarif", help="Write SARIF report to path")
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )
    parser.add_argument(
        "--comment",
        help="Write PR comment markdown to path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any HIGH severity regardless of delta",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        exit_code = run_audit(args)
    except PlaceholderAuditError as error:
        parser.error(str(error))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
