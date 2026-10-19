"""Regression tests for gitleaks report parsing in ``scripts/security_gate.py``.

gitleaks emits capitalized report keys (``RuleID``, ``File``, ``Secret``,
``StartLine``, ...). The gate must read that schema for both the pinned CI
binary (8.30.x) and the tracked local binary (8.18.x); these tests fail if
field normalization regresses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import security_gate

_FILE = "tests/scripts/test_editorial_critic_canary.py"

# Shape emitted by gitleaks 8.30.1 (verified against a synthetic probe).
GITLEAKS_830_RECORD: dict[str, object] = {
    "Description": "Generic API or secret token",
    "StartLine": 281,
    "EndLine": 281,
    "StartColumn": 49,
    "EndColumn": 68,
    "Match": "key=fixturevalue",
    "Secret": "fixturevalue",
    "File": _FILE,
    "SymlinkFile": "",
    "Commit": "a480ca1c75456cb972964ca18851c4e0be185187",
    "Entropy": 3.5,
    "Author": "Fixture Author",
    "Email": "fixture@example.invalid",
    "Date": "2026-10-19T12:12:13Z",
    "Message": "synthetic fixture record",
    "Tags": ["secret", "generic"],
    "RuleID": "generic-api-key",
    "Fingerprint": (
        "a480ca1c75456cb972964ca18851c4e0be185187:" f"{_FILE}:generic-api-key:281"
    ),
}

# gitleaks 8.18.1 emits the same keys (verified against a synthetic probe);
# only commit/fingerprint metadata differs when scanning the working tree.
GITLEAKS_818_RECORD: dict[str, object] = {
    **GITLEAKS_830_RECORD,
    "Commit": "",
    "Fingerprint": f":{_FILE}:generic-api-key:281",
}


@pytest.fixture(autouse=True)
def _isolated_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the repository's real allowlist in these tests."""
    monkeypatch.setattr(
        security_gate, "GITLEAKS_CONFIG", tmp_path / "absent.toml", raising=False
    )


def _write_report(path: Path, records: list[object]) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _write_config(
    path: Path,
    *,
    paths: tuple[str, ...] = (),
    regexes: tuple[str, ...] = (),
) -> Path:
    lines = ["[allowlist]", "paths = ["]
    lines.extend(f"  '''{pattern}'''," for pattern in paths)
    lines.append("]")
    lines.append("regexes = [")
    lines.extend(f"  '''{pattern}'''," for pattern in regexes)
    lines.append("]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_capitalized_report_keys_are_parsed(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "report.json", [GITLEAKS_830_RECORD])

    assert security_gate.gitleaks_findings(report, "HIGH") == [
        {
            "path": _FILE,
            "rule_id": "generic-api-key",
            "severity": "HIGH",
        }
    ]


def test_path_allowlist_skips_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(
        tmp_path / "gitleaks.toml",
        paths=(r"^tests/scripts/test_editorial_critic_canary\.py$",),
    )
    monkeypatch.setattr(security_gate, "GITLEAKS_CONFIG", config, raising=False)
    report = _write_report(tmp_path / "report.json", [GITLEAKS_830_RECORD])

    assert security_gate.gitleaks_findings(report, "HIGH") == []


def test_secret_allowlist_uses_capitalized_secret_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "gitleaks.toml", regexes=(r"^fixturevalue$",))
    monkeypatch.setattr(security_gate, "GITLEAKS_CONFIG", config, raising=False)
    record = {**GITLEAKS_830_RECORD, "File": "alerts/exposed.txt"}
    report = _write_report(tmp_path / "report.json", [record])

    assert security_gate.gitleaks_findings(report, "HIGH") == []


def test_818_and_830_records_normalize_identically(tmp_path: Path) -> None:
    report_818 = _write_report(tmp_path / "report-818.json", [GITLEAKS_818_RECORD])
    report_830 = _write_report(tmp_path / "report-830.json", [GITLEAKS_830_RECORD])

    assert security_gate.gitleaks_findings(
        report_818, "HIGH"
    ) == security_gate.gitleaks_findings(report_830, "HIGH")


def test_unknown_record_shape_still_counts_as_high(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "report.json", [{"unexpected": "shape"}])

    assert security_gate.gitleaks_findings(report, "HIGH") == [
        {"path": "", "rule_id": "", "severity": "HIGH"}
    ]


def test_non_object_report_entry_is_rejected(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "report.json", [GITLEAKS_830_RECORD, "junk"])

    with pytest.raises(ValueError, match="not a JSON object"):
        security_gate.gitleaks_findings(report, "HIGH")


def test_malformed_report_exits_nonzero(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "report.json", [GITLEAKS_830_RECORD, "junk"])
    status = tmp_path / "status.json"

    result = security_gate.main(
        [
            "gitleaks",
            str(report),
            "--severity",
            "HIGH",
            "--status",
            str(status),
        ]
    )

    assert result == 1
    assert not status.exists()
