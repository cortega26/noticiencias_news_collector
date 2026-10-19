"""The uploaded gitleaks artifact must not carry matched secret values.

Plan 142: gitleaks runs without ``--redact`` (baseline matching is
content-based), so ``scripts/sanitize_gitleaks_report.py`` produces the copy
that is safe to publish as a CI artifact. The fixture below uses a synthetic
sentinel only — never a real credential.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import sanitize_gitleaks_report

# Synthetic, non-credential sentinel. It only has to be a value that a naive
# upload would leak.
SENTINEL = "SENTINEL_fake-secret-value-3f9c2d1a"


def _fixture_report() -> list[dict]:
    return [
        {
            "RuleID": "generic-api-key",
            "Description": "Detected a Generic API Key",
            "File": "config/example.env",
            "StartLine": 12,
            "EndLine": 12,
            "StartColumn": 8,
            "EndColumn": 48,
            "Match": f'AUTH_TOKEN = "{SENTINEL}"',
            "Secret": SENTINEL,
            "Commit": "a" * 40,
            "Author": "CI Bot",
            "Email": "ci@example.com",
            "Date": "2026-10-18T00:00:00Z",
            "Fingerprint": "b" * 64,
        }
    ]


def test_sentinel_value_is_absent_while_triage_fields_survive():
    sanitized = sanitize_gitleaks_report.sanitize_report(_fixture_report())

    assert SENTINEL not in json.dumps(sanitized)
    entry = sanitized[0]
    assert entry["RuleID"] == "generic-api-key"
    assert entry["File"] == "config/example.env"
    assert entry["StartLine"] == 12
    assert entry["Commit"] == "a" * 40
    assert entry["Author"] == "CI Bot"
    assert entry["Date"] == "2026-10-18T00:00:00Z"
    assert entry["Secret"] == sanitize_gitleaks_report.REDACTED_VALUE
    assert entry["Match"] == sanitize_gitleaks_report.REDACTED_VALUE


def test_sanitize_file_round_trip(tmp_path: Path):
    source = tmp_path / "gitleaks.json"
    source.write_text(json.dumps(_fixture_report()), encoding="utf-8")
    destination = tmp_path / "out" / "gitleaks-sanitized.json"

    count = sanitize_gitleaks_report.sanitize_file(source, destination)

    assert count == 1
    written = destination.read_text(encoding="utf-8")
    assert SENTINEL not in written
    assert json.loads(written)[0]["RuleID"] == "generic-api-key"


def test_missing_source_writes_empty_report(tmp_path: Path):
    destination = tmp_path / "gitleaks-sanitized.json"

    count = sanitize_gitleaks_report.sanitize_file(
        tmp_path / "missing.json", destination
    )

    assert count == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == []


def test_non_array_report_fails_closed(tmp_path: Path):
    source = tmp_path / "gitleaks.json"
    source.write_text(json.dumps({"Secret": SENTINEL}), encoding="utf-8")

    with pytest.raises(ValueError):
        sanitize_gitleaks_report.sanitize_file(source, tmp_path / "out.json")


def test_cli_reports_failure_for_unexpected_shape(tmp_path: Path):
    source = tmp_path / "gitleaks.json"
    source.write_text(json.dumps({"Secret": SENTINEL}), encoding="utf-8")

    exit_code = sanitize_gitleaks_report.main([str(source), str(tmp_path / "out.json")])

    assert exit_code == 1
    assert not (tmp_path / "out.json").exists()
