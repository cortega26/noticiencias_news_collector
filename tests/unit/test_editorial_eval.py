from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tools" / "editorial_eval"
FIXTURES = REPO_ROOT / "tests" / "data" / "editorial_eval"
PREPARE_SCRIPT = TOOL_DIR / "prepare.py"
ASSERTIONS_SCRIPT = TOOL_DIR / "assertions.py"

EXPECTED_CASE_IDS = [
    "empty_body",
    "executable_markup",
    "missing_required_detail",
    "prohibited_overclaim",
    "skipped_heading",
    "structural_pass",
]

# Kept in the test, never fed back into the evaluator as an answer.
EXPECTED_FAILURES = {
    ("candidate", "empty_body"),
    ("candidate", "executable_markup"),
    ("candidate", "missing_required_detail"),
    ("candidate", "prohibited_overclaim"),
    ("candidate", "skipped_heading"),
}
EXPECTED_REASON_FRAGMENTS = {
    "empty_body": "editorial_placeholder_blocked",
    "executable_markup": "editorial_executable_content_blocked",
    "missing_required_detail": "missing required literal substring(s)",
    "prohibited_overclaim": "forbidden literal substring(s) present",
    "skipped_heading": "editorial_heading_structure_invalid",
}

_PROMPTFOO_INTEGRATION = (
    os.getenv("EDITORIAL_EVAL_PROMPTFOO_INTEGRATION", "").lower() == "true"
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prepare_module() -> ModuleType:
    return _load_module("editorial_eval_prepare", PREPARE_SCRIPT)


@pytest.fixture(scope="module")
def assertions_module() -> ModuleType:
    return _load_module("editorial_eval_assertions", ASSERTIONS_SCRIPT)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _seeded_rows() -> (
    tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]
):
    return (
        _read_jsonl(FIXTURES / "cases.jsonl"),
        _read_jsonl(FIXTURES / "baseline.jsonl"),
        _read_jsonl(FIXTURES / "candidate.jsonl"),
    )


def _prepare_seeded(prepare: ModuleType, output_dir: Path) -> None:
    prepare.prepare_replay(
        FIXTURES / "cases.jsonl",
        FIXTURES / "baseline.jsonl",
        FIXTURES / "candidate.jsonl",
        output_dir,
    )


