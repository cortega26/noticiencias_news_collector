"""Tests for security gating utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import security_gate


def test_load_json_lines_handles_json_lines(tmp_path: Path) -> None:
    report = tmp_path / "gitleaks.json"
    payload = {
        "file": "alerts/exposed_key.txt",
        "secret": "abcd1234abcd1234",
        "ruleID": "generic-api-key",
    }
    report.write_text("\n".join(json.dumps(payload) for _ in range(2)), encoding="utf-8")

    records = security_gate._load_json_lines(report)  # type: ignore[attr-defined]

    assert len(records) == 2
    assert records[0]["file"] == "alerts/exposed_key.txt"


def test_gitleaks_findings_enforces_allowlist_and_severity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / ".gitleaks.toml"
    config.write_text(
        """title = \"Test\"\n[allowlist]\npaths = ['''^ignore/''']\nregexes = []\n""",
        encoding="utf-8",
    )
    monkeypatch.setattr(security_gate, "GITLEAKS_CONFIG", config, raising=False)

    report = tmp_path / "report.json"
    findings = [
        {
            "file": "alerts/critical.txt",
            "secret": "abcd1234abcd1234",
            "ruleID": "generic-api-key",
            "severity": "HIGH",
        },
        {
            "file": "ignore/fixture.txt",
            "secret": "abcd1234abcd1234",
            "ruleID": "generic-api-key",
            "severity": "HIGH",
        },
        {
            "file": "alerts/medium.txt",
            "secret": "abcd1234abcd1234",
            "ruleID": "generic-api-key",
            "severity": "LOW",
        },
    ]
    report.write_text("\n".join(json.dumps(item) for item in findings), encoding="utf-8")

    gated = security_gate.gitleaks_findings(report, "HIGH")

    assert gated == [
        {
            "path": "alerts/critical.txt",
            "rule_id": "generic-api-key",
            "severity": "HIGH",
        }
    ]


def test_pip_audit_findings_honors_allowlist(tmp_path: Path) -> None:
    report = tmp_path / "pip-audit.json"
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "jinja2",
                        "version": "3.1.4",
                        "vulns": [
                            {"id": "GHSA-q2x7-8rv6-6q7h", "severity": "HIGH"},
                            {"id": "CVE-0000-0000", "severity": "HIGH"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    findings = security_gate.pip_audit_findings(report, "HIGH")

    assert findings == [
        {
            "dependency": "jinja2==3.1.4",
            "id": "CVE-0000-0000",
            "severity": "HIGH",
            "fix_versions": [],
        }
    ]
