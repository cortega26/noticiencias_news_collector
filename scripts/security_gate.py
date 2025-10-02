#!/usr/bin/env python3
"""Evaluate security scanner reports and fail on high severity findings."""

from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[import]

GITLEAKS_CONFIG = Path(".gitleaks.toml")

SEVERITY_RANK = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
    "UNKNOWN": 3,
}


def load_status(status_path: Path) -> Dict[str, Any]:
    if status_path.exists():
        return json.loads(status_path.read_text())
    return {}


def save_status(status_path: Path, data: Dict[str, Any]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _load_json(report_path: Path, default: Any) -> Any:
    if not report_path.exists():
        return default

    content = report_path.read_text().strip()
    if not content:
        return default

    return json.loads(content)


def load_allowlist(config_path: Path) -> tuple[list[str], list[str]]:
    if not config_path.exists():
        return [], []

    data = tomllib.loads(config_path.read_text())
    allowlist = data.get("allowlist", {})
    paths = [
        str(item).strip() for item in allowlist.get("paths", []) if str(item).strip()
    ]
    regexes = [
        str(item).strip() for item in allowlist.get("regexes", []) if str(item).strip()
    ]
    return paths, regexes


def pip_audit_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_json(report_path, {})
    findings: List[Dict[str, Any]] = []
    for dependency in data.get("dependencies", []):
        name = dependency.get("name")
        version = dependency.get("version")
        for vuln in dependency.get("vulns", []):
            severity = (vuln.get("severity") or "UNKNOWN").upper()
            if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]:
                findings.append(
                    {
                        "dependency": f"{name}=={version}",
                        "id": vuln.get("id"),
                        "severity": severity,
                        "fix_versions": vuln.get("fix_versions", []),
                    }
                )
    return findings


def bandit_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_json(report_path, {})
    findings: List[Dict[str, Any]] = []
    for issue in data.get("results", []):
        severity = (issue.get("issue_severity") or "LOW").upper()
        confidence = (issue.get("issue_confidence") or "LOW").upper()
        if (
            SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]
            and SEVERITY_RANK.get(confidence, 0) >= SEVERITY_RANK["MEDIUM"]
        ):
            findings.append(
                {
                    "filename": issue.get("filename"),
                    "test_id": issue.get("test_id"),
                    "severity": severity,
                    "confidence": confidence,
                    "line_number": issue.get("line_number"),
                }
            )
    return findings


def trufflehog_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_json(report_path, [])
    allow_paths, allow_regexes = load_allowlist(GITLEAKS_CONFIG)
    path_patterns = []
    for pattern in allow_paths:
        try:
            path_patterns.append(re.compile(pattern))
        except re.error:
            continue

    secret_patterns = []
    for pattern in allow_regexes:
        try:
            secret_patterns.append(re.compile(pattern))
        except re.error:
            continue
    findings: List[Dict[str, Any]] = []
    for record in data:
        rule = record.get("rule", {})
        severity = (rule.get("severity") or "LOW").upper()
        path = record.get("path", "")
        secret = record.get("secret", "")
        if any(regex.search(path) for regex in path_patterns):
            continue
        if any(regex.search(secret) for regex in secret_patterns):
            continue
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]:
            findings.append(
                {
                    "path": path,
                    "rule_id": rule.get("id"),
                    "severity": severity,
                }
            )
    return findings


FINDER_MAP = {
    "pip-audit": pip_audit_findings,
    "bandit": bandit_findings,
    "trufflehog": trufflehog_findings,
}


def evaluate(tool: str, report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    finder = FINDER_MAP[tool]
    return finder(report_path, threshold)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=sorted(FINDER_MAP.keys()))
    parser.add_argument("report", type=Path)
    parser.add_argument("--severity", default="HIGH")
    parser.add_argument(
        "--status",
        type=Path,
        default=Path("reports/security/status.json"),
        help="Where to persist aggregated scan results.",
    )
    args = parser.parse_args(argv)

    threshold = args.severity.upper()
    findings = evaluate(args.tool, args.report, threshold)

    status = load_status(args.status)
    status[args.tool] = {
        "severity_threshold": threshold,
        "high_findings": findings,
        "status": "fail" if findings else "pass",
    }
    save_status(args.status, status)

    if findings:
        print(f"[{args.tool}] High severity findings detected:")
        for finding in findings:
            print(json.dumps(finding, indent=2))
        return 1

    print(f"[{args.tool}] No findings above {threshold} severity threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
