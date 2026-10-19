"""Tests for scripts/check_toolchain.py (plan 144).

The gate compares `.pre-commit-config.yaml` pins with the installed tool
versions. These tests use fixture configs (and a faked installed-version
lookup) so the unit suite never depends on the developer/CI venv being
aligned — enforcing that alignment is the gate's job, not the test suite's.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_toolchain.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_toolchain  # noqa: E402

TOOL_REPOS = {
    "ruff": "https://github.com/astral-sh/ruff-pre-commit",
    "black": "https://github.com/psf/black",
    "isort": "https://github.com/pycqa/isort",
    "bandit": "https://github.com/pycqa/bandit",
}


def write_config(path: Path, versions: Dict[str, str]) -> Path:
    lines = ["repos:"]
    for tool, repo in TOOL_REPOS.items():
        lines += [
            f"  - repo: {repo}",
            f"    rev: v{versions[tool]}",
            "    hooks:",
            f"      - id: {tool}",
        ]
    lines += [
        "  - repo: local",
        "    hooks:",
        "      - id: generate-api-docs",
        "        language: python",
        "        additional_dependencies:",
        f"          - pdoc=={versions['pdoc']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_pins_reads_hook_revisions(tmp_path: Path) -> None:
    versions = {
        "ruff": "1.2.3",
        "black": "4.5.6",
        "isort": "5.13.2",
        "bandit": "1.7.9",
        "pdoc": "15.0.4",
    }
    config = write_config(tmp_path / ".pre-commit-config.yaml", versions)

    pins = check_toolchain.load_pins(config)

    assert {tool: pins[tool].version for tool in TOOL_REPOS} == {
        tool: versions[tool] for tool in TOOL_REPOS
    }
    assert pins["pdoc"].version == "15.0.4"
    assert pins["mypy"].version == check_toolchain.MYPY_PIN


def test_pins_matching_installed_versions_pass(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    versions = {tool: "9.9.9" for tool in (*TOOL_REPOS, "pdoc", "mypy")}
    config = write_config(tmp_path / ".pre-commit-config.yaml", versions)
    monkeypatch.setattr(check_toolchain, "MYPY_PIN", "9.9.9")
    monkeypatch.setattr(
        check_toolchain, "installed_version", lambda module: versions.get(module)
    )

    exit_code = check_toolchain.main(["--config", str(config)])

    assert exit_code == 0
    assert "[toolchain] OK" in capsys.readouterr().out


def test_mismatched_pin_fails_and_names_the_tool(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / ".pre-commit-config.yaml",
        {
            "ruff": "0.0.1",
            "black": "4.5.6",
            "isort": "5.13.2",
            "bandit": "1.7.9",
            "pdoc": "15.0.4",
        },
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "MISMATCH" in result.stdout
    assert "ruff" in result.stdout
