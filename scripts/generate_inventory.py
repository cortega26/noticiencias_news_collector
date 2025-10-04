#!/usr/bin/env python3
"""Generate and compare repository inventory snapshots."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import platform
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Mapping, MutableMapping, Optional

import tomllib

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class InventoryOptions:
    """Configuration for inventory generation."""

    sample_size: int = 10
    include_dirs: tuple[str, ...] = ("src", "scripts")


def _list_top_level(root: Path) -> MutableMapping[str, Optional[List[str]]]:
    inventory: "OrderedDict[str, Optional[List[str]]]" = OrderedDict()
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if entry.name in {".git", "__pycache__", ".venv"}:
            continue
        if entry.is_dir():
            children = [child.name for child in sorted(entry.iterdir(), key=lambda path: path.name)]
            inventory[f"{entry.name}/"] = children
        else:
            inventory[entry.name] = None
    return inventory


def _collect_make_targets(makefile: Path) -> List[Mapping[str, str]]:
    targets: List[Mapping[str, str]] = []
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if "##" not in line:
            continue
        if line.strip().startswith("#"):
            continue
        lhs, _, description = line.partition("##")
        target = lhs.split(":", 1)[0].strip()
        description = description.strip()
        if not target:
            continue
        targets.append({"target": target, "description": description})
    return targets


def _parse_requirements(path: Path) -> List[str]:
    packages: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        packages.append(line.rstrip())
    return packages


def _optional_security(pyproject: Path) -> List[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    security = data.get("project", {}).get("optional-dependencies", {}).get("security", [])
    return list(security)


def _markdown_files(root: Path) -> List[str]:
    files = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*.md")
        if ".venv" not in path.parts
    )
    return files


def _python_modules(root: Path, options: InventoryOptions) -> Iterator[Path]:
    for include in options.include_dirs:
        base = root / include
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _module_inventory(paths: Iterable[Path], sample_size: int, root: Path) -> Mapping[str, Mapping[str, List[str]]]:
    sample: "OrderedDict[str, Mapping[str, List[str]]]" = OrderedDict()
    for path in paths:
        if len(sample) >= sample_size:
            break
        try:
            module_ast = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        functions: List[str] = []
        classes: List[str] = []
        for node in module_ast.body:
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
        relative = str(path.relative_to(root)).replace("\\", "/")
        sample[relative] = {"functions": functions, "classes": classes}
    return sample


def _open_questions(missing_file: Path) -> List[str]:
    if not missing_file.exists():
        return []
    questions: List[str] = []
    for line in missing_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- Missing:"):
            questions.append(stripped[2:].strip())
    return questions


def build_inventory(root: Path, options: InventoryOptions) -> Mapping[str, object]:
    makefile = root / "Makefile"
    requirements_txt = root / "requirements.txt"
    pyproject = root / "pyproject.toml"
    missing_md = root / "missing.md"

    top_level = _list_top_level(root)
    make_targets = _collect_make_targets(makefile) if makefile.exists() else []
    requirements = _parse_requirements(requirements_txt) if requirements_txt.exists() else []
    security_optional = _optional_security(pyproject) if pyproject.exists() else []
    markdown_files = _markdown_files(root)
    module_paths = _python_modules(root, options)
    function_index = _module_inventory(module_paths, options.sample_size, root)
    open_questions = _open_questions(missing_md)

    entrypoints: MutableMapping[str, object] = OrderedDict()
    main_module = "main.py"
    entrypoints["main_module"] = main_module if (root / main_module).exists() else None
    cli_path = Path("run_collector.py")
    if cli_path.exists():
        entrypoints["cli"] = {"path": cli_path.as_posix(), "help": f"python {cli_path.as_posix()} --help"}
    entrypoints["make"] = "See make_targets section"

    inventory: "OrderedDict[str, object]" = OrderedDict(
        (
            ("generated_at", datetime.now(timezone.utc).isoformat()),
            ("python_version", platform.python_version()),
            ("top_level_inventory", top_level),
            ("entrypoints", entrypoints),
            ("make_targets", make_targets),
            (
                "dependencies",
                {
                    "requirements_txt": requirements,
                    "optional_security": security_optional,
                },
            ),
            ("function_index_sample", function_index),
            ("markdown_files", markdown_files),
            ("open_questions", open_questions),
        )
    )
    return inventory


def _sanitize(payload: Mapping[str, object]) -> Mapping[str, object]:
    sanitized = OrderedDict(payload)
    sanitized.pop("generated_at", None)
    sanitized.pop("python_version", None)
    return sanitized


def _diff_summary(previous: Mapping[str, object], current: Mapping[str, object]) -> tuple[int, List[str], str]:
    before_dump = json.dumps(previous, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    after_dump = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    diff_lines = list(difflib.unified_diff(before_dump, after_dump, fromfile="baseline", tofile="current", lineterm=""))
    relevant = [
        line
        for line in diff_lines
        if line and not line.startswith(("+++", "---", "@@")) and line[0] in {"+", "-"}
    ]

    changed_paths = sorted(_diff_keys(previous, current))
    return len(relevant), changed_paths, "\n".join(diff_lines)


def _diff_keys(before: object, after: object, prefix: str | None = None) -> set[str]:
    path_prefix = prefix or ""
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        keys = set(before) | set(after)
        changes: set[str] = set()
        for key in keys:
            next_prefix = f"{path_prefix}.{key}" if path_prefix else str(key)
            if key not in before or key not in after:
                changes.add(next_prefix)
                continue
            changes |= _diff_keys(before[key], after[key], next_prefix)
        return changes
    if isinstance(before, list) and isinstance(after, list):
        return {path_prefix} if before != after else set()
    return {path_prefix} if before != after else set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the repository inventory snapshot.")
    parser.add_argument("--output", type=Path, default=ROOT / "audit" / "00_inventory.json", help="Path to write the inventory JSON.")
    parser.add_argument("--sample-size", type=int, default=10, help="Number of modules to include in the function index sample.")
    parser.add_argument("--compare-to", type=Path, help="Existing inventory JSON to compare against.")
    parser.add_argument("--diff-output", type=Path, help="Optional file to store a unified diff between snapshots.")
    parser.add_argument("--summary-output", type=Path, help="Optional file to store drift metadata as JSON.")
    args = parser.parse_args()

    options = InventoryOptions(sample_size=args.sample_size)
    inventory = build_inventory(ROOT, options)

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.compare_to and args.compare_to.exists():
        previous = json.loads(args.compare_to.read_text(encoding="utf-8"))
        drift_count, changed_paths, diff_text = _diff_summary(_sanitize(previous), _sanitize(inventory))
        if args.diff_output:
            diff_path = args.diff_output
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(diff_text + ("\n" if diff_text and not diff_text.endswith("\n") else ""), encoding="utf-8")
        if args.summary_output:
            summary_path = args.summary_output
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps({"drift_count": drift_count, "changed_paths": changed_paths}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(json.dumps({"drift_count": drift_count, "changed_paths": changed_paths}, ensure_ascii=False))
    else:
        print(json.dumps({"drift_count": 0, "changed_paths": []}, ensure_ascii=False))


if __name__ == "__main__":
    main()
