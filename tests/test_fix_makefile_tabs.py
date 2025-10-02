from __future__ import annotations

from pathlib import Path

from tools.fix_makefile_tabs import fix_paths


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_fix_paths_replaces_leading_spaces(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "target:\n"
        "        if true; then \\\n"
        "                echo ok; \\\n"
        "        fi\n",
        encoding="utf-8",
    )

    exit_code = fix_paths((makefile,), tab_size=8, check_only=False)

    assert exit_code == 0
    lines = read_lines(makefile)
    assert lines[1].startswith("\t")
    assert lines[2].startswith("\t")
    assert lines[3].startswith("\t")


def test_fix_paths_check_mode_leaves_file_unchanged(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    original = "target:\n    echo spaced\n"
    makefile.write_text(original, encoding="utf-8")

    exit_code = fix_paths((makefile,), tab_size=8, check_only=True)

    assert exit_code == 1
    assert makefile.read_text(encoding="utf-8") == original
