"""Tests for the Makefile tab indentation validator."""
from __future__ import annotations

from pathlib import Path

from tools.check_makefile_tabs import find_tab_violations, validate_makefiles


def test_find_tab_violations_detects_space_indented_recipe(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("target:\n    echo hi\n", encoding="utf-8")

    violations = find_tab_violations(makefile)

    assert len(violations) == 1
    assert violations[0].line_number == 2
    assert violations[0].line.startswith("    echo")


def test_validate_makefiles_accepts_tab_indented_recipe(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("target:\n\t@echo hi\n", encoding="utf-8")

    exit_code = validate_makefiles((makefile,))

    assert exit_code == 0
