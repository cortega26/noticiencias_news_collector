"""Unit tests for scripts/adversarial_review.py.

Covers the Codex P2 findings fixed on PR #323: the default scope must
include the work-tree, path filters must apply to the changed-file list,
and a truncated diff must surface as an explicit incomplete review.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import adversarial_review as review


def _fake_git_factory(calls):
    def fake_git(*args):
        calls.append(args)
        if "--name-only" in args:
            return "a.py\nb.py\n"
        return "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"

    return fake_git


def test_collect_diff_default_includes_worktree(monkeypatch):
    calls = []
    monkeypatch.setattr(review, "_git", _fake_git_factory(calls))

    diff, files = review.collect_diff("origin/main", staged=False, paths=[])

    assert diff.startswith("diff --git a/a.py")
    assert files == ["a.py", "b.py"]
    assert calls == [
        ("diff", "origin/main", "--"),
        ("diff", "origin/main", "--name-only", "--"),
    ]


def test_collect_diff_staged_uses_index(monkeypatch):
    calls = []
    monkeypatch.setattr(review, "_git", _fake_git_factory(calls))

    review.collect_diff("origin/main", staged=True, paths=[])

    assert calls == [
        ("diff", "--cached", "--"),
        ("diff", "--cached", "--name-only", "--"),
    ]


def test_path_filter_applies_to_name_only(monkeypatch):
    calls = []
    monkeypatch.setattr(review, "_git", _fake_git_factory(calls))

    review.collect_diff("main", staged=False, paths=["scripts/", "tests/"])

    assert calls[1] == ("diff", "main", "--name-only", "--", "scripts/", "tests/")


def _two_file_diff():
    return (
        "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/big.py b/big.py\n+++ b/big.py\n@@ -1 +1 @@\n" + "x\n" * 50
    )


def test_truncate_keeps_short_diff_untouched():
    diff = "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"

    excerpt, truncated = review.truncate_diff(diff, max_chars=10_000)

    assert excerpt == diff
    assert truncated is False


def test_truncate_marks_hunk_boundary_and_reports_omitted_files():
    diff = _two_file_diff()

    excerpt, truncated = review.truncate_diff(diff, max_chars=len(diff) - 10)

    assert truncated is True
    assert "[TRUNCATED by reviewer:" in excerpt
    assert review.omitted_files(excerpt, ["a.py", "big.py"]) == ["big.py"]


def test_omitted_files_empty_when_every_section_has_hunks():
    diff = _two_file_diff()

    assert review.omitted_files(diff, ["a.py", "big.py"]) == []


def test_build_prompt_flags_incomplete_input():
    prompt = review.build_prompt(
        "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
        ["a.py", "b.py"],
        "## A",
        ["b.py"],
    )

    assert "INCOMPLETE INPUT" in prompt
    assert "INCOMPLETE REVIEW" in prompt
    assert "b.py" in prompt


def test_validate_api_rejects_non_http_schemes():
    with pytest.raises(SystemExit):
        review.validate_api("file:///etc/passwd")


def test_validate_api_accepts_http_and_normalizes_slash():
    assert review.validate_api("http://localhost:11434/") == "http://localhost:11434"


def test_git_uses_resolved_executable(monkeypatch):
    captured = {}

    class Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return Proc()

    monkeypatch.setattr(review.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(review.subprocess, "run", fake_run)

    assert review._git("status") == "ok"
    assert captured["argv"][0] == "/usr/bin/git"


def test_git_missing_executable_fails_explicitly(monkeypatch):
    monkeypatch.setattr(review.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit):
        review._git("status")


def test_git_failure_surfaces_stderr(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(review.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(review.subprocess, "run", lambda *a, **k: Proc())

    with pytest.raises(SystemExit):
        review._git("status")


def test_query_ollama_returns_model_response(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"response": "hello"}'

    monkeypatch.setattr(review.urllib.request, "urlopen", lambda req, timeout: Resp())

    assert (
        review.query_ollama("prompt", "model", "http://localhost:11434", 100, 5)
        == "hello"
    )


def test_query_ollama_wraps_transport_errors(monkeypatch):
    def boom(req, timeout):
        raise ConnectionError("down")

    monkeypatch.setattr(review.urllib.request, "urlopen", boom)

    with pytest.raises(SystemExit):
        review.query_ollama("prompt", "model", "http://localhost:11434", 100, 5)


def test_load_checklist_missing_file_fails(tmp_path):
    with pytest.raises(SystemExit):
        review.load_checklist(tmp_path / "missing.md")


def test_load_checklist_rejects_empty_file(tmp_path):
    empty = tmp_path / "checklist.md"
    empty.write_text("no sections here", encoding="utf-8")

    with pytest.raises(SystemExit):
        review.load_checklist(empty)


def test_main_print_prompt_skips_model(monkeypatch, tmp_path, capsys):
    checklist = tmp_path / "checklist.md"
    checklist.write_text("## Section\n- item\n", encoding="utf-8")
    monkeypatch.setattr(review, "CHECKLIST_PATH", checklist)
    diff = "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    monkeypatch.setattr(review, "collect_diff", lambda *a, **k: (diff, ["a.py"]))
    monkeypatch.setattr(
        review, "query_ollama", lambda *a, **k: pytest.fail("model must not run")
    )

    assert review.main(["--print-prompt"]) == 0
    assert "CLOSED-WORLD RULE" in capsys.readouterr().out


def test_main_handles_empty_model_response(monkeypatch, tmp_path, capsys):
    checklist = tmp_path / "checklist.md"
    checklist.write_text("## Section\n- item\n", encoding="utf-8")
    monkeypatch.setattr(review, "CHECKLIST_PATH", checklist)
    diff = "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    monkeypatch.setattr(review, "collect_diff", lambda *a, **k: (diff, ["a.py"]))
    monkeypatch.setattr(review, "query_ollama", lambda *a, **k: "")

    assert review.main([]) == 0
    output = capsys.readouterr().out
    assert "no findings" in output
    assert "_No findings reported._" in output


def test_main_empty_diff_returns_zero(monkeypatch, tmp_path, capsys):
    checklist = tmp_path / "checklist.md"
    checklist.write_text("## Section\n- item\n", encoding="utf-8")
    monkeypatch.setattr(review, "CHECKLIST_PATH", checklist)
    monkeypatch.setattr(review, "collect_diff", lambda *a, **k: ("", []))

    assert review.main([]) == 0
    assert "empty diff" in capsys.readouterr().out


def test_main_reports_incomplete_review(monkeypatch, tmp_path, capsys):
    checklist = tmp_path / "checklist.md"
    checklist.write_text("## Section\n- item\n", encoding="utf-8")
    monkeypatch.setattr(review, "CHECKLIST_PATH", checklist)
    diff = _two_file_diff()
    monkeypatch.setattr(
        review, "collect_diff", lambda *a, **k: (diff, ["a.py", "big.py"])
    )
    monkeypatch.setattr(review, "query_ollama", lambda *a, **k: "### [P2] finding")
    out = tmp_path / "report.md"

    assert review.main(["--max-chars", str(len(diff) - 10), "--out", str(out)]) == 0

    written = out.read_text(encoding="utf-8")
    assert written.startswith("> INCOMPLETE REVIEW")
    assert "big.py" in written
    assert "finding" in written
    assert "WARNING" in capsys.readouterr().err


def test_main_complete_review_has_no_incomplete_banner(monkeypatch, tmp_path):
    checklist = tmp_path / "checklist.md"
    checklist.write_text("## Section\n- item\n", encoding="utf-8")
    monkeypatch.setattr(review, "CHECKLIST_PATH", checklist)
    diff = "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    monkeypatch.setattr(review, "collect_diff", lambda *a, **k: (diff, ["a.py"]))
    monkeypatch.setattr(review, "query_ollama", lambda *a, **k: "### [P3] nit")
    out = tmp_path / "report.md"

    assert review.main(["--out", str(out)]) == 0

    assert out.read_text(encoding="utf-8") == "### [P3] nit"
