#!/usr/bin/env python3
"""Evaluate security scanner reports and fail on high severity findings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

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

SECRET_SEVERITY_DEFAULT = "HIGH"

# pip-audit advisories that remain accepted risks until upstream fixes ship.
# Document the rationale and review cadence in SECURITY.md under the Suppression Policy table.
PIP_AUDIT_ALLOWLIST: dict[str, str] = {
    "GHSA-q2x7-8rv6-6q7h": "trufflehog3==3.0.10 pins jinja2==3.1.4",
    "GHSA-gmj6-6f8f-6699": "trufflehog3==3.0.10 pins jinja2==3.1.4",
    "GHSA-cpwx-vrp4-4pq7": "trufflehog3==3.0.10 pins jinja2==3.1.4",
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


def _load_json_lines(report_path: Path) -> list[Dict[str, Any]]:
    """Load a JSON document or JSON lines payload into a list of records."""

    if not report_path.exists():
        return []

    text = report_path.read_text().strip()
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        records: list[Dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


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
            vuln_id = (vuln.get("id") or "").strip()
            if vuln_id in PIP_AUDIT_ALLOWLIST:
                continue
            severity = (vuln.get("severity") or "UNKNOWN").upper()
            if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]:
                findings.append(
                    {
                        "dependency": f"{name}=={version}",
                        "id": vuln_id,
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


def _build_secret_allowlist() -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    allow_paths, allow_regexes = load_allowlist(GITLEAKS_CONFIG)
    path_patterns: list[re.Pattern[str]] = []
    for pattern in allow_paths:
        try:
            path_patterns.append(re.compile(pattern))
        except re.error:
            continue

    secret_patterns: list[re.Pattern[str]] = []
    for pattern in allow_regexes:
        try:
            secret_patterns.append(re.compile(pattern))
        except re.error:
            continue
    return path_patterns, secret_patterns


def _secret_is_allowlisted(
    *,
    path: str,
    secret: str,
    path_patterns: Iterable[re.Pattern[str]],
    secret_patterns: Iterable[re.Pattern[str]],
) -> bool:
    return any(regex.search(path) for regex in path_patterns) or any(
        regex.search(secret) for regex in secret_patterns
    )


def trufflehog_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_json(report_path, [])
    path_patterns, secret_patterns = _build_secret_allowlist()
    findings: List[Dict[str, Any]] = []
    for record in data:
        rule = record.get("rule", {})
        severity = (rule.get("severity") or "LOW").upper()
        path = record.get("path", "")
        secret = record.get("secret", "")
        if _secret_is_allowlisted(
            path=path,
            secret=secret,
            path_patterns=path_patterns,
            secret_patterns=secret_patterns,
        ):
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


def gitleaks_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    records = _load_json_lines(report_path)
    path_patterns, secret_patterns = _build_secret_allowlist()
    findings: List[Dict[str, Any]] = []
    for record in records:
        path = str(record.get("file") or record.get("path") or record.get("File") or "")
        secret = str(
            record.get("secret")
            or record.get("line")
            or record.get("offender")
            or record.get("match")
            or ""
        )
        rule_id = str(
            record.get("ruleID")
            or record.get("rule_id")
            or record.get("description")
            or ""
        )
        severity_raw = str(record.get("severity") or SECRET_SEVERITY_DEFAULT).upper()
        severity = (
            severity_raw if severity_raw in SEVERITY_RANK else SECRET_SEVERITY_DEFAULT
        )
        if _secret_is_allowlisted(
            path=path,
            secret=secret,
            path_patterns=path_patterns,
            secret_patterns=secret_patterns,
        ):
            continue
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]:
            findings.append(
                {
                    "path": path,
                    "rule_id": rule_id,
                    "severity": severity,
                }
            )
    return findings


FINDER_MAP = {
    "pip-audit": pip_audit_findings,
    "bandit": bandit_findings,
    "trufflehog": trufflehog_findings,
    "gitleaks": gitleaks_findings,
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
