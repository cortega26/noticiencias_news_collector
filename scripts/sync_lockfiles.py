"""Utility script to regenerate dependency lockfiles with pip-tools."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Sequence

LOGGER = logging.getLogger("sync_lockfiles")
ROOT_DIR = Path(__file__).resolve().parent.parent
LOCK_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "requirements.lock",
        (
            "-m",
            "piptools",
            "compile",
            "--no-header",
            "--generate-hashes",
            "--output-file",
            "requirements.lock",
            "requirements.txt",
        ),
    ),
    (
        "requirements-security.lock",
        (
            "-m",
            "piptools",
            "compile",
            "--no-header",
            "--generate-hashes",
            "--allow-unsafe",
            "-c",
            "requirements.lock",
            "--extra",
            "security",
            "--output-file",
            "requirements-security.lock",
            "pyproject.toml",
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the lockfiles change after running the sync.",
    )
    parser.add_argument(
        "--install-pip-tools",
        action="store_true",
        help="Force (re)installation of pip-tools before syncing the lockfiles.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output.",
    )
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    """Configure logging with the desired verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")


def ensure_piptools_installed(force: bool) -> None:
    """Ensure pip-tools is available before invoking compile commands."""
    try:
        if not force:
            import piptools  # type: ignore  # noqa: F401

            LOGGER.debug("pip-tools already installed; skipping installation.")
            return
    except ImportError:
        LOGGER.info("pip-tools not found; installing now.")
    else:
        LOGGER.info("Reinstalling pip-tools as requested.")

    run_command((sys.executable, "-m", "pip", "install", "pip-tools"))


def run_command(command: Sequence[str], description: str | None = None) -> None:
    """Run a command in the project root, raising on failure."""
    if description:
        LOGGER.info("%s", description)
    LOGGER.debug("Running command: %s", " ".join(command))
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def sync_lockfiles() -> None:
    """Regenerate both lockfiles using pip-tools."""
    for lockfile, args in LOCK_TARGETS:
        command = (sys.executable, *args)
        run_command(command, description=f"Regenerating {lockfile}")
        
        # Post-process: Strip 'pip' package lines to prevent CI instability due to version mismatches
        path = ROOT_DIR / lockfile
        if path.exists():
            lines = path.read_text().splitlines()
            filtered_lines = []
            skipping = False
            for line in lines:
                # Keep empty lines, but reset skipping state
                if not line.strip():
                    if skipping:
                        skipping = False
                        continue
                    filtered_lines.append(line)
                    continue

                # Check for start of a new package block (non-indented) or a warning block
                if line and not line[0].isspace():
                    if (
                        line.startswith("pip==")
                        or line.startswith("# pip==")
                        or "The following packages are considered to be unsafe" in line
                    ):
                        skipping = True
                    else:
                        skipping = False
                
                if not skipping:
                    filtered_lines.append(line)

            path.write_text("\n".join(filtered_lines) + "\n")



def ensure_lockfiles_clean() -> None:
    """Verify that lockfiles did not change after syncing."""
    run_command(
        (
            "git",
            "diff",
            "--quiet",
            "--",
            "requirements.lock",
            "requirements-security.lock",
        ),
        description="Verifying lockfiles are up to date",
    )


def main() -> None:
    """Entry point for CLI execution."""
    args = parse_args()
    configure_logging(args.verbose)
    ensure_piptools_installed(force=args.install_pip_tools)
    sync_lockfiles()
    if args.check:
        ensure_lockfiles_clean()


if __name__ == "__main__":
    main()
