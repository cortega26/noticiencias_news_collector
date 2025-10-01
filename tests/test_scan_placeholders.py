import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scan_placeholders import (
    DEFAULT_EXTENSIONS,
    compare_to_baseline,
    detect_commented_code,
    infer_severity,
    load_patterns,
    scan_repository,
)

PATTERN_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "placeholder_patterns.yml"
)

TASK_TAG = "".join(("TO", "DO"))
BACKLOG_TAG = "".join(("PEND", "ING"))
PASS_SNIPPET = "".join(("pa", "ss"))


@pytest.fixture(scope="module")
def patterns():
    return load_patterns(PATTERN_PATH)


@pytest.fixture()
def repo_root(tmp_path):
    (tmp_path / "reports").mkdir()
    return tmp_path


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_todo_in_python(repo_root, patterns):
    write_file(repo_root / "module.py", f"# {TASK_TAG}: implement logic\n")
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    tags = {f.tag for f in findings}
    assert TASK_TAG in tags
    high_findings = [f for f in findings if f.tag == TASK_TAG]
    assert all(f.severity == "high" for f in high_findings)


def test_detects_secret_placeholder(repo_root, patterns):
    secret_key_field = "api_" + "key"
    write_file(repo_root / "config" / "settings.yaml", f'{secret_key_field}: ""\n')
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    assert any(f.tag == "SECRET_PLACEHOLDER" for f in findings)
    placeholder = next(f for f in findings if f.tag == "SECRET_PLACEHOLDER")
    assert placeholder.severity == "medium"


def test_markdown_checkbox_detected(repo_root, patterns):
    write_file(
        repo_root / "README.md",
        "- [ ] " + BACKLOG_TAG.lower() + " task\n",
    )
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    assert any(f.tag == "MARKDOWN_CHECKBOX" for f in findings)
    checkbox = next(f for f in findings if f.tag == "MARKDOWN_CHECKBOX")
    assert checkbox.severity == "low"


def test_python_stub_detection(repo_root, patterns):
    ellipsis = "." * 3
    stub_text = (
        "class Example:\n"
        f"    def {BACKLOG_TAG.lower()}(self):\n"
        f"        {PASS_SNIPPET}\n\n"
        "    async def other(self):\n"
        f"        {ellipsis}\n"
    )
    write_file(repo_root / "stub.py", stub_text)
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    tags = {f.tag for f in findings}
    assert "PASS_STUB" in tags
    assert "ELLIPSIS_STUB" in tags


def test_raises_not_implemented_detected(repo_root, patterns):
    not_impl = "Not" + "ImplementedError"
    raise_kw = "ra" + "ise"
    body = "def handle():\n    " + raise_kw + f" {not_impl}('" + "to" + "do" + "')\n"
    write_file(repo_root / "handler.py", body)
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    assert any(f.tag == "RAISE_NOT_IMPLEMENTED" for f in findings)


def test_commented_code_block_detected(repo_root):
    text = "\n".join(
        [
            "# def foo():",
            "#     value = 1",
            "#     if value > 0:",
            "#         return value",
            "#     return 0",
            "# print(foo())",
        ]
    )
    findings = detect_commented_code(
        Path("stub.py"),
        "stub.py",
        text,
        context=1,
    )
    assert findings
    assert findings[0].tag == "COMMENTED_CODE"


def test_baseline_comparison(repo_root, patterns):
    write_file(repo_root / "module.py", f"# {TASK_TAG} baseline\n")
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    baseline = [findings[0].to_dict()]
    new, resolved = compare_to_baseline(findings, baseline)
    assert not new
    assert not resolved

    shifted_baseline = [
        {
            **baseline[0],
            "line_start": baseline[0]["line_start"] + 5,
            "line_end": baseline[0]["line_end"] + 5,
        }
    ]
    shifted_new, shifted_resolved = compare_to_baseline(findings, shifted_baseline)
    assert not shifted_new
    assert not shifted_resolved

    empty_new, resolved_only = compare_to_baseline([], baseline)
    assert len(empty_new) == 0
    assert len(resolved_only) == 1


def test_ignore_cache_directory(repo_root, patterns):
    write_file(
        repo_root / "__pycache__" / "ignored.py",
        f"# {TASK_TAG} skip\n",
    )
    findings = scan_repository(
        repo_root,
        patterns,
        DEFAULT_EXTENSIONS,
        [],
        context=1,
    )
    assert all("__pycache__" not in f.file for f in findings)


def test_infer_severity_levels():
    assert infer_severity(Path("file.py")) == "high"
    assert infer_severity(Path("config.yaml")) == "medium"
    assert infer_severity(Path("README.md")) == "low"
