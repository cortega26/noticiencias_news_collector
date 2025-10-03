"""Generate API reference documentation using pdoc."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

LOGGER = logging.getLogger("docs.api")
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "api"
SOURCE_PATH = ROOT / "src"


def _preferred_python() -> str:
    """Return the Python executable with project dependencies available."""

    candidates = [
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _run_command(command: Sequence[str]) -> None:
    """Execute a command, raising on failure."""
    LOGGER.debug("Executing command", extra={"command": list(command)})
    subprocess.run(command, check=True, cwd=ROOT)


def _prepare_output_directory() -> None:
    if OUTPUT_DIR.exists():
        LOGGER.info("Removing previous API docs", extra={"path": str(OUTPUT_DIR)})
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _flatten_pdoc_structure() -> None:
    generated_root = OUTPUT_DIR / SOURCE_PATH.name
    if not generated_root.exists():
        return

    for item in generated_root.iterdir():
        destination = OUTPUT_DIR / item.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(item), destination)
    shutil.rmtree(generated_root)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    LOGGER.info("Generating API documentation", extra={"output_dir": str(OUTPUT_DIR)})

    if not SOURCE_PATH.exists():
        LOGGER.error("Source path does not exist", extra={"path": str(SOURCE_PATH)})
        return 1

    _prepare_output_directory()

    command = [
        _preferred_python(),
        "-m",
        "pdoc",
        "-o",
        str(OUTPUT_DIR),
        str(SOURCE_PATH),
    ]

    try:
        _run_command(command)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        LOGGER.exception("pdoc generation failed", extra={"returncode": exc.returncode})
        return exc.returncode

    _flatten_pdoc_structure()
    LOGGER.info("API documentation generated", extra={"output_dir": str(OUTPUT_DIR)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
