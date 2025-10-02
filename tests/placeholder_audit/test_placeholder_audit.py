"""Tests for the placeholder audit tooling."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import List

import pytest

from tools.placeholder_audit import (
    AgeThresholds,
    AuditConfig,
    AuditReport,
    DiffFile,
    DiffLine,
    PlaceholderRecord,
    build_pr_comment,
    build_sarif,
    classify_context,
    detect_placeholders,
    evaluate_placeholder,
    parse_attributes,
    parse_diff,
    scan_files,
    should_fail,
    track_fences,
)


@pytest.fixture
def audit_config() -> AuditConfig:
    """Return an audit configuration matching the repository defaults."""
    return AuditConfig(
        include=("**/*.py", "**/*.md"),
        exclude=("venv/**", ".venv/**", "**/generated/**"),
        contexts={
            "prod_code": ("**/*.py",),
            "tests": ("tests/**", "examples/**"),
            "docs": ("**/*.md",),
        },
        required_fields=("owner", "due", "issue"),
        due_format="YYYY-MM-DD",
        warn_window_days=7,
        age_threshold_days=AgeThresholds(warn=30, high=90),
        block_severities=("HIGH",),
        delta_mode=True,
        pr_halo_lines=10,
    )


def test_parse_attributes_trims_whitespace() -> None:
    attrs = parse_attributes("owner=@alice ; due =2025-10-31; issue=https://example")
    assert attrs == {
        "owner": "@alice",
        "due": "2025-10-31",
        "issue": "https://example",
    }


def test_classify_context_prefers_tests_over_prod(audit_config: AuditConfig) -> None:
    path = Path("tests/module/example_test.py")
    assert classify_context(path, audit_config) == "tests"


def test_track_fences_identifies_lines() -> None:
    content = """```\nTBD[issue=#1]: sample\n```\nOutside"""
    fence_lines = track_fences(content)
    assert 2 in fence_lines
    assert 3 not in fence_lines


def test_evaluate_placeholder_flags_missing_fields(audit_config: AuditConfig) -> None:
    severity, score, reasons, _, expired = evaluate_placeholder(
        marker="TODO",
        attributes={"owner": "@alice", "issue": "#123"},
        text="fill in",  # pragma: no mutate - descriptive text
        context="prod_code",
        config=audit_config,
        age_days=None,
        inside_fence=False,
    )
    assert severity == "HIGH"
    assert "missing due" in " ".join(reasons)
    assert not expired
    assert pytest.approx(score, abs=0.001) == 0.5


def test_evaluate_placeholder_warns_due_soon(audit_config: AuditConfig) -> None:
    upcoming = (dt.date.today() + dt.timedelta(days=3)).strftime("%Y-%m-%d")
    severity, _, reasons, _, expired = evaluate_placeholder(
        marker="FIXME",
        attributes={
            "owner": "@bob",
            "due": upcoming,
            "issue": "#200",
        },
        text="follow up",
        context="tests",
        config=audit_config,
        age_days=5,
        inside_fence=False,
    )
    assert severity == "MED"
    assert "due within warn window" in reasons
    assert not expired


def test_detect_placeholders_skips_markdown_fenced_code(
    audit_config: AuditConfig,
) -> None:
    path = Path("tests/placeholder_audit/fixtures/doc_page.md")
    content = path.read_text(encoding="utf-8")
    fence_lines = track_fences(content)
    new_lines = {idx: "+" for idx in range(1, len(content.splitlines()) + 1)}
    findings = detect_placeholders(
        path=path,
        content=content,
        new_lines=new_lines,
        context="docs",
        config=audit_config,
        inside_fence_lines=fence_lines,
    )
    assert any(
        finding.line_number == 11 and finding.marker == "TBD" for finding in findings
    )
    assert all(f.line_number != 6 for f in findings)


def test_scan_files_flags_net_new_high(
    monkeypatch: pytest.MonkeyPatch,
    audit_config: AuditConfig,
    tmp_path: Path,
) -> None:
    path = tmp_path / "src" / "module.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "def example() -> None:",
                "    value = 1",
                "    # TODO[owner=@alice; issue=#123]: add retries",
            ]
        ),
        encoding="utf-8",
    )
    diff = DiffFile(
        path=path,
        lines=[
            DiffLine(old_number=2, new_number=2, symbol=" "),
            DiffLine(old_number=None, new_number=3, symbol="+"),
        ],
    )
    base_content = path.read_text(encoding="utf-8").replace(
        "# TODO[owner=@alice; issue=#123]: add retries",
        "# TODO[owner=@alice; due=2025-12-31; issue=#123]: add retries",
    )
    monkeypatch.setattr(
        "tools.placeholder_audit.compute_age_days",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        "tools.placeholder_audit.read_base_file",
        lambda *_args, **_kwargs: base_content,
    )
    report = scan_files([diff], audit_config, "origin/main")
    assert report.net_new_high == 1
    assert report.head_high_count == 1
    assert report.base_high_count == 0


def test_build_sarif_levels_map_severities() -> None:
    finding_high = PlaceholderRecord(
        marker="TODO",
        attributes={"owner": "@a", "issue": "#1"},
        text="fix",
        file_path=Path("src/app.py"),
        line_number=12,
        context="prod_code",
        inside_fence=False,
        severity="HIGH",
        score=1.5,
        reasons=["missing due"],
        suggested_fix="Add due",
        expired=False,
        is_added_or_modified=True,
    )
    finding_low = dataclasses.replace(
        finding_high,
        marker="TBD",
        severity="LOW",
        reasons=["docs TBD"],
        file_path=Path("docs/page.md"),
        line_number=4,
        is_added_or_modified=False,
    )
    sarif = build_sarif([finding_high, finding_low])
    levels = {result["level"] for result in sarif["runs"][0]["results"]}
    assert levels == {"error", "note"}


def test_pr_comment_limits_rows() -> None:
    findings: List[PlaceholderRecord] = []
    for idx in range(30):
        findings.append(
            PlaceholderRecord(
                marker="TODO",
                attributes={},
                text="fix",
                file_path=Path(f"src/module_{idx}.py"),
                line_number=idx + 1,
                context="prod_code",
                inside_fence=False,
                severity="HIGH",
                score=1.5,
                reasons=["missing metadata"],
                suggested_fix="Add owner/due/issue",
                expired=False,
                is_added_or_modified=True,
            )
        )
    comment = build_pr_comment(findings)
    assert comment.count("\n") <= 27  # header + separator + 25 rows


def test_should_fail_respects_delta_mode(audit_config: AuditConfig) -> None:
    finding = PlaceholderRecord(
        marker="TODO",
        attributes={},
        text="fix",
        file_path=Path("src/a.py"),
        line_number=1,
        context="prod_code",
        inside_fence=False,
        severity="HIGH",
        score=1.0,
        reasons=["missing metadata"],
        suggested_fix="Add owner/due/issue",
        expired=False,
        is_added_or_modified=True,
    )
    report = AuditReport(
        findings=[finding],
        base_high_count=0,
        head_high_count=1,
        net_new_high=1,
        expired_blockers=0,
    )
    assert should_fail(report, audit_config, strict=False, pr_diff_only=True)
    assert not should_fail(report, audit_config, strict=False, pr_diff_only=False)
    assert should_fail(report, audit_config, strict=True, pr_diff_only=False)


def test_parse_diff_extracts_new_and_old_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    diff_text = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        " import os\n"
        "+TODO[owner=@x; issue=#1]: note\n"
        " print('done')\n"
    )
    monkeypatch.setattr(
        "tools.placeholder_audit.run_git", lambda *_args, **_kwargs: diff_text
    )
    files = parse_diff("main", 3)
    assert files[0].new_line_numbers()[2] == "+"
    assert files[0].old_line_numbers()[1] == " "
