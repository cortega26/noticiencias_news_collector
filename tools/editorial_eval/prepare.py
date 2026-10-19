#!/usr/bin/env python3
"""Prepare deterministic Promptfoo configs for offline editorial replay.

Plan 080 Phase 3, development-only tooling. This module reads captured
editorial outputs from JSONL, validates the local input contract, and writes
Promptfoo configs plus a provenance manifest. It never calls a provider, never
constructs an editor and never touches production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence

import yaml

PROVENANCES = frozenset({"synthetic", "recorded"})
LABELS = ("baseline", "candidate")
CASE_KEYS = frozenset(
    {
        "case_id",
        "source_text",
        "language",
        "source_url",
        "provenance",
        "review_evidence",
        "required_substrings",
        "forbidden_substrings",
    }
)
OUTPUT_KEYS = frozenset({"case_id", "output", "error", "provenance", "metadata"})
METADATA_KEYS = frozenset(
    {"model", "provider", "prompt_hash", "source_hash", "captured_at"}
)


class InputValidationError(ValueError):
    """Raised when replay inputs are malformed, incomplete, or contradictory."""


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    source_text: str
    language: str
    source_url: str | None
    provenance: str
    review_evidence: str | None
    required_substrings: tuple[str, ...]
    forbidden_substrings: tuple[str, ...]


@dataclass(frozen=True)
class OutputMetadata:
    model: str | None = None
    provider: str | None = None
    prompt_hash: str | None = None
    source_hash: str | None = None
    captured_at: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "model": self.model,
            "provider": self.provider,
            "prompt_hash": self.prompt_hash,
            "source_hash": self.source_hash,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class OutputRecord:
    case_id: str
    output: str | None
    error: str | None
    provenance: str
    metadata: OutputMetadata

    @property
    def status(self) -> str:
        return "provider_error" if self.output is None else "captured_output"


@dataclass(frozen=True)
class PreparationSummary:
    case_count: int
    row_count: int
    output_dir: Path


def _fail(source: str, message: str) -> NoReturn:
    raise InputValidationError(f"{source}: {message}")


def _require_mapping(value: Any, source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(source, f"expected an object, got {type(value).__name__}")
    return value


def _reject_unknown_keys(
    record: dict[str, Any], allowed: frozenset[str], source: str
) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        _fail(source, f"unknown field(s): {', '.join(unknown)}")


def _require_str(value: Any, source: str, field: str, *, nonempty: bool) -> str:
    if not isinstance(value, str):
        _fail(source, f"'{field}' must be a string, got {type(value).__name__}")
    if nonempty and value == "":
        _fail(source, f"'{field}' must be a nonempty string")
    return value


def _require_optional_str(value: Any, source: str, field: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, source, field, nonempty=False)


def _require_provenance(value: Any, source: str) -> str:
    provenance = _require_str(value, source, "provenance", nonempty=True)
    if provenance not in PROVENANCES:
        _fail(
            source,
            "'provenance' must be one of: " + ", ".join(sorted(PROVENANCES)),
        )
    return provenance


def _require_string_list(value: Any, source: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail(source, f"'{field}' must be a list of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        items.append(_require_str(item, source, f"{field}[{index}]", nonempty=True))
    return tuple(items)


def _read_jsonl(path: Path) -> tuple[bytes, list[tuple[int, dict[str, Any]]]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputValidationError(f"{path}: cannot read input: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError(f"{path}: input is not valid UTF-8") from exc

    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        source = f"{path}:{line_number}"
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(source, f"invalid JSON: {exc.msg} at column {exc.colno}")
        records.append((line_number, _require_mapping(value, source)))
    return raw, records


def load_cases(path: Path) -> tuple[dict[str, CaseRecord], bytes]:
    if not path.is_file():
        raise InputValidationError(f"{path}: cases file does not exist")
    raw, records = _read_jsonl(path)
    if not records:
        raise InputValidationError(f"{path}: cases file contains no records")

    cases: dict[str, CaseRecord] = {}
    for line_number, record in records:
        source = f"{path}:{line_number}"
        _reject_unknown_keys(record, CASE_KEYS, source)
        missing = sorted(CASE_KEYS - set(record))
        if missing:
            _fail(source, f"missing field(s): {', '.join(missing)}")

        case_id = _require_str(record["case_id"], source, "case_id", nonempty=True)
        if case_id in cases:
            _fail(source, f"duplicate case_id {case_id!r}")
        source_text = _require_str(
            record["source_text"], source, "source_text", nonempty=True
        )
        cases[case_id] = CaseRecord(
            case_id=case_id,
            source_text=source_text,
            language=_require_str(
                record["language"], source, "language", nonempty=False
            ),
            source_url=_require_optional_str(
                record["source_url"], source, "source_url"
            ),
            provenance=_require_provenance(record["provenance"], source),
            review_evidence=_require_optional_str(
                record["review_evidence"], source, "review_evidence"
            ),
            required_substrings=_require_string_list(
                record["required_substrings"], source, "required_substrings"
            ),
            forbidden_substrings=_require_string_list(
                record["forbidden_substrings"], source, "forbidden_substrings"
            ),
        )
    return cases, raw


def _load_metadata(record: dict[str, Any], source: str) -> OutputMetadata:
    value = record.get("metadata")
    if value is None:
        return OutputMetadata()
    metadata = _require_mapping(value, source)
    _reject_unknown_keys(metadata, METADATA_KEYS, source)
    return OutputMetadata(
        model=_require_optional_str(metadata.get("model"), source, "metadata.model"),
        provider=_require_optional_str(
            metadata.get("provider"), source, "metadata.provider"
        ),
        prompt_hash=_require_optional_str(
            metadata.get("prompt_hash"), source, "metadata.prompt_hash"
        ),
        source_hash=_require_optional_str(
            metadata.get("source_hash"), source, "metadata.source_hash"
        ),
        captured_at=_require_optional_str(
            metadata.get("captured_at"), source, "metadata.captured_at"
        ),
    )


def _validate_output_pair(
    record: dict[str, Any], source: str
) -> tuple[str | None, str | None]:
    output = record["output"]
    error = record["error"]
    if output is not None and not isinstance(output, str):
        _fail(source, "'output' must be a string or null")
    if error is not None and not isinstance(error, str):
        _fail(source, "'error' must be a string or null")
    if isinstance(output, str) and error is not None:
        _fail(source, "a string 'output' must have null 'error'")
    if output is None:
        if error is None or error.strip() == "":
            _fail(
                source,
                "null 'output' requires a nonempty 'error' string",
            )
    return output, error


def load_outputs(path: Path, label: str) -> tuple[dict[str, OutputRecord], bytes]:
    if not path.is_file():
        raise InputValidationError(f"{path}: {label} file does not exist")
    raw, records = _read_jsonl(path)
    if not records:
        raise InputValidationError(f"{path}: {label} file contains no records")

    outputs: dict[str, OutputRecord] = {}
    for line_number, record in records:
        source = f"{path}:{line_number}"
        _reject_unknown_keys(record, OUTPUT_KEYS, source)
        missing = sorted({"case_id", "output", "error", "provenance"} - set(record))
        if missing:
            _fail(source, f"missing field(s): {', '.join(missing)}")

        case_id = _require_str(record["case_id"], source, "case_id", nonempty=True)
        if case_id in outputs:
            _fail(source, f"duplicate case_id {case_id!r}")
        output, error = _validate_output_pair(record, source)
        outputs[case_id] = OutputRecord(
            case_id=case_id,
            output=output,
            error=error,
            provenance=_require_provenance(record["provenance"], source),
            metadata=_load_metadata(record, source),
        )
    return outputs, raw


def _check_case_sets(
    cases: dict[str, CaseRecord],
    baseline: dict[str, OutputRecord],
    candidate: dict[str, OutputRecord],
) -> None:
    expected = set(cases)
    for label, rows in (("baseline", baseline), ("candidate", candidate)):
        missing = sorted(expected - set(rows))
        extra = sorted(set(rows) - expected)
        if missing:
            raise InputValidationError(
                f"{label} is missing output(s) for case_id(s): {', '.join(missing)}"
            )
        if extra:
            raise InputValidationError(
                f"{label} has output(s) for unknown case_id(s): {', '.join(extra)}"
            )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _relative_assertion_path(output_dir: Path) -> str:
    assertions = Path(__file__).resolve().parent / "assertions.py"
    relative = Path(os.path.relpath(assertions, start=output_dir)).as_posix()
    return f"file://{relative}:get_assert"


def _test_vars(case: CaseRecord, output: OutputRecord, label: str) -> dict[str, Any]:
    return {
        "logged_output": output.output if output.output is not None else "",
        "case_id": case.case_id,
        "label": label,
        "source_text": case.source_text,
        "language": case.language,
        "source_url": case.source_url if case.source_url is not None else "",
        "case_provenance": case.provenance,
        "review_evidence": (
            case.review_evidence if case.review_evidence is not None else ""
        ),
        "required_substrings": list(case.required_substrings),
        "forbidden_substrings": list(case.forbidden_substrings),
        "row_provenance": output.provenance,
        "stored_error": output.error if output.error is not None else "",
        "source_text_sha256": _sha256_text(case.source_text),
        "output_sha256": (
            _sha256_text(output.output) if output.output is not None else ""
        ),
        "capture_metadata": json.dumps(
            output.metadata.as_dict(), ensure_ascii=False, sort_keys=True
        ),
    }


def _test_entry(case: CaseRecord, output: OutputRecord, label: str) -> dict[str, Any]:
    return {
        "description": f"{label}:{case.case_id}",
        # Lists in vars are case expectations, not cartesian value sets.
        "options": {"disableVarExpansion": True},
        "vars": _test_vars(case, output, label),
    }


def _config(
    assertion_reference: str,
    tests: Sequence[dict[str, Any]],
    *,
    description: str,
) -> dict[str, Any]:
    return {
        "description": description,
        "prompts": ["{{logged_output}}"],
        "providers": ["echo"],
        "defaultTest": {
            "assert": [{"type": "python", "value": assertion_reference}],
        },
        "tests": list(tests),
    }


def _manifest(
    cases: dict[str, CaseRecord],
    baseline: dict[str, OutputRecord],
    candidate: dict[str, OutputRecord],
    hashes: dict[str, str],
) -> dict[str, Any]:
    case_ids = sorted(cases)
    rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        for label, records in (("baseline", baseline), ("candidate", candidate)):
            output = records[case_id]
            rows.append(
                {
                    "case_id": case_id,
                    "label": label,
                    "provenance": output.provenance,
                    "status": output.status,
                    "output_sha256": (
                        _sha256_text(output.output)
                        if output.output is not None
                        else None
                    ),
                    "error": output.error,
                    "metadata": output.metadata.as_dict(),
                }
            )
    return {
        "schema_version": 1,
        "case_count": len(case_ids),
        "labels": list(LABELS),
        "row_counts": {
            label: len(records)
            for label, records in (
                ("baseline", baseline),
                ("candidate", candidate),
            )
        },
        "inputs": hashes,
        "cases": [
            {
                "case_id": case.case_id,
                "language": case.language,
                "source_url": case.source_url,
                "provenance": case.provenance,
                "review_evidence": case.review_evidence,
                "source_text_sha256": _sha256_text(case.source_text),
                "required_substrings": list(case.required_substrings),
                "forbidden_substrings": list(case.forbidden_substrings),
            }
            for case in (cases[case_id] for case_id in case_ids)
        ],
        "rows": rows,
    }


def _dump_yaml(document: dict[str, Any]) -> str:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )


def prepare_replay(
    cases_path: Path,
    baseline_path: Path,
    candidate_path: Path,
    output_dir: Path,
) -> PreparationSummary:
    output_dir = output_dir.resolve()
    cases, cases_raw = load_cases(cases_path)
    baseline, baseline_raw = load_outputs(baseline_path, "baseline")
    candidate, candidate_raw = load_outputs(candidate_path, "candidate")
    _check_case_sets(cases, baseline, candidate)

    case_ids = sorted(cases)
    assertion_reference = _relative_assertion_path(output_dir)
    paired_tests = [
        _test_entry(cases[case_id], records[case_id], label)
        for case_id in case_ids
        for label, records in (("baseline", baseline), ("candidate", candidate))
    ]
    baseline_tests = [
        _test_entry(cases[case_id], baseline[case_id], "baseline")
        for case_id in case_ids
    ]
    paired = _config(
        assertion_reference,
        paired_tests,
        description=(
            "Plan 080 offline editorial replay (baseline and candidate). "
            "Structural/content guardrails and literal expectations only; "
            "no factual-correctness claim."
        ),
    )
    baseline_doc = _config(
        assertion_reference,
        baseline_tests,
        description=(
            "Plan 080 offline editorial replay baseline control (recorded "
            "outputs only; must pass)."
        ),
    )
    hashes = {
        "cases_sha256": _sha256_bytes(cases_raw),
        "baseline_sha256": _sha256_bytes(baseline_raw),
        "candidate_sha256": _sha256_bytes(candidate_raw),
    }
    manifest = _manifest(cases, baseline, candidate, hashes)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "promptfooconfig.yaml").write_text(
        _dump_yaml(paired), encoding="utf-8", newline="\n"
    )
    (output_dir / "promptfooconfig.baseline.yaml").write_text(
        _dump_yaml(baseline_doc), encoding="utf-8", newline="\n"
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return PreparationSummary(
        case_count=len(cases),
        row_count=len(paired_tests),
        output_dir=output_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare deterministic Promptfoo configs for offline editorial "
            "replay (plan 080; development-only)."
        )
    )
    parser.add_argument("--cases", required=True, type=Path, help="cases JSONL file")
    parser.add_argument(
        "--baseline", required=True, type=Path, help="baseline outputs JSONL file"
    )
    parser.add_argument(
        "--candidate", required=True, type=Path, help="candidate outputs JSONL file"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory for the generated configs and manifest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = prepare_replay(
            args.cases.resolve(),
            args.baseline.resolve(),
            args.candidate.resolve(),
            args.output_dir.resolve(),
        )
    except InputValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        "prepared "
        f"{summary.case_count} cases / {summary.row_count} rows -> "
        f"{summary.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
