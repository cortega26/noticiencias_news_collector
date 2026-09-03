#!/usr/bin/env python3
"""Evaluate security scanner reports and fail on high severity findings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore, import-not-found, import-untyped]

GITLEAKS_CONFIG = Path(".gitleaks.toml")

SEVERITY_RANK = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
    "UNKNOWN": 3,
}

SECRET_SEVERITY_DEFAULT = "HIGH"  # nosec

# pip-audit advisories that remain accepted risks until upstream fixes ship.
# Each entry must include an expiry date so suppressions cannot become permanent.
# Empty: the Pygments 2.20.0 / python-dotenv 1.2.2 / requests 2.34.2 upgrades
# already shipped in requirements.lock, so the previous suppressions
# (GHSA-5239-wwwm-4pmq, GHSA-mf9w-mj56-hr94, GHSA-gc5v-m9x4-r6x2 — all expired
# 2026-08-31) were removed rather than renewed.
PIP_AUDIT_ALLOWLIST: dict[str, dict[str, str]] = {}


def _active_pip_audit_allowlist(today: date | None = None) -> dict[str, str]:
    active: dict[str, str] = {}
    today = today or date.today()
    expired: list[str] = []
    for vuln_id, payload in PIP_AUDIT_ALLOWLIST.items():
        expires_raw = payload.get("expires_on", "").strip()
        reason = payload.get("reason", "").strip()
        if not expires_raw or not reason:
            raise ValueError(
                f"pip-audit allowlist entry {vuln_id} must define reason/expires_on."
            )
        try:
            expires_on = date.fromisoformat(expires_raw)
        except ValueError as exc:
            raise ValueError(
                f"pip-audit allowlist entry {vuln_id} has invalid expires_on: {expires_raw}"
            ) from exc
        if expires_on < today:
            expired.append(f"{vuln_id} (expired {expires_on.isoformat()})")
            continue
        active[vuln_id] = reason

    if expired:
        raise ValueError(
            "Expired pip-audit allowlist entries detected: " + ", ".join(expired)
        )

    return active


def load_status(status_path: Path) -> Dict[str, Any]:
    if status_path.exists():
        data = json.loads(status_path.read_text())
        return data if isinstance(data, dict) else {}
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


def _load_required_json(report_path: Path, tool: str) -> Any:
    if not report_path.exists():
        raise ValueError(
            f"{tool} report not found at {report_path} - scan did not run; "
            "failing closed."
        )

    content = report_path.read_text().strip()
    if not content:
        raise ValueError(
            f"{tool} report at {report_path} is empty - scan produced no output; "
            "failing closed."
        )

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


def _pip_audit_vuln_matches_allowlist(vuln: dict, allowlist: dict[str, str]) -> bool:
    """True when the vuln's primary ID or any alias is in the allowlist."""
    vuln_id = (vuln.get("id") or "").strip()
    aliases = [a.strip() for a in vuln.get("aliases", []) if isinstance(a, str)]
    return bool(
        (vuln_id and vuln_id in allowlist)
        or any(alias in allowlist for alias in aliases)
    )


def pip_audit_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_required_json(report_path, "pip-audit")
    findings: List[Dict[str, Any]] = []
    allowlist = _active_pip_audit_allowlist()
    for dependency in data.get("dependencies", []):
        name = dependency.get("name")
        version = dependency.get("version")
        for vuln in dependency.get("vulns", []):
            if _pip_audit_vuln_matches_allowlist(vuln, allowlist):
                continue
            severity = (vuln.get("severity") or "UNKNOWN").upper()
            if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[threshold]:
                findings.append(
                    {
                        "dependency": f"{name}=={version}",
                        "id": (vuln.get("id") or "").strip(),
                        "severity": severity,
                        "fix_versions": vuln.get("fix_versions", []),
                    }
                )
    return findings


def bandit_findings(report_path: Path, threshold: str) -> List[Dict[str, Any]]:
    data = _load_required_json(report_path, "bandit")
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
    try:
        findings = evaluate(args.tool, args.report, threshold)
    except ValueError as exc:
        print(f"[{args.tool}] {exc}")
        return 1

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