def _load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_prepare(
    prepare: ModuleType,
    tmp_path: Path,
    cases: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    _write_jsonl(cases_path, cases)
    _write_jsonl(baseline_path, baseline)
    _write_jsonl(candidate_path, candidate)
    prepare.prepare_replay(cases_path, baseline_path, candidate_path, tmp_path / "out")


def test_seeded_controls_prepare_to_expected_pair_outcomes(
    prepare_module: ModuleType,
    assertions_module: ModuleType,
    tmp_path: Path,
) -> None:
    _prepare_seeded(prepare_module, tmp_path / "out")
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    config = _load_config(tmp_path / "out" / "promptfooconfig.yaml")

    assert manifest["case_count"] == 6
    assert manifest["row_counts"] == {"baseline": 6, "candidate": 6}
    assert len(manifest["rows"]) == 12
    assert [case["case_id"] for case in manifest["cases"]] == EXPECTED_CASE_IDS
    assert len(config["tests"]) == 12

    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    for test in config["tests"]:
        label, case_id = test["description"].split(":", 1)
        outcomes[(label, case_id)] = assertions_module.get_assert(
            test["vars"]["logged_output"], {"vars": test["vars"]}
        )

    passing = {key for key, result in outcomes.items() if result["pass"]}
    failing = {key for key, result in outcomes.items() if not result["pass"]}
    assert len(passing) == 7
    assert failing == EXPECTED_FAILURES
    assert {key for key in passing if key[0] == "baseline"} == {
        ("baseline", case_id) for case_id in EXPECTED_CASE_IDS
    }
    assert ("candidate", "structural_pass") in passing

    for case_id, fragment in EXPECTED_REASON_FRAGMENTS.items():
        reason = outcomes[("candidate", case_id)]["reason"]
        assert fragment in reason, (case_id, reason)


def test_preparation_is_deterministic_and_sorted(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _prepare_seeded(prepare_module, first)
    _prepare_seeded(prepare_module, second)

    names = ("manifest.json", "promptfooconfig.yaml", "promptfooconfig.baseline.yaml")
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name

    config = _load_config(first / "promptfooconfig.yaml")
    assert [test["description"] for test in config["tests"]] == [
        f"{label}:{case_id}"
        for case_id in EXPECTED_CASE_IDS
        for label in ("baseline", "candidate")
    ]
    assert config["providers"] == ["echo"]
    assert config["prompts"] == ["{{logged_output}}"]

    baseline_config = _load_config(first / "promptfooconfig.baseline.yaml")
    assert [test["description"] for test in baseline_config["tests"]] == [
        f"baseline:{case_id}" for case_id in EXPECTED_CASE_IDS
    ]

    manifest = json.loads((first / "manifest.json").read_text())
    assert [(row["case_id"], row["label"]) for row in manifest["rows"]] == [
        (case_id, label)
        for case_id in EXPECTED_CASE_IDS
        for label in ("baseline", "candidate")
    ]
    assert str(tmp_path) not in (first / "manifest.json").read_text()
    assert set(manifest["inputs"]) == {
        "cases_sha256",
        "baseline_sha256",
        "candidate_sha256",
    }


def test_manifest_hashes_match_input_files(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "out"
    _prepare_seeded(prepare_module, output)
    manifest = json.loads((output / "manifest.json").read_text())
    for name, key in (
        ("cases.jsonl", "cases_sha256"),
        ("baseline.jsonl", "baseline_sha256"),
        ("candidate.jsonl", "candidate_sha256"),
    ):
        expected = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        assert manifest["inputs"][key] == expected


def test_assertion_reference_resolves_from_config_directory(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "out"
    _prepare_seeded(prepare_module, output)
    config = _load_config(output / "promptfooconfig.yaml")
    reference = config["defaultTest"]["assert"][0]["value"]
    assert reference.endswith(":get_assert")
    file_reference = reference.removeprefix("file://").removesuffix(":get_assert")
    assert not os.path.isabs(file_reference)
    assert (output / file_reference).resolve() == ASSERTIONS_SCRIPT.resolve()


def test_prepare_rejects_duplicate_case_ids(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    cases.append(dict(cases[0]))
    with pytest.raises(prepare_module.InputValidationError, match="duplicate case_id"):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_empty_corpus(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    _cases, baseline, candidate = _seeded_rows()
    with pytest.raises(
        prepare_module.InputValidationError, match="contains no records"
    ):
        _run_prepare(prepare_module, tmp_path, [], baseline, candidate)


def test_prepare_rejects_invalid_json(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(cases_path, cases)
    with cases_path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
    with pytest.raises(prepare_module.InputValidationError, match="invalid JSON"):
        prepare_module.prepare_replay(
            cases_path,
            _write_and_return(tmp_path / "baseline.jsonl", baseline),
            _write_and_return(tmp_path / "candidate.jsonl", candidate),
            tmp_path / "out",
        )


def test_prepare_rejects_invalid_types(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    cases[0]["case_id"] = 3
    with pytest.raises(
        prepare_module.InputValidationError, match="'case_id' must be a string"
    ):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)

    cases, baseline, candidate = _seeded_rows()
    cases[0]["required_substrings"] = [1]
    with pytest.raises(
        prepare_module.InputValidationError,
        match="'required_substrings\\[0\\]' must be a string",
    ):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_unknown_case_fields(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    cases[0]["unexpected"] = "value"
    with pytest.raises(prepare_module.InputValidationError, match="unknown field"):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_missing_outputs(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    baseline = baseline[:-1]
    with pytest.raises(
        prepare_module.InputValidationError,
        match="baseline is missing output",
    ):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_outputs_for_unknown_cases(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    candidate.append(dict(candidate[0], case_id="unknown_case"))
    with pytest.raises(prepare_module.InputValidationError, match="unknown case_id"):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_contradictory_output_and_error(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    candidate[0]["error"] = "provider exploded"
    with pytest.raises(
        prepare_module.InputValidationError, match="must have null 'error'"
    ):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_prepare_rejects_null_output_without_error(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    cases, baseline, candidate = _seeded_rows()
    candidate[0]["output"] = None
    candidate[0]["error"] = None
    with pytest.raises(
        prepare_module.InputValidationError,
        match="requires a nonempty 'error'",
    ):
        _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)


def test_provider_errors_survive_preparation_and_fail_before_content(
    prepare_module: ModuleType,
    assertions_module: ModuleType,
    tmp_path: Path,
) -> None:
    cases, baseline, candidate = _seeded_rows()
    candidate[0]["output"] = None
    candidate[0]["error"] = "upstream timeout"
    _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)

    config = _load_config(tmp_path / "out" / "promptfooconfig.yaml")
    error_test = next(
        test
        for test in config["tests"]
        if test["description"] == f"candidate:{cases[0]['case_id']}"
    )
    assert error_test["vars"]["logged_output"] == ""
    assert error_test["vars"]["stored_error"] == "upstream timeout"
    result = assertions_module.get_assert("", {"vars": error_test["vars"]})
    assert result["pass"] is False
    assert "captured provider error" in result["reason"]

    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    error_row = next(
        row
        for row in manifest["rows"]
        if row["label"] == "candidate" and row["case_id"] == cases[0]["case_id"]
    )
    assert error_row["status"] == "provider_error"
    assert error_row["error"] == "upstream timeout"


def test_empty_string_is_a_captured_output_not_a_provider_error(
    prepare_module: ModuleType,
    assertions_module: ModuleType,
    tmp_path: Path,
) -> None:
    cases, baseline, candidate = _seeded_rows()
    candidate[0]["output"] = ""
    candidate[0]["error"] = None
    _run_prepare(prepare_module, tmp_path, cases, baseline, candidate)

    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    row = next(
        row
        for row in manifest["rows"]
        if row["label"] == "candidate" and row["case_id"] == cases[0]["case_id"]
    )
    assert row["status"] == "captured_output"
    assert row["output_sha256"] == hashlib.sha256(b"").hexdigest()

    config = _load_config(tmp_path / "out" / "promptfooconfig.yaml")
    test = next(
        test
        for test in config["tests"]
        if test["description"] == f"candidate:{cases[0]['case_id']}"
    )
    result = assertions_module.get_assert(
        test["vars"]["logged_output"], {"vars": test["vars"]}
    )
    assert result["pass"] is False
    assert "content validation failed" in result["reason"]
    assert "provider error" not in result["reason"]


def test_assertion_does_not_catch_unexpected_validator_errors(
    assertions_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(markdown: str) -> None:
        raise RuntimeError("evaluator bug")

    monkeypatch.setattr(assertions_module, "validate_generated_article_markdown", boom)
    with pytest.raises(RuntimeError, match="evaluator bug"):
        assertions_module.get_assert(
            "text",
            {
                "vars": {
                    "case_id": "case",
                    "stored_error": "",
                    "required_substrings": [],
                    "forbidden_substrings": [],
                }
            },
        )


def test_provider_error_short_circuits_before_validator(
    assertions_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(markdown: str) -> None:
        raise AssertionError("validator must not run for provider errors")

    monkeypatch.setattr(
        assertions_module, "validate_generated_article_markdown", unexpected
    )
    result = assertions_module.get_assert(
        "ignored",
        {
            "vars": {
                "case_id": "case",
                "stored_error": "timeout",
                "required_substrings": ["must not matter"],
                "forbidden_substrings": [],
            }
        },
    )
    assert result["pass"] is False
    assert "captured provider error" in result["reason"]


def test_literal_expectations_are_case_sensitive(
    assertions_module: ModuleType,
) -> None:
    baseline = _read_jsonl(FIXTURES / "baseline.jsonl")[0]["output"]
    base_vars = {
        "case_id": "case",
        "stored_error": "",
        "required_substrings": [],
        "forbidden_substrings": [],
    }
    assert assertions_module.get_assert(baseline, {"vars": base_vars})["pass"] is True

    missing = dict(base_vars, required_substrings=["centrolene mutum"])
    assert assertions_module.get_assert(baseline, {"vars": missing})["pass"] is False

    forbidden = dict(base_vars, forbidden_substrings=["Centrolene mutum"])
    assert assertions_module.get_assert(baseline, {"vars": forbidden})["pass"] is False


def test_assertion_rejects_malformed_context(assertions_module: ModuleType) -> None:
    with pytest.raises(TypeError):
        assertions_module.get_assert("text", {})
    with pytest.raises(TypeError):
        assertions_module.get_assert(
            "text",
            {
                "vars": {
                    "case_id": "case",
                    "stored_error": "",
                    "required_substrings": "not-a-list",
                    "forbidden_substrings": [],
                }
            },
        )


def test_raw_template_syntax_survives_preparation(
    prepare_module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "out"
    _prepare_seeded(prepare_module, output)
    config = _load_config(output / "promptfooconfig.yaml")
    candidate = next(
        test
        for test in config["tests"]
        if test["description"] == "candidate:structural_pass"
    )
    assert "{{ template_marker }}" in candidate["vars"]["logged_output"]


def test_cli_exit_codes(tmp_path: Path) -> None:
    valid = subprocess.run(
        [
            sys.executable,
            str(PREPARE_SCRIPT),
            "--cases",
            str(FIXTURES / "cases.jsonl"),
            "--baseline",
            str(FIXTURES / "baseline.jsonl"),
            "--candidate",
            str(FIXTURES / "candidate.jsonl"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert "prepared 6 cases / 12 rows" in valid.stdout

    invalid = subprocess.run(
        [
            sys.executable,
            str(PREPARE_SCRIPT),
            "--cases",
            str(tmp_path / "missing.jsonl"),
            "--baseline",
            str(FIXTURES / "baseline.jsonl"),
            "--candidate",
            str(FIXTURES / "candidate.jsonl"),
            "--output-dir",
            str(tmp_path / "out-invalid"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "error:" in invalid.stderr


def _write_and_return(path: Path, rows: list[dict[str, Any]]) -> Path:
    _write_jsonl(path, rows)
    return path


@pytest.mark.skipif(
    not _PROMPTFOO_INTEGRATION,
    reason=(
        "Set EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true after "
        "`make editorial-eval-install` to run the real Promptfoo replay."
    ),
)
@pytest.mark.timeout(300)
def test_real_promptfoo_baseline_and_paired_replay() -> None:
    output = REPO_ROOT / "reports" / "editorial-eval"
    subprocess.run(
        [
            sys.executable,
            str(PREPARE_SCRIPT),
            "--cases",
            str(FIXTURES / "cases.jsonl"),
            "--baseline",
            str(FIXTURES / "baseline.jsonl"),
            "--candidate",
            str(FIXTURES / "candidate.jsonl"),
            "--output-dir",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    env = os.environ.copy()
    env.update(
        {
            "PROMPTFOO_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
            "PROMPTFOO_DISABLE_TELEMETRY": "1",
            "PROMPTFOO_DISABLE_UPDATE": "1",
            "PROMPTFOO_DISABLE_REMOTE_GENERATION": "true",
            "PROMPTFOO_DISABLE_SHARING": "1",
            "PROMPTFOO_SELF_HOSTED": "1",
        }
    )

    validate = subprocess.run(
        ["npm", "run", "eval:validate"],
        cwd=TOOL_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stderr

    baseline = subprocess.run(
        ["npm", "run", "eval:baseline"],
        cwd=TOOL_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert baseline.returncode == 0, baseline.stderr
    baseline_results = json.loads((output / "baseline-results.json").read_text())
    baseline_rows = baseline_results["results"]["results"]
    assert len(baseline_rows) == 6
    assert all(row["success"] for row in baseline_rows)

    replay = subprocess.run(
        ["npm", "run", "eval:replay"],
        cwd=TOOL_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert replay.returncode == 100, replay.stderr
    results = json.loads((output / "results.json").read_text())["results"]["results"]
    assert len(results) == 12
    assert sum(row["success"] for row in results) == 7
    failing = {row["testCase"]["description"] for row in results if not row["success"]}
    assert failing == {f"candidate:{case_id}" for _label, case_id in EXPECTED_FAILURES}
    assert all(
        row["response"]["output"] == row["vars"]["logged_output"] for row in results
    )
