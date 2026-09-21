"""Utility script to regenerate dependency lockfiles with pip-tools."""

from __future__ import annotations

import argparse
import logging
import re
import subprocess  # nosec
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
            "pyproject.toml",
        ),
    ),
    (
        "requirements-refinery.lock",
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
            "refinery",
            "--output-file",
            "requirements-refinery.lock",
            "pyproject.toml",
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
            # Note: No -c requirements.lock here because semgrep requires
            # click~=8.1.8 which conflicts with scrapling[fetchers]'s click>=8.3.0
            # pinned in the main lockfile. These are separate environments so
            # the constraint is not needed.
            "--extra",
            "security",
            "--extra",
            "test",
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
        "--upgrade-package",
        action="append",
        default=[],
        metavar="NAME[==VERSION]",
        help=(
            "Upgrade only this package (repeatable) in every lockfile; everything "
            "else keeps its current pin. Use it to bump dependencies group by group."
        ),
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

    # pip>=26 removed pip._internal.utils.compat.stdlib_pkgs, which pip-tools
    # 7.5.3 still imports; keep pip on the known-good pairing until pip-tools
    # is bumped to a version compatible with pip 26+.
    run_command(
        (sys.executable, "-m", "pip", "install", "pip-tools==7.5.3", "pip<26.0")
    )


def run_command(command: Sequence[str], description: str | None = None) -> None:
    """Run a command in the project root, raising on failure."""
    if description:
        LOGGER.info("%s", description)
    LOGGER.debug("Running command: %s", " ".join(command))
    subprocess.run(command, cwd=ROOT_DIR, check=True)  # noqa: S603


def build_compile_args(
    args: Sequence[str], upgrade_packages: Sequence[str] = ()
) -> tuple[str, ...]:
    """``pip-compile`` arguments with one ``--upgrade-package`` per requested package.

    The flags go right before the positional input file (last argument), so pip-tools
    sees them as options of the compile command.
    """
    upgrades = tuple(
        part for name in upgrade_packages for part in ("--upgrade-package", name)
    )
    return (*args[:-1], *upgrades, args[-1])


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.split("==")[0].strip()).lower()


def pinned_names(lock_text: str) -> set[str]:
    """Normalized names pinned (``name==version``) in a lockfile's text."""
    return {
        _norm(m.group(1))
        for m in re.finditer(
            r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", lock_text, re.MULTILINE
        )
    }


def upgrades_for_lock(lockfile: str, upgrade_packages: Sequence[str]) -> list[str]:
    """Only the requested packages that this lock already pins.

    ``pip-compile --upgrade-package X`` *adds* X when the lock does not contain it, which
    would drag e.g. the whole security toolchain into the runtime lock.
    """
    path = ROOT_DIR / lockfile
    present = pinned_names(path.read_text(encoding="utf-8")) if path.exists() else set()
    return [name for name in upgrade_packages if _norm(name) in present]


def sync_lockfiles(upgrade_packages: Sequence[str] = ()) -> None:  # noqa: C901
    """Regenerate the lockfiles using pip-tools (optionally upgrading some packages)."""
    for lockfile, args in LOCK_TARGETS:
        command = (
            sys.executable,
            *build_compile_args(args, upgrades_for_lock(lockfile, upgrade_packages)),
        )
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
                        or line.startswith("wheel==")
                        or line.startswith("# wheel==")
                        or "The following packages are considered to be unsafe" in line
                    ):
                        skipping = True
                    else:
                        skipping = False

                if not skipping:
                    filtered_lines.append(line)

            path.write_text("\n".join(filtered_lines).rstrip() + "\n")

            # Post-write verification
            final_content = path.read_text()
            if "The following packages are considered to be unsafe" in final_content:
                print(f"❌ Error: Unsafe header found in {lockfile} after stripping!")
                for i, ln in enumerate(final_content.splitlines()):
                    if "unsafe" in ln:
                        print(f"Line {i+1}: {ln}")
                sys.exit(1)

            if "pip==" in final_content and "# pip==" not in final_content:
                pass  # We trust the line-by-line logic generally, but header check is critical.


def ensure_lockfiles_clean() -> None:
    """Verify that lockfiles did not change after syncing."""
    try:
        run_command(
            (
                "git",
                "diff",
                "--quiet",
                "--",
                "requirements.lock",
                "requirements-refinery.lock",
                "requirements-security.lock",
            ),
            description="Verifying lockfiles are up to date",
        )
    except subprocess.CalledProcessError:
        LOGGER.error("Lockfiles have changed! Printing diff:")
        subprocess.run(
            (
                "git",
                "diff",
                "--",
                "requirements.lock",
                "requirements-refinery.lock",
                "requirements-security.lock",
            ),
            cwd=ROOT_DIR,
            check=False,
        )  # noqa: S603
        sys.exit(1)


def main() -> None:
    """Entry point for CLI execution."""
    args = parse_args()
    configure_logging(args.verbose)
    ensure_piptools_installed(force=args.install_pip_tools)
    sync_lockfiles(args.upgrade_package)
    if args.check:
        ensure_lockfiles_clean()


if __name__ == "__main__":
    main()
