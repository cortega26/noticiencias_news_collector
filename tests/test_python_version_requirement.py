"""Ensure Python compatibility requirements stay in sync across the project."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import news_collector as src
from news_collector.config.version import (
    MIN_PYTHON_VERSION_STR,
    PYTHON_REQUIRES_SPECIFIER,
)


def test_python_version_single_source_of_truth() -> None:
    """The declared Python version should match the project metadata and docs."""

    # Package metadata must reflect the canonical requirement specifier.
    assert src.__package_info__["python_requires"] == PYTHON_REQUIRES_SPECIFIER

    readme_text = Path("README.md").read_text(encoding="utf-8")
    assert f"python-{MIN_PYTHON_VERSION_STR}+-blue.svg" in readme_text
    assert f"Python {MIN_PYTHON_VERSION_STR}+" in readme_text

    with Path("pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    assert pyproject["project"]["requires-python"] == PYTHON_REQUIRES_SPECIFIER
