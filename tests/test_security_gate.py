"""Tests for security gating utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import security_gate


def test_pip_audit_missing_report_fails(tmp_path: Path) -> None:
    status = tmp_path / "status.json"

    result = security_gate.main(
        [
            "pip-audit",
            str(tmp_path / "missing.json"),
            "--severity",
            "HIGH",
            "--status",
            str(status),
        ]
    )

    assert result == 1
    assert not status.exists()


def test_bandit_empty_report_fails(tmp_path: Path) -> None:
    report = tmp_path / "bandit.json"
    report.write_text("", encoding="utf-8")
    status = tmp_path / "status.json"

    result = security_gate.main(
        [
            "bandit",
            str(report),
            "--severity",
            "HIGH",
            "--status",
            str(status),
        ]
    )

    assert result == 1
    assert not status.exists()


def test_gitleaks_missing_report_is_clean(tmp_path: Path) -> None:
    status = tmp_path / "status.json"

    result = security_gate.main(
        [
            "gitleaks",
            str(tmp_path / "missing.json"),
            "--severity",
            "HIGH",
            "--status",
            str(status),
        ]
    )

    assert result == 0
    assert (
        json.loads(status.read_text(encoding="utf-8"))["gitleaks"]["status"] == "pass"
    )


def test_load_json_lines_handles_json_lines(tmp_path: Path) -> None:
    report = tmp_path / "gitleaks.json"
    payload = {
        "file": "alerts/exposed_key.txt",
        "secret": "abcd1234abcd1234",
        "ruleID": "generic-api-key",
    }
    report.write_text(
        "\n".join(json.dumps(payload) for _ in range(2)), encoding="utf-8"
    )

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
    report.write_text(
        "\n".join(json.dumps(item) for item in findings), encoding="utf-8"
    )

    gated = security_gate.gitleaks_findings(report, "HIGH")

    assert gated == [
        {
            "path": "alerts/critical.txt",
            "rule_id": "generic-api-key",
            "severity": "HIGH",
        }
    ]


def test_pip_audit_findings_honors_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        security_gate.PIP_AUDIT_ALLOWLIST,
        "GHSA-q2x7-8rv6-6q7h",
        {"reason": "Test suppression", "expires_on": "2099-01-01"},
    )

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


def test_pip_audit_allowlist_entries_are_expiring() -> None:
    # Plan 156 retired the last exception once (GHSA-84m7-p3x7-pcfv). The
    # mechanism is back for the pillow GHSAs (blocked by streamlit's
    # pillow<13 cap in requirements-refinery.lock, 2026-10-20), so instead of
    # an always-empty invariant the guard now asserts every live entry is
    # temporary: reason present and an expiry date bounded into the future.
    from datetime import date, timedelta

    active = security_gate._active_pip_audit_allowlist()  # type: ignore[attr-defined]
    assert active, "allowlist cannot remain while no risk remains — retire it"
    for vuln_id, reason in active.items():
        assert reason.strip(), f"{vuln_id} needs a re-read reason"
    expiry_dates = [
        date.fromisoformat(security_gate.PIP_AUDIT_ALLOWLIST[vuln_id]["expires_on"])  # type: ignore[attr-defined]
        for vuln_id in active
    ]
    horizon = date.today() + timedelta(days=90)
    assert max(expiry_dates) <= horizon, "no suppression may exceed 90 days"


def test_pip_audit_allowlist_expiry_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        security_gate.PIP_AUDIT_ALLOWLIST,
        "TEST-EXPIRED",
        {"reason": "Temporary test", "expires_on": "2000-01-01"},
    )

    with pytest.raises(ValueError, match="Expired pip-audit allowlist entries"):
        security_gate._active_pip_audit_allowlist()  # type: ignore[attr-defined]
